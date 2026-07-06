import sqlite3
import tempfile
import unittest
from pathlib import Path


class RouterTests(unittest.TestCase):
    def test_routes_known_item_groups(self):
        from agents.review_router import route_item

        self.assertEqual(route_item("1"), "rule")
        self.assertEqual(route_item("2"), "attachment")
        self.assertEqual(route_item("4"), "rule")
        self.assertEqual(route_item("12"), "table")
        self.assertEqual(route_item("16"), "llm")
        self.assertEqual(route_item("5"), "llm")


class VerificationTests(unittest.TestCase):
    def test_agreement_without_evidence_is_grounding_problem(self):
        from agents.models import ReviewResult
        from agents.verification_agent import VerificationAgent

        first = ReviewResult(
            item_no="12",
            route_type="table",
            result="준수",
            is_target=True,
            confidence=0.82,
            evidence_pages=[],
            evidence_text=[],
            reason="평가표에 반영되어 있음",
            recommendation="",
            needs_human_review=False,
            source="rule",
        )
        second = ReviewResult(
            item_no="12",
            route_type="table",
            result="준수",
            is_target=True,
            confidence=0.8,
            evidence_pages=[],
            evidence_text=[],
            reason="동일 판단",
            recommendation="",
            needs_human_review=False,
            source="llm",
        )

        final = VerificationAgent().verify("12", [first, second], parse_status="ok")

        self.assertEqual(final.final_status, "근거 부족")

    def test_disagreement_requires_human_review(self):
        from agents.models import ReviewResult
        from agents.verification_agent import VerificationAgent

        first = ReviewResult(
            item_no="15",
            route_type="attachment",
            result="준수",
            is_target=True,
            confidence=0.75,
            evidence_pages=[30],
            evidence_text=["블라인드 평가로 진행"],
            reason="블라인드 문구 확인",
            recommendation="",
            needs_human_review=False,
            source="rule",
        )
        second = ReviewResult(
            item_no="15",
            route_type="attachment",
            result="미준수",
            is_target=True,
            confidence=0.71,
            evidence_pages=[31],
            evidence_text=["성명 및 소속 기재"],
            reason="비식별 미흡",
            recommendation="블라인드 처리 문구를 명확히 하십시오.",
            needs_human_review=True,
            source="llm",
        )

        final = VerificationAgent().verify("15", [first, second], parse_status="ok")

        self.assertEqual(final.final_status, "검토 결과 불일치")


class OrchestratorCostTests(unittest.TestCase):
    def test_rule_item_does_not_call_llm_when_keyword_found(self):
        from orchestrator import RfpReviewPipeline

        class CountingLlm:
            calls = 0

            def is_configured(self):
                return True

            def json_response(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("LLM should not be called")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE rfp_document (
                    id INTEGER PRIMARY KEY,
                    document_name TEXT,
                    file_path TEXT,
                    total_pages INTEGER,
                    parse_status TEXT,
                    parse_warning_count INTEGER
                );
                CREATE TABLE rfp_page (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER,
                    page_no INTEGER,
                    page_text TEXT,
                    text_length INTEGER,
                    has_table_candidate INTEGER,
                    has_attachment_candidate INTEGER,
                    has_eval_table_candidate INTEGER,
                    has_toc_candidate INTEGER,
                    has_blind_candidate INTEGER,
                    has_commercial_sw_candidate INTEGER,
                    parser_warning TEXT
                );
                CREATE TABLE legal_item (item_no TEXT, title TEXT, target_text TEXT);
                """
            )
            conn.execute("INSERT INTO rfp_document VALUES (1, 'sample.pdf', '', 1, 'ok', 0)")
            conn.execute(
                """
                INSERT INTO rfp_page VALUES (
                    1, 1, 1, '과업심의위원회 심의를 완료하고 결과를 반영한다.',
                    25, 0, 0, 0, 0, 0, 0, NULL
                )
                """
            )
            conn.execute("INSERT INTO legal_item VALUES ('1', '과업내용 확정', '')")
            conn.commit()
            conn.close()

            client = CountingLlm()
            pipeline = RfpReviewPipeline(db_path=db_path, output_dir=Path(tmp) / "out", llm_client=client)
            final = pipeline.review_existing_document(document_id=1, item_nos=["1"]).final_reviews[0]

            self.assertEqual(client.calls, 0)
            self.assertEqual(final.final_result, "준수")
            self.assertEqual(final.final_status, "자동 확정 가능")


if __name__ == "__main__":
    unittest.main()
