from __future__ import annotations

from agents.models import CandidatePage


def dedupe_pages(pages: list[CandidatePage]) -> list[CandidatePage]:
    best_by_page: dict[int, CandidatePage] = {}
    for page in pages:
        current = best_by_page.get(page.page_no)
        if current is None or page_quality(page) > page_quality(current):
            best_by_page[page.page_no] = page
    return [best_by_page[page_no] for page_no in sorted(best_by_page)]


def page_quality(page: CandidatePage) -> tuple[int, int, int, int]:
    return (
        0 if page.parser_warning else 1,
        int(page.has_table_candidate),
        int(page.has_attachment_candidate or page.has_eval_table_candidate),
        page.text_length,
    )
