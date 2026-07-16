from __future__ import annotations

import unittest

from agents.attach_review_agent import AttachmentReviewAgent
from agents.internal_assessment import build_internal_assessment
from agents.llm_review_agent import LlmReviewAgent
from agents.models import CandidatePage, FinalReview, RagContext, ReviewResult
from agents.review_common import postprocess_final_review
from agents.rule_review_agent import RuleReviewAgent


class FeedbackRegressionTests(unittest.TestCase):
    def test_item_four_subcontract_checklist_excludes_form_pages_and_lists_missing_items(self):
        pages = [
            CandidatePage(
                page_no=90,
                page_text="서식 하도급계획 적정성 확인서 하도급 사전승인 50% 초과할 수 없음",
                text_length=80,
                has_attachment_candidate=True,
            ),
            CandidatePage(
                page_no=21,
                page_text=(
                    "제안 안내 사항 하도급 사전승인 안내. 하도급 비율은 50%를 초과할 수 없음. "
                    "재하도급은 원칙적으로 불허함. 계약체결 시 하도급 계획서를 제출하여야 함."
                ),
                text_length=120,
            ),
        ]

        result = RuleReviewAgent().review("4", pages, RagContext(item_no="4"))

        self.assertEqual(result.result, "보완필요")
        self.assertIn("☑ 하도급 사전 승인 안내 명시 (p.21)", result.reason)
        self.assertIn("☐ \"소프트웨어사업 하도급 계획 적정성 확인서\" 제출 안내 미명시", result.reason)
        self.assertNotIn(90, result.evidence_pages)
        assessment = build_internal_assessment("4", result.evidence_pages, result.evidence_text)
        self.assertIsNotNone(assessment)
        self.assertEqual(assessment["rows"][0]["explicit_status"], "명시")
        self.assertEqual(assessment["rows"][0]["evidence_pairs"][0]["page"], 21)

    def test_item_six_internal_assessment_treats_joint_ownership_as_joint_attribution(self):
        assessment = build_internal_assessment(
            "6",
            [10],
            [
                "지식재산권은 발주기관과 계약상대자가 공동소유한다. "
                "SW산출물 반출 요청절차, 누출금지정보 삭제, 확약서 제출, 제3자 사전승인, 입찰참가자격 제한을 명시한다."
            ],
        )

        self.assertIsNotNone(assessment)
        self.assertEqual(assessment["rows"][0]["explicit_status"], "명시")
        self.assertEqual(assessment["final_result"], "준수")

    def test_item_two_target_advisory_includes_budget_and_direct_purchase_plan_recommendation(self):
        pages = [
            CandidatePage(
                page_no=5,
                page_text="사업 개요 총 사업금액 4억원이며 직접구매 대상 상용SW 구매를 포함한다.",
                text_length=60,
            )
        ]

        result = AttachmentReviewAgent().review("2", pages, RagContext(item_no="2"))

        self.assertEqual(result.result, "보완필요")
        self.assertIn("4억 원", result.reason)
        self.assertIn("상용SW 직접구매 계획표", result.recommendation)

    def test_budget_basis_is_applied_to_items_2_3_13_18(self):
        pages = [
            CandidatePage(
                page_no=7,
                page_text="사업 개요 총 사업금액 12억원 부가가치세 포함",
                text_length=40,
            )
        ]
        for item_no in ["2", "3", "13", "18"]:
            with self.subTest(item_no=item_no):
                review = FinalReview(
                    item_no=item_no,
                    final_status="자동 확정 가능",
                    final_result="보완필요",
                    is_target=True,
                    confidence=0.8,
                    evidence_pages=[],
                    evidence_text=[],
                    reason="대상 사업으로 판단",
                    recommendation="",
                    reviews=[],
                )
                postprocess_final_review(review, pages)
                self.assertIn("p.7", review.reason)
                self.assertIn("12억 원", review.reason)

    def test_project_amount_ignores_non_budget_amount_context(self):
        from agents.review_common import find_project_amount_evidence

        pages = [
            CandidatePage(
                page_no=8,
                page_text="하도급 금액 5억원 및 평가점수 90점 관련 안내",
                text_length=40,
            )
        ]

        self.assertIsNone(find_project_amount_evidence(pages))

    def test_attachment_pages_force_manual_check_status_with_specific_instruction(self):
        review = FinalReview(
            item_no="17",
            final_status="자동 확정 가능",
            final_result="준수",
            is_target=True,
            confidence=0.9,
            evidence_pages=[12],
            evidence_text=["영향평가 실시"],
            reason="영향평가 결과서가 확인되었습니다.",
            recommendation="",
            reviews=[
                ReviewResult(
                    item_no="17",
                    route_type="attachment_review",
                    result="준수",
                    is_target=True,
                    confidence=0.9,
                    evidence_pages=[12],
                    evidence_text=["영향평가 실시"],
                    reason="영향평가 결과서가 확인되었습니다.",
                    recommendation="",
                    needs_human_review=False,
                    source="test",
                )
            ],
        )
        pages = [
            CandidatePage(
                page_no=44,
                page_text="붙임 소프트웨어사업 영향평가 검토결과서 기관장 날인",
                text_length=40,
                has_attachment_candidate=True,
            )
        ]

        postprocess_final_review(review, pages)

        self.assertEqual(review.final_result, "확인요망")
        self.assertIn("기관장 날인 여부", review.recommendation)
        self.assertEqual(review.evidence_pages, [44])

    def test_item_fifteen_missing_attachment_uses_noncompliant_template(self):
        pages = [
            CandidatePage(
                page_no=20,
                page_text="본 사업은 소프트웨어 개발사업 적정 사업기간 산정 기준에 따른 사업이다.",
                text_length=50,
            )
        ]

        result = AttachmentReviewAgent().review("15", pages, RagContext(item_no="15"))

        self.assertEqual(result.result, "미준수")
        self.assertIn("위원명 및 서명을 제외한", result.recommendation)
        self.assertNotIn("확인 후 검토의견", result.recommendation)

    def test_item_seventeen_empty_attachment_uses_noncompliant_template(self):
        pages = [
            CandidatePage(
                page_no=74,
                page_text="본 사업은 소프트웨어사업 영향평가를 실시한 사업이며 결과서를 첨부한다.",
                text_length=50,
            ),
            CandidatePage(
                page_no=75,
                page_text="붙임 소프트웨어사업 영향평가 결과서",
                text_length=30,
                has_attachment_candidate=True,
            ),
        ]

        result = AttachmentReviewAgent().review("17", pages, RagContext(item_no="17"))

        self.assertEqual(result.result, "미준수")
        self.assertIn("제안요청서 p.74", result.recommendation)
        self.assertIn("기관장 직인이 날인된", result.recommendation)
        self.assertNotIn("기관장 날인 여부를 확인", result.recommendation)

    def test_item_seventeen_substantive_attachment_is_manual_check_after_postprocess(self):
        review = FinalReview(
            item_no="17",
            final_status="자동 확정 가능",
            final_result="준수",
            is_target=True,
            confidence=0.9,
            evidence_pages=[74, 75],
            evidence_text=["영향평가 실시", "영향평가 결과서 본문"],
            reason="소프트웨어사업 영향평가 실시 명시와 영향평가 검토 결과서 첨부 본문이 함께 확인되었습니다.",
            recommendation="",
            reviews=[],
        )
        pages = [
            CandidatePage(
                page_no=74,
                page_text="본 사업은 소프트웨어사업 영향평가를 실시한 사업이며 결과서를 첨부한다.",
                text_length=50,
            ),
            CandidatePage(
                page_no=75,
                page_text=(
                    "붙임 소프트웨어사업 영향평가 결과서\n"
                    "영향평가단계 발주 전 평가항목 민간시장 침해 가능성 낮음 평가결과 해당 없음 "
                    "종합의견 본 사업은 내부 행정서비스 개선을 위한 구축 사업으로 민간서비스 중복 가능성이 낮고 "
                    "검토 결과 소프트웨어사업 영향평가 기준에 타당함."
                ),
                text_length=150,
                has_attachment_candidate=True,
            ),
        ]

        postprocess_final_review(review, pages)

        self.assertEqual(review.final_result, "확인요망")
        self.assertIn("기관장 날인 여부", review.recommendation)

    def test_item_sixteen_uses_relaxed_workforce_triggers_and_fp_sla_guidance(self):
        pages = [
            CandidatePage(
                page_no=30,
                page_text="기능 요구사항 FUR-001 조회 기능. 제안사는 전문 인력 이력사항 및 업무분장을 제출하여야 한다.",
                text_length=80,
            )
        ]

        result = LlmReviewAgent().review("16", pages, RagContext(item_no="16"))

        self.assertEqual(result.result, "보완필요")
        self.assertIn("FP(Function Point)", result.reason)
        self.assertIn("업무분장", result.recommendation)
        self.assertIn("모두 삭제", result.recommendation)


if __name__ == "__main__":
    unittest.main()
