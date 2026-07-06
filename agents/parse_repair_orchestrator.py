from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

from agents.audit_agent import ParseAuditAgent
from agents.gpt_parser_agent import GptParserAgent, ensure_parse_schema, insert_page
from agents.models import CandidatePage, ParsedDocument
from agents.page_selection import dedupe_pages

REPAIR_REQUIRED_WARNING_TYPES = {
    "empty_page",
    "table_page_empty",
    "critical_content_missing",
    "page_number_mismatch",
    "missing_page",
    "json_parse_failed",
}

REPAIR_PARSER_WARNING_KEYWORDS = [
    "텍스트 추출 불가",
    "OCR",
    "이미지 기반",
    "내용 없음",
    "인식 불가",
    "no pages",
    "empty",
]


class ParseRepairOrchestrator:
    def __init__(
        self,
        parser: GptParserAgent,
        auditor: ParseAuditAgent,
        max_rounds: int = 1,
    ) -> None:
        self.parser = parser
        self.auditor = auditor
        self.max_rounds = max_rounds

    def parse_audit_repair(self, pdf_path: Path | str, page_numbers: list[int] | None = None) -> ParsedDocument:
        document = self.parser.parse(pdf_path, page_numbers=page_numbers)
        audited = self.auditor.audit(document)

        for _round in range(self.max_rounds):
            bad_pages = collect_bad_pages(audited)
            if not bad_pages:
                break
            repaired = self.parser.parse(pdf_path, page_numbers=bad_pages)
            sync_pages_to_document(self.parser.db_path, audited.document_id, repaired.pages)
            audited = replace_pages(audited, repaired.pages)
            audited.audit_warnings = []
            audited.audit_score = None
            audited = self.auditor.audit(audited)

        return audited


def collect_bad_pages(document: ParsedDocument) -> list[int]:
    bad_pages = {
        page.page_no
        for page in document.pages
        if page.text_length == 0 or is_repair_required_parser_warning(page.parser_warning)
    }
    for warning in document.audit_warnings:
        if warning.page_no and warning.warning_type in REPAIR_REQUIRED_WARNING_TYPES:
            bad_pages.add(warning.page_no)
        elif warning.page_no and warning.warning_type == "parser_warning" and is_repair_required_parser_warning(
            warning.message
        ):
            bad_pages.add(warning.page_no)
    return sorted(bad_pages)


def is_repair_required_parser_warning(message: str | None) -> bool:
    if not message:
        return False
    normalized = str(message).lower()
    return any(keyword.lower() in normalized for keyword in REPAIR_PARSER_WARNING_KEYWORDS)


def replace_pages(document: ParsedDocument, repaired_pages: list[CandidatePage]) -> ParsedDocument:
    repaired_by_no = {page.page_no: page for page in repaired_pages}
    merged_pages = [
        repaired_by_no.get(page.page_no, page)
        for page in sorted(document.pages, key=lambda item: item.page_no)
    ]
    existing = {page.page_no for page in merged_pages}
    for page in repaired_pages:
        if page.page_no not in existing:
            merged_pages.append(page)
    return replace(document, pages=dedupe_pages(merged_pages))


def sync_pages_to_document(db_path: Path | str, document_id: int, repaired_pages: list[CandidatePage]) -> None:
    if not repaired_pages:
        return
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_parse_schema(conn)
    try:
        for page in dedupe_pages(repaired_pages):
            conn.execute(
                "DELETE FROM rfp_page WHERE document_id = ? AND page_no = ?",
                (document_id, page.page_no),
            )
            insert_page(conn, document_id, page)
        conn.execute(
            """
            UPDATE rfp_document
            SET parse_warning_count = (
                SELECT count(*) FROM rfp_page
                WHERE document_id = ? AND parser_warning IS NOT NULL
            )
            WHERE id = ?
            """,
            (document_id, document_id),
        )
        conn.commit()
    finally:
        conn.close()
