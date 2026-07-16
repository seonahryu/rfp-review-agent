from __future__ import annotations

from agents.gpt_judgement import gpt_review
from agents.llm_client import DisabledLlmClient
from agents.models import CandidatePage, RagContext, ReviewResult
from agents.rule_review_agent import evidence_window, rfp_display_page_no


class LlmReviewAgent:
    route_type = "llm_review"

    def __init__(self, llm_client: object | None = None) -> None:
        self.llm_client = llm_client or DisabledLlmClient()

    def review(self, item_no: str, pages: list[CandidatePage], rag: RagContext) -> ReviewResult:
        if str(item_no) == "16":
            heuristic = review_item_16_workforce_management(pages)
            if heuristic is not None:
                return heuristic
        gpt_result = gpt_review(
            llm_client=self.llm_client,
            model_role="general",
            item_no=item_no,
            route_type=self.route_type,
            pages=pages,
            rag=rag,
        )
        if gpt_result is not None:
            return gpt_result
        return ReviewResult(
            item_no=str(item_no),
            route_type=self.route_type,
            result="보완필요",
            is_target=None,
            confidence=0.4,
            evidence_pages=[],
            evidence_text=[],
            reason="OPENAI_API_KEY가 설정되어 있지 않아 일반 GPT 검토를 건너뜁니다.",
            recommendation="API 키 설정 후 다시 실행하세요.",
            needs_human_review=True,
            source="llm_disabled",
            warnings=["OPENAI_API_KEY missing"],
            used_llm=False,
        )


ITEM_16_TRIGGER_TERMS = [
    "투입인력",
    "투입 인력",
    "인력현황",
    "인력 현황",
    "이력사항",
    "이력 사항",
    "전문 인력",
    "전문인력",
    "업무분장",
    "업무 분장",
]


def review_item_16_workforce_management(pages: list[CandidatePage]) -> ReviewResult | None:
    trigger_pages: list[tuple[int, str]] = []
    function_pages: list[int] = []
    for page in pages:
        if page.has_toc_candidate:
            continue
        text = str(page.page_text or "")
        compact = "".join(text.split())
        if any("".join(term.split()) in compact for term in ITEM_16_TRIGGER_TERMS):
            trigger_pages.append((rfp_display_page_no(page), evidence_window(text, "인력", radius=220)))
        if has_function_requirement_signal(compact):
            function_pages.append(rfp_display_page_no(page))

    if not trigger_pages:
        return None

    fp_sla_sentence = (
        "기능 요구사항이 확인되어 FP(Function Point) 방식 사업대가 산정 가능성이 있으나, "
        if function_pages
        else ""
    )
    page_text = ", ".join(f"{page}쪽" for page, _ in trigger_pages[:5])
    return ReviewResult(
        item_no="16",
        route_type=LlmReviewAgent.route_type,
        result="보완필요",
        is_target=True,
        confidence=0.78,
        evidence_pages=[page for page, _ in trigger_pages[:5]],
        evidence_text=[text for _, text in trigger_pages[:5]],
        reason=(
            f"{fp_sla_sentence}제안요청서 내용만으로 FP 방식 또는 SLA 방식 적용 여부를 명확히 확정하기 어렵습니다. "
            "발주기관이 해당 방식 적용 여부를 직접 판단해야 합니다."
        ),
        recommendation=(
            f"제안요청서({page_text})에 명시한 투입인력 요구 및 관리 관련 내용"
            "(인력현황, 이력사항, 전문인력, 업무분장, 투입인력 수·경력·수행조직 등)을 모두 삭제하시기 바랍니다. "
            "다만 제안요청서만으로 FP 방식 또는 SLA 방식 적용 여부가 명확하지 않은 경우 발주기관에서 해당 여부를 먼저 판단하시기 바랍니다."
        ),
        needs_human_review=True,
        source="python_llm_item_16_workforce_trigger",
        used_llm=False,
    )


def has_function_requirement_signal(compact: str) -> bool:
    return any(term in compact for term in ["기능요구사항", "기능요구", "요구사항분류기능", "FUR-", "SFR-"])
