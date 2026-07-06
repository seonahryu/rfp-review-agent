import unittest


class ParseAuditHybridTests(unittest.TestCase):
    def test_attachment_index_page_is_not_treated_as_parse_error(self):
        from agents.audit_agent import ParseAuditAgent
        from agents.models import CandidatePage, ParsedDocument

        document = ParsedDocument(
            document_id=1,
            document_name="sample.pdf",
            pdf_path=None,
            total_pages=120,
            parse_status="ok",
            pages=[
                CandidatePage(
                    page_no=113,
                    page_text=(
                        "Ⅶ. 별첨\n"
                        "별첨 1 소프트웨어 개발사업의 적정 사업기간 종합 산정서\n"
                        "별첨 2 보안위반 처리기준\n"
                        "별첨 3 보안서약서"
                    ),
                    text_length=58,
                    rfp_printed_page_no=111,
                    has_attachment_candidate=True,
                    parser_warning="내용 없음으로 오인 가능",
                )
            ],
        )

        warnings = ParseAuditAgent(use_gpt=False).python_audit(document)

        self.assertEqual([warning.warning_type for warning in warnings if warning.page_no == 113], [])

    def test_partial_parse_does_not_warn_about_late_evaluation_sections(self):
        from agents.audit_agent import ParseAuditAgent
        from agents.models import CandidatePage, ParsedDocument

        document = ParsedDocument(
            document_id=1,
            document_name="sample.pdf",
            pdf_path=None,
            total_pages=76,
            parse_status="ok",
            pages=[
                CandidatePage(
                    page_no=3,
                    page_text="Ⅰ 사업개요\n사업명 테스트",
                    text_length=12,
                ),
                CandidatePage(
                    page_no=10,
                    page_text="Ⅴ 제안요청 내용\n요구사항 총괄표",
                    text_length=18,
                ),
            ],
        )

        audited = ParseAuditAgent(use_gpt=False).audit(document)
        warning_types = {warning.warning_type for warning in audited.audit_warnings}

        self.assertNotIn("eval_table_not_found", warning_types)
        self.assertNotIn("attachment_not_found", warning_types)

    def test_suspicious_unicode_noise_is_flagged(self):
        from agents.audit_agent import ParseAuditAgent
        from agents.models import CandidatePage, ParsedDocument

        document = ParsedDocument(
            document_id=1,
            document_name="sample.pdf",
            pdf_path=None,
            total_pages=10,
            parse_status="ok",
            pages=[
                CandidatePage(
                    page_no=3,
                    page_text="업무 및 조직 미래모델 설계 ৑ 운영ঔ유지관리 요건 ॑율적 업무기능",
                    text_length=45,
                )
            ],
        )

        warnings = ParseAuditAgent(use_gpt=False).python_audit(document)

        self.assertIn("suspicious_unicode_noise", {warning.warning_type for warning in warnings})

    def test_gpt_audit_can_override_false_positive_flags(self):
        from agents.audit_agent import ParseAuditAgent
        from agents.models import CandidatePage, ParsedDocument

        class FakeClient:
            def is_configured(self):
                return True

            def json_response(self, *args, **kwargs):
                return {
                    "page_overrides": [
                        {
                            "page_no": 2,
                            "has_attachment_candidate": False,
                            "has_table_candidate": False,
                        }
                    ],
                    "warnings": [
                        {
                            "warning_type": "attachment_false_positive",
                            "page_no": 2,
                            "severity": "low",
                            "message": "목차의 붙임 참조일 뿐 실제 별첨 본문이 아닙니다.",
                            "related_item_nos": [],
                        }
                    ],
                }

        page = CandidatePage(
            page_no=2,
            page_text="목차\nⅠ 사업개요 3\n붙임 8 참조",
            text_length=20,
            has_attachment_candidate=True,
            has_table_candidate=True,
        )
        document = ParsedDocument(
            document_id=1,
            document_name="sample.pdf",
            pdf_path=None,
            total_pages=76,
            parse_status="ok",
            pages=[page],
        )

        audited = ParseAuditAgent(llm_client=FakeClient()).audit(document)

        self.assertFalse(audited.pages[0].has_attachment_candidate)
        self.assertFalse(audited.pages[0].has_table_candidate)
        self.assertTrue(any(w.warning_type == "attachment_false_positive" for w in audited.audit_warnings))

    def test_orchestrator_evidence_selection_ignores_table_and_attachment_flags(self):
        from agents.models import CandidatePage, RagContext, RagHit
        from orchestrator import select_evidence_pages

        rag = RagContext(
            item_no="12",
            hits=[
                RagHit(
                    item_no="12",
                    source_type="criteria",
                    source_name="criteria.xlsx",
                    title="alpha beta",
                    category="criteria",
                    snippet="alpha beta gamma",
                )
            ],
        )
        pages = [
            CandidatePage(
                page_no=1,
                page_text="unrelated content",
                text_length=17,
                has_eval_table_candidate=True,
                has_attachment_candidate=True,
            ),
            CandidatePage(
                page_no=2,
                page_text="alpha beta gamma relevant content",
                text_length=33,
            ),
        ]

        selected = select_evidence_pages("12", rag, pages, limit=1)

        self.assertEqual([page.page_no for page in selected], [2])


if __name__ == "__main__":
    unittest.main()
