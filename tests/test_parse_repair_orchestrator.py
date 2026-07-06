import unittest


class ParseRepairOrchestratorTests(unittest.TestCase):
    def test_collects_bad_pages_from_text_usability_warnings(self):
        from agents.models import AuditWarning, CandidatePage, ParsedDocument
        from agents.parse_repair_orchestrator import collect_bad_pages

        document = ParsedDocument(
            document_id=1,
            document_name="sample.pdf",
            pdf_path=None,
            total_pages=3,
            parse_status="warning",
            pages=[
                CandidatePage(page_no=1, page_text="ok", text_length=100),
                CandidatePage(page_no=2, page_text="", text_length=0),
                CandidatePage(page_no=3, page_text="warn", text_length=100, parser_warning="layout issue"),
                CandidatePage(page_no=4, page_text="short", text_length=5),
            ],
            audit_warnings=[
                AuditWarning("layout_error", "bad layout", page_no=3, severity="medium"),
                AuditWarning("low_text_density", "short title", page_no=4, severity="low"),
                AuditWarning("required_section_missing", "not page specific", severity="medium"),
            ],
        )

        self.assertEqual(collect_bad_pages(document), [2])

    def test_collects_parser_failure_pages_for_repair(self):
        from agents.models import AuditWarning, CandidatePage, ParsedDocument
        from agents.parse_repair_orchestrator import collect_bad_pages

        document = ParsedDocument(
            document_id=1,
            document_name="sample.pdf",
            pdf_path=None,
            total_pages=3,
            parse_status="warning",
            pages=[
                CandidatePage(page_no=1, page_text="ok", text_length=100),
                CandidatePage(page_no=2, page_text="", text_length=0, parser_warning="이미지 기반 페이지로 텍스트 추출 불가"),
                CandidatePage(page_no=3, page_text="table", text_length=100),
            ],
            audit_warnings=[
                AuditWarning("empty_page", "empty", page_no=2, severity="high"),
                AuditWarning("parser_warning", "OCR 실패", page_no=2, severity="medium"),
                AuditWarning("table_page_empty", "table expected but empty", page_no=3, severity="high"),
            ],
        )

        self.assertEqual(collect_bad_pages(document), [2, 3])

    def test_replaces_repaired_pages_and_reaudits(self):
        from agents.models import CandidatePage, ParsedDocument
        from agents.parse_repair_orchestrator import replace_pages

        document = ParsedDocument(
            document_id=1,
            document_name="sample.pdf",
            pdf_path=None,
            total_pages=2,
            parse_status="warning",
            pages=[
                CandidatePage(page_no=1, page_text="old one", text_length=7),
                CandidatePage(page_no=2, page_text="", text_length=0),
            ],
        )
        repaired = [
            CandidatePage(page_no=2, page_text="repaired text", text_length=13),
        ]

        merged = replace_pages(document, repaired)

        self.assertEqual([page.page_text for page in merged.pages], ["old one", "repaired text"])

    def test_deduplicates_duplicate_page_numbers_by_keeping_best_parse(self):
        from agents.models import CandidatePage
        from agents.page_selection import dedupe_pages

        pages = [
            CandidatePage(page_no=56, page_text="", text_length=0, parser_warning="empty"),
            CandidatePage(
                page_no=56,
                page_text="요구사항 분류 프로젝트지원 요구사항 고유번호 PSR-001",
                text_length=35,
                has_table_candidate=True,
            ),
            CandidatePage(page_no=57, page_text="short", text_length=5),
        ]

        deduped = dedupe_pages(pages)

        self.assertEqual([page.page_no for page in deduped], [56, 57])
        self.assertEqual(deduped[0].text_length, 35)
        self.assertTrue(deduped[0].has_table_candidate)
        self.assertIsNone(deduped[0].parser_warning)

    def test_gpt_parser_maps_bad_page_numbers_to_requested_chunk_order(self):
        from agents.gpt_parser_agent import normalized_chunk_page_no

        requested_pages = [4, 5, 6]
        seen: set[int] = set()

        self.assertEqual(normalized_chunk_page_no(3, 0, requested_pages, seen), 4)
        self.assertEqual(normalized_chunk_page_no(3, 1, requested_pages, seen), 5)
        self.assertEqual(normalized_chunk_page_no(6, 2, requested_pages, seen), 6)

    def test_audit_score_counts_page_once_by_highest_severity(self):
        from agents.audit_agent import audit_quality_summary
        from agents.models import AuditWarning

        warnings = [
            AuditWarning("parser_warning", "bad", page_no=26, severity="medium"),
            AuditWarning("empty_page", "empty", page_no=26, severity="high"),
            AuditWarning("layout_error", "layout", page_no=17, severity="low"),
            AuditWarning("parser_warning", "layout", page_no=17, severity="medium"),
        ]

        summary = audit_quality_summary(total_pages=139, warnings=warnings)

        self.assertEqual(summary["audit_warning_count"], 4)
        self.assertEqual(summary["affected_page_count"], 2)
        self.assertEqual(summary["critical_page_count"], 1)
        self.assertEqual(summary["audit_score"], 86)

    def test_parse_schema_round_trips_rfp_printed_page_no(self):
        import sqlite3
        import tempfile
        from pathlib import Path

        from agents.models import CandidatePage
        from agents.gpt_parser_agent import ensure_parse_schema, insert_page, row_to_candidate

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "parse.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                ensure_parse_schema(conn)
                conn.execute(
                    """
                    INSERT INTO rfp_document (document_name, file_path, total_pages, parse_status)
                    VALUES ('sample.pdf', 'sample.pdf', 1, 'ok')
                    """
                )
                insert_page(
                    conn,
                    1,
                    CandidatePage(
                        page_no=4,
                        page_text="본문",
                        text_length=2,
                        rfp_printed_page_no=2,
                    ),
                )
                row = conn.execute("SELECT * FROM rfp_page WHERE document_id=1").fetchone()
            finally:
                conn.close()

        self.assertEqual(row_to_candidate(row).rfp_printed_page_no, 2)

    def test_jsonl_loader_parses_numeric_rfp_printed_page_no(self):
        import json
        import tempfile
        from pathlib import Path

        from tools.run_review_from_candidate_jsonl import load_candidate_pages

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pages.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "page_no": 60,
                        "rfp_printed_page_no": 57,
                        "page_text": "협상에 의한 계약체결 방법",
                        "text_length": 13,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            pages = load_candidate_pages(path)

        self.assertEqual(pages[0].rfp_printed_page_no, 57)

    def test_jsonl_loader_keeps_only_digits_from_rfp_printed_page_no(self):
        import json
        import tempfile
        from pathlib import Path

        from tools.run_review_from_candidate_jsonl import load_candidate_pages

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pages.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "page_no": 60,
                        "rfp_printed_page_no": "제안요청서 p.57",
                        "page_text": "협상에 의한 계약체결 방법",
                        "text_length": 13,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            pages = load_candidate_pages(path)

        self.assertEqual(pages[0].rfp_printed_page_no, 57)

    def test_gpt_parser_and_jsonl_use_same_rfp_printed_page_number_normalization(self):
        from agents.gpt_parser_agent import parse_optional_int
        from tools.run_review_from_candidate_jsonl import parse_jsonl_page_no

        values = [57, "57", "p.57", "제안요청서 p.57", "- 57 -", "57쪽"]

        self.assertEqual([parse_optional_int(value) for value in values], [57] * len(values))
        self.assertEqual([parse_jsonl_page_no(value) for value in values], [57] * len(values))

    def test_gpt_parser_fills_only_null_rfp_printed_page_numbers(self):
        from agents.gpt_parser_agent import fill_missing_rfp_printed_page_numbers
        from agents.models import CandidatePage

        pages = [
            CandidatePage(page_no=60, page_text="명시 페이지", text_length=5, rfp_printed_page_no=57),
            CandidatePage(page_no=61, page_text="누락 페이지", text_length=5, rfp_printed_page_no=None),
            CandidatePage(page_no=62, page_text="다른 명시 페이지", text_length=7, rfp_printed_page_no=99),
        ]

        filled = fill_missing_rfp_printed_page_numbers(pages)

        self.assertEqual([page.rfp_printed_page_no for page in filled], [57, 58, 99])

    def test_jsonl_loader_fills_only_null_rfp_printed_page_numbers(self):
        import json
        import tempfile
        from pathlib import Path

        from tools.run_review_from_candidate_jsonl import load_candidate_pages

        rows = [
            {"page_no": 60, "rfp_printed_page_no": 57, "page_text": "명시 페이지", "text_length": 5},
            {"page_no": 61, "rfp_printed_page_no": None, "page_text": "누락 페이지", "text_length": 5},
            {"page_no": 62, "rfp_printed_page_no": 99, "page_text": "다른 명시 페이지", "text_length": 7},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pages.jsonl"
            path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )

            pages = load_candidate_pages(path)

        self.assertEqual([page.rfp_printed_page_no for page in pages], [57, 58, 99])

    def test_repair_sync_updates_original_document_pages(self):
        import sqlite3
        import tempfile
        from pathlib import Path

        from agents.models import CandidatePage
        from agents.parse_repair_orchestrator import sync_pages_to_document
        from agents.gpt_parser_agent import ensure_parse_schema, insert_page

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "parse.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                ensure_parse_schema(conn)
                conn.execute(
                    """
                    INSERT INTO rfp_document (document_name, file_path, total_pages, parse_status)
                    VALUES ('sample.pdf', 'sample.pdf', 1, 'warning')
                    """
                )
                insert_page(conn, 1, CandidatePage(page_no=2, page_text="", text_length=0, parser_warning="empty"))
                conn.commit()
            finally:
                conn.close()

            sync_pages_to_document(
                db_path,
                1,
                [CandidatePage(page_no=2, page_text="repaired", text_length=8, rfp_printed_page_no=1)],
            )

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute("SELECT * FROM rfp_page WHERE document_id=1 AND page_no=2").fetchall()
            finally:
                conn.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["page_text"], "repaired")
        self.assertEqual(rows[0]["rfp_printed_page_no"], 1)


if __name__ == "__main__":
    unittest.main()
