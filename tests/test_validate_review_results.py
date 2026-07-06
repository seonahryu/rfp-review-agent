import json
import tempfile
import unittest
from pathlib import Path


class ValidateReviewResultsTests(unittest.TestCase):
    def sample_payload(self):
        return {
            "group": "sample",
            "item_results": [
                {
                    "item_no": "5",
                    "route": "llm",
                    "rag_hits": [],
                }
            ],
            "merged_final_reviews": [
                {
                    "item_no": "5",
                    "final_status": "자동 확정 가능",
                    "final_result": "준수",
                    "is_target": True,
                    "confidence": 0.9,
                    "evidence_pages": [25],
                    "evidence_text": ["작업장소 상호협의 및 원격지 개발방법"],
                    "reason": "작업장소, 원격지 개발방법, 보안관리 대책이 모두 확인됨",
                    "recommendation": "",
                    "reviews": [],
                    "warnings": [],
                }
            ],
        }

    def test_validate_payload_attaches_audit_without_replacing_review(self):
        from agents.llm_client import DisabledLlmClient
        from tools.validate_review_results import validate_payload

        payload = self.sample_payload()

        validated = validate_payload(payload, llm_client=DisabledLlmClient(), adjudicate=False)

        final = validated["merged_final_reviews"][0]
        self.assertEqual(final["final_result"], "준수")
        self.assertIn("verification_audit", final)
        self.assertEqual(final["verification_audit"]["item_no"], "5")
        self.assertEqual(validated["validation"]["mode"], "audit_only")

    def test_validation_output_can_feed_sentence_generation(self):
        from agents.llm_client import DisabledLlmClient
        from tools.second_review_content_report import build_report_rows
        from tools.validate_review_results import validate_payload

        payload = self.sample_payload()
        validated = validate_payload(payload, llm_client=DisabledLlmClient(), adjudicate=False)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.validated.json"
            path.write_text(json.dumps(validated, ensure_ascii=False), encoding="utf-8")

            rows = build_report_rows([path])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item_no"], "5")
        self.assertEqual(rows[0]["generated_content"], "제안요청서 p.25 명시")

    def test_cli_writes_validated_json(self):
        from tools.validate_review_results import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "review_type1.json"
            out_dir = root / "validated"
            source.write_text(json.dumps(self.sample_payload(), ensure_ascii=False), encoding="utf-8")

            main(
                [
                    "--input-glob",
                    str(source),
                    "--output-dir",
                    str(out_dir),
                    "--no-api",
                ]
            )

            output = out_dir / "review_type1.validated.json"
            self.assertTrue(output.exists())
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("verification_audit", data["merged_final_reviews"][0])


if __name__ == "__main__":
    unittest.main()
