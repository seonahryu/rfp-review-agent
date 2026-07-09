import unittest

from api.main import JSONResponse


class JsonResponseEncodingTests(unittest.TestCase):
    def test_json_response_declares_utf8_charset(self):
        response = JSONResponse({"result": "준수"})

        self.assertEqual(response.headers["content-type"], "application/json; charset=utf-8")
        self.assertIn("준수".encode("utf-8"), response.body)


if __name__ == "__main__":
    unittest.main()
