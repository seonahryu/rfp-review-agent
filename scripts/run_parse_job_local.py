from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.parse_job_orchestrator import ParseJobRunner


def parse_page_spec(value: str) -> list[int] | None:
    text = str(value or "").strip()
    if not text:
        return None
    pages: list[int] = []
    for part in text.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text.strip())
            end = int(end_text.strip())
            step = 1 if start <= end else -1
            pages.extend(range(start, end + step, step))
        else:
            pages.append(int(token))
    return pages


def export_parsed_pages(
    db_path: Path,
    document_id: int,
    export_path: Path,
    created: dict,
    finished: dict,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT page_no, rfp_printed_page_no, page_text, text_length,
                   has_table_candidate, has_attachment_candidate, has_eval_table_candidate,
                   has_toc_candidate, has_blind_candidate, has_commercial_sw_candidate,
                   parser_warning
            FROM rfp_page
            WHERE document_id = ?
            ORDER BY page_no
            """,
            (document_id,),
        ).fetchall()
    finally:
        conn.close()

    sources = load_page_sources(db_path, str(finished.get("job_id", "")))
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(
        json.dumps(
            {
                "created": created,
                "finished": finished,
                "pages": [
                    {
                        "page_no": row["page_no"],
                        "rfp_printed_page_no": row["rfp_printed_page_no"],
                        "page_text": row["page_text"],
                        "text_length": row["text_length"],
                        "source": sources.get(int(row["page_no"]), ""),
                        "flags": {
                            "has_table_candidate": bool(row["has_table_candidate"]),
                            "has_requirement_table_candidate": is_requirement_table_text(row["page_text"]),
                            "has_attachment_candidate": bool(row["has_attachment_candidate"]),
                            "has_eval_table_candidate": bool(row["has_eval_table_candidate"]),
                            "has_toc_candidate": bool(row["has_toc_candidate"]),
                            "has_blind_candidate": bool(row["has_blind_candidate"]),
                            "has_commercial_sw_candidate": bool(row["has_commercial_sw_candidate"]),
                        },
                        "parser_warning": row["parser_warning"],
                    }
                    for row in rows
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def is_requirement_table_text(value: object) -> bool:
    compact = "".join(str(value or "").split())
    signals = [
        "요구사항구분",
        "요구사항분류",
        "고유번호",
        "요구사항명",
        "요구사항명칭",
        "요구사항상세설명",
    ]
    return sum(1 for signal in signals if signal in compact) >= 2


def load_page_sources(db_path: Path, job_id: str) -> dict[int, str]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'parse_job_page'"
        ).fetchone()
        if table is None:
            return {}
        rows = conn.execute(
            "SELECT page_no, source FROM parse_job_page WHERE job_id = ?",
            (job_id,),
        ).fetchall()
        return {int(row["page_no"]): str(row["source"] or "") for row in rows}
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the experimental checkpointed GPT PDF parser locally."
    )
    parser.add_argument("--pdf", required=True, help="PDF file to parse")
    parser.add_argument("--db", default="rfp 법제도 검토항목.db", help="SQLite DB path")
    parser.add_argument(
        "--pages-per-chunk",
        type=int,
        default=None,
        help="Pages per GPT call. Defaults to OPENAI_PDF_PAGES_PER_CALL or 1.",
    )
    parser.add_argument(
        "--pages",
        default="",
        help="Optional PDF pages to parse, e.g. 1-3,12,40-45. Defaults to every page.",
    )
    parser.add_argument(
        "--export-json",
        default="",
        help="Optional path to write parsed page text as JSON after the job finishes.",
    )
    parser.add_argument(
        "--hybrid",
        action="store_true",
        help="Use Python pre-scan first and call GPT only for pages that need visual/table/legal parsing.",
    )
    args = parser.parse_args()

    runner = ParseJobRunner(
        db_path=Path(args.db),
        pages_per_chunk=args.pages_per_chunk,
        hybrid=args.hybrid,
    )
    created = runner.create_job(Path(args.pdf), parse_page_spec(args.pages))
    print(json.dumps({"created": created.to_dict()}, ensure_ascii=False, indent=2))

    finished = runner.run_job(created.job_id)
    finished_data = finished.to_dict()
    print(json.dumps({"finished": finished_data}, ensure_ascii=False, indent=2))
    if args.export_json:
        export_path = Path(args.export_json)
        export_parsed_pages(Path(args.db), finished.document_id, export_path, created.to_dict(), finished_data)
        print(json.dumps({"export_json": str(export_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
