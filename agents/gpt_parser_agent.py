from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter

from agents.llm_client import extract_response_text, parse_json_object
from agents.models import CandidatePage, ParsedDocument
from agents.page_selection import dedupe_pages


SYSTEM_PROMPT = """당신은 RFP PDF 파싱 에이전트입니다.
목표는 법제도 검토에 필요한 원문 텍스트, 표, 섹션 경계, 붙임/별첨 후보를 페이지별로 정확히 추출하는 것입니다.

규칙:
- 보이는 내용을 그대로 추출하고, 없는 내용을 만들지 마세요.
- 표는 가능한 Markdown table로 보존하세요.
- 평가표/배점표/제안서 작성요령/붙임/별첨/블라인드/상용SW 관련 신호를 boolean으로 표시하세요.
- 페이지별 pdf_page_no는 반드시 page_numbers_in_this_file에 있는 PDF 물리 페이지 번호를 사용하세요.
- 문서 본문에 인쇄된 쪽수는 pdf_page_no가 아니며, rfp_printed_page_no에 별도로 적으세요.
- rfp_printed_page_no는 반드시 숫자만 적으세요. 예: 본문에 "제안요청서 p.57", "- 57 -", "57쪽"으로 보이면 57만 적고, 숫자를 확인할 수 없으면 null로 적으세요.
- 어떤 페이지의 rfp_printed_page_no가 보이지 않으면, 같은 RFP의 직전/직후 페이지에서 확인되는 연속된 인쇄 쪽수 흐름을 근거로 추정해 숫자를 적어도 됩니다. 단, 이미 숫자가 보이는 페이지는 그 숫자를 우선하고 추정값으로 덮어쓰지 마세요.
- 읽기 어려운 부분, 표 구조 깨짐, 이미지 기반 페이지는 parser_warning에 적으세요.
- JSON 객체 하나만 반환하세요."""


@dataclass
class GptParserConfig:
    model: str = "gpt-4.1"
    pages_per_call: int = 3
    timeout_seconds: int = 180
    max_retries: int = 2
    raw_output_dir: Path | None = None


class GptParserAgent:
    def __init__(
        self,
        db_path: Path | str,
        api_key: str | None = None,
        config: GptParserConfig | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.config = config or GptParserConfig(
            model=os.getenv("OPENAI_PDF_MODEL", "gpt-4.1"),
            pages_per_call=int(os.getenv("OPENAI_PDF_PAGES_PER_CALL", "3")),
        )

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def parse(self, pdf_path: Path | str, page_numbers: list[int] | None = None) -> ParsedDocument:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")

        pdf = Path(pdf_path)
        reader = PdfReader(str(pdf))
        total_pages = len(reader.pages)
        selected_pages = page_numbers or list(range(1, total_pages + 1))

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        ensure_parse_schema(conn)
        try:
            cur = conn.execute(
                """
                INSERT INTO rfp_document (document_name, file_path, total_pages, parse_status, parse_warning_count)
                VALUES (?, ?, ?, 'gpt_running', 0)
                """,
                (pdf.name, str(pdf), total_pages),
            )
            document_id = int(cur.lastrowid)
            pages: list[CandidatePage] = []
            for chunk in chunked(selected_pages, self.config.pages_per_call):
                chunk_path = write_pdf_pages(reader, chunk)
                try:
                    extracted = self.extract_chunk(chunk_path, chunk)
                finally:
                    chunk_path.unlink(missing_ok=True)
                if not extracted:
                    raise RuntimeError(
                        f"GPT parser returned no pages for PDF page chunk {chunk}. "
                        "Check raw response logs or reduce --pages-per-call."
                    )
                for page in extracted:
                    pages.append(page)

            pages = fill_missing_rfp_printed_page_numbers(pages)
            for page in pages:
                insert_page(conn, document_id, page)
            conn.commit()

            warning_count = sum(1 for page in pages if page.parser_warning)
            status = "warning" if warning_count else "ok"
            conn.execute(
                "UPDATE rfp_document SET parse_status = ?, parse_warning_count = ? WHERE id = ?",
                (status, warning_count, document_id),
            )
            conn.commit()
            return ParsedDocument(document_id, pdf.name, pdf, total_pages, status, pages)
        finally:
            conn.close()

    def load(self, document_id: int) -> ParsedDocument:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        ensure_parse_schema(conn)
        try:
            doc = conn.execute("SELECT * FROM rfp_document WHERE id = ?", (document_id,)).fetchone()
            if doc is None:
                raise RuntimeError(f"document_id not found: {document_id}")
            rows = conn.execute(
                """
                SELECT page_no, page_text, text_length, rfp_printed_page_no, has_table_candidate,
                       has_attachment_candidate, has_eval_table_candidate,
                       has_toc_candidate, has_blind_candidate,
                       has_commercial_sw_candidate, parser_warning
                FROM rfp_page
                WHERE document_id = ?
                ORDER BY page_no
                """,
                (document_id,),
            ).fetchall()
            pages = dedupe_pages([row_to_candidate(row) for row in rows])
            pages = fill_missing_rfp_printed_page_numbers(pages)
            return ParsedDocument(
                document_id=int(doc["id"]),
                document_name=str(doc["document_name"]),
                pdf_path=Path(doc["file_path"]) if doc["file_path"] else None,
                total_pages=int(doc["total_pages"]),
                parse_status=str(doc["parse_status"]),
                pages=pages,
            )
        finally:
            conn.close()

    def extract_chunk(self, chunk_path: Path, page_numbers: list[int]) -> list[CandidatePage]:
        payload = {
            "model": self.config.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "filename": chunk_path.name,
                            "file_data": pdf_to_data_url(chunk_path),
                        },
                        {"type": "input_text", "text": build_prompt(page_numbers)},
                    ],
                }
            ],
            "temperature": 0,
        }
        response = post_json(
            "https://api.openai.com/v1/responses",
            payload,
            self.api_key or "",
            self.config.timeout_seconds,
            self.config.max_retries,
        )
        response_text = extract_response_text(response)
        if self.config.raw_output_dir:
            self.config.raw_output_dir.mkdir(parents=True, exist_ok=True)
            raw_path = self.config.raw_output_dir / f"gpt_parser_pages_{page_numbers[0]}_{page_numbers[-1]}.json"
            raw_path.write_text(
                json.dumps(
                    {
                        "requested_pages": page_numbers,
                        "response": response,
                        "output_text": response_text,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        data = parse_json_object(response_text)
        page_items = extract_page_items(data)
        pages: list[CandidatePage] = []
        seen_page_numbers: set[int] = set()
        for idx, item in enumerate(page_items):
            page_text = str(item.get("page_text", "")).strip()
            tables_markdown = str(item.get("tables_markdown", "")).strip()
            combined = page_text
            if tables_markdown:
                combined = f"{page_text}\n\n[표 추출]\n{tables_markdown}".strip()
            raw_page_no = item.get("pdf_page_no", item.get("page_no"))
            page_no = normalized_chunk_page_no(raw_page_no, idx, page_numbers, seen_page_numbers)
            pages.append(
                CandidatePage(
                    page_no=page_no,
                    page_text=combined,
                    text_length=len(combined.replace(" ", "").replace("\n", "")),
                    rfp_printed_page_no=parse_optional_int(item.get("rfp_printed_page_no")),
                    has_table_candidate=bool(item.get("has_table_candidate", False)),
                    has_attachment_candidate=bool(item.get("has_attachment_candidate", False)),
                    has_eval_table_candidate=bool(item.get("has_eval_table_candidate", False)),
                    has_toc_candidate=bool(item.get("has_toc_candidate", False)),
                    has_blind_candidate=bool(item.get("has_blind_candidate", False)),
                    has_commercial_sw_candidate=bool(item.get("has_commercial_sw_candidate", False)),
                    parser_warning=item.get("parser_warning"),
                )
            )
        return pages


def normalized_chunk_page_no(
    raw_page_no: object,
    index: int,
    page_numbers: list[int],
    seen_page_numbers: set[int],
) -> int:
    fallback = page_numbers[min(index, len(page_numbers) - 1)]
    try:
        page_no = int(raw_page_no)
    except (TypeError, ValueError):
        page_no = fallback
    if page_no not in page_numbers or page_no in seen_page_numbers:
        page_no = fallback
    seen_page_numbers.add(page_no)
    return page_no


def parse_optional_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        text = str(value).strip()
        match = re.search(r"\d{1,4}", text)
        return int(match.group(0)) if match else None
    except (TypeError, ValueError):
        return None


def fill_missing_rfp_printed_page_numbers(pages: list[CandidatePage]) -> list[CandidatePage]:
    anchors = {
        page.page_no: page.rfp_printed_page_no
        for page in pages
        if page.rfp_printed_page_no is not None
    }
    if not anchors:
        return pages

    for page in sorted(pages, key=lambda item: item.page_no):
        if page.rfp_printed_page_no is not None:
            continue
        candidates = [
            printed + (page.page_no - page_no)
            for page_no, printed in anchors.items()
            if printed + (page.page_no - page_no) > 0
        ]
        if candidates:
            page.rfp_printed_page_no = min(candidates, key=lambda value: abs(value - page.page_no))
    return pages


def ensure_parse_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS rfp_document (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_name TEXT NOT NULL,
            file_path TEXT,
            total_pages INTEGER NOT NULL,
            parse_status TEXT NOT NULL,
            parse_warning_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS rfp_page (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            page_no INTEGER NOT NULL,
            page_text TEXT,
            text_length INTEGER NOT NULL,
            rfp_printed_page_no INTEGER,
            has_table_candidate INTEGER NOT NULL DEFAULT 0,
            has_attachment_candidate INTEGER NOT NULL DEFAULT 0,
            has_eval_table_candidate INTEGER NOT NULL DEFAULT 0,
            has_toc_candidate INTEGER NOT NULL DEFAULT 0,
            has_blind_candidate INTEGER NOT NULL DEFAULT 0,
            has_commercial_sw_candidate INTEGER NOT NULL DEFAULT 0,
            image_count INTEGER NOT NULL DEFAULT 0,
            parser_warning TEXT,
            FOREIGN KEY (document_id) REFERENCES rfp_document(id)
        );
        CREATE INDEX IF NOT EXISTS idx_rfp_page_document_page
            ON rfp_page(document_id, page_no);
        """
    )
    ensure_column(conn, "rfp_page", "rfp_printed_page_no", "INTEGER")
    conn.commit()


def ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str) -> None:
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")]
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def insert_page(conn: sqlite3.Connection, document_id: int, page: CandidatePage) -> None:
    conn.execute(
        """
        INSERT INTO rfp_page (
            document_id, page_no, page_text, text_length, rfp_printed_page_no,
            has_table_candidate, has_attachment_candidate, has_eval_table_candidate,
            has_toc_candidate, has_blind_candidate, has_commercial_sw_candidate,
            image_count, parser_warning
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            document_id,
            page.page_no,
            page.page_text,
            page.text_length,
            page.rfp_printed_page_no,
            int(page.has_table_candidate),
            int(page.has_attachment_candidate),
            int(page.has_eval_table_candidate),
            int(page.has_toc_candidate),
            int(page.has_blind_candidate),
            int(page.has_commercial_sw_candidate),
            page.parser_warning,
        ),
    )


def row_to_candidate(row: sqlite3.Row) -> CandidatePage:
    return CandidatePage(
        page_no=int(row["page_no"]),
        page_text=str(row["page_text"] or ""),
        text_length=int(row["text_length"] or 0),
        rfp_printed_page_no=parse_optional_int(row["rfp_printed_page_no"]) if "rfp_printed_page_no" in row.keys() else None,
        has_table_candidate=bool(row["has_table_candidate"]),
        has_attachment_candidate=bool(row["has_attachment_candidate"]),
        has_eval_table_candidate=bool(row["has_eval_table_candidate"]),
        has_toc_candidate=bool(row["has_toc_candidate"]),
        has_blind_candidate=bool(row["has_blind_candidate"]),
        has_commercial_sw_candidate=bool(row["has_commercial_sw_candidate"]),
        parser_warning=row["parser_warning"],
    )


def extract_page_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    pages = data.get("pages")
    if isinstance(pages, list):
        return [item for item in pages if isinstance(item, dict)]

    output_schema = data.get("output_schema")
    if isinstance(output_schema, dict) and isinstance(output_schema.get("pages"), list):
        return [item for item in output_schema["pages"] if isinstance(item, dict)]

    nested = data.get("result")
    if isinstance(nested, dict) and isinstance(nested.get("pages"), list):
        return [item for item in nested["pages"] if isinstance(item, dict)]

    return []


def build_prompt(page_numbers: list[int]) -> str:
    return SYSTEM_PROMPT + "\n\n" + json.dumps(
        {
            "task": "RFP PDF page parsing",
            "page_numbers_in_this_file": page_numbers,
            "output_schema": {
                "pages": [
                    {
                        "pdf_page_no": "반드시 page_numbers_in_this_file 중 하나인 PDF 물리 페이지 번호",
                        "rfp_printed_page_no": "문서 본문에 인쇄된 쪽수의 숫자만. 예: '제안요청서 p.57', '- 57 -', '57쪽'은 모두 57. 없으면 null. PDF 물리 페이지 번호가 아님.",
                        "section_heading": "페이지 대표 장/절 제목. 예: Ⅰ. 사업 개요, 1. 제안개요",
                        "page_text": "페이지에서 보이는 본문 텍스트. 표 본문도 누락하지 말 것.",
                        "tables_markdown": "표가 있으면 Markdown table. 없으면 빈 문자열.",
                        "has_table_candidate": "boolean",
                        "has_attachment_candidate": "boolean",
                        "has_eval_table_candidate": "boolean",
                        "has_toc_candidate": "boolean",
                        "has_blind_candidate": "boolean",
                        "has_commercial_sw_candidate": "boolean",
                        "parser_warning": "문제 없으면 null",
                    }
                ]
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def chunked(values: list[int], size: int) -> list[list[int]]:
    return [values[idx : idx + size] for idx in range(0, len(values), size)]


def write_pdf_pages(reader: PdfReader, page_numbers: list[int]) -> Path:
    writer = PdfWriter()
    for page_no in page_numbers:
        page = reader.pages[page_no - 1]
        if "/Annots" in page:
            del page["/Annots"]
        writer.add_page(page)
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=f"_pages_{page_numbers[0]}_{page_numbers[-1]}.pdf")
    path = Path(handle.name)
    handle.close()
    with path.open("wb") as f:
        writer.write(f)
    return path


def pdf_to_data_url(pdf_path: Path) -> str:
    data = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
    return f"data:application/pdf;base64,{data}"


def post_json(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout_seconds: int,
    max_retries: int = 2,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < max_retries:
                wait = retry_after_seconds(exc, attempt)
                time.sleep(wait)
                continue
            raise RuntimeError(f"OpenAI API call failed: HTTP {exc.code} {body}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt >= max_retries:
                raise RuntimeError(
                    f"OpenAI API call timed out or failed after {max_retries + 1} attempts. "
                    f"Increase --timeout-seconds or reduce --pages-per-call. Last error: {exc}"
                ) from exc
            time.sleep(2**attempt)
    raise RuntimeError("OpenAI API call failed unexpectedly.")


def retry_after_seconds(exc: urllib.error.HTTPError, attempt: int) -> float:
    retry_after = exc.headers.get("retry-after") if exc.headers else None
    if retry_after:
        try:
            return min(60.0, max(1.0, float(retry_after)))
        except ValueError:
            pass
    return min(60.0, 5.0 * (2**attempt))
