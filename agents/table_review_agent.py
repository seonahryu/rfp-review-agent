from __future__ import annotations

import re

from agents.gpt_judgement import gpt_review
from agents.llm_client import DisabledLlmClient
from agents.models import CandidatePage, RagContext, ReviewResult
from agents.rule_review_agent import (
    best_rag_keyword_match,
    evidence_for_keywords,
    evidence_window,
    is_project_subcontract_disallowed,
    loose_contains,
    rfp_display_page_no,
)


TABLE_KEYWORDS = {
    "11": ["정량평가", "정성평가", "배점"],
    "12": ["SW기술성", "차등점수", "하도급계획", "적정성", "배점"],
}


class TableReviewAgent:
    route_type = "table_review"

    def __init__(self, llm_client: object | None = None) -> None:
        self.llm_client = llm_client or DisabledLlmClient()

    def review(self, item_no: str, pages: list[CandidatePage], rag: RagContext) -> ReviewResult:
        if str(item_no) == "11":
            score_matches = evidence_for_technical_score_90(pages)
            if score_matches:
                return ReviewResult(
                    item_no=str(item_no),
                    route_type=self.route_type,
                    result="준수",
                    is_target=True,
                    confidence=0.9,
                    evidence_pages=[page for page, _ in score_matches[:3]],
                    evidence_text=[text for _, text in score_matches[:3]],
                    reason="기술능력평가 90점과 가격평가 10점이 확인되어 기술능력평가 비중 90% 기준을 충족합니다.",
                    recommendation="",
                    needs_human_review=False,
                    source="python_table_score_90",
                    used_llm=False,
                )

        if str(item_no) == "12":
            differential_result = review_differential_score_rule(pages)
            if differential_result is not None:
                return differential_result

        gpt_result = gpt_review(
            llm_client=self.llm_client,
            model_role="table",
            item_no=item_no,
            route_type=self.route_type,
            pages=pages,
            rag=rag,
        )
        if gpt_result is not None:
            return gpt_result

        table_pages = [page for page in pages if page.has_eval_table_candidate or page.has_table_candidate]
        candidate_pages = table_pages or pages

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
                reason=f"DB 기준문구 핵심 키워드의 {coverage:.0%}가 평가표 후보 페이지에서 확인되어 70% 기준을 충족했습니다.",
                recommendation="",
                needs_human_review=False,
                source="python_table_rag_overlap",
                used_llm=False,
            )

        matches = evidence_for_keywords(candidate_pages, TABLE_KEYWORDS.get(str(item_no), []))
        if matches:
            return ReviewResult(
                item_no=str(item_no),
                route_type=self.route_type,
                result="보완필요",
                is_target=True,
                confidence=0.7,
                evidence_pages=[page for page, _ in matches[:5]],
                evidence_text=[text for _, text in matches[:5]],
                reason="평가표 후보와 관련 키워드를 찾았지만 DB 기준문구 70% 커버리지는 충족하지 못했습니다.",
                recommendation="표의 세부 배점과 법제도 검토 기준을 대조하세요.",
                needs_human_review=True,
                source="python_table",
                used_llm=False,
            )
        return ReviewResult(
            item_no=str(item_no),
            route_type=self.route_type,
            result="확인필요",
            is_target=None,
            confidence=0.36,
            evidence_pages=[rfp_display_page_no(page) for page in candidate_pages[:3]],
            evidence_text=[page.page_text[:180] for page in candidate_pages[:3]],
            reason="평가표 후보 또는 관련 키워드가 부족합니다.",
            recommendation="파싱 결과의 표 추출 상태를 먼저 확인하세요.",
            needs_human_review=True,
            source="python_table",
            used_llm=False,
        )


def evidence_for_technical_score_90(pages: list[CandidatePage]) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    for page in pages:
        text = page.page_text
        has_technical = loose_contains(text, "기술능력평가")
        has_price = loose_contains(text, "가격평가") or loose_contains(text, "입찰가격평가")
        has_90 = re.search(r"90\s*(?:점|%)", text) is not None
        has_10 = re.search(r"10\s*(?:점|%)", text) is not None
        if has_technical and has_price and has_90 and has_10:
            matches.append((rfp_display_page_no(page), evidence_for_score_text(text)))
    return matches


def evidence_for_score_text(text: str) -> str:
    for keyword in ["기술능력평가점수", "기술능력평가", "평가원칙"]:
        if loose_contains(text, keyword):
            return evidence_window(text, keyword, radius=120)
    return text[:220]


def review_differential_score_rule(pages: list[CandidatePage]) -> ReviewResult | None:
    score_pages = [
        page
        for page in pages
        if has_differential_score_signal(page)
    ]
    not_applied_pages = [
        page
        for page in pages
        if has_differential_score_not_applied(page)
    ]
    subcontract_disallowed_pages = [
        page
        for page in pages
        if is_project_subcontract_disallowed(page.page_text)
    ]
    table_pages = [
        page
        for page in pages
        if is_differential_score_table_page(page)
    ]
    subcontract_plan_score_pages = [
        page
        for page in table_pages
        if has_subcontract_plan_score(page)
    ]
    if not score_pages and not table_pages and not not_applied_pages:
        return None

    if table_pages and not subcontract_disallowed_pages and not subcontract_plan_score_pages:
        evidence_pages, evidence_text = evidence_for_differential_score_pages(
            score_pages[:1] or not_applied_pages[:1],
            table_pages[:3],
            [],
        )
        return ReviewResult(
            item_no="12",
            route_type=TableReviewAgent.route_type,
            result="미준수",
            is_target=True,
            confidence=0.86,
            evidence_pages=evidence_pages,
            evidence_text=evidence_text,
            reason="제안서 기술평가항목 및 배점표에서 하도급계획 적정성 평가항목이 5점 이상 배점으로 명확히 확인되지 않습니다.",
            recommendation="제안서 기술평가항목 및 배점표에 하도급계획 적정성 평가항목을 5점 이상으로 명시해주시기 바랍니다.",
            needs_human_review=False,
            source="python_table_subcontract_plan_score_missing",
            used_llm=False,
        )

    if not_applied_pages:
        evidence_pages, evidence_text = evidence_for_differential_score_pages(
            not_applied_pages[:1],
            subcontract_plan_score_pages[:3] or table_pages[:3],
            subcontract_disallowed_pages[:1],
        )
        return ReviewResult(
            item_no="12",
            route_type=TableReviewAgent.route_type,
            result="준수",
            is_target=True,
            confidence=0.86,
            evidence_pages=evidence_pages,
            evidence_text=evidence_text,
            reason="차등점수제 미적용 사업임이 명시되어 있고, 평가항목 및 배점한도도 확인됩니다.",
            recommendation="",
            needs_human_review=False,
            source="python_table_differential_score_not_applied",
            used_llm=False,
        )

    all_compact = compact_text(" ".join(page.page_text for page in pages))
    required = (
        "원점수기준의순위별점수차가차등점수보다큰경우" in all_compact
        and "동점인경우" in all_compact
    )
    evidence_pages, evidence_text = evidence_for_differential_score_pages(
        score_pages[:1],
        subcontract_plan_score_pages[:3] or table_pages[:3],
        subcontract_disallowed_pages[:1],
    )
    if required:
        return ReviewResult(
            item_no="12",
            route_type=TableReviewAgent.route_type,
            result="준수",
            is_target=True,
            confidence=0.86,
            evidence_pages=evidence_pages,
            evidence_text=evidence_text,
            reason="차등점수제 적용 여부와 평가항목 및 배점한도가 확인되고, 원점수차 및 동점 처리 기준도 명시되어 있습니다.",
            recommendation="",
            needs_human_review=False,
            source="python_table_differential_score",
            used_llm=False,
        )
    return ReviewResult(
        item_no="12",
        route_type=TableReviewAgent.route_type,
        result="보완필요",
        is_target=True,
        confidence=0.84,
        evidence_pages=evidence_pages,
        evidence_text=evidence_text,
        reason="",
        recommendation=(
            "차등점수제 적용 시 원점수 기준의 순위별 점수차가 차등점수보다 큰 경우에는 "
            "원점수 기준 점수차를 적용하고, 동점인 경우 처리 기준을 명시하시기 바랍니다."
        ),
        needs_human_review=False,
        source="python_table_differential_score_missing",
        used_llm=False,
    )


def compact_text(text: str) -> str:
    return "".join(str(text or "").split())


def has_differential_score_signal(page: CandidatePage) -> bool:
    return loose_contains(page.page_text, "차등점수제") or (
        loose_contains(page.page_text, "순위간") and loose_contains(page.page_text, "점수차")
    )


def has_differential_score_not_applied(page: CandidatePage) -> bool:
    return loose_contains(page.page_text, "차등점수제") and loose_contains(page.page_text, "미적용")


def evidence_for_differential_score_pages(
    score_pages: list[CandidatePage],
    table_pages: list[CandidatePage],
    subcontract_disallowed_pages: list[CandidatePage],
) -> tuple[list[int], list[str]]:
    evidence_by_page: dict[int, str] = {}
    for page in score_pages:
        add_page_evidence(evidence_by_page, page, differential_score_evidence_text(page))
    for page in table_pages:
        add_page_evidence(evidence_by_page, page, table_score_evidence_text(page))
    for page in subcontract_disallowed_pages:
        add_page_evidence(evidence_by_page, page, evidence_window(page.page_text, "하도급", radius=180))
    pages = sorted(evidence_by_page)
    return pages, [evidence_by_page[page] for page in pages]


def add_page_evidence(evidence_by_page: dict[int, str], page: CandidatePage, text: str) -> None:
    page_no = rfp_display_page_no(page)
    if page_no not in evidence_by_page:
        evidence_by_page[page_no] = text
        return
    if text and text not in evidence_by_page[page_no]:
        evidence_by_page[page_no] = f"{evidence_by_page[page_no]}\n{text}"


def differential_score_evidence_text(page: CandidatePage) -> str:
    if loose_contains(page.page_text, "미적용"):
        return evidence_window(page.page_text, "차등점수", radius=220)
    if loose_contains(page.page_text, "차등점수"):
        return evidence_window(page.page_text, "차등점수", radius=220)
    if loose_contains(page.page_text, "순위간"):
        return evidence_window(page.page_text, "순위간", radius=220)
    return page.page_text[:260]


def table_score_evidence_text(page: CandidatePage) -> str:
    if has_subcontract_plan_score(page):
        return evidence_window(page.page_text, "하도급", radius=180)
    if loose_contains(page.page_text, "평가항목"):
        return evidence_window(page.page_text, "평가항목", radius=180)
    if loose_contains(page.page_text, "배점"):
        return evidence_window(page.page_text, "배점", radius=180)
    return page.page_text[:260]


def has_subcontract_plan_score(page: CandidatePage, minimum_score: float = 5.0) -> bool:
    text = str(page.page_text or "")
    if not (loose_contains(text, "하도급") and loose_contains(text, "계획") and loose_contains(text, "적정성")):
        return False

    for line in text.splitlines():
        if loose_contains(line, "하도급") and loose_contains(line, "계획") and loose_contains(line, "적정성"):
            if max_score_in_text(line) >= minimum_score:
                return True

    compact = compact_text(text)
    for match in re.finditer("하도급", compact):
        window = compact[max(0, match.start() - 40): match.end() + 80]
        if "계획" in window and "적정성" in window and max_score_in_text(window) >= minimum_score:
            return True
    return False


def max_score_in_text(text: str) -> float:
    scores = [
        float(match.group(1))
        for match in re.finditer(r"(?<!\d)(\d+(?:\.\d+)?)(?=\s*(?:점|$))", str(text or ""))
    ]
    return max(scores, default=0.0)


def unique_pages(pages: list[CandidatePage]) -> list[int]:
    result = []
    for page in pages:
        page_no = rfp_display_page_no(page)
        if page_no not in result:
            result.append(page_no)
    return result[:5]


def is_differential_score_table_page(page: CandidatePage) -> bool:
    text = page.page_text
    if "평가항목" in text and ("배점" in text or "배점한도" in text):
        return True
    if "소프트웨어기술성평가기준" in text:
        return True
    return "하자보수" in text and "비상 대책" in text
