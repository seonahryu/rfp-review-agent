import unittest


class ParserRepairDecisionTests(unittest.TestCase):
    def test_gpt_parser_extracts_pages_from_current_schema(self):
        from agents.gpt_parser_agent import extract_page_items

        items = extract_page_items({"pages": [{"pdf_page_no": 10, "page_text": "본문"}]})

        self.assertEqual(items, [{"pdf_page_no": 10, "page_text": "본문"}])

    def test_gpt_parser_extracts_pages_from_legacy_nested_schema(self):
        from agents.gpt_parser_agent import extract_page_items

        items = extract_page_items({"result": {"pages": [{"pdf_page_no": 11, "page_text": "별첨"}]}})

        self.assertEqual(items, [{"pdf_page_no": 11, "page_text": "별첨"}])


if __name__ == "__main__":
    unittest.main()
