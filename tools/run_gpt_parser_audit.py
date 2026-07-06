from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.audit_agent import ParseAuditAgent
from agents.audit_agent import audit_quality_summary
from agents.gpt_parser_agent import GptParserAgent, GptParserConfig
from agents.llm_client import OpenAILowCostClient
from agents.parse_repair_orchestrator import ParseRepairOrchestrator, collect_bad_pages


def parse_pages(value: str | None) -> list[int] | None:
    if not value:
        return None
    pages: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = [int(x.strip()) for x in part.split("-", 1)]
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def main() -> None:
    parser = argparse.ArgumentParser(description="GPT-4.1 PDF parser + Python parser audit")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--db", type=Path, default=Path("gpt41_parser_audit.db"))
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument(
        "--audit-model",
        default=None,
        help="파서 검증용 약한 GPT 모델. 기본값: OPENAI_PARSE_AUDIT_MODEL, 없으면 OPENAI_LOW_MODEL, 없으면 gpt-4.1-mini",
    )
    parser.add_argument("--pages", help="테스트할 페이지. 예: 1-5,9,10. 생략하면 전체 PDF")
    parser.add_argument("--pages-per-call", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=360)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--raw-output-dir", type=Path, default=Path("gpt_parser_raw"))
    parser.add_argument("--no-gpt-audit", action="store_true")
    parser.add_argument("--repair-rounds", type=int, default=1)
    parser.add_argument("--json", type=Path, default=Path("gpt41_parser_audit.json"))
    args = parser.parse_args()

    agent = GptParserAgent(
        db_path=args.db,
        config=GptParserConfig(
            model=args.model,
            pages_per_call=args.pages_per_call,
            timeout_seconds=args.timeout_seconds,
            max_retries=args.max_retries,
            raw_output_dir=args.raw_output_dir,
        ),
    )
    audit_model = args.audit_model or os.getenv("OPENAI_PARSE_AUDIT_MODEL") or os.getenv("OPENAI_LOW_MODEL") or "gpt-4.1-mini"
    audit_client = OpenAILowCostClient(
        low_model=audit_model,
        role_models={"parse_audit": audit_model},
    )
    auditor = ParseAuditAgent(llm_client=audit_client, use_gpt=not args.no_gpt_audit)
    repair_orchestrator = ParseRepairOrchestrator(
        parser=agent,
        auditor=auditor,
        max_rounds=max(0, args.repair_rounds),
    )
    audited = repair_orchestrator.parse_audit_repair(args.pdf, page_numbers=parse_pages(args.pages))
    unresolved_bad_pages = collect_bad_pages(audited)
    quality = audit_quality_summary(audited.total_pages, audited.audit_warnings)
    summary = {
        "parser": "gpt",
        "model": args.model,
        "audit": "python+gpt" if audit_client.is_configured() and not args.no_gpt_audit else "python",
        "audit_model": audit_model if audit_client.is_configured() and not args.no_gpt_audit else None,
        "db": str(args.db),
        "document_id": audited.document_id,
        "document_name": audited.document_name,
        "total_pages": audited.total_pages,
        "parsed_pages": [page.page_no for page in audited.pages],
        "parse_status": audited.parse_status,
        "audit_score": audited.audit_score,
        "audit_warning_count": len(audited.audit_warnings),
        "affected_page_count": quality["affected_page_count"],
        "all_affected_page_count": quality["all_affected_page_count"],
        "critical_page_count": quality["critical_page_count"],
        "high_severity_page_count": quality["high_severity_page_count"],
        "affected_ratio": quality["affected_ratio"],
        "warnings": [warning.__dict__ for warning in audited.audit_warnings],
        "repair_rounds": args.repair_rounds,
        "unresolved_parse_pages": unresolved_bad_pages,
        "text_usability": {
            "parsed_page_count": len(audited.pages),
            "expected_page_count": len(parse_pages(args.pages) or list(range(1, audited.total_pages + 1))),
            "low_or_empty_pages": [page.page_no for page in audited.pages if page.text_length < 30],
            "pages_with_parser_warning": [page.page_no for page in audited.pages if page.parser_warning],
        },
        "debug_metadata": {
            "table_candidate_pages": [page.page_no for page in audited.pages if page.has_table_candidate],
            "eval_table_candidate_pages": [page.page_no for page in audited.pages if page.has_eval_table_candidate],
            "attachment_candidate_pages": [page.page_no for page in audited.pages if page.has_attachment_candidate],
        },
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
