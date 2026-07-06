from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.compliance_content_agent import ComplianceContentAgent
from agents.models import FinalReview, RagContext, RagHit, ReviewResult


DEFAULT_INPUT_GLOB = "output/second_review_*.json"
DEFAULT_JSON_OUTPUT = Path("output/second_review_content_test_report.json")
DEFAULT_XLSX_OUTPUT = Path("output/second_review_content_test_report.xlsx")


def build_report_rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    content_agent = ComplianceContentAgent()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not is_source_review_payload(payload):
            continue
        rag_by_item = rag_contexts_by_item(payload)
        route_by_item = routes_by_item(payload)
        for raw_review in payload.get("merged_final_reviews", []):
            review = final_review_from_dict(raw_review)
            rag = rag_by_item.get(str(review.item_no), RagContext(item_no=str(review.item_no)))
            content = content_agent.generate(review, rag)
            rows.append(
                {
                    "source_file": path.name,
                    "group": payload.get("group", ""),
                    "item_no": review.item_no,
                    "route": route_by_item.get(str(review.item_no), ""),
                    "final_status": review.final_status,
                    "final_result": review.final_result,
                    "is_target": review.is_target,
                    "confidence": review.confidence,
                    "raw_evidence_pages": join_values(review.evidence_pages),
                    "selected_content_pages": join_values(content.primary_evidence_pages),
                    "generated_content": content.compliance_content,
                    "content_warnings": join_values(content.warnings),
                    "reason": review.reason,
                    "recommendation": clean_report_recommendation(review.recommendation),
                    "rag_hit_count": len(rag.hits),
                    "tacit_knowledge_count": len([hit for hit in rag.hits if hit.source_type == "tacit_knowledge"]),
                    "pass_fail": "PASS" if content.compliance_content or content.warnings else "CHECK",
                }
            )
    return sorted(dedupe_rows_by_item_no(rows), key=report_row_sort_key)


def dedupe_rows_by_item_no(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_item: dict[str, dict[str, Any]] = {}
    for row in rows:
        item_no = str(row.get("item_no", ""))
        if not item_no:
            continue
        current = by_item.get(item_no)
        if current is None or row_quality_score(row) > row_quality_score(current):
            by_item[item_no] = row
    return list(by_item.values())


def row_quality_score(row: dict[str, Any]) -> tuple[int, int, int, float, int]:
    has_generated_content = 1 if str(row.get("generated_content", "")).strip() else 0
    has_selected_pages = 1 if str(row.get("selected_content_pages", "")).strip() else 0
    is_patch = 1 if "patch" in str(row.get("source_file", "")).lower() else 0
    confidence = safe_float(row.get("confidence"))
    source_rank = source_file_rank(str(row.get("source_file", "")))
    return (is_patch, has_generated_content, has_selected_pages, confidence, source_rank)


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def source_file_rank(source_file: str) -> int:
    if "rule_no_api" in source_file:
        return 4
    if "type3" in source_file:
        return 3
    if "type2" in source_file:
        return 2
    if "type1" in source_file:
        return 1
    return 0


def is_source_review_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("merged_final_reviews"), list)


def clean_report_recommendation(text: str) -> str:
    value = str(text or "").strip()
    if "->" in value:
        value = value.split("->", 1)[1].strip()
    return value


def report_row_sort_key(row: dict[str, Any]) -> tuple[int, int, str, str]:
    source_order = str(row.get("source_file", ""))
    item = str(row.get("item_no", ""))
    main, suffix = split_item_no(item)
    return (main, suffix, item, source_order)


def split_item_no(item_no: str) -> tuple[int, int]:
    match = re_item_no(item_no)
    if not match:
        return (9999, 9999)
    main = int(match.group(1))
    suffix = int(match.group(2) or 0)
    return (main, suffix)


def re_item_no(item_no: str):
    import re

    return re.match(r"^\s*(\d+)(?:-(\d+))?\s*$", item_no)


def final_review_from_dict(data: dict[str, Any]) -> FinalReview:
    allowed = {field.name for field in fields(FinalReview)}
    values = {key: value for key, value in data.items() if key in allowed and key != "reviews"}
    values["reviews"] = [review_result_from_dict(item) for item in data.get("reviews", [])]
    return FinalReview(**values)


def review_result_from_dict(data: dict[str, Any]) -> ReviewResult:
    allowed = {field.name for field in fields(ReviewResult)}
    values = {key: value for key, value in data.items() if key in allowed}
    return ReviewResult(**values)


def rag_contexts_by_item(payload: dict[str, Any]) -> dict[str, RagContext]:
    result: dict[str, RagContext] = {}
    for item in payload.get("item_results", []):
        item_no = str(item.get("item_no", ""))
        if not item_no:
            continue
        hits = [rag_hit_from_dict(hit) for hit in item.get("rag_hits", [])]
        result[item_no] = RagContext(item_no=item_no, hits=hits)
    if "2-1" in result and "2" not in result:
        result["2"] = result["2-1"]
    return result


def routes_by_item(payload: dict[str, Any]) -> dict[str, str]:
    result = {
        str(item.get("item_no", "")): str(item.get("route", ""))
        for item in payload.get("item_results", [])
        if item.get("item_no")
    }
    if "2-1" in result and "2" not in result:
        result["2"] = result["2-1"]
    return result


def rag_hit_from_dict(data: dict[str, Any]) -> RagHit:
    allowed = {field.name for field in fields(RagHit)}
    values = {key: value for key, value in data.items() if key in allowed}
    return RagHit(**values)


def write_json_report(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def write_xlsx_report(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "second_review_content"
    headers = list(rows[0].keys()) if rows else ["message"]
    ws.append(headers)
    if rows:
        for row in rows:
            ws.append([row.get(header, "") for header in headers])
    else:
        ws.append(["No rows"])
    for column in ws.columns:
        width = max(len(str(cell.value or "")) for cell in column)
        ws.column_dimensions[column[0].column_letter].width = min(max(width + 2, 12), 80)
    wb.save(path)


def join_values(values: list[Any]) -> str:
    return ", ".join(str(value) for value in values)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build compliance-content test report from second_review JSON outputs.")
    parser.add_argument("--input-glob", default=DEFAULT_INPUT_GLOB)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--xlsx-output", type=Path, default=DEFAULT_XLSX_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = sorted(Path().glob(args.input_glob))
    rows = build_report_rows(paths)
    write_json_report(rows, args.json_output)
    write_xlsx_report(rows, args.xlsx_output)
    print(f"inputs={len(paths)} rows={len(rows)}")
    print(f"json={args.json_output}")
    print(f"xlsx={args.xlsx_output}")


if __name__ == "__main__":
    main()
