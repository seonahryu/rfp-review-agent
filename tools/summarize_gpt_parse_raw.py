from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.llm_client import extract_response_text, parse_json_object
from agents.gpt_parser_agent import extract_page_items


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize raw GPT PDF parser responses by page.")
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = []
    for path in sorted(args.raw_dir.glob("gpt_parser_pages_*.json"), key=sort_key):
        data = json.loads(path.read_text(encoding="utf-8"))
        response = data.get("response", data)
        text = data.get("output_text") or extract_response_text(response)
        try:
            parsed = parse_json_object(text)
            page_items = extract_page_items(parsed)
        except Exception as exc:
            rows.append(f"## {path.name}\n\nPARSE ERROR: {exc}\n")
            continue

        rows.append(f"## {path.name}\n")
        requested_pages = requested_pages_from_data(data, path, page_items)
        for idx, item in enumerate(page_items):
            page_text = str(item.get("page_text", "") or "")
            tables = str(item.get("tables_markdown", "") or "")
            gpt_reported_page_no = item.get("pdf_page_no", item.get("page_no"))
            effective_pdf_page_no = requested_pages[min(idx, len(requested_pages) - 1)] if requested_pages else None
            flags = [
                name
                for name in [
                    "has_table_candidate",
                    "has_eval_table_candidate",
                    "has_attachment_candidate",
                    "has_toc_candidate",
                    "has_blind_candidate",
                    "has_commercial_sw_candidate",
                ]
                if item.get(name)
            ]
            warning = item.get("parser_warning")
            rows.extend(
                [
                    f"### effective_pdf_page_no={effective_pdf_page_no}",
                    f"- gpt_reported_page_no: {gpt_reported_page_no}",
                    f"- rfp_printed_page_no: {item.get('rfp_printed_page_no', '-')}",
                    f"- section_heading: {item.get('section_heading', '-')}",
                    f"- text_chars: {len(page_text)}",
                    f"- tables_chars: {len(tables)}",
                    f"- flags: {', '.join(flags) if flags else '-'}",
                    f"- parser_warning: {warning or '-'}",
                    "",
                    "```text",
                    page_text[:1600],
                    "```",
                ]
            )
            if tables:
                rows.extend(["", "```markdown", tables[:1600], "```"])
            rows.append("")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(rows), encoding="utf-8")


def sort_key(path: Path) -> tuple[int, int]:
    stem = path.stem.replace("gpt_parser_pages_", "")
    parts = stem.split("_")
    try:
        return int(parts[0]), int(parts[-1])
    except (ValueError, IndexError):
        return 0, 0


def requested_pages_from_filename(path: Path) -> list[int]:
    start, end = sort_key(path)
    if start <= 0 or end < start:
        return []
    return list(range(start, end + 1))


def requested_pages_from_data(data: dict, path: Path, page_items: list[dict]) -> list[int]:
    explicit_pages = data.get("requested_pages")
    if isinstance(explicit_pages, list):
        parsed = [parse_int(value) for value in explicit_pages]
        if all(value is not None for value in parsed):
            return [int(value) for value in parsed]

    reported_pages = [parse_int(item.get("pdf_page_no", item.get("page_no"))) for item in page_items]
    if reported_pages and all(value is not None for value in reported_pages):
        values = [int(value) for value in reported_pages]
        if len(set(values)) == len(values):
            return values

    return requested_pages_from_filename(path)


def parse_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
