from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.rag_agent import RagAgent


DEFAULT_ITEMS = [str(no) for no in range(1, 19)]
CONTAMINATION_MARKERS = ["[양식]", "피드백", "결과정리", "검토의견서_한국부동산원"]


def parse_items(value: str | None) -> list[str]:
    if not value:
        return DEFAULT_ITEMS
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 기준자료 coverage test")
    parser.add_argument("--db", type=Path, default=Path("clean_legal_rag.db"))
    parser.add_argument("--items", type=str, default=None)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--json", type=Path, default=Path("rag_coverage_report.json"))
    args = parser.parse_args()

    rag = RagAgent(args.db)
    rag.ensure_schema()
    rows = []
    contaminated_sources: set[str] = set()
    missing_items = []

    for item_no in parse_items(args.items):
        context = rag.context_for_item(item_no, limit=args.limit)
        sources = sorted({hit.source_name for hit in context.hits})
        for source in sources:
            if any(marker in source for marker in CONTAMINATION_MARKERS):
                contaminated_sources.add(source)
        if not context.hits:
            missing_items.append(item_no)
        rows.append(
            {
                "item_no": item_no,
                "hit_count": len(context.hits),
                "hit_item_nos": sorted({hit.item_no for hit in context.hits if hit.item_no}),
                "sources": sources,
                "sample_titles": [hit.title for hit in context.hits[:3]],
                "sample_snippets": [hit.snippet for hit in context.hits[:2]],
                "ok": bool(context.hits),
            }
        )

    report = {
        "db": str(args.db),
        "item_count": len(rows),
        "missing_items": missing_items,
        "contaminated_sources": sorted(contaminated_sources),
        "ok": not missing_items and not contaminated_sources,
        "items": rows,
    }
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
