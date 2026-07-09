import sqlite3
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter

from agents.audit_agent import ParseAuditAgent
from agents.gpt_parser_agent import insert_page
from agents.models import CandidatePage
from agents.parse_job_orchestrator import ParseJobRunner, ensure_parse_job_schema


class FakeParser:
    def __init__(self, fail_on: set[int] | None = None):
        self.calls: list[tuple[int, ...]] = []
        self.fail_on = fail_on or set()

    def extract_chunk_with_fallback(self, reader, page_numbers: list[int]) -> list[CandidatePage]:
        self.calls.append(tuple(page_numbers))
        if any(page_no in self.fail_on for page_no in page_numbers):
            raise RuntimeError(f"forced page failure: {page_numbers}")
        return [
            CandidatePage(
                page_no=page_no,
                page_text=f"parsed page {page_no}",
                text_length=len(f"parsed page {page_no}"),
            )
            for page_no in page_numbers
        ]


def write_blank_pdf(path: Path, page_count: int) -> None:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)


class FakeReader:
    def __init__(self, texts: list[str]):
        self.pages = [FakePage(text) for text in texts]


class FakePage:
    def __init__(self, text: str):
        self.text = text

    def extract_text(self) -> str:
        return self.text


class ParseJobOrchestratorTests(unittest.TestCase):
    def test_run_job_checkpoints_each_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "rfp.pdf"
            db_path = tmp_path / "parse.db"
            write_blank_pdf(pdf_path, 3)

            fake_parser = FakeParser()
            runner = ParseJobRunner(
                db_path,
                parser=fake_parser,
                auditor=ParseAuditAgent(use_gpt=False),
                pages_per_chunk=2,
            )
            created = runner.create_job(pdf_path)

            finished = runner.run_job(created.job_id)

            self.assertEqual(finished.status, "succeeded")
            self.assertEqual(finished.processed_pages, 3)
            self.assertEqual(fake_parser.calls, [(1, 2), (3,)])

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                page_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM rfp_page WHERE document_id = ?",
                    (created.document_id,),
                ).fetchone()["count"]
                succeeded_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM parse_job_page WHERE job_id = ? AND status = 'succeeded'",
                    (created.job_id,),
                ).fetchone()["count"]
            finally:
                conn.close()

            self.assertEqual(page_count, 3)
            self.assertEqual(succeeded_count, 3)

    def test_run_job_can_parse_selected_pages_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "rfp.pdf"
            db_path = tmp_path / "parse.db"
            write_blank_pdf(pdf_path, 5)

            fake_parser = FakeParser()
            runner = ParseJobRunner(
                db_path,
                parser=fake_parser,
                auditor=ParseAuditAgent(use_gpt=False),
                pages_per_chunk=2,
            )
            created = runner.create_job(pdf_path, page_numbers=[2, 4, 5])

            finished = runner.run_job(created.job_id)

            self.assertEqual(finished.status, "succeeded")
            self.assertEqual(finished.total_pages, 5)
            self.assertEqual(finished.selected_pages, [2, 4, 5])
            self.assertEqual(finished.processed_pages, 3)
            self.assertEqual(finished.progress_percent, 100)
            self.assertEqual(fake_parser.calls, [(2, 4), (5,)])

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                page_numbers = [
                    row["page_no"]
                    for row in conn.execute(
                        "SELECT page_no FROM rfp_page WHERE document_id = ? ORDER BY page_no",
                        (created.document_id,),
                    )
                ]
            finally:
                conn.close()

            self.assertEqual(page_numbers, [2, 4, 5])

    def test_hybrid_mode_uses_python_for_simple_pages_and_gpt_for_hard_pages(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "rfp.pdf"
            db_path = tmp_path / "parse.db"
            write_blank_pdf(pdf_path, 3)

            fake_parser = FakeParser()
            fake_reader = FakeReader(
                [
                    "일반 사업 개요입니다. " * 20,
                    "요구사항 분류 기능요구사항 고유번호 SFR-001 요구사항 상세설명입니다.",
                    "일반 추진 일정입니다. " * 20,
                ]
            )
            runner = ParseJobRunner(
                db_path,
                parser=fake_parser,
                auditor=ParseAuditAgent(use_gpt=False),
                pages_per_chunk=1,
                hybrid=True,
            )
            created = runner.create_job(pdf_path)

            with patch("agents.parse_job_orchestrator.PdfReader", return_value=fake_reader):
                finished = runner.run_job(created.job_id)

            self.assertEqual(finished.status, "succeeded")
            self.assertEqual(finished.python_pages, 2)
            self.assertEqual(finished.gpt_pages, 1)
            self.assertEqual(fake_parser.calls, [(2,)])

    def test_hybrid_sends_dense_layout_tables_to_gpt(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "rfp.pdf"
            db_path = tmp_path / "parse.db"
            write_blank_pdf(pdf_path, 2)

            fake_parser = FakeParser()
            fake_reader = FakeReader(
                [
                    "담당 소속 직위 성명 전화번호 e-mail 기관 부장 홍길동 02-0000-0000 a@test.kr",
                    "일반 사업 개요입니다. " * 20,
                ]
            )
            runner = ParseJobRunner(
                db_path,
                parser=fake_parser,
                auditor=ParseAuditAgent(use_gpt=False),
                pages_per_chunk=1,
                hybrid=True,
            )
            created = runner.create_job(pdf_path)

            with patch("agents.parse_job_orchestrator.PdfReader", return_value=fake_reader):
                finished = runner.run_job(created.job_id)

            self.assertEqual(finished.status, "succeeded")
            self.assertEqual(finished.python_pages, 1)
            self.assertEqual(finished.gpt_pages, 1)
            self.assertEqual(fake_parser.calls, [(1,)])

    def test_hybrid_sends_review_relevant_text_to_gpt_even_without_table(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "rfp.pdf"
            db_path = tmp_path / "parse.db"
            write_blank_pdf(pdf_path, 2)

            fake_parser = FakeParser()
            fake_reader = FakeReader(
                [
                    "산출물 반출 절차 및 지식재산 공동소유 관련 문장입니다. " * 10,
                    "일반 기관 소개 문장입니다. " * 20,
                ]
            )
            runner = ParseJobRunner(
                db_path,
                parser=fake_parser,
                auditor=ParseAuditAgent(use_gpt=False),
                pages_per_chunk=1,
                hybrid=True,
            )
            created = runner.create_job(pdf_path)

            with patch("agents.parse_job_orchestrator.PdfReader", return_value=fake_reader):
                finished = runner.run_job(created.job_id)

            self.assertEqual(finished.status, "succeeded")
            self.assertEqual(finished.python_pages, 1)
            self.assertEqual(finished.gpt_pages, 1)
            self.assertEqual(fake_parser.calls, [(1,)])

    def test_resume_skips_completed_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "rfp.pdf"
            db_path = tmp_path / "parse.db"
            write_blank_pdf(pdf_path, 3)

            fake_parser = FakeParser()
            runner = ParseJobRunner(
                db_path,
                parser=fake_parser,
                auditor=ParseAuditAgent(use_gpt=False),
                pages_per_chunk=1,
            )
            created = runner.create_job(pdf_path)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                ensure_parse_job_schema(conn)
                insert_page(
                    conn,
                    created.document_id,
                    CandidatePage(page_no=1, page_text="already parsed", text_length=14),
                )
                conn.execute(
                    """
                    INSERT INTO parse_job_page (job_id, page_no, status, error, completed_at)
                    VALUES (?, 1, 'succeeded', '', CURRENT_TIMESTAMP)
                    """,
                    (created.job_id,),
                )
                conn.commit()
            finally:
                conn.close()

            finished = runner.run_job(created.job_id)

            self.assertEqual(finished.status, "succeeded")
            self.assertEqual(fake_parser.calls, [(2,), (3,)])

    def test_failed_chunk_records_failed_page_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "rfp.pdf"
            db_path = tmp_path / "parse.db"
            write_blank_pdf(pdf_path, 2)

            runner = ParseJobRunner(
                db_path,
                parser=FakeParser(fail_on={2}),
                auditor=ParseAuditAgent(use_gpt=False),
                pages_per_chunk=1,
            )
            created = runner.create_job(pdf_path)

            finished = runner.run_job(created.job_id)

            self.assertEqual(finished.status, "failed")
            self.assertEqual(finished.processed_pages, 1)
            self.assertEqual(finished.failed_pages, 1)


if __name__ == "__main__":
    unittest.main()
