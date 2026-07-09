from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from agents.audit_agent import ParseAuditAgent
from agents.gpt_parser_agent import (
    GptParserAgent,
    ensure_column,
    ensure_parse_schema,
    fill_missing_rfp_printed_page_numbers,
    infer_table_candidates,
    insert_page,
)
from agents.models import CandidatePage, ParsedDocument


RUNNING_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"succeeded", "failed", "canceled"}


@dataclass
class ParseJobSnapshot:
    job_id: str
    document_id: int
    document_name: str
    file_path: str
    total_pages: int
    status: str
    processed_pages: int
    failed_pages: int
    current_page: int | None
    error: str
    selected_pages: list[int]
    python_pages: int = 0
    gpt_pages: int = 0

    @property
    def progress_percent(self) -> int:
        page_count = len(self.selected_pages) or self.total_pages
        if page_count <= 0:
            return 0
        return int(round((self.processed_pages / page_count) * 100))

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "file_path": self.file_path,
            "total_pages": self.total_pages,
            "status": self.status,
            "processed_pages": self.processed_pages,
            "failed_pages": self.failed_pages,
            "current_page": self.current_page,
            "error": self.error,
            "selected_pages": self.selected_pages,
            "python_pages": self.python_pages,
            "gpt_pages": self.gpt_pages,
            "progress_percent": self.progress_percent,
            "is_terminal": self.status in TERMINAL_STATUSES,
        }


class ParseJobRunner:
    """Checkpointed PDF parse runner that keeps GPT as the actual page parser."""

    def __init__(
        self,
        db_path: Path | str,
        parser: GptParserAgent | None = None,
        auditor: ParseAuditAgent | None = None,
        pages_per_chunk: int | None = None,
        hybrid: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self.parser = parser or GptParserAgent(self.db_path)
        self.auditor = auditor or ParseAuditAgent()
        self.hybrid = hybrid
        self.pages_per_chunk = max(
            1,
            pages_per_chunk
            if pages_per_chunk is not None
            else int(os.getenv("OPENAI_PDF_PAGES_PER_CALL", "1")),
        )

    def create_job(self, pdf_path: Path | str, page_numbers: list[int] | None = None) -> ParseJobSnapshot:
        pdf = Path(pdf_path)
        reader = PdfReader(str(pdf))
        total_pages = len(reader.pages)
        selected_pages = normalize_page_numbers(page_numbers, total_pages)
        job_id = uuid.uuid4().hex

        conn = self._connect()
        try:
            ensure_parse_job_schema(conn)
            cur = conn.execute(
                """
                INSERT INTO rfp_document (document_name, file_path, total_pages, parse_status, parse_warning_count)
                VALUES (?, ?, ?, 'job_queued', 0)
                """,
                (pdf.name, str(pdf), total_pages),
            )
            document_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO parse_job (
                    job_id, document_id, document_name, file_path, total_pages,
                    status, processed_pages, failed_pages, current_page, error, selected_pages
                )
                VALUES (?, ?, ?, ?, ?, 'queued', 0, 0, NULL, '', ?)
                """,
                (job_id, document_id, pdf.name, str(pdf), total_pages, json.dumps(selected_pages)),
            )
            conn.commit()
            return self.snapshot(job_id, conn)
        finally:
            conn.close()

    def run_job(self, job_id: str) -> ParseJobSnapshot:
        conn = self._connect()
        try:
            ensure_parse_job_schema(conn)
            snapshot = self.snapshot(job_id, conn)
            if snapshot.status in TERMINAL_STATUSES:
                return snapshot

            self._mark_job_running(conn, snapshot)
            reader = PdfReader(snapshot.file_path)
            pending_pages = self._pending_pages(conn, snapshot)
            if self.hybrid:
                pending_pages = self._consume_python_pages(conn, snapshot, reader, pending_pages)

            current_chunk: list[int] = []
            for chunk in chunked(pending_pages, self.pages_per_chunk):
                current_chunk = chunk
                self._mark_pages_running(conn, job_id, chunk)
                extracted = self.parser.extract_chunk_with_fallback(reader, chunk)
                by_page = {page.page_no: page for page in extracted}
                missing_pages = [page_no for page_no in chunk if page_no not in by_page]
                if missing_pages:
                    raise RuntimeError(f"GPT parser returned no page result for PDF pages: {missing_pages}")

                for page_no in chunk:
                    self._replace_page(conn, snapshot.document_id, by_page[page_no])
                    self._mark_page_done(conn, job_id, page_no, "gpt")
                self._refresh_job_progress(conn, job_id)

            document = self._finalize_document(conn, snapshot.document_id)
            audited = self.auditor.audit(document)
            warning_count = len(audited.audit_warnings) + sum(1 for page in audited.pages if page.parser_warning)
            conn.execute(
                "UPDATE rfp_document SET parse_status = ?, parse_warning_count = ? WHERE id = ?",
                (audited.parse_status, warning_count, snapshot.document_id),
            )
            conn.execute(
                """
                UPDATE parse_job
                SET status = 'succeeded',
                    processed_pages = ?,
                    failed_pages = 0,
                    current_page = NULL,
                    error = '',
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (len(snapshot.selected_pages), job_id),
            )
            conn.commit()
            return self.snapshot(job_id, conn)
        except Exception as exc:
            current_chunk = locals().get("current_chunk", [])
            for page_no in current_chunk:
                conn.execute(
                    """
                    UPDATE parse_job_page
                    SET status = 'failed',
                        error = ?,
                        completed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = ? AND page_no = ? AND status = 'running'
                    """,
                    (str(exc), job_id, page_no),
                )
            self._refresh_job_progress(conn, job_id)
            conn.execute(
                """
                UPDATE parse_job
                SET status = 'failed',
                    error = ?,
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (str(exc), job_id),
            )
            conn.commit()
            return self.snapshot(job_id, conn)
        finally:
            conn.close()

    def snapshot(self, job_id: str, conn: sqlite3.Connection | None = None) -> ParseJobSnapshot:
        should_close = conn is None
        conn = conn or self._connect()
        try:
            ensure_parse_job_schema(conn)
            row = conn.execute("SELECT * FROM parse_job WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise RuntimeError(f"parse job not found: {job_id}")
            return ParseJobSnapshot(
                job_id=str(row["job_id"]),
                document_id=int(row["document_id"]),
                document_name=str(row["document_name"]),
                file_path=str(row["file_path"]),
                total_pages=int(row["total_pages"]),
                status=str(row["status"]),
                processed_pages=int(row["processed_pages"] or 0),
                failed_pages=int(row["failed_pages"] or 0),
                current_page=int(row["current_page"]) if row["current_page"] is not None else None,
                error=str(row["error"] or ""),
                selected_pages=parse_selected_pages(row["selected_pages"], int(row["total_pages"])),
                python_pages=int(row["python_pages"] or 0) if "python_pages" in row.keys() else 0,
                gpt_pages=int(row["gpt_pages"] or 0) if "gpt_pages" in row.keys() else 0,
            )
        finally:
            if should_close:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _mark_job_running(self, conn: sqlite3.Connection, snapshot: ParseJobSnapshot) -> None:
        conn.execute(
            """
            UPDATE parse_job
            SET status = 'running',
                current_page = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE job_id = ?
            """,
            (snapshot.current_page or snapshot.selected_pages[0], snapshot.job_id),
        )
        conn.execute(
            "UPDATE rfp_document SET parse_status = 'job_running' WHERE id = ?",
            (snapshot.document_id,),
        )
        conn.commit()

    def _pending_pages(self, conn: sqlite3.Connection, snapshot: ParseJobSnapshot) -> list[int]:
        completed = {
            int(row["page_no"])
            for row in conn.execute(
                "SELECT page_no FROM parse_job_page WHERE job_id = ? AND status = 'succeeded'",
                (snapshot.job_id,),
            )
        }
        return [page_no for page_no in snapshot.selected_pages if page_no not in completed]

    def _mark_pages_running(self, conn: sqlite3.Connection, job_id: str, pages: list[int]) -> None:
        for page_no in pages:
            conn.execute(
                """
                INSERT INTO parse_job_page (job_id, page_no, status, error, started_at, updated_at)
                VALUES (?, ?, 'running', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(job_id, page_no) DO UPDATE SET
                    status = 'running',
                    error = '',
                    started_at = COALESCE(parse_job_page.started_at, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (job_id, page_no),
            )
        conn.execute(
            "UPDATE parse_job SET current_page = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?",
            (pages[0], job_id),
        )
        conn.commit()

    def _mark_page_done(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        page_no: int,
        source: str,
    ) -> None:
        conn.execute(
            """
            UPDATE parse_job_page
            SET status = 'succeeded',
                error = '',
                source = ?,
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE job_id = ? AND page_no = ?
            """,
            (source, job_id, page_no),
        )
        conn.commit()

    def _refresh_job_progress(self, conn: sqlite3.Connection, job_id: str) -> None:
        counts = conn.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS processed_pages,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_pages,
                SUM(CASE WHEN status = 'succeeded' AND source = 'python_prescan' THEN 1 ELSE 0 END) AS python_pages,
                SUM(CASE WHEN status = 'succeeded' AND source = 'gpt' THEN 1 ELSE 0 END) AS gpt_pages
            FROM parse_job_page
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        conn.execute(
            """
            UPDATE parse_job
            SET processed_pages = ?,
                failed_pages = ?,
                python_pages = ?,
                gpt_pages = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE job_id = ?
            """,
            (
                int(counts["processed_pages"] or 0),
                int(counts["failed_pages"] or 0),
                int(counts["python_pages"] or 0),
                int(counts["gpt_pages"] or 0),
                job_id,
            ),
        )
        conn.commit()

    def _replace_page(self, conn: sqlite3.Connection, document_id: int, page: CandidatePage) -> None:
        conn.execute(
            "DELETE FROM rfp_page WHERE document_id = ? AND page_no = ?",
            (document_id, page.page_no),
        )
        insert_page(conn, document_id, page)
        conn.commit()

    def _consume_python_pages(
        self,
        conn: sqlite3.Connection,
        snapshot: ParseJobSnapshot,
        reader: PdfReader,
        pending_pages: list[int],
    ) -> list[int]:
        gpt_pages: list[int] = []
        for page_no in pending_pages:
            decision = python_prescan_page(reader, page_no)
            if decision["needs_gpt"]:
                gpt_pages.append(page_no)
                continue
            self._mark_pages_running(conn, snapshot.job_id, [page_no])
            self._replace_page(conn, snapshot.document_id, decision["page"])
            self._mark_page_done(conn, snapshot.job_id, page_no, "python_prescan")
            self._refresh_job_progress(conn, snapshot.job_id)
        return gpt_pages

    def _finalize_document(self, conn: sqlite3.Connection, document_id: int) -> ParsedDocument:
        rows = conn.execute(
            """
            SELECT page_no, page_text, text_length, rfp_printed_page_no,
                   has_table_candidate, has_attachment_candidate, has_eval_table_candidate,
                   has_toc_candidate, has_blind_candidate, has_commercial_sw_candidate,
                   parser_warning
            FROM rfp_page
            WHERE document_id = ?
            ORDER BY page_no
            """,
            (document_id,),
        ).fetchall()
        pages = [
            CandidatePage(
                page_no=int(row["page_no"]),
                page_text=str(row["page_text"] or ""),
                text_length=int(row["text_length"] or 0),
                rfp_printed_page_no=row["rfp_printed_page_no"],
                has_table_candidate=bool(row["has_table_candidate"]),
                has_attachment_candidate=bool(row["has_attachment_candidate"]),
                has_eval_table_candidate=bool(row["has_eval_table_candidate"]),
                has_toc_candidate=bool(row["has_toc_candidate"]),
                has_blind_candidate=bool(row["has_blind_candidate"]),
                has_commercial_sw_candidate=bool(row["has_commercial_sw_candidate"]),
                parser_warning=row["parser_warning"],
            )
            for row in rows
        ]
        pages = fill_missing_rfp_printed_page_numbers(pages)
        infer_table_candidates(pages)
        conn.execute("DELETE FROM rfp_page WHERE document_id = ?", (document_id,))
        for page in pages:
            insert_page(conn, document_id, page)

        doc = conn.execute("SELECT * FROM rfp_document WHERE id = ?", (document_id,)).fetchone()
        conn.commit()
        return ParsedDocument(
            document_id=document_id,
            document_name=str(doc["document_name"]),
            pdf_path=Path(doc["file_path"]) if doc["file_path"] else None,
            total_pages=int(doc["total_pages"]),
            parse_status=str(doc["parse_status"]),
            pages=pages,
        )


def ensure_parse_job_schema(conn: sqlite3.Connection) -> None:
    ensure_parse_schema(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS parse_job (
            job_id TEXT PRIMARY KEY,
            document_id INTEGER NOT NULL,
            document_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
                    total_pages INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    processed_pages INTEGER NOT NULL DEFAULT 0,
                    failed_pages INTEGER NOT NULL DEFAULT 0,
                    current_page INTEGER,
                    error TEXT NOT NULL DEFAULT '',
                    selected_pages TEXT NOT NULL DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            FOREIGN KEY (document_id) REFERENCES rfp_document(id)
        );
        CREATE TABLE IF NOT EXISTS parse_job_page (
            job_id TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            status TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (job_id, page_no),
            FOREIGN KEY (job_id) REFERENCES parse_job(job_id)
        );
        CREATE INDEX IF NOT EXISTS idx_parse_job_status
            ON parse_job(status, updated_at);
        """
    )
    ensure_column(conn, "parse_job", "selected_pages", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "parse_job", "python_pages", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "parse_job", "gpt_pages", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "parse_job_page", "source", "TEXT NOT NULL DEFAULT ''")
    conn.commit()


def chunked(values: list[int], size: int) -> list[list[int]]:
    return [values[idx : idx + size] for idx in range(0, len(values), size)]


def normalize_page_numbers(page_numbers: list[int] | None, total_pages: int) -> list[int]:
    if not page_numbers:
        return list(range(1, total_pages + 1))
    selected = sorted({int(page_no) for page_no in page_numbers if 1 <= int(page_no) <= total_pages})
    if not selected:
        raise ValueError("No valid PDF pages were selected.")
    return selected


def parse_selected_pages(value: object, total_pages: int) -> list[int]:
    if value:
        try:
            parsed = json.loads(str(value))
            if isinstance(parsed, list):
                return normalize_page_numbers([int(item) for item in parsed], total_pages)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return list(range(1, total_pages + 1))


def python_prescan_page(reader: PdfReader, page_no: int) -> dict[str, Any]:
    text = reader.pages[page_no - 1].extract_text() or ""
    clean_text = normalize_extracted_text(text)
    compact = re.sub(r"\s+", "", clean_text)
    text_length = len(compact)
    has_requirement_table = is_requirement_table_text(compact)
    has_eval_table = is_eval_table_text(compact)
    has_table = has_requirement_table or has_eval_table or is_table_like_prescan_text(clean_text)
    hard_reason = first_hard_page_reason(clean_text, compact, text_length, has_table)
    page = CandidatePage(
        page_no=page_no,
        page_text=clean_text,
        text_length=text_length,
        has_table_candidate=has_table,
        has_eval_table_candidate=has_eval_table,
        has_attachment_candidate=contains_any(compact, ["별첨", "붙임", "서식"]),
        has_toc_candidate=contains_any(compact, ["목차", "차례"]),
        parser_warning=None if hard_reason is None else f"python_prescan_needs_gpt: {hard_reason}",
    )
    return {
        "page": page,
        "needs_gpt": hard_reason is not None,
        "reason": hard_reason or "python_text_good_enough",
    }


def normalize_extracted_text(text: str) -> str:
    return "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip()).strip()


def first_hard_page_reason(
    text: str,
    compact: str,
    text_length: int,
    has_table: bool,
) -> str | None:
    if is_low_value_navigation_page(compact, text_length):
        return None
    if text_length < 120:
        return "short_or_image_heavy_page"
    if has_suspicious_text_noise(compact):
        return "suspicious_text_noise"
    if has_review_relevant_signal(compact):
        return "review_relevant_keyword_page"
    if has_table:
        return "table_or_requirement_page"
    if has_dense_layout_table_signal(text, compact):
        return "dense_layout_table_candidate"
    if contains_any(
        compact,
        [
            "작업장소",
            "원격개발",
            "원격지",
            "지식재산",
            "공동소유",
            "공동귀속",
            "산출물반출",
            "누출금지",
            "사전승인",
            "제3자",
            "보안요구사항",
        ],
    ):
        return "legal_or_security_keyword_page"
    return None


def is_low_value_navigation_page(compact: str, text_length: int) -> bool:
    if text_length > 80:
        return False
    section_titles = [
        "Ⅰ.사업개요",
        "Ⅱ.시스템현황",
        "Ⅲ.사업추진방안",
        "Ⅳ.제안요청내용",
        "Ⅴ.제안서작성요령",
        "Ⅵ.제안안내사항",
        "Ⅶ.별첨",
        "Ⅷ.서식",
    ]
    if any(title in compact for title in section_titles):
        return True
    return bool(re.fullmatch(r"\d{1,3}[ⅠⅡⅢⅣⅤⅥⅦⅧ]?.{0,30}", compact))


def has_review_relevant_signal(compact: str) -> bool:
    return contains_any(
        compact,
        [
            "요구사항",
            "제안요청",
            "제안서",
            "계약",
            "하도급",
            "보안",
            "산출물",
            "평가",
            "과업",
            "작업장소",
            "원격개발",
            "원격지",
            "지식재산",
            "공동소유",
            "공동귀속",
            "반출",
            "누출금지",
            "사전승인",
            "제3자",
            "개인정보",
            "기술적용",
            "기능요구",
            "품질요구",
            "프로젝트관리",
            "유지관리",
            "별첨",
            "서식",
        ],
    )


def has_suspicious_text_noise(compact: str) -> bool:
    if not compact:
        return True
    replacement_count = compact.count("?") + compact.count("�")
    return replacement_count / max(1, len(compact)) > 0.03


def is_requirement_table_text(compact: str) -> bool:
    signals = ["요구사항구분", "요구사항분류", "고유번호", "요구사항명", "요구사항명칭", "요구사항상세설명"]
    return sum(1 for signal in signals if signal in compact) >= 2


def is_eval_table_text(compact: str) -> bool:
    return contains_any(compact, ["평가항목", "평가기준", "배점", "기술평가", "정량평가", "정성평가"])


def is_table_like_prescan_text(text: str) -> bool:
    source = str(text or "")
    compact = re.sub(r"\s+", "", source)
    return (
        source.count("|") >= 4
        or len(re.findall(r"\s{2,}", source)) >= 12
        or contains_any(compact, ["구분내용", "구분항목", "구분위규사항", "적용계획/결과"])
    )


def has_dense_layout_table_signal(text: str, compact: str) -> bool:
    signals = [
        ["담당", "소속", "직위", "성명", "전화번호"],
        ["구분", "규격/모델", "수량"],
        ["구분", "규격", "모델", "수량"],
        ["HW", "SW", "수량"],
        ["자본금", "매출액", "구분"],
        ["사업명", "사업기간", "계약금액", "발주처"],
        ["구분", "적용", "부분적용", "미적용"],
        ["구분", "위규사항", "처벌"],
    ]
    if any(all(signal in compact for signal in group) for group in signals):
        return True
    if len(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", text)) >= 2:
        return True
    return False


def contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)
