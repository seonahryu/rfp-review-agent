from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.attach_review_agent import AttachmentReviewAgent
from agents.audit_agent import ParseAuditAgent
from agents.llm_client import DisabledLlmClient, OpenAILowCostClient
from agents.llm_review_agent import LlmReviewAgent
from agents.models import CandidatePage, FinalReview, ParsedDocument, ReviewResult
from agents.rag_agent import RagAgent
from agents.review_router import route_item
from agents.rule_review_agent import RuleReviewAgent
from agents.table_review_agent import TableReviewAgent
from agents.verification_agent import VerificationAgent


DEFAULT_ITEM_NOS = [str(no) for no in range(1, 19)]


DEFAULT_GROUPS = {
    "rule_no_api": ["1", "3", "6", "7", "14"],
    "type1": ["11", "17", "9", "13"],
    "type2": ["2", "4", "12", "15"],
    "type3": ["5", "8", "10", "16", "18"],
}


class ResumeState:
    def __init__(
        self,
        *,
        item_results: list[dict[str, Any]],
        final_reviews: list[FinalReview],
        remaining_items: list[str],
    ) -> None:
        self.item_results = item_results
        self.final_reviews = final_reviews
        self.remaining_items = remaining_items


def parse_fail_review(item_no: str, document: ParsedDocument) -> FinalReview:
    problem_pages = sorted({warning.page_no for warning in document.audit_warnings if warning.page_no})[:10]
    warning_messages = [
        f"p.{warning.page_no}: {warning.warning_type} - {warning.message}"
        if warning.page_no
        else f"{warning.warning_type} - {warning.message}"
        for warning in document.audit_warnings[:10]
    ]
    review = ReviewResult(
        item_no=str(item_no),
        route_type="parse_gate",
        result="판단보류",
        is_target=None,
        confidence=0.0,
        evidence_pages=problem_pages,
        evidence_text=[],
        reason="PDF 파싱 상태가 fail이므로 법제도 검토를 자동 수행하지 않았습니다.",
        recommendation="파싱 오류 페이지를 보완한 뒤 RFP 검토를 다시 실행하세요.",
        needs_human_review=True,
        source="parse_status_gate",
        warnings=warning_messages,
        used_llm=False,
    )
    return FinalReview(
        item_no=str(item_no),
        final_status="파싱 문제로 판단 보류",
        final_result=review.result,
        is_target=None,
        confidence=0.0,
        evidence_pages=problem_pages,
        evidence_text=[],
        reason=review.reason,
        recommendation=review.recommendation,
        reviews=[review],
        warnings=warning_messages,
    )


def merge_final_reviews(final_reviews: list[FinalReview]) -> list[FinalReview]:
    by_item: dict[str, FinalReview] = {}
    order: list[str] = []
    for review in final_reviews:
        key = "2" if str(review.item_no) == "2-1" else str(review.item_no)
        normalized = review if key == str(review.item_no) else replace(review, item_no=key)
        if key not in by_item:
            by_item[key] = normalized
            order.append(key)
            continue
        by_item[key] = merge_two_final_reviews(by_item[key], normalized, key)
    return [by_item[key] for key in order]


def merge_two_final_reviews(left: FinalReview, right: FinalReview, item_no: str) -> FinalReview:
    chosen = max([left, right], key=lambda review: (result_rank(review.final_result), review.confidence))
    other = right if chosen is left else left
    evidence_pages = sorted(set(left.evidence_pages + right.evidence_pages))
    evidence_text = left.evidence_text + [text for text in right.evidence_text if text not in left.evidence_text]
    warnings = left.warnings + [warning for warning in right.warnings if warning not in left.warnings]
    return replace(
        chosen,
        item_no=item_no,
        evidence_pages=evidence_pages,
        evidence_text=evidence_text,
        reason=combine_text(chosen.reason, other.reason),
        recommendation=combine_text(chosen.recommendation, other.recommendation),
        reviews=left.reviews + right.reviews,
        warnings=warnings,
    )


def result_rank(result: str) -> int:
    text = str(result or "").strip()
    if text == "미준수":
        return 4
    if text == "보완필요":
        return 3
    if text == "확인필요":
        return 2
    if text == "준수":
        return 1
    if text == "해당없음":
        return 0
    return 1


def combine_text(*values: str) -> str:
    parts: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in parts:
            parts.append(text)
    return "\n".join(parts)


def load_resume_state(output_path: Path, item_nos: list[str]) -> ResumeState:
    if not output_path.exists():
        return ResumeState(item_results=[], final_reviews=[], remaining_items=item_nos)
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    requested = set(item_nos)
    item_results = [
        item
        for item in payload.get("item_results", [])
        if str(item.get("item_no")) in requested and isinstance(item.get("final"), dict)
    ]
    completed = {str(item.get("item_no")) for item in item_results}
    final_reviews = [final_review_from_dict(item["final"]) for item in item_results]
    remaining_items = [item_no for item_no in item_nos if item_no not in completed]
    return ResumeState(
        item_results=item_results,
        final_reviews=final_reviews,
        remaining_items=remaining_items,
    )


def final_review_from_dict(data: dict[str, Any]) -> FinalReview:
    return FinalReview(
        item_no=str(data.get("item_no", "")),
        final_status=str(data.get("final_status", "")),
        final_result=str(data.get("final_result", "")),
        is_target=data.get("is_target"),
        confidence=float(data.get("confidence", 0.0)),
        evidence_pages=[int(page) for page in data.get("evidence_pages", [])],
        evidence_text=[str(text) for text in data.get("evidence_text", [])],
        reason=str(data.get("reason", "")),
        recommendation=str(data.get("recommendation", "")),
        reviews=[],
        warnings=[str(warning) for warning in data.get("warnings", [])],
    )


def configure_utf8_output() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def load_candidate_pages(path: Path) -> list[CandidatePage]:
    pages: list[CandidatePage] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        obj = json.loads(line)
        pages.append(
            CandidatePage(
                page_no=int(obj["page_no"]),
                page_text=str(obj.get("page_text") or ""),
                text_length=int(obj.get("text_length") or 0),
                rfp_printed_page_no=parse_jsonl_page_no(obj.get("rfp_printed_page_no")),
                has_table_candidate=bool(obj.get("has_table_candidate")),
                has_attachment_candidate=bool(obj.get("has_attachment_candidate")),
                has_eval_table_candidate=bool(obj.get("has_eval_table_candidate")),
                has_toc_candidate=bool(obj.get("has_toc_candidate")),
                has_blind_candidate=bool(obj.get("has_blind_candidate")),
                has_commercial_sw_candidate=bool(obj.get("has_commercial_sw_candidate")),
                parser_warning=obj.get("parser_warning"),
            )
        )
    if not pages:
        raise SystemExit(f"No pages loaded from {path}")
    return fill_missing_rfp_printed_page_numbers_for_jsonl(pages)


def parse_jsonl_page_no(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if value is None or value == "":
        return None
    text = str(value).strip()
    match = re.search(r"\d{1,4}", text)
    return int(match.group(0)) if match else None


def fill_missing_rfp_printed_page_numbers_for_jsonl(pages: list[CandidatePage]) -> list[CandidatePage]:
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


def parse_items(value: str | None, group: str | None) -> list[str]:
    if group:
        if group not in DEFAULT_GROUPS:
            raise SystemExit(f"Unknown group: {group}. Use one of: {', '.join(DEFAULT_GROUPS)}")
        items = DEFAULT_GROUPS[group]
    elif value:
        items = [item.strip() for item in value.split(",") if item.strip()]
    else:
        items = [str(i) for i in range(1, 19)]

    expanded: list[str] = []
    for item in items:
        if item == "2":
            for alias in ["2", "2-1"]:
                if alias not in expanded:
                    expanded.append(alias)
        elif item not in expanded:
            expanded.append(item)
    return expanded


def review_item(
    item_no: str,
    pages: list[CandidatePage],
    rag_agent: RagAgent,
    llm_client: object,
    parse_status: str,
):
    rag_context = rag_agent.context_for_item(item_no)
    route = route_item(item_no)
    if route == "rule":
        review = RuleReviewAgent(llm_client).review(item_no, pages, rag_context)
    elif route == "table":
        review = TableReviewAgent(llm_client).review(item_no, pages, rag_context)
    elif route == "attachment":
        review = AttachmentReviewAgent(llm_client).review(item_no, pages, rag_context)
    else:
        review = LlmReviewAgent(llm_client).review(item_no, pages, rag_context)

    review = normalize_review_evidence_pages_for_jsonl(review, pages)
    final = VerificationAgent(llm_client).verify(item_no, [review], parse_status=parse_status)
    return {
        "item_no": item_no,
        "route": route,
        "rag_hit_count": len(rag_context.hits),
        "rag_hits": [asdict(hit) for hit in rag_context.hits],
        "review": review.to_dict(),
        "final": final.to_dict(),
    }, final


def normalize_review_evidence_pages_for_jsonl(
    review: ReviewResult,
    pages: list[CandidatePage],
) -> ReviewResult:
    if not review.evidence_pages:
        return review
    by_pdf_page = {
        page.page_no: page.rfp_printed_page_no
        for page in pages
        if page.rfp_printed_page_no is not None
    }
    printed_pages = {page for page in by_pdf_page.values() if page is not None}
    normalized: list[int] = []
    for page in review.evidence_pages:
        if page in printed_pages:
            normalized.append(page)
        else:
            normalized.append(by_pdf_page.get(page, page))
    review.evidence_pages = normalized
    return review


def write_review_output(
    output_path: Path,
    *,
    input_path: Path,
    db_path: Path,
    use_gpt: bool,
    skip_parse_audit: bool,
    requested_items: str | None,
    group: str | None,
    expanded_items: list[str],
    page_count: int,
    parse_status: str,
    audit_score: int | None,
    audit_warnings: list[dict[str, Any]],
    pages_to_reparse: list[int],
    debug_counts: dict[str, int],
    item_results: list[dict[str, Any]],
    final_reviews: list[FinalReview],
    resume_enabled: bool = False,
    completed: bool = False,
) -> None:
    completed_items = [str(item.get("item_no")) for item in item_results]
    output = {
        "input": str(input_path),
        "db": str(db_path),
        "use_gpt": bool(use_gpt),
        "skip_parse_audit": bool(skip_parse_audit),
        "requested_items": requested_items,
        "group": group,
        "expanded_items": expanded_items,
        "page_count": page_count,
        "parse_status": parse_status,
        "audit_score": audit_score,
        "audit_warnings": audit_warnings,
        "pages_to_reparse": pages_to_reparse,
        "debug_counts": debug_counts,
        "resume": {
            "enabled": bool(resume_enabled),
            "completed": bool(completed),
            "completed_items": completed_items,
            "remaining_items": [item_no for item_no in expanded_items if item_no not in set(completed_items)],
        },
        "item_results": item_results,
        "merged_final_reviews": [review.to_dict() for review in merge_final_reviews(final_reviews)],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


def review_debug_counts(pages: list[CandidatePage]) -> dict[str, int]:
    return {
        "table_candidate_pages": sum(page.has_table_candidate for page in pages),
        "eval_table_candidate_pages": sum(page.has_eval_table_candidate for page in pages),
        "attachment_candidate_pages": sum(page.has_attachment_candidate for page in pages),
        "toc_candidate_pages": sum(page.has_toc_candidate for page in pages),
        "parser_warning_pages": sum(1 for page in pages if page.parser_warning),
    }


def main() -> None:
    configure_utf8_output()
    parser = argparse.ArgumentParser(description="Run existing review agents from CandidatePage JSONL.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=Path("rfp 법제도 검토항목.db"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--items", type=str)
    parser.add_argument("--group", choices=sorted(DEFAULT_GROUPS))
    parser.add_argument("--use-gpt", action="store_true")
    parser.add_argument("--skip-parse-audit", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Reuse completed item_results from the output file.")
    args = parser.parse_args()

    pages = load_candidate_pages(args.input)
    document = ParsedDocument(
        document_id=0,
        document_name=args.input.name,
        pdf_path=None,
        total_pages=len(pages),
        parse_status="ok",
        pages=pages,
    )

    item_nos = parse_items(args.items, args.group)
    llm_client = OpenAILowCostClient() if args.use_gpt else DisabledLlmClient()
    parse_audit_agent = ParseAuditAgent(llm_client=llm_client, use_gpt=args.use_gpt)
    audited = document if args.skip_parse_audit else parse_audit_agent.audit(document)

    if audited.parse_status == "fail":
        final_reviews = [
            parse_fail_review(item_no, audited)
            for item_no in (item_nos or DEFAULT_ITEM_NOS)
            if item_no != "2-1"
        ]
        write_review_output(
            args.output,
            input_path=args.input,
            db_path=args.db,
            use_gpt=bool(args.use_gpt),
            skip_parse_audit=bool(args.skip_parse_audit),
            requested_items=args.items,
            group=args.group,
            expanded_items=item_nos,
            page_count=len(pages),
            parse_status=audited.parse_status,
            audit_score=audited.audit_score,
            audit_warnings=[asdict(warning) for warning in audited.audit_warnings],
            pages_to_reparse=parse_audit_agent.pages_to_reparse(audited),
            debug_counts=review_debug_counts(pages),
            item_results=[],
            final_reviews=final_reviews,
            resume_enabled=bool(args.resume),
            completed=True,
        )
        print(f"done: {args.output}")
        print(f"parse_status=fail audit_score={audited.audit_score} review skipped")
        return

    rag_agent = RagAgent(args.db)
    rag_agent.ensure_schema()

    resume_state = (
        load_resume_state(args.output, item_nos)
        if args.resume
        else ResumeState(item_results=[], final_reviews=[], remaining_items=item_nos)
    )
    item_results = list(resume_state.item_results)
    final_reviews = list(resume_state.final_reviews)
    if args.resume and resume_state.item_results:
        skipped = ",".join(item["item_no"] for item in resume_state.item_results)
        print(f"resume: reusing completed items={skipped}")

    for item_no in resume_state.remaining_items:
        item_result, final = review_item(item_no, audited.pages, rag_agent, llm_client, audited.parse_status)
        item_results.append(item_result)
        final_reviews.append(final)
        write_review_output(
            args.output,
            input_path=args.input,
            db_path=args.db,
            use_gpt=bool(args.use_gpt),
            skip_parse_audit=bool(args.skip_parse_audit),
            requested_items=args.items,
            group=args.group,
            expanded_items=item_nos,
            page_count=len(pages),
            parse_status=audited.parse_status,
            audit_score=audited.audit_score,
            audit_warnings=[asdict(warning) for warning in audited.audit_warnings],
            pages_to_reparse=parse_audit_agent.pages_to_reparse(audited),
            debug_counts=review_debug_counts(pages),
            item_results=item_results,
            final_reviews=final_reviews,
            resume_enabled=bool(args.resume),
            completed=False,
        )
    merged_finals = merge_final_reviews(final_reviews)

    write_review_output(
        args.output,
        input_path=args.input,
        db_path=args.db,
        use_gpt=bool(args.use_gpt),
        skip_parse_audit=bool(args.skip_parse_audit),
        requested_items=args.items,
        group=args.group,
        expanded_items=item_nos,
        page_count=len(pages),
        parse_status=audited.parse_status,
        audit_score=audited.audit_score,
        audit_warnings=[asdict(warning) for warning in audited.audit_warnings],
        pages_to_reparse=parse_audit_agent.pages_to_reparse(audited),
        debug_counts=review_debug_counts(pages),
        item_results=item_results,
        final_reviews=merged_finals,
        resume_enabled=bool(args.resume),
        completed=True,
    )

    print(f"done: {args.output}")
    print(
        f"items={','.join(item_nos)} pages={len(pages)} use_gpt={bool(args.use_gpt)} "
        f"parse_status={audited.parse_status} audit_score={audited.audit_score}"
    )
    for result in item_results:
        review = result["review"]
        final = result["final"]
        print(
            f"item {result['item_no']} route={result['route']} rag={result['rag_hit_count']} "
            f"review={review.get('result')} final={final.get('final_result')} "
            f"status={final.get('final_status')} confidence={final.get('confidence')}"
        )


if __name__ == "__main__":
    main()
