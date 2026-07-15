from __future__ import annotations

import re

from agents.gpt_judgement import gpt_review
from agents.llm_client import DisabledLlmClient
from agents.models import CandidatePage, RagContext, ReviewResult
from agents.review_common import (
    find_project_amount_evidence,
    format_amount_억원,
    has_commercial_sw_purchase_signal,
)
from agents.rule_review_agent import best_rag_keyword_match, evidence_for_keywords, rfp_display_page_no


ATTACHMENT_KEYWORDS = {
    "2": ["상용SW", "상용소프트웨어", "직접구매", "분리발주"],
    "2-1": ["직접구매", "상용소프트웨어"],
    "15": ["블라인드", "비식별", "익명", "성명", "소속", "학력", "출신"],
    "17": ["블라인드", "비식별", "제안서 작성", "성명", "소속", "생년월일"],
}


class AttachmentReviewAgent:
    route_type = "attachment_review"

    def __init__(self, llm_client: object | None = None) -> None:
        self.llm_client = llm_client or DisabledLlmClient()

    def review(self, item_no: str, pages: list[CandidatePage], rag: RagContext) -> ReviewResult:
        if str(item_no) == "15":
            period_attachment_result = review_sw_project_period_attachment(pages)
            if period_attachment_result is not None:
                return period_attachment_result

        if str(item_no) == "17":
            impact_attachment_result = review_sw_impact_assessment_attachment(pages)
            if impact_attachment_result is not None:
                return impact_attachment_result

        if str(item_no) in {"15", "17"}:
            gpt_result = gpt_review(
                llm_client=self.llm_client,
                model_role="attachment",
                item_no=item_no,
                route_type=self.route_type,
                pages=pages,
                rag=rag,
            )
            if gpt_result is not None:
                return validate_attachment_gpt_result(str(item_no), gpt_result, pages)

        if str(item_no) == "2":
            direct_purchase_result = review_commercial_sw_direct_purchase_target(pages)
            if direct_purchase_result is not None:
                return direct_purchase_result
            direct_purchase_advisory = commercial_sw_direct_purchase_advisory(pages)
            if direct_purchase_advisory is not None:
                return direct_purchase_advisory

        if str(item_no) == "2-1":
            bmt_result = review_bmt_target(pages)
            if bmt_result is not None:
                return bmt_result

        attachment_pages = [
            page
            for page in pages
            if page.has_attachment_candidate or page.has_blind_candidate or page.has_commercial_sw_candidate
        ]
        candidate_pages = attachment_pages or pages

        title_only_result = review_title_only_attachment(str(item_no), candidate_pages)
        if title_only_result is not None:
            return title_only_result

        gpt_result = gpt_review(
            llm_client=self.llm_client,
            model_role="attachment",
            item_no=item_no,
            route_type=self.route_type,
            pages=pages,
            rag=rag,
        )
        if gpt_result is not None:
            return validate_attachment_gpt_result(str(item_no), gpt_result, pages)

        rag_match = best_rag_keyword_match(candidate_pages, rag)
        if rag_match and float(rag_match["coverage"]) >= 0.7:
            coverage = float(rag_match["coverage"])
            return ReviewResult(
                item_no=str(item_no),
                route_type=self.route_type,
                result="준수",
                is_target=True,
                confidence=round(min(0.88, 0.43 + coverage * 0.5), 3),
                evidence_pages=[int(rag_match["page_no"])],
                evidence_text=[str(rag_match["evidence"])],
                reason=f"DB 기준문구 핵심 키워드의 {coverage:.0%}가 첨부/별첨 후보 페이지에서 확인되어 70% 기준을 충족했습니다.",
                recommendation="",
                needs_human_review=False,
                source="python_attachment_rag_overlap",
                used_llm=False,
            )

        matches = evidence_for_keywords(candidate_pages, ATTACHMENT_KEYWORDS.get(str(item_no), []))
        if matches:
            return ReviewResult(
                item_no=str(item_no),
                route_type=self.route_type,
                result="보완필요",
                is_target=True,
                confidence=0.68,
                evidence_pages=[page for page, _ in matches[:5]],
                evidence_text=[text for _, text in matches[:5]],
                reason="붙임/별첨 본문 후보에서 관련 문구를 찾았지만 DB 기준문구 70% 커버리지는 충족하지 못했습니다.",
                recommendation="첨부 본문의 원문 문구와 검토 기준을 대조하세요.",
                needs_human_review=True,
                source="python_attachment",
                used_llm=False,
            )
        return ReviewResult(
            item_no=str(item_no),
            route_type=self.route_type,
            result="확인필요",
            is_target=None,
            confidence=0.34,
            evidence_pages=[rfp_display_page_no(page) for page in candidate_pages[:3]],
            evidence_text=[page.page_text[:180] for page in candidate_pages[:3]],
            reason="붙임/별첨 또는 관련 키워드가 충분하지 않습니다.",
            recommendation="붙임 파일 또는 별첨 본문 누락 여부를 확인하세요.",
            needs_human_review=True,
            source="python_attachment",
            used_llm=False,
        )


def review_sw_impact_assessment_attachment(pages: list[CandidatePage]) -> ReviewResult | None:
    declaration_pages = sw_impact_declaration_pages(pages)
    actual_pages = [
        page
        for page in pages
        if has_sw_impact_assessment_title(page.page_text) and not page.has_toc_candidate
        and not is_attachment_reference_only(page.page_text, "소프트웨어사업 영향평가")
    ]
    if actual_pages:
        complete_pages = [page for page in actual_pages if attachment_has_body(page.page_text, "소프트웨어사업 영향평가")]
        if complete_pages:
            if not declaration_pages:
                return ReviewResult(
                    item_no="17",
                    route_type=AttachmentReviewAgent.route_type,
                    result="미준수",
                    is_target=True,
                    confidence=0.82,
                    evidence_pages=combined_page_numbers(complete_pages),
                    evidence_text=combined_page_texts(complete_pages),
                    reason="소프트웨어사업 영향평가 결과서 첨부 본문은 있으나, RFP 본문에서 영향평가 실시 및 첨부 명시가 확인되지 않았습니다.",
                    recommendation=sw_impact_assessment_recommendation(),
                    needs_human_review=False,
                    source="python_attachment_sw_impact_missing_declaration",
                    used_llm=False,
                )
            return ReviewResult(
                item_no="17",
                route_type=AttachmentReviewAgent.route_type,
                result="준수",
                is_target=True,
                confidence=0.88,
                evidence_pages=combined_page_numbers(declaration_pages, complete_pages),
                evidence_text=combined_page_texts(declaration_pages, complete_pages),
                reason="소프트웨어사업 영향평가 실시 명시와 영향평가 검토 결과서 첨부 본문이 함께 확인되었습니다.",
                recommendation="",
                needs_human_review=False,
                source="python_attachment_sw_impact",
                used_llm=False,
            )
        return ReviewResult(
            item_no="17",
            route_type=AttachmentReviewAgent.route_type,
            result="미준수",
            is_target=True,
            confidence=0.82,
            evidence_pages=combined_page_numbers(declaration_pages, actual_pages),
            evidence_text=combined_page_texts(declaration_pages, actual_pages),
            reason="소프트웨어사업 영향평가 실시 명시는 있으나, 영향평가 결과서 제목만 있고 실제 검토 내용이 없는 빈 문서로 확인됩니다.",
            recommendation=sw_impact_assessment_recommendation(),
            needs_human_review=False,
            source="python_attachment_sw_impact_empty",
            used_llm=False,
        )

    reference_pages = [
        page
        for page in pages
        if has_sw_impact_assessment_title(page.page_text)
        and not page.has_toc_candidate
        and is_attachment_reference_only(page.page_text, "소프트웨어사업 영향평가")
    ]
    if reference_pages:
        return ReviewResult(
            item_no="17",
            route_type=AttachmentReviewAgent.route_type,
            result="미준수",
            is_target=True,
            confidence=0.84,
            evidence_pages=combined_page_numbers(declaration_pages, reference_pages),
            evidence_text=combined_page_texts(declaration_pages, reference_pages),
            reason="소프트웨어사업 영향평가 결과서를 첨부한다고 명시되어 있으나, 실제 별첨 본문은 확인되지 않았습니다.",
            recommendation=sw_impact_assessment_recommendation(),
            needs_human_review=False,
            source="python_attachment_sw_impact_missing",
            used_llm=False,
        )

    listed_pages = [
        page
        for page in pages
        if has_sw_impact_assessment_title(page.page_text) and page.has_toc_candidate
    ]
    if listed_pages:
        return ReviewResult(
            item_no="17",
            route_type=AttachmentReviewAgent.route_type,
            result="미준수",
            is_target=True,
            confidence=0.82,
            evidence_pages=combined_page_numbers(declaration_pages, listed_pages),
            evidence_text=combined_page_texts(declaration_pages, listed_pages),
            reason="목차 및 붙임 목록에는 소프트웨어사업 영향평가 검토 결과서가 표시되어 있으나 실제 첨부 본문이 확인되지 않았습니다.",
            recommendation=sw_impact_assessment_recommendation(),
            needs_human_review=False,
            source="python_attachment_sw_impact_missing",
            used_llm=False,
        )
    return None


def sw_impact_declaration_pages(pages: list[CandidatePage]) -> list[CandidatePage]:
    return [
        page
        for page in pages
        if not page.has_toc_candidate and has_sw_impact_declaration(page.page_text)
    ]


def has_sw_impact_declaration(text: str) -> bool:
    compact = compact_attachment_text(text)
    has_impact = "소프트웨어사업영향평가" in compact or "SW사업영향평가" in compact
    has_conducted = any(term in compact for term in ["미리실시한사업", "실시한사업", "영향평가를실시"])
    has_attachment = any(term in compact for term in ["결과서첨부", "결과서를첨부", "별지제1호서식", "검토결과서첨부"])
    return has_impact and (has_conducted or has_attachment)


def combined_page_numbers(*page_groups: list[CandidatePage], limit: int = 5) -> list[int]:
    numbers: list[int] = []
    for group in page_groups:
        for page in group:
            number = rfp_display_page_no(page)
            if number not in numbers:
                numbers.append(number)
            if len(numbers) >= limit:
                return numbers
    return numbers


def combined_page_texts(*page_groups: list[CandidatePage], limit: int = 5) -> list[str]:
    texts: list[str] = []
    seen_pages: set[int] = set()
    for group in page_groups:
        for page in group:
            number = rfp_display_page_no(page)
            if number in seen_pages:
                continue
            seen_pages.add(number)
            texts.append(page.page_text[:220])
            if len(texts) >= limit:
                return texts
    return texts


def validate_attachment_gpt_result(item_no: str, review: ReviewResult, pages: list[CandidatePage]) -> ReviewResult:
    if item_no == "15":
        limit_project_period_gpt_evidence(review)
    if item_no == "17":
        limit_sw_impact_gpt_evidence(review)
    if str(review.result).strip() != "준수":
        return review
    if item_no == "17" and not has_complete_sw_impact_attachment(pages):
        missing = review_sw_impact_assessment_attachment(pages)
        if missing is not None and missing.result == "미준수":
            return missing
    if item_no == "15" and not has_complete_project_period_attachment(pages):
        missing = review_sw_project_period_attachment(pages)
        if missing is not None and missing.result == "미준수":
            return missing
    return review


def limit_project_period_gpt_evidence(review: ReviewResult) -> None:
    keep_attachment_evidence(
        review,
        [
            "소프트웨어 개발사업",
            "적정 사업기간",
            "적정사업기간",
            "종합 산정서",
            "종합산정서",
            "별지 제4호",
            "별지제4호",
        ],
    )


def limit_sw_impact_gpt_evidence(review: ReviewResult) -> None:
    keep_attachment_evidence(
        review,
        [
            "소프트웨어사업 영향평가",
            "SW사업 영향평가",
            "영향평가 결과서",
            "영향평가 검토결과서",
            "별지 제1호",
            "별지제1호",
        ],
    )


def keep_attachment_evidence(review: ReviewResult, keywords: list[str]) -> None:
    kept: list[tuple[int, str]] = []
    compact_keywords = [compact_attachment_text(keyword) for keyword in keywords]
    for idx, page in enumerate(review.evidence_pages):
        text = review.evidence_text[idx] if idx < len(review.evidence_text) else ""
        compact = compact_attachment_text(text)
        if any(keyword in compact for keyword in compact_keywords):
            kept.append((page, text))
    review.evidence_pages = [page for page, _ in kept]
    review.evidence_text = [text for _, text in kept]


def has_complete_sw_impact_attachment(pages: list[CandidatePage]) -> bool:
    return bool(sw_impact_declaration_pages(pages)) and any(
        has_sw_impact_assessment_title(page.page_text)
        and not page.has_toc_candidate
        and not is_attachment_reference_only(page.page_text, "소프트웨어사업 영향평가")
        and attachment_has_body(page.page_text, "소프트웨어사업 영향평가")
        for page in pages
    )


def has_complete_project_period_attachment(pages: list[CandidatePage]) -> bool:
    return bool(project_period_declaration_pages(pages)) and any(
        has_project_period_attachment_title(page.page_text)
        and not page.has_toc_candidate
        and not is_attachment_reference_only(page.page_text, "소프트웨어 개발사업")
        and attachment_has_body(page.page_text, "소프트웨어 개발사업")
        for page in pages
    )


def has_sw_impact_assessment_title(text: str) -> bool:
    compact = "".join(str(text or "").split())
    return "소프트웨어사업영향평가검토결과서" in compact or "소프트웨어사업영향평가결과서" in compact


def sw_impact_assessment_recommendation() -> str:
    return (
        "국가기관 등의 장이 소프트웨어사업을 추진하는 경우「소프트웨어 진흥법」 제43조에 따라 "
        "민간시장에 미치는 영향을 분석하는 SW사업 영향평가를 실시하고, "
        "‘소프트웨어사업 계약 및 관리감독에 관한 지침’ 제5조에 따라 제안요청서에 "
        "별지 제1호서식 SW사업 영향평가 결과서를 작성하여 첨부하여야 합니다."
    )


def review_sw_project_period_attachment(pages: list[CandidatePage]) -> ReviewResult | None:
    declaration_pages = project_period_declaration_pages(pages)
    title_pages = [
        page
        for page in pages
        if has_project_period_attachment_title(page.page_text) and not page.has_toc_candidate
        and not is_attachment_reference_only(page.page_text, "소프트웨어 개발사업")
    ]
    if title_pages:
        complete_pages = [page for page in title_pages if attachment_has_body(page.page_text, "소프트웨어 개발사업")]
        if complete_pages:
            if not declaration_pages:
                return ReviewResult(
                    item_no="15",
                    route_type=AttachmentReviewAgent.route_type,
                    result="미준수",
                    is_target=True,
                    confidence=0.82,
                    evidence_pages=combined_page_numbers(complete_pages),
                    evidence_text=combined_page_texts(complete_pages),
                    reason="소프트웨어 개발사업 적정 사업기간 종합산정서 첨부 본문은 있으나, RFP 본문에서 적정 사업기간 산정 기준 적용 명시가 확인되지 않았습니다.",
                    recommendation=project_period_recommendation(),
                    needs_human_review=False,
                    source="python_attachment_project_period_missing_declaration",
                    used_llm=False,
                )
            return ReviewResult(
                item_no="15",
                route_type=AttachmentReviewAgent.route_type,
                result="준수",
                is_target=True,
                confidence=0.86,
                evidence_pages=combined_page_numbers(declaration_pages, complete_pages),
                evidence_text=combined_page_texts(declaration_pages, complete_pages),
                reason="소프트웨어 개발사업 적정 사업기간 산정 기준 적용 명시와 종합산정서 첨부 본문이 함께 확인되었습니다.",
                recommendation="",
                needs_human_review=False,
                source="python_attachment_project_period",
                used_llm=False,
            )
        return ReviewResult(
            item_no="15",
            route_type=AttachmentReviewAgent.route_type,
            result="미준수",
            is_target=True,
            confidence=0.82,
            evidence_pages=combined_page_numbers(declaration_pages, title_pages),
            evidence_text=combined_page_texts(declaration_pages, title_pages),
            reason="소프트웨어 개발사업 적정 사업기간 산정 기준 적용 명시는 있으나, 종합산정서 제목만 있고 실제 산정 내용이 없는 빈 문서로 확인됩니다.",
            recommendation=project_period_recommendation(),
            needs_human_review=False,
            source="python_attachment_project_period_empty",
            used_llm=False,
        )
    listed_pages = [
        page
        for page in pages
        if has_project_period_attachment_title(page.page_text) and page.has_toc_candidate
    ]
    if listed_pages:
        return ReviewResult(
            item_no="15",
            route_type=AttachmentReviewAgent.route_type,
            result="미준수",
            is_target=True,
            confidence=0.8,
            evidence_pages=combined_page_numbers(declaration_pages, listed_pages),
            evidence_text=combined_page_texts(declaration_pages, listed_pages),
            reason="붙임 목차에는 소프트웨어 개발사업 적정 사업기간 종합산정서가 표시되어 있으나 실제 첨부 본문이 확인되지 않았습니다.",
            recommendation=project_period_recommendation(),
            needs_human_review=False,
            source="python_attachment_project_period_missing",
            used_llm=False,
        )
    return ReviewResult(
        item_no="15",
        route_type=AttachmentReviewAgent.route_type,
        result="미준수",
        is_target=True,
        confidence=0.82,
        evidence_pages=combined_page_numbers(declaration_pages),
        evidence_text=combined_page_texts(declaration_pages),
        reason=(
            "소프트웨어 개발사업의 적정 사업기간 종합 산정서 첨부가 확인되지 않았습니다."
            if declaration_pages
            else "소프트웨어 개발사업의 적정 사업기간 종합 산정서 첨부 또는 적정 사업기간 산정 기준 적용 명시가 확인되지 않았습니다."
        ),
        recommendation=project_period_recommendation(),
        needs_human_review=False,
        source=(
            "python_attachment_project_period_missing_attachment"
            if declaration_pages
            else "python_attachment_project_period_missing_all"
        ),
        used_llm=False,
    )


def project_period_declaration_pages(pages: list[CandidatePage]) -> list[CandidatePage]:
    return [
        page
        for page in pages
        if not page.has_toc_candidate
        and has_project_period_declaration(page.page_text)
    ]


def has_project_period_declaration(text: str) -> bool:
    compact = compact_attachment_text(text)
    has_period = "적정사업기간" in compact and ("소프트웨어개발사업" in compact or "SW사업" in compact)
    has_project_statement = "본사업" in compact or "해당사업" in compact
    has_basis = any(term in compact for term in ["산정기준에따른사업", "제10조", "별지제4호서식"])
    return has_period and has_project_statement and has_basis


def is_attachment_reference_only(text: str, title_hint: str) -> bool:
    compact = compact_attachment_text(text)
    if title_hint and compact_attachment_text(title_hint) not in compact:
        return False
    reference_signals = [
        "첨부별첨",
        "별첨참조",
        "별첨을참조",
        "별첨1참조",
        "별첨2참조",
        "별첨3참조",
        "서식참조",
        "붙임참조",
        "별지제1호서식에따른",
        "결과서를첨부",
        "산정서를공지함",
    ]
    appendix_body_signals = [
        "사업명",
        "영향평가단계",
        "평가항목",
        "평가결과",
        "종합의견",
        "산정기준",
        "산정결과",
        "위원명",
    ]
    has_reference = any(signal in compact for signal in reference_signals)
    has_body_form = sum(1 for signal in appendix_body_signals if signal in compact) >= 3
    return has_reference and not has_body_form


def has_project_period_attachment_title(text: str) -> bool:
    compact = "".join(str(text or "").split())
    return "소프트웨어개발사업" in compact and "적정사업기간" in compact and "종합산정서" in compact


def project_period_recommendation() -> str:
    return (
        "소프트웨어사업 계약 및 관리감독에 관한 지침 제10조에 의거 별지 제4호서식 "
        "소프트웨어 개발사업의 적정 사업기간 종합 산정서(단, 위원명 및 서명은 제외한다)를 첨부하시기 바랍니다."
    )


def attachment_has_body(text: str, title_hint: str) -> bool:
    if has_attachment_missing_signal(text):
        return False
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    body_lines = [
        line
        for line in lines
        if not line.startswith("[붙임")
        and not line.startswith("【붙임")
        and title_hint not in line
        and not ("영향평가" in line and "결과서" in line)
        and not ("적정 사업기간" in line and "산정서" in line)
        and not line.startswith("-")
        and not is_attachment_label_only_line(line)
        and not is_attachment_instruction_line(line)
    ]
    body_text = " ".join(body_lines)
    if len(body_text) < 80:
        return False
    if attachment_substantive_signal_count(body_text) < 2:
        return False
    return True


def has_attachment_missing_signal(text: str) -> bool:
    compact = compact_attachment_text(text)
    missing_signals = [
        "추후제출",
        "추후작성",
        "작성예정",
        "제출예정",
        "첨부예정",
        "별도첨부",
        "별도제출",
        "미첨부",
        "미작성",
    ]
    return any(signal in compact for signal in missing_signals)


def is_attachment_label_only_line(line: str) -> bool:
    compact = compact_attachment_text(line).strip(":-ㆍ·[]()")
    if not compact:
        return True
    label_terms = {
        "사업명",
        "발주기관",
        "사업기간",
        "사업예산",
        "예산편성대상사업발주",
        "영향평가단계",
        "구분",
        "번호",
        "내용",
        "주요내용",
        "평가항목",
        "평가결과",
        "비고",
        "종합의견",
        "작성자",
        "작성일",
        "제출일",
        "위원명",
        "서명",
        "산정기준",
        "산정근거",
        "산정결과",
        "기능점수",
        "보정계수",
    }
    if compact in label_terms:
        return True
    return len(compact) <= 24 and any(term == compact or compact.endswith(term) for term in label_terms)


def is_attachment_instruction_line(line: str) -> bool:
    compact = compact_attachment_text(line)
    instruction_terms = [
        "작성방법",
        "작성요령",
        "작성안내",
        "해당사항을기재",
        "필요시작성",
        "아래사항을작성",
        "양식",
        "예시",
    ]
    return any(term in compact for term in instruction_terms)


def attachment_substantive_signal_count(text: str) -> int:
    compact = compact_attachment_text(text)
    signals = [
        "없음",
        "낮음",
        "높음",
        "타당",
        "검토",
        "분석",
        "산정",
        "적정",
        "결과",
        "가능성",
        "중복",
        "침해",
        "활용",
        "개선",
        "구축",
        "기간",
        "기능점수",
        "보정계수",
        "개월",
    ]
    return sum(1 for signal in signals if signal in compact)


def compact_attachment_text(text: str) -> str:
    return re.sub(r"[\s:：,，.ㆍ·\-_/()\[\]{}<>「」『』]+", "", str(text or ""))


ATTACHMENT_TITLE_HINTS = {
    "2": [
        "상용소프트웨어 직접구매",
        "상용SW 직접구매",
        "직접구매 대상 상용소프트웨어",
        "직접구매 대상 상용SW",
    ],
    "2-1": [
        "품질성능 평가시험",
        "BMT",
        "상용소프트웨어 품질성능",
        "상용SW 품질성능",
    ],
    "15": [
        "소프트웨어 개발사업 적정 사업기간 종합산정서",
        "소프트웨어개발사업 적정사업기간 종합산정서",
    ],
    "17": [
        "소프트웨어사업 영향평가 검토 결과서",
        "소프트웨어사업 영향평가 결과서",
        "SW사업 영향평가 결과서",
    ],
}


def review_title_only_attachment(item_no: str, pages: list[CandidatePage]) -> ReviewResult | None:
    title_pages = [
        page
        for page in pages
        if has_known_attachment_title(item_no, page.page_text) and not page.has_toc_candidate
    ]
    if not title_pages:
        return None

    complete_pages = [
        page
        for page in title_pages
        if attachment_has_body(page.page_text, best_attachment_title_hint(item_no, page.page_text))
    ]
    if complete_pages:
        return None

    return ReviewResult(
        item_no=item_no,
        route_type=AttachmentReviewAgent.route_type,
        result="미준수",
        is_target=True,
        confidence=0.78,
        evidence_pages=[rfp_display_page_no(page) for page in title_pages[:3]],
        evidence_text=[page.page_text[:260] for page in title_pages[:3]],
        reason="첨부 제목은 있으나 실제 검토·산정·확인 내용이 없는 빈 문서로 확인됩니다.",
        recommendation="제목만 있는 붙임이 아니라 실제 검토·산정·확인 내용이 포함된 첨부문서를 제안요청서에 포함하여야 합니다.",
        needs_human_review=False,
        source="python_attachment_title_only",
        used_llm=False,
    )


def has_known_attachment_title(item_no: str, text: str) -> bool:
    compact = "".join(str(text or "").split())
    return any("".join(hint.split()) in compact for hint in ATTACHMENT_TITLE_HINTS.get(str(item_no), []))


def best_attachment_title_hint(item_no: str, text: str) -> str:
    compact = "".join(str(text or "").split())
    for hint in ATTACHMENT_TITLE_HINTS.get(str(item_no), []):
        if "".join(hint.split()) in compact:
            return hint
    return ""


def review_commercial_sw_direct_purchase_target(pages: list[CandidatePage]) -> ReviewResult | None:
    text = " ".join(page.page_text for page in pages if not page.has_toc_candidate)
    amount = find_project_amount_evidence(pages, 300_000_000)
    has_budget = amount is not None
    has_direct_purchase_sw = has_direct_purchase_commercial_sw(text) or has_commercial_sw_purchase_signal(pages)
    if not (has_budget and has_direct_purchase_sw):
        return ReviewResult(
            item_no="2",
            route_type=AttachmentReviewAgent.route_type,
            result="해당없음",
            is_target=False,
            confidence=0.78,
            evidence_pages=[],
            evidence_text=[],
            reason=(
                "RFP 본문에서 총사업금액 3억원 이상이면서 직접구매 대상 상용SW를 구매하는 사업으로 볼 "
                "근거가 모두 확인되지 않았습니다."
            ),
            recommendation="",
            needs_human_review=False,
            source="python_attachment_direct_purchase_not_target",
            used_llm=False,
        )
    return None


def commercial_sw_direct_purchase_advisory(pages: list[CandidatePage]) -> ReviewResult | None:
    amount = find_project_amount_evidence(pages, 300_000_000)
    if amount is None:
        return None
    text = " ".join(page.page_text for page in pages if not page.has_toc_candidate)
    if not (has_direct_purchase_commercial_sw(text) or has_commercial_sw_purchase_signal(pages)):
        return None
    return ReviewResult(
        item_no="2",
        route_type=AttachmentReviewAgent.route_type,
        result="보완필요",
        is_target=True,
        confidence=0.82,
        evidence_pages=[amount.page_no],
        evidence_text=[amount.context],
        reason=(
            f"총 사업금액 {format_amount_억원(amount.amount_won)} 및 상용SW 구매 가능성이 확인되어 "
            "상용SW 직접구매 대상 여부 확인이 필요합니다."
        ),
        recommendation="발주기관에서 해당 여부를 확인 후 상용SW 직접구매 계획표 작성을 권고합니다.",
        needs_human_review=True,
        source="python_attachment_direct_purchase_target_advisory",
        used_llm=False,
    )


def review_bmt_target(pages: list[CandidatePage]) -> ReviewResult | None:
    text = " ".join(page.page_text for page in pages if not page.has_toc_candidate)
    checks = [
        has_competitive_bid(text),
        has_direct_purchase_sw_amount_at_least(text, 100_000_000),
        has_bmt_appendix_three_sw_type(text),
        is_not_g2b_mall_registered(text),
    ]
    if not all(checks):
        return ReviewResult(
            item_no="2-1",
            route_type=AttachmentReviewAgent.route_type,
            result="해당없음",
            is_target=False,
            confidence=0.78,
            evidence_pages=[],
            evidence_text=[],
            reason=(
                "RFP 본문에서 경쟁입찰, 직접구매 대상 상용SW 1억원 이상, 품질성능 평가시험 지침 별표3의 "
                "34종 SW 해당, 조달청 종합쇼핑몰 미등록 조건이 모두 확인되지 않았습니다."
            ),
            recommendation="",
            needs_human_review=False,
            source="python_attachment_bmt_not_target",
            used_llm=False,
        )
    return None


def has_direct_purchase_commercial_sw(text: str) -> bool:
    source = str(text or "")
    compact = "".join(source.split())
    has_sw = "상용SW" in compact or "상용소프트웨어" in compact
    has_direct_purchase = "직접구매" in compact or "분리발주" in compact
    if not (has_sw and has_direct_purchase):
        return False
    for keyword in ["상용SW", "상용소프트웨어", "직접구매", "분리발주"]:
        for match in re.finditer(re.escape(keyword), source):
            window = source[match.start() : min(len(source), match.end() + 35)]
            if any(term in window for term in ["없음", "해당 없음", "미포함", "제외", "없다"]):
                return False
    return True


def has_total_project_budget_at_least(text: str, threshold_won: int) -> bool:
    return max_amount_near_keywords(text, ["총사업금액", "사업금액", "사업예산", "추정가격", "예산"]) >= threshold_won


def has_direct_purchase_sw_amount_at_least(text: str, threshold_won: int) -> bool:
    return max_amount_near_keywords(text, ["상용SW", "상용소프트웨어", "직접구매", "분리발주"]) >= threshold_won


def max_amount_near_keywords(text: str, keywords: list[str]) -> int:
    amounts: list[int] = []
    source = str(text or "")
    for match in re.finditer(r"[\d,]+(?:\.\d+)?\s*(?:억원|억|천만원|천만|백만원|백만|만원|원)", source):
        start = max(0, match.start() - 80)
        end = min(len(source), match.end() + 80)
        window = source[start:end]
        if any(keyword in window for keyword in keywords):
            amounts.append(parse_korean_amount(match.group(0)))
    return max(amounts or [0])


def parse_korean_amount(value: str) -> int:
    compact = value.replace(",", "").replace(" ", "")
    number_match = re.search(r"\d+(?:\.\d+)?", compact)
    if not number_match:
        return 0
    number = float(number_match.group(0))
    if "억원" in compact or "억" in compact:
        return int(number * 100_000_000)
    if "천만원" in compact or "천만" in compact:
        return int(number * 10_000_000)
    if "백만원" in compact or "백만" in compact:
        return int(number * 1_000_000)
    if "만원" in compact:
        return int(number * 10_000)
    if "원" in compact:
        return int(number)
    return 0


def has_competitive_bid(text: str) -> bool:
    compact = "".join(str(text or "").split())
    return "경쟁입찰" in compact or "일반경쟁" in compact or "제한경쟁" in compact


def has_bmt_appendix_three_sw_type(text: str) -> bool:
    compact = "".join(str(text or "").split())
    appendix_terms = ["별표3", "34종", "품질성능평가시험", "BMT"]
    return ("별표3" in compact and "34종" in compact) or sum(term in compact for term in appendix_terms) >= 2


def is_not_g2b_mall_registered(text: str) -> bool:
    compact = "".join(str(text or "").split())
    return (
        "조달청종합쇼핑몰미등록" in compact
        or "종합쇼핑몰등록제품이아닌" in compact
        or ("종합쇼핑몰" in compact and "미등록" in compact)
        or ("종합쇼핑몰" in compact and "등록제품" in compact and "아닐" in compact)
    )
