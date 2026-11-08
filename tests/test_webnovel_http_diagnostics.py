"""Offline tests for safe, single-request HTTP status diagnostics."""
import io
from email.message import Message
import unittest
from unittest.mock import Mock

from urllib.error import HTTPError, URLError
from tools.webnovel_http_diagnostics import diagnose, _safe_headers, AGENT

BOOK = "https://www.webnovel.com/book/33422293300201205"


class FakeResponse:
    status = 200
    headers = {"Content-Type": "text/html"}
    def __init__(self, url): self.url = url
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def geturl(self): return self.url


class DiagnosticsTests(unittest.TestCase):
    def test_one_request_and_no_body_read(self):
        calls = []
        def opener(request, timeout):
            calls.append((request, timeout))
            return FakeResponse(BOOK)
        result = diagnose(BOOK, opener)
        self.assertEqual(result["status"], 200)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0].get_header("User-agent"), AGENT)

    def test_forbidden_is_reported_and_not_retried(self):
        calls = []
        headers = Message()
        headers["Content-Type"] = "text/html"
        headers["Retry-After"] = "120"
        headers["Set-Cookie"] = "secret"
        def opener(request, timeout):
            calls.append(request)
            raise HTTPError(BOOK, 403, "Forbidden", headers, io.BytesIO(b"secret page"))
        report = diagnose(BOOK, opener)
        self.assertEqual(report["status"], 403)
        self.assertEqual(report["headers"]["retry-after"], "120")
        self.assertNotIn("set-cookie", report["headers"])
        self.assertEqual(len(calls), 1)

    def test_refuses_other_domains(self):
        with self.assertRaises(ValueError):
            diagnose("https://webnovel.com.evil.example/book/33422293300201205", Mock())

    def test_network_errors_do_not_leak_details(self):
        def opener(*args, **kwargs):
            raise URLError("Sensitive proxy address token=secret")
        report = diagnose(BOOK, opener)
        self.assertIsNone(report["status"])
        self.assertNotIn("secret", str(report))

    def test_allowlist_only(self):
        report = _safe_headers({"content-type": "text/html", "authorization": "secret",
                                "set-cookie": "secret", "server": "test-server"})
        self.assertIn("content-type", report)
        self.assertNotIn("authorization", report)
        self.assertNotIn("set-cookie", report)


if __name__ == "__main__":
    unittest.main()
