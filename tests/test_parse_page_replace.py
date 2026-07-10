import sqlite3

from agents.parse_bundle import import_pages_to_db, replace_document_pages_in_db


def test_replace_document_pages_overwrites_failed_placeholders(tmp_path):
    db_path = tmp_path / "parse_replace.db"
    document = import_pages_to_db(
        db_path,
        document_name="rfp.pdf",
        total_pages=3,
        pages_data=[
            {"page_no": 1, "page_text": "page one"},
            {
                "page_no": 2,
                "page_text": "[parse_chunk_failed] PDF page 2 could not be parsed automatically.",
                "parser_warning": "parse_chunk_failed: timeout",
            },
            {"page_no": 3, "page_text": "page three"},
        ],
    )

    updated = replace_document_pages_in_db(
        db_path,
        document_id=document.document_id,
        pages_data=[{"page_no": 2, "page_text": "retried page two"}],
    )

    assert updated.document_id == document.document_id
    assert updated.parse_status == "ok"
    assert [page.page_no for page in updated.pages] == [1, 2, 3]
    assert updated.pages[1].page_text == "retried page two"
    assert updated.pages[1].parser_warning is None

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT page_no, page_text, parser_warning FROM rfp_page WHERE document_id = ? AND page_no = 2",
            (document.document_id,),
        ).fetchall()

    assert rows == [(2, "retried page two", None)]


def test_replace_document_pages_keeps_unselected_failed_placeholders(tmp_path):
    db_path = tmp_path / "parse_replace_selected.db"
    document = import_pages_to_db(
        db_path,
        document_name="rfp.pdf",
        total_pages=4,
        pages_data=[
            {"page_no": 1, "page_text": "page one"},
            {
                "page_no": 2,
                "page_text": "[parse_chunk_failed] PDF page 2 could not be parsed automatically.",
                "parser_warning": "parse_chunk_failed: timeout",
            },
            {
                "page_no": 3,
                "page_text": "[parse_chunk_failed] PDF page 3 could not be parsed automatically.",
                "parser_warning": "parse_chunk_failed: timeout",
            },
            {"page_no": 4, "page_text": "page four"},
        ],
    )

    updated = replace_document_pages_in_db(
        db_path,
        document_id=document.document_id,
        pages_data=[{"page_no": 2, "page_text": "selected page two"}],
    )

    by_page = {page.page_no: page for page in updated.pages}
    assert by_page[2].page_text == "selected page two"
    assert by_page[2].parser_warning is None
    assert by_page[3].parser_warning == "parse_chunk_failed: timeout"
    assert updated.parse_status == "warning"
