from __future__ import annotations

import argparse
from pathlib import Path

from agents.gpt_parser_agent import ensure_parse_schema
from agents.rag_agent import RagAgent


def init_db(db_path: Path, excel_paths: list[Path] | None = None) -> int:
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        ensure_parse_schema(conn)
    finally:
        conn.close()

    rag = RagAgent(db_path)
    rag.ensure_schema()
    if excel_paths:
        return rag.rebuild_from_excels(excel_paths)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="RFP 검토 DB 초기화")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--excel", type=Path, action="append", default=[])
    args = parser.parse_args()
    count = init_db(args.db, args.excel)
    print(f"DB initialized: {args.db}")
    print(f"RAG documents: {count}")


if __name__ == "__main__":
    main()
