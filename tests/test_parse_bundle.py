import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from agents.parse_bundle import import_pages_to_db, import_parse_bundle_to_db


class ParseBundleImportTests(unittest.TestCase):
    def test_import_parse_bundle_writes_document_and_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bundle_path = tmp_path / "parse_bundle.zip"
            db_path = tmp_path / "parse.db"
            with zipfile.ZipFile(bundle_path, "w") as archive:
                archive.writestr(
                    "parse_meta.json",
                    '{"document_name":"sample.pdf","total_pages":2,"parser_version":"test"}',
                )
                archive.writestr(
                    "parsed_pages.jsonl",
                    '{"page_no":1,"page_text":"first page","text_length":9}\n'
                    '{"page_no":2,"page_text":"second page","has_table_candidate":true}\n',
                )

            document = import_parse_bundle_to_db(bundle_path, db_path)

            self.assertEqual(document.document_name, "sample.pdf")
            self.assertEqual(document.total_pages, 2)
            self.assertEqual(document.parse_status, "ok")
            self.assertEqual([page.page_no for page in document.pages], [1, 2])
            self.assertTrue(document.pages[1].has_table_candidate)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                doc_count = conn.execute("SELECT COUNT(*) AS count FROM rfp_document").fetchone()["count"]
                page_count = conn.execute("SELECT COUNT(*) AS count FROM rfp_page").fetchone()["count"]
            finally:
                conn.close()

            self.assertEqual(doc_count, 1)
            self.assertEqual(page_count, 2)

    def test_import_pages_writes_document_and_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "parse.db"

            document = import_pages_to_db(
                db_path,
                document_name="browser.pdf",
                total_pages=2,
                pages_data=[
                    {"page_no": 2, "page_text": "second page"},
                    {"page_no": 1, "page_text": "first page"},
                ],
            )

            self.assertEqual(document.document_name, "browser.pdf")
            self.assertEqual(document.total_pages, 2)
            self.assertEqual([page.page_no for page in document.pages], [1, 2])


if __name__ == "__main__":
    unittest.main()
