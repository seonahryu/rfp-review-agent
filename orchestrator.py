from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from agents.attach_review_agent import AttachmentReviewAgent
from agents.audit_agent import ParseAuditAgent
from agents.compliance_content_agent import ComplianceContentAgent
from agents.gpt_judgement import find_page_for_evidence_text, rfp_printed_page_no
from agents.gpt_parser_agent import GptParserAgent
from agents.llm_client import OpenAILowCostClient
from agents.llm_review_agent import LlmReviewAgent
from agents.models import CandidatePage, FinalReview, ParsedDocument, PipelineSummary, ReviewResult
from agents.rag_agent import RagAgent
from agents.report_agent import ReportAgent
from agents.review_common import postprocess_final_review
from agents.review_router import route_item
from agents.rule_review_agent import RuleReviewAgent
from agents.table_review_agent import TableReviewAgent
from agents.verification_agent import VerificationAgent


DEFAULT_ITEM_NOS = [str(no) for no in range(1, 19)]


def configure_utf8_output() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


configure_utf8_output()


class RfpReviewPipeline:
    def __init__(
        self,
        db_path: Path | str,
        output_dir: Path | str = "outputs",
        llm_client: object | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.llm_client = llm_client or OpenAILowCostClient()
        self.parser = GptParserAgent(self.db_path)
        self.audit = ParseAuditAgent()
        self.rag = RagAgent(self.db_path)
        self.report = ReportAgent(output_dir)
        self.compliance_content = ComplianceContentAgent()
        self.rule_review = RuleReviewAgent(self.llm_client)
        self.table_review = TableReviewAgent(self.llm_client)
        self.attach_review = AttachmentReviewAgent(self.llm_client)
        self.llm_review = LlmReviewAgent(self.llm_client)
        self.verifier = VerificationAgent(self.llm_client)
        self.review_concurrency = max(1, int(os.getenv("RFP_REVIEW_CONCURRENCY", "1")))

    async def run(self, pdf_path: Path | str, item_nos: list[str] | None = None) -> PipelineSummary:
        document = self.parser.parse(pdf_path)
        return await self._review_document(document, item_nos or DEFAULT_ITEM_NOS)

    def review_existing_document(self, document_id: int, item_nos: list[str] | None = None) -> PipelineSummary:
        document = self.parser.load(document_id)
        return asyncio.run(self._review_document(document, item_nos or DEFAULT_ITEM_NOS))

    async def _review_document(self, document: ParsedDocument, item_nos: list[str]) -> PipelineSummary:
        audited = self.audit.audit(document)
        if audited.parse_status == "fail":
            final_reviews = [parse_fail_review(item_no, audited) for item_no in item_nos]
            excel_path = self.report.write_excel(
                audited.document_id,
                final_reviews,
                audited.audit_warnings,
            )
            return PipelineSummary(
                document_id=audited.document_id,
                parse_status=audited.parse_status,
                audit_score=audited.audit_score or 0,
                audit_warnings=audited.audit_warnings,
                final_reviews=final_reviews,
                excel_path=excel_path,
            )
        self.rag.ensure_schema()
        semaphore = asyncio.Semaphore(self.review_concurrency)
        tasks = [self._review_item_limited(item_no, audited, semaphore) for item_no in item_nos]
        final_reviews = attach_compliance_contents(
            merge_final_reviews(await asyncio.gather(*tasks)),
            self.rag,
            self.compliance_content,
        )
        excel_path = self.report.write_excel(
            audited.document_id,
            list(final_reviews),
            audited.audit_warnings,
        )
        return PipelineSummary(
            document_id=audited.document_id,
            parse_status=audited.parse_status,
            audit_score=audited.audit_score or 0,
            audit_warnings=audited.audit_warnings,
            final_reviews=list(final_reviews),
            excel_path=excel_path,
            compliance_contents=[
                review.compliance_content for review in final_reviews if review.compliance_content is not None
            ],
        )

    async def _review_item_limited(self, item_no: str, document: ParsedDocument, semaphore: asyncio.Semaphore):
        async with semaphore:
            return await self._review_item(item_no, document)

    async def _review_item(self, item_no: str, document: ParsedDocument):
        rag_context = self.rag.context_for_item(item_no)
        pages = document.pages
        review_tasks = [asyncio.to_thread(self._run_primary_agent, item_no, pages, rag_context)]
        reviews = [
            normalize_review_evidence_pages(review, pages)
            for review in await asyncio.gather(*review_tasks)
            if review is not None
        ]
        final_review = self.verifier.verify(item_no, reviews, parse_status=document.parse_status)
        return postprocess_final_review(final_review, pages)

    def _run_primary_agent(self, item_no: str, pages: list[CandidatePage], rag_context):
        route = route_item(item_no)
        if route == "rule":
            return self.rule_review.review(item_no, pages, rag_context)
        if route == "table":
            return self.table_review.review(item_no, pages, rag_context)
        if route == "attachment":
            return self.attach_review.review(item_no, pages, rag_context)
        return self.llm_review.review(item_no, pages, rag_context)


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


def normalize_review_evidence_pages(review: ReviewResult, pages: list[CandidatePage]) -> ReviewResult:
    if not review.evidence_pages or not pages:
        return review

    index_to_printed = {
        page.page_no: printed
        for page in pages
        if (printed := rfp_printed_page_no(page)) is not None
    }
    printed_pages = set(index_to_printed.values())
    normalized_pages: list[int] = []

    for idx, page_no in enumerate(review.evidence_pages):
        text = review.evidence_text[idx] if idx < len(review.evidence_text) else ""
        matched_page = find_page_for_evidence_text(text, pages)
        matched_printed = rfp_printed_page_no(matched_page) if matched_page is not None else None

        if matched_printed is not None:
            normalized = matched_printed
        elif page_no in printed_pages:
            normalized = page_no
        else:
            normalized = index_to_printed.get(page_no, page_no)

        normalized_pages.append(normalized)

    review.evidence_pages = normalized_pages
    return review


def select_evidence_pages(item_no: str, rag_context, pages: list[CandidatePage], limit: int = 10) -> list[CandidatePage]:
    query_terms = {str(item_no)}
    for hit in getattr(rag_context, "hits", [])[:5]:
        for text in [hit.title, hit.category or "", hit.snippet]:
            for token in simple_tokens(text):
                query_terms.add(token)

    scored: list[tuple[int, CandidatePage]] = []
    for page in pages:
        page_text = page.page_text.lower()
        score = sum(1 for term in query_terms if term and term.lower() in page_text)
        score += special_item_score(item_no, page)
        if str(item_no) in page_text:
            score += 3
        if page.parser_warning:
            score -= 1
        if score > 0:
            scored.append((score, page))
    scored.sort(key=lambda item: (-item[0], item[1].page_no))
    selected = [page for _, page in scored[:limit]]
    return selected or pages[:limit]


def simple_tokens(text: str) -> list[str]:
    import re

    stopwords = {"관련", "검토", "기준", "내용", "사항", "법령", "또는", "대한", "경우"}
    return [
        token.lower()
        for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", text or "")
        if token.lower() not in stopwords
    ][:12]


def special_item_score(item_no: str, page: CandidatePage) -> int:
    item = str(item_no).strip()
    if page.has_toc_candidate:
        return 0
    text = page.page_text
    compact = "".join(text.split())
    if item == "12":
        score = 0
        if "차등점수제" in text or ("순위간" in text and "점수차" in text):
            score += 50
        if "평가항목" in text and ("배점" in text or "배점한도" in text):
            score += 35
        if "소프트웨어기술성평가기준" in text or ("하자보수" in text and "비상 대책" in text):
            score += 30
        return score
    if item == "13":
        score = 0
        if "제안서 보상" in text or "보상대상" in text:
            score += 60
        if "20억원" in text or "20억" in text:
            score += 35
        if "사업 예산" in text or "사업예산" in text or "총사업금액" in text:
            score += 25
        if "소프트웨어 진흥법" in text and "제52조" in text:
            score += 30
        return score
    if item == "16":
        relevant_terms = [
            "투입인력",
            "투입 인력",
            "사업수행조직",
            "수행조직",
            "인력현황",
            "인원 현황",
            "M/M",
            "투입률",
            "투입계획",
            "교체",
            "발주기관의 승인",
            "기능점수",
            "FP",
            "서비스수준협약",
        ]
        score = sum(12 for term in relevant_terms if term in text)
        if "기능점수" in text or "FP" in text or "서비스수준협약" in text:
            score += 35
        if any(term in text for term in ["투입인력", "투입 인력", "사업수행조직", "인력현황", "M/M", "투입률"]):
            score += 45
        if any(term in text for term in ["개인정보", "누출금지", "보안약점", "암호화"]) and not any(
            term in text for term in ["투입인력", "투입 인력", "인력", "M/M", "기능점수", "FP"]
        ):
            score -= 60
        return score
    if item == "15":
        return 60 if ("소프트웨어개발사업" in compact and "적정사업기간" in compact and "종합산정서" in compact) else 0
    if item == "17":
        return 60 if ("소프트웨어사업영향평가검토결과서" in compact or "소프트웨어사업영향평가결과서" in compact) else 0
    if item == "11":
        has_technical = "기술능력평가" in text
        has_price = "가격평가" in text or "입찰가격평가" in text
        has_90 = "90점" in text or "90%" in text
        has_10 = "10점" in text or "10%" in text
        return 50 if has_technical and has_price and has_90 and has_10 else 0
    if item != "14":
        return 0
    score = 0
    if "요구사항 총괄표" in text:
        score += 30
    detail_terms = ["요구사항 고유번호", "요구사항 명칭", "정의", "상세 세부내용", "산출정보"]
    detail_count = sum(1 for term in detail_terms if term in text)
    if detail_count >= 4:
        score += 15
    return score


def parse_items(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def merge_final_reviews(final_reviews):
    by_item = {}
    order = []
    for review in final_reviews:
        key = "2" if str(review.item_no) == "2-1" else str(review.item_no)
        if key not in by_item:
            order.append(key)
            if key == review.item_no:
                by_item[key] = review
            else:
                by_item[key] = replace_final_item_no(review, key)
            continue
        by_item[key] = merge_two_final_reviews(by_item[key], review, key)
    return [by_item[key] for key in order]


def attach_compliance_contents(final_reviews, rag_agent, content_agent: ComplianceContentAgent | None = None):
    from dataclasses import replace

    generator = content_agent or ComplianceContentAgent()
    attached = []
    for review in final_reviews:
        rag_context = rag_agent.context_for_item(str(review.item_no))
        content = generator.generate(review, rag_context)
        if content.compliance_content:
            attached.append(replace(review, compliance_content=content))
        else:
            attached.append(review)
    return attached


def replace_final_item_no(review, item_no: str):
    from dataclasses import replace

    return replace(review, item_no=item_no)


def merge_two_final_reviews(left, right, item_no: str):
    from dataclasses import replace

    if item_no == "2":
        merged_reviews = list(left.reviews) + list(right.reviews)
        warnings = list(left.warnings) + [warning for warning in right.warnings if warning not in left.warnings]
        target_reviews = [
            review
            for review in [left, right]
            if review.is_target is True and str(review.final_result).strip() != "해당없음"
        ]
        if target_reviews:
            chosen = max(target_reviews, key=lambda review: (status_rank(review.final_result), review.confidence))
            other = right if chosen is left else left
            evidence_pages, evidence_text = merge_evidence(left, right)
            return replace(
                chosen,
                item_no=item_no,
                evidence_pages=evidence_pages,
                evidence_text=evidence_text,
                reason=combine_text(chosen.reason, other.reason),
                recommendation=combine_text(chosen.recommendation, other.recommendation),
                reviews=merged_reviews,
                warnings=warnings,
            )
        chosen = max([left, right], key=lambda review: review.confidence)
        return replace(
            chosen,
            item_no=item_no,
            reviews=merged_reviews,
            warnings=warnings,
        )

    chosen = max([left, right], key=lambda review: (status_rank(review.final_result), review.confidence))
    merged_reviews = list(left.reviews) + list(right.reviews)
    evidence_pages, evidence_text = merge_evidence(left, right)
    warnings = list(left.warnings) + [warning for warning in right.warnings if warning not in left.warnings]
    reason = combine_text(left.reason, right.reason)
    recommendation = combine_text(left.recommendation, right.recommendation)
    return replace(
        chosen,
        item_no=item_no,
        evidence_pages=evidence_pages,
        evidence_text=evidence_text,
        reason=reason,
        recommendation=recommendation,
        reviews=merged_reviews,
        warnings=warnings,
    )


def merge_evidence(left: FinalReview, right: FinalReview) -> tuple[list[int], list[str]]:
    evidence_by_page: dict[int, str] = {}
    for review in [left, right]:
        for idx, page in enumerate(review.evidence_pages):
            text = review.evidence_text[idx] if idx < len(review.evidence_text) else ""
            if page not in evidence_by_page:
                evidence_by_page[page] = text
            elif text and text not in evidence_by_page[page]:
                evidence_by_page[page] = combine_text(evidence_by_page[page], text)
    pages = sorted(evidence_by_page)
    return pages, [evidence_by_page[page] for page in pages]


def status_rank(result: str) -> int:
    return {
        "미준수": 4,
        "보완필요": 3,
        "확인필요": 2,
        "준수": 1,
        "해당없음": 0,
    }.get(str(result).strip(), 1)


def combine_text(*values: str) -> str:
    parts = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in parts:
            parts.append(text)
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="RFP 법제도 검토 멀티 에이전트 파이프라인")
    parser.add_argument("pdf", type=Path, nargs="?")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--document-id", type=int)
    parser.add_argument("--items", type=str)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    pipeline = RfpReviewPipeline(db_path=args.db, output_dir=args.output_dir)
    if args.document_id:
        summary = pipeline.review_existing_document(args.document_id, parse_items(args.items))
    else:
        if not args.pdf:
            raise SystemExit("pdf 또는 --document-id가 필요합니다.")
        summary = asyncio.run(pipeline.run(args.pdf, parse_items(args.items)))

    if args.json:
        args.json.write_text(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"document_id={summary.document_id}")
    print(f"audit_score={summary.audit_score}")
    print(f"excel={summary.excel_path}")


if __name__ == "__main__":
    main()
