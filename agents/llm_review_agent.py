from __future__ import annotations

from agents.gpt_judgement import gpt_review
from agents.llm_client import DisabledLlmClient
from agents.models import CandidatePage, RagContext, ReviewResult


class LlmReviewAgent:
    route_type = "llm_review"

    def __init__(self, llm_client: object | None = None) -> None:
        self.llm_client = llm_client or DisabledLlmClient()

    def review(self, item_no: str, pages: list[CandidatePage], rag: RagContext) -> ReviewResult:
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
