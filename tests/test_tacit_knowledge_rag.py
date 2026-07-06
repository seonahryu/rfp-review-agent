import sqlite3
import tempfile
import unittest
from pathlib import Path


class TacitKnowledgeRagTests(unittest.TestCase):
    def test_context_includes_item_tacit_knowledge_from_separate_table(self):
        from agents.rag_agent import RagAgent

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag.db"
            rag = RagAgent(db_path)
            rag.ensure_schema()

            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO rag_document (
                        source_type, source_name, item_no, title, category, content, metadata_json
                    )
                    VALUES (
                        'criteria_db', 'legal_item+legal_requirement', '1',
                        'Committee criteria', 'legal_review_criteria',
                        'task change wording is required', '{}'
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO rag_fts (
                        title, category, content, item_no, source_type, source_name, doc_id
                    )
                    VALUES (
                        'Committee criteria', 'legal_review_criteria',
                        'task change wording is required', '1',
                        'criteria_db', 'legal_item+legal_requirement', 1
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO legal_tacit_knowledge (item_no, title, content)
                    VALUES (
                        '1', 'Tacit item guidance',
                        'scheduled committee wording alone is not noncompliant'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            context = rag.context_for_item("1", query="committee")

        self.assertEqual([hit.source_type for hit in context.hits], ["criteria_db", "tacit_knowledge"])
        self.assertIn("scheduled committee", context.hits[1].snippet)

    def test_context_includes_common_tacit_knowledge_for_every_item(self):
        from agents.rag_agent import RagAgent

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag.db"
            rag = RagAgent(db_path)
            rag.ensure_schema()

            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO legal_tacit_knowledge (item_no, title, content)
                    VALUES (
                        '공통', 'Common output guidance',
                        'compliant output should be one short RFP page reference'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            context = rag.context_for_item("8", query="defect")

        self.assertEqual([hit.source_type for hit in context.hits], ["tacit_knowledge"])
        self.assertIn("one short RFP page reference", context.hits[0].snippet)

    def test_context_falls_back_to_item_documents_for_numeric_item(self):
        from agents.rag_agent import RagAgent

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag.db"
            rag = RagAgent(db_path)
            rag.ensure_schema()

            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO rag_document (
                        source_type, source_name, item_no, title, category, content, metadata_json
                    )
                    VALUES (
                        'requirement_db', 'legal_requirement', '1',
                        '과업심의위원회', '명시',
                        '요구사항: 과업내용 확정 심의 여부 명시', '{}'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            context = rag.context_for_item("1")

        self.assertEqual(len(context.hits), 1)
        self.assertEqual(context.hits[0].item_no, "1")
        self.assertEqual(context.hits[0].source_type, "requirement_db")

    def test_tacit_knowledge_schema_has_no_id_or_priority_columns(self):
        from agents.rag_agent import RagAgent

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag.db"
            RagAgent(db_path).ensure_schema()

            conn = sqlite3.connect(db_path)
            try:
                columns = [row[1] for row in conn.execute("PRAGMA table_info(legal_tacit_knowledge)")]
            finally:
                conn.close()

        self.assertEqual(columns, ["item_no", "title", "content", "created_at"])

    def test_clean_db_rebuild_preserves_tacit_knowledge_table(self):
        from tools.build_clean_legal_db import build_clean_legal_db

        with tempfile.TemporaryDirectory() as tmp:
            source_db = Path(tmp) / "source.db"
            target_db = Path(tmp) / "target.db"
            conn = sqlite3.connect(source_db)
            try:
                conn.executescript(
                    """
                    CREATE TABLE legal_item (
                        item_no TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        target_text TEXT
                    );
                    CREATE TABLE legal_requirement (
                        item_no TEXT NOT NULL,
                        category TEXT,
                        requirement_text TEXT NOT NULL,
                        example_sentence TEXT,
                        "case" TEXT
                    );
                    CREATE TABLE legal_reference_example (
                        item_no TEXT NOT NULL,
                        reference_type TEXT,
                        reference_subtype TEXT,
                        content TEXT NOT NULL
                    );
                    CREATE TABLE legal_tacit_knowledge (
                        item_no TEXT NOT NULL,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                conn.execute("INSERT INTO legal_item VALUES ('1', 'Committee', 'SW project')")
                conn.execute(
                    """
                    INSERT INTO legal_tacit_knowledge (item_no, title, content)
                    VALUES ('1', 'Tacit item guidance', 'scheduled wording alone is not noncompliant')
                    """
                )
                conn.commit()
            finally:
                conn.close()

            build_clean_legal_db(source_db, target_db)

            conn = sqlite3.connect(target_db)
            try:
                count = conn.execute("SELECT count(*) FROM legal_tacit_knowledge").fetchone()[0]
                columns = [row[1] for row in conn.execute("PRAGMA table_info(legal_tacit_knowledge)")]
            finally:
                conn.close()

        self.assertEqual(count, 1)
        self.assertEqual(columns, ["item_no", "title", "content", "created_at"])


if __name__ == "__main__":
    unittest.main()
