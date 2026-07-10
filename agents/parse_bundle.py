from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

from agents.gpt_parser_agent import (
    ensure_parse_schema,
    fill_missing_rfp_printed_page_numbers,
    infer_table_candidates,
    insert_page,
    row_to_candidate,
)
from agents.models import CandidatePage, ParsedDocument


PARSER_VERSION = "chunk-proxy-poc-v0.1"


def candidate_page_from_dict(data: dict[str, Any]) -> CandidatePage:
    page_text = str(data.get("page_text") or "")
    return CandidatePage(
        page_no=int(data["page_no"]),
        page_text=page_text,
        text_length=int(data.get("text_length") or len(page_text.replace(" ", "").replace("\n", ""))),
        rfp_printed_page_no=parse_optional_int(data.get("rfp_printed_page_no")),
        has_table_candidate=bool(data.get("has_table_candidate", False)),
        has_attachment_candidate=bool(data.get("has_attachment_candidate", False)),
        has_eval_table_candidate=bool(data.get("has_eval_table_candidate", False)),
        has_toc_candidate=bool(data.get("has_toc_candidate", False)),
        has_blind_candidate=bool(data.get("has_blind_candidate", False)),
        has_commercial_sw_candidate=bool(data.get("has_commercial_sw_candidate", False)),
        parser_warning=data.get("parser_warning"),
    )


def candidate_page_to_dict(page: CandidatePage) -> dict[str, Any]:
    return {
        "page_no": page.page_no,
        "page_text": page.page_text,
        "text_length": page.text_length,
        "rfp_printed_page_no": page.rfp_printed_page_no,
        "has_table_candidate": page.has_table_candidate,
        "has_attachment_candidate": page.has_attachment_candidate,
        "has_eval_table_candidate": page.has_eval_table_candidate,
        "has_toc_candidate": page.has_toc_candidate,
        "has_blind_candidate": page.has_blind_candidate,
        "has_commercial_sw_candidate": page.has_commercial_sw_candidate,
        "parser_warning": page.parser_warning,
    }


def write_parse_bundle(
    bundle_path: Path,
    *,
    document_name: str,
    total_pages: int,
    pages: list[CandidatePage],
    meta: dict[str, Any] | None = None,
) -> None:
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    meta_data = {
        "document_name": document_name,
        "total_pages": total_pages,
        "parser_version": PARSER_VERSION,
        **(meta or {}),
    }
    jsonl = "\n".join(json.dumps(candidate_page_to_dict(page), ensure_ascii=False) for page in pages)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("parse_meta.json", json.dumps(meta_data, ensure_ascii=False, indent=2))
        archive.writestr("parsed_pages.jsonl", jsonl + ("\n" if jsonl else ""))


def load_parse_bundle(bundle_path: Path) -> tuple[dict[str, Any], list[CandidatePage]]:
    with zipfile.ZipFile(bundle_path) as archive:
        meta = json.loads(archive.read("parse_meta.json").decode("utf-8-sig"))
        lines = archive.read("parsed_pages.jsonl").decode("utf-8-sig").splitlines()

    pages = [
        candidate_page_from_dict(json.loads(line))
        for line in lines
        if line.strip()
    ]
    if not pages:
        raise ValueError("parse bundle has no parsed pages")
    return meta, pages


def import_parse_bundle_to_db(bundle_path: Path, db_path: Path | str) -> ParsedDocument:
    meta, pages = load_parse_bundle(bundle_path)
    return import_pages_to_db(
        db_path,
        document_name=str(meta.get("document_name") or bundle_path.stem),
        total_pages=int(meta.get("total_pages") or max(page.page_no for page in pages)),
        pages_data=[candidate_page_to_dict(page) for page in pages],
        file_path=str(bundle_path),
    )


def import_pages_to_db(
    db_path: Path | str,
    *,
    document_name: str,
    total_pages: int,
    pages_data: list[dict[str, Any]],
    file_path: str | None = None,
) -> ParsedDocument:
    pages = [candidate_page_from_dict(data) for data in pages_data]
    pages = fill_missing_rfp_printed_page_numbers(sorted(pages, key=lambda page: page.page_no))
    infer_table_candidates(pages)
    warning_count = sum(1 for page in pages if page.parser_warning)
    parse_status = "warning" if warning_count else "ok"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        ensure_parse_schema(conn)
        cur = conn.execute(
            """
            INSERT INTO rfp_document (document_name, file_path, total_pages, parse_status, parse_warning_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (document_name, file_path, total_pages, parse_status, warning_count),
        )
        document_id = int(cur.lastrowid)
        for page in pages:
            insert_page(conn, document_id, page)
        conn.commit()
    finally:
        conn.close()

    return ParsedDocument(
        document_id=document_id,
        document_name=document_name,
        pdf_path=None,
        total_pages=total_pages,
        parse_status=parse_status,
        pages=pages,
    )


def replace_document_pages_in_db(
    db_path: Path | str,
    *,
    document_id: int,
    pages_data: list[dict[str, Any]],
) -> ParsedDocument:
    replacement_pages = [candidate_page_from_dict(data) for data in pages_data]
    if not replacement_pages:
        raise ValueError("pages_data cannot be empty")

    page_numbers = sorted({page.page_no for page in replacement_pages})
    infer_table_candidates(replacement_pages)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        ensure_parse_schema(conn)
        doc = conn.execute("SELECT * FROM rfp_document WHERE id = ?", (document_id,)).fetchone()
        if doc is None:
            raise ValueError(f"document_id not found: {document_id}")

        placeholders = ",".join("?" for _ in page_numbers)
        conn.execute(
            f"DELETE FROM rfp_page WHERE document_id = ? AND page_no IN ({placeholders})",
            (document_id, *page_numbers),
        )
        for page in sorted(replacement_pages, key=lambda item: item.page_no):
            insert_page(conn, document_id, page)

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
        pages = [row_to_candidate(row) for row in rows]
        warning_count = sum(1 for page in pages if page.parser_warning)
        parse_status = "warning" if warning_count else "ok"
        conn.execute(
            "UPDATE rfp_document SET parse_status = ?, parse_warning_count = ? WHERE id = ?",
            (parse_status, warning_count, document_id),
        )
        conn.commit()
    finally:
        conn.close()

    return ParsedDocument(
        document_id=document_id,
        document_name=str(doc["document_name"]),
        pdf_path=None,
        total_pages=int(doc["total_pages"]),
        parse_status=parse_status,
        pages=pages,
    )


def parse_optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
