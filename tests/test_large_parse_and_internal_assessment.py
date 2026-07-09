import unittest
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys


def json_dumps(value):
    return json.dumps(value, ensure_ascii=False)


class LargeParseAndInternalAssessmentTests(unittest.TestCase):
    def import_review_for_ui(self):
        if "fastapi" not in sys.modules:
            fastapi = ModuleType("fastapi")
            fastapi.FastAPI = lambda *args, **kwargs: SimpleNamespace(
                add_middleware=lambda *a, **k: None,
                get=lambda *a, **k: (lambda fn: fn),
                post=lambda *a, **k: (lambda fn: fn),
            )
            fastapi.File = lambda *args, **kwargs: None
            fastapi.Form = lambda *args, **kwargs: None
            fastapi.BackgroundTasks = object
            fastapi.UploadFile = object
            sys.modules["fastapi"] = fastapi
            middleware = ModuleType("fastapi.middleware")
            cors = ModuleType("fastapi.middleware.cors")
            cors.CORSMiddleware = object
            responses = ModuleType("fastapi.responses")
            responses.FileResponse = lambda *args, **kwargs: None
            responses.JSONResponse = lambda data=None, *args, **kwargs: data
            sys.modules["fastapi.middleware"] = middleware
            sys.modules["fastapi.middleware.cors"] = cors
            sys.modules["fastapi.responses"] = responses
        from api.main import review_for_ui

        return review_for_ui

    def test_parser_retries_failed_multi_page_chunk_as_single_pages(self):
        from pypdf import PdfWriter
        import tempfile

        from agents.gpt_parser_agent import GptParserAgent, GptParserConfig
        from agents.models import CandidatePage

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "large-ish.pdf"
            writer = PdfWriter()
            for _ in range(4):
                writer.add_blank_page(width=72, height=72)
            with pdf_path.open("wb") as handle:
                writer.write(handle)

            class FallbackParser(GptParserAgent):
                def __init__(self, db_path):
                    super().__init__(
                        db_path,
                        api_key="test-key",
                        config=GptParserConfig(pages_per_call=2, timeout_seconds=1, max_retries=0),
                    )
                    self.calls = []

                def extract_chunk(self, chunk_path: Path, page_numbers: list[int]):
                    self.calls.append(tuple(page_numbers))
                    if len(page_numbers) > 1:
                        raise RuntimeError("chunk too large")
                    page_no = page_numbers[0]
                    return [
                        CandidatePage(
                            page_no=page_no,
                            page_text=f"page {page_no} parsed",
                            text_length=len(f"page {page_no} parsed"),
                        )
                    ]

            parser = FallbackParser(tmp_path / "parse.db")

            document = parser.parse(pdf_path)

            self.assertEqual([page.page_no for page in document.pages], [1, 2, 3, 4])
            self.assertEqual(parser.calls, [(1, 2), (1,), (2,), (3, 4), (3,), (4,)])

    def test_extract_chunk_returns_every_page_in_multi_page_response(self):
        import tempfile
        from unittest.mock import patch

        from agents.gpt_parser_agent import GptParserAgent

        response_text = {
            "pages": [
                {"pdf_page_no": 1, "page_text": "첫 페이지", "tables_markdown": ""},
                {"pdf_page_no": 2, "page_text": "둘째 페이지", "tables_markdown": ""},
            ]
        }

        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        try:
            path = Path(handle.name)
            handle.write(b"%PDF-1.4\n")
            handle.close()
            parser = GptParserAgent("unused.db", api_key="test-key")
            with patch("agents.gpt_parser_agent.post_json", return_value={}), patch(
                "agents.gpt_parser_agent.extract_response_text",
                return_value=json_dumps(response_text),
            ):
                pages = parser.extract_chunk(path, [1, 2])
        finally:
            Path(handle.name).unlink(missing_ok=True)

        self.assertEqual([page.page_no for page in pages], [1, 2])
        self.assertEqual([page.page_text for page in pages], ["첫 페이지", "둘째 페이지"])

    def test_openai_api_key_placeholder_fails_with_clear_error(self):
        from agents.gpt_parser_agent import validate_openai_api_key

        with self.assertRaisesRegex(RuntimeError, "non-ASCII"):
            validate_openai_api_key("여기에_실제_OpenAI_API_KEY")

    def test_review_for_ui_draws_item_5_internal_assessment_table(self):
        from agents.models import FinalReview, ReviewResult
        review_for_ui = self.import_review_for_ui()

        evidence = [
            "제안요청서에는 작업장소를 상호 협의하여 정하고 작업장소 관련 비용을 제안가격에 포함한다고 명시한다.",
            "공급자는 원격지 개발 장소를 제시하고 발주기관은 보안요건 충족 여부를 검토한다.",
            "원격지 개발 장소는 출입통제, 저장매체 반출입 제한 등 보안요구사항을 준수하여야 한다.",
        ]
        review = ReviewResult(
            item_no="5",
            route_type="llm_review",
            result="준수",
            is_target=True,
            confidence=0.91,
            evidence_pages=[10, 11, 12],
            evidence_text=evidence,
            reason="세부 항목 3개가 모두 명시됨",
            recommendation="",
            needs_human_review=False,
            source="test",
        )
        final = FinalReview(
            item_no="5",
            final_status="자동 확정 가능",
            final_result="준수",
            is_target=True,
            confidence=0.91,
            evidence_pages=[10, 11, 12],
            evidence_text=evidence,
            reason=review.reason,
            recommendation="",
            reviews=[review],
        )

        data = review_for_ui(final, {"5": {"title": "SW사업 작업장소(원격개발)"}})

        self.assertEqual(data["detailed_assessment"]["item_no"], "5")
        self.assertEqual(
            [row["explicit_status"] for row in data["detailed_assessment"]["rows"]],
            ["명시", "명시", "명시"],
        )
        self.assertEqual(data["detailed_assessment"]["final_result"], "준수")

    def test_review_for_ui_marks_item_6_partial_internal_assessment_as_revision(self):
        from agents.models import FinalReview, ReviewResult
        review_for_ui = self.import_review_for_ui()

        evidence = [
            "계약목적물의 지식재산권은 공동귀속으로 한다.",
            "공급자는 SW산출물 반출을 요청할 수 있으며 발주기관 검토 후 승인한다.",
            "누출금지정보는 삭제 후 공급자 대표 명의 확약서를 제출한다.",
        ]
        review = ReviewResult(
            item_no="6",
            route_type="rule_review",
            result="준수",
            is_target=True,
            confidence=0.88,
            evidence_pages=[20, 21, 22],
            evidence_text=evidence,
            reason="일부 항목 확인",
            recommendation="",
            needs_human_review=False,
            source="test",
        )
        final = FinalReview(
            item_no="6",
            final_status="자동 확정 가능",
            final_result="준수",
            is_target=True,
            confidence=0.88,
            evidence_pages=[20, 21, 22],
            evidence_text=evidence,
            reason=review.reason,
            recommendation="",
            reviews=[review],
        )

        data = review_for_ui(final, {"6": {"title": "SW사업 산출물 활용 보장"}})

        self.assertEqual(
            [row["explicit_status"] for row in data["detailed_assessment"]["rows"]],
            ["명시", "일부명시"],
        )
        self.assertEqual(data["detailed_assessment"]["final_result"], "보완필요")
        self.assertEqual(data["normalized_result"], "보완필요")


if __name__ == "__main__":
    unittest.main()
