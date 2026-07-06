import json
import tempfile
import unittest
from pathlib import Path


class RunReviewResumeTests(unittest.TestCase):
    def test_resume_state_reuses_completed_items_and_lists_remaining_items(self):
        from tools.run_review_from_candidate_jsonl import load_resume_state

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "review_type3.json"
            output.write_text(
                json.dumps(
                    {
                        "item_results": [
                            {
                                "item_no": "5",
                                "route": "general",
                                "rag_hit_count": 1,
                                "rag_hits": [],
                                "review": {
                                    "item_no": "5",
                                    "route_type": "llm_review",
                                    "result": "준수",
                                    "is_target": True,
                                    "confidence": 0.9,
                                    "evidence_pages": [21],
                                    "evidence_text": ["작업장소"],
                                    "reason": "ok",
                                    "recommendation": "",
                                    "needs_human_review": False,
                                    "source": "openai_general",
                                    "warnings": [],
                                    "used_llm": True,
                                },
                                "final": {
                                    "item_no": "5",
                                    "final_status": "자동 확정 가능",
                                    "final_result": "준수",
                                    "is_target": True,
                                    "confidence": 0.9,
                                    "evidence_pages": [21],
                                    "evidence_text": ["작업장소"],
                                    "reason": "ok",
                                    "recommendation": "",
                                    "reviews": [],
                                    "warnings": [],
                                },
                            }
                        ],
                        "merged_final_reviews": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            state = load_resume_state(output, ["5", "8", "10"])

        self.assertEqual([item["item_no"] for item in state.item_results], ["5"])
        self.assertEqual([final.item_no for final in state.final_reviews], ["5"])
        self.assertEqual(state.remaining_items, ["8", "10"])

    def test_write_review_output_persists_partial_results_for_resume(self):
        from agents.models import FinalReview
        from tools.run_review_from_candidate_jsonl import write_review_output

        final = FinalReview(
            item_no="5",
            final_status="자동 확정 가능",
            final_result="준수",
            is_target=True,
            confidence=0.9,
            evidence_pages=[21],
            evidence_text=["작업장소"],
            reason="ok",
            recommendation="",
            reviews=[],
            warnings=[],
        )
        item_result = {
            "item_no": "5",
            "route": "general",
            "rag_hit_count": 1,
            "rag_hits": [],
            "review": {},
            "final": final.to_dict(),
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "review.json"
            write_review_output(
                output,
                input_path=Path("candidate.jsonl"),
                db_path=Path("criteria.db"),
                use_gpt=True,
                skip_parse_audit=True,
                requested_items=None,
                group="type3",
                expanded_items=["5", "8"],
                page_count=10,
                parse_status="ok",
                audit_score=None,
                audit_warnings=[],
                pages_to_reparse=[],
                debug_counts={"toc_candidate_pages": 0},
                item_results=[item_result],
                final_reviews=[final],
                resume_enabled=True,
                completed=True,
            )

            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(data["resume"]["enabled"], True)
        self.assertEqual(data["resume"]["completed_items"], ["5"])
        self.assertEqual(data["resume"]["remaining_items"], ["8"])
        self.assertEqual(data["item_results"][0]["item_no"], "5")


if __name__ == "__main__":
    unittest.main()
