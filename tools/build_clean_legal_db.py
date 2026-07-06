from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.rag_agent import RagAgent, documents_from_legal_tables, insert_rag_document


LEGAL_TABLES = ["legal_item", "legal_requirement", "legal_reference_example"]
OPTIONAL_LEGAL_TABLES = ["legal_tacit_knowledge"]
TITLE_CORRECTIONS = {
    "10": "협상에 의한 계약 방식 적용\n(또는 경쟁적 대화에 의한 계약방식 적용)",
}


def copy_table(source: sqlite3.Connection, target: sqlite3.Connection, table_name: str) -> None:
    ddl_row = source.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    if ddl_row is None:
        raise RuntimeError(f"Source table not found: {table_name}")
    target.execute(ddl_row[0])

    columns = [row[1] for row in source.execute(f"PRAGMA table_info({table_name})")]
    quoted = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    rows = source.execute(f"SELECT {quoted} FROM {table_name}").fetchall()
    if rows:
        target.executemany(
            f"INSERT INTO {table_name} ({quoted}) VALUES ({placeholders})",
            [tuple(row) for row in rows],
        )


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def build_clean_legal_db(source_db: Path, target_db: Path) -> dict[str, int]:
    if target_db.exists():
        target_db.unlink()

    source = sqlite3.connect(source_db)
    source.row_factory = sqlite3.Row
    target = sqlite3.connect(target_db)
    target.row_factory = sqlite3.Row
    try:
        counts: dict[str, int] = {}
        for table in LEGAL_TABLES:
            copy_table(source, target, table)
            counts[table] = target.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in OPTIONAL_LEGAL_TABLES:
            if table_exists(source, table):
                copy_table(source, target, table)
                counts[table] = target.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        apply_clean_corrections(target)
        target.commit()

        rag = RagAgent(target_db)
        rag.ensure_schema()
        docs = documents_from_legal_tables(target)
        for doc in docs:
            insert_rag_document(target, doc)
        target.commit()
        counts["rag_document"] = target.execute("SELECT count(*) FROM rag_document").fetchone()[0]
        return counts
    finally:
        source.close()
        target.close()


def apply_clean_corrections(conn: sqlite3.Connection) -> None:
    for item_no, title in TITLE_CORRECTIONS.items():
        conn.execute(
            "UPDATE legal_item SET title = ? WHERE item_no = ?",
            (title, item_no),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build clean legal criteria DB from existing legal tables only.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    counts = build_clean_legal_db(args.source, args.target)
    for table, count in counts.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
