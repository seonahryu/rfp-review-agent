import json
import tempfile
import unittest
from pathlib import Path


class SecondReviewOutputReportTests(unittest.TestCase):
    def test_candidate_jsonl_review_groups_cover_all_item_numbers(self):
        from tools.run_review_from_candidate_jsonl import DEFAULT_GROUPS

        normalized_items = [
            "2" if item == "2-1" else item
            for items in DEFAULT_GROUPS.values()
            for item in items
        ]
        covered = set(normalized_items)

        self.assertEqual(covered, {str(number) for number in range(1, 19)})
        self.assertEqual(len(normalized_items), len(covered))

    def test_build_report_rows_from_second_review_json(self):
        from tools.second_review_content_report import build_report_rows

        payload = {
            "group": "sample",
            "expanded_items": ["8"],
            "item_results": [
                {
                    "item_no": "8",
                    "route": "llm",
                    "rag_hits": [
                        {
                            "item_no": "8",
                            "source_type": "authoritative_criteria_db",
                            "source_name": "criteria",
                            "title": "하자담보 책임기간",
                            "category": "legal_review_criteria",
                            "snippet": "SW 하자담보 책임기간",
                        }
                    ],
                }
            ],
            "merged_final_reviews": [
                {
                    "item_no": "8",
                    "final_status": "자동 확정 가능",
                    "final_result": "미준수",
                    "is_target": True,
                    "confidence": 0.9,
                    "evidence_pages": [3, 57, 103],
                    "evidence_text": [
                        "사업개요 및 계약대상 확인",
                        "SW 하자담보 책임기간을 1년으로 명시",
                        "SW 하자담보 책임기간을 1년 이내로 명시",
                    ],
                    "reason": "하자담보 책임기간 기준에 맞지 않음",
                    "recommendation": "SW 하자담보 책임기간을 ‘1년’ 또는 ‘1년 이내’ 로 명시하시기 바랍니다.",
                    "reviews": [],
                    "warnings": [],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "second_review_sample.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            rows = build_report_rows([path])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item_no"], "8")
        self.assertEqual(rows[0]["selected_content_pages"], "57, 103")
        self.assertEqual(
            rows[0]["generated_content"],
            "제안요청서 p.57, p.103에 SW 하자담보 책임기간을 ‘1년’ 또는 ‘1년 이내’ 로 명시하시기 바랍니다.",
        )

    def test_report_rows_are_sorted_by_item_no(self):
        from tools.second_review_content_report import build_report_rows

        payload = {
            "group": "sample",
            "item_results": [],
            "merged_final_reviews": [
                {
                    "item_no": "18",
                    "final_status": "자동 확정 가능",
                    "final_result": "보완필요",
                    "is_target": True,
                    "confidence": 0.8,
                    "evidence_pages": [104],
                    "evidence_text": ["소프트웨어사업정보 제출 일부 명시"],
                    "reason": "",
                    "recommendation": "제안요청서에 소프트웨어사업정보 제출 절차를 명시하시기 바랍니다.",
                    "reviews": [],
                    "warnings": [],
                },
                {
                    "item_no": "1",
                    "final_status": "자동 확정 가능",
                    "final_result": "준수",
                    "is_target": True,
                    "confidence": 0.9,
                    "evidence_pages": [10],
                    "evidence_text": ["과업심의위원회 명시"],
                    "reason": "",
                    "recommendation": "",
                    "reviews": [],
                    "warnings": [],
                },
                {
                    "item_no": "2-1",
                    "final_status": "자동 확정 가능",
                    "final_result": "준수",
                    "is_target": True,
                    "confidence": 0.9,
                    "evidence_pages": [20],
                    "evidence_text": ["BMT 실시 여부 명시"],
                    "reason": "",
                    "recommendation": "",
                    "reviews": [],
                    "warnings": [],
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "second_review_sample.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            rows = build_report_rows([path])

        self.assertEqual([row["item_no"] for row in rows], ["1", "2-1", "18"])

    def test_non_source_report_json_is_ignored(self):
        from tools.second_review_content_report import build_report_rows

        source_payload = {
            "group": "sample",
            "item_results": [],
            "merged_final_reviews": [
                {
                    "item_no": "1",
                    "final_status": "자동 확정 가능",
                    "final_result": "준수",
                    "is_target": True,
                    "confidence": 0.9,
                    "evidence_pages": [10],
                    "evidence_text": ["과업심의위원회 명시"],
                    "reason": "",
                    "recommendation": "",
                    "reviews": [],
                    "warnings": [],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "rerun_review_type1.json"
            report = Path(tmp) / "rerun_review_content_test_report_latest.json"
            source.write_text(json.dumps(source_payload, ensure_ascii=False), encoding="utf-8")
            report.write_text(json.dumps([{"item_no": "old"}], ensure_ascii=False), encoding="utf-8")

            rows = build_report_rows([report, source])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item_no"], "1")

    def test_report_recommendation_does_not_keep_partial_page_prefix(self):
        from tools.second_review_content_report import build_report_rows

        payload = {
            "group": "sample",
            "item_results": [],
            "merged_final_reviews": [
                {
                    "item_no": "13",
                    "final_status": "자동 확정 가능",
                    "final_result": "보완필요",
                    "is_target": True,
                    "confidence": 0.8,
                    "evidence_pages": [103],
                    "evidence_text": ["적정 사업기간 관련 일부 명시"],
                    "reason": "",
                    "recommendation": (
                        "제안요청서 p.103 일부 명시 -> 소프트웨어사업 계약 및 관리감독에 관한 지침 "
                        "제10조에 의거 별지 제4호서식 소프트웨어 개발사업의 적정 사업기간 종합 산정서를 첨부하시기 바랍니다."
                    ),
                    "reviews": [],
                    "warnings": [],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rerun_review_type3.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            rows = build_report_rows([path])

        self.assertNotIn("일부 명시 ->", rows[0]["recommendation"])
        self.assertTrue(rows[0]["recommendation"].startswith("소프트웨어사업 계약 및 관리감독에 관한 지침"))

    def test_duplicate_item_no_keeps_single_best_row(self):
        from tools.second_review_content_report import build_report_rows

        base_review = {
            "item_no": "13",
            "final_status": "사람 확인 필요",
            "final_result": "보완필요",
            "is_target": None,
            "confidence": 0.4,
            "evidence_pages": [],
            "evidence_text": [],
            "reason": "OPENAI_API_KEY가 설정되어 있지 않아 일반 GPT 검토를 건너뜁니다.",
            "recommendation": "API 키 설정 후 다시 실행하세요.",
            "reviews": [],
            "warnings": [],
        }
        better_review = {
            **base_review,
            "confidence": 0.8,
            "evidence_pages": [74],
            "evidence_text": ["제안요청서 보상 기준 일부 명시"],
            "reason": "제안요청서 보상 기준은 일부 명시되어 있습니다.",
            "recommendation": "제안서 보상 기준을 명시하시기 바랍니다.",
        }

        with tempfile.TemporaryDirectory() as tmp:
            weak = Path(tmp) / "rerun_review_type1.json"
            strong = Path(tmp) / "rerun_review_type3.json"
            weak.write_text(
                json.dumps({"group": "type1", "item_results": [], "merged_final_reviews": [base_review]}, ensure_ascii=False),
                encoding="utf-8",
            )
            strong.write_text(
                json.dumps({"group": "type3", "item_results": [], "merged_final_reviews": [better_review]}, ensure_ascii=False),
                encoding="utf-8",
            )

            rows = build_report_rows([weak, strong])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item_no"], "13")
        self.assertEqual(rows[0]["source_file"], "rerun_review_type3.json")

    def test_duplicate_item_no_prefers_patch_file(self):
        from tools.second_review_content_report import build_report_rows

        old_review = {
            "item_no": "15",
            "final_status": "자동 확정 가능",
            "final_result": "보완필요",
            "is_target": True,
            "confidence": 0.95,
            "evidence_pages": [6, 12, 15, 16, 30, 37, 38, 42, 43, 44, 45],
            "evidence_text": ["old broad evidence"],
            "reason": "old broad review",
            "recommendation": "old recommendation",
            "reviews": [],
            "warnings": [],
        }
        patch_review = {
            **old_review,
            "confidence": 0.6,
            "evidence_pages": [103],
            "evidence_text": ["patched focused evidence"],
            "reason": "patched review",
            "recommendation": "patched recommendation",
        }

        with tempfile.TemporaryDirectory() as tmp:
            old_path = Path(tmp) / "fresh_full_type2.validated.json"
            patch_path = Path(tmp) / "fresh_full_patch_15.validated.json"
            old_path.write_text(
                json.dumps({"group": "type2", "item_results": [], "merged_final_reviews": [old_review]}, ensure_ascii=False),
                encoding="utf-8",
            )
            patch_path.write_text(
                json.dumps({"group": "type2", "item_results": [], "merged_final_reviews": [patch_review]}, ensure_ascii=False),
                encoding="utf-8",
            )

            rows = build_report_rows([old_path, patch_path])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item_no"], "15")
        self.assertEqual(rows[0]["source_file"], "fresh_full_patch_15.validated.json")

    def test_duplicate_item_no_prefers_patch_file_even_without_generated_content(self):
        from tools.second_review_content_report import build_report_rows

        old_review = {
            "item_no": "15",
            "final_status": "자동 확정 가능",
            "final_result": "보완필요",
            "is_target": True,
            "confidence": 0.95,
            "evidence_pages": [6, 12, 15, 16, 30, 37, 38, 42, 43, 44, 45],
            "evidence_text": ["old broad evidence"],
            "reason": "old broad review",
            "recommendation": "old recommendation",
            "reviews": [],
            "warnings": [],
        }
        patch_review = {
            **old_review,
            "final_result": "미준수",
            "confidence": 0.82,
            "evidence_pages": [],
            "evidence_text": [],
            "reason": "소프트웨어 개발사업의 적정 사업기간 종합 산정서 첨부가 확인되지 않았습니다.",
            "recommendation": "소프트웨어 개발사업의 적정 사업기간 종합 산정서를 첨부하시기 바랍니다.",
        }

        with tempfile.TemporaryDirectory() as tmp:
            old_path = Path(tmp) / "fresh_full_type2.validated.json"
            patch_path = Path(tmp) / "fresh_full_patch_15.validated.json"
            old_path.write_text(
                json.dumps({"group": "type2", "item_results": [], "merged_final_reviews": [old_review]}, ensure_ascii=False),
                encoding="utf-8",
            )
            patch_path.write_text(
                json.dumps({"group": "type2", "item_results": [], "merged_final_reviews": [patch_review]}, ensure_ascii=False),
                encoding="utf-8",
            )

            rows = build_report_rows([old_path, patch_path])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item_no"], "15")
        self.assertEqual(rows[0]["source_file"], "fresh_full_patch_15.validated.json")


if __name__ == "__main__":
    unittest.main()
