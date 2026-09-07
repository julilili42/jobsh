import unittest
from unittest.mock import patch

import httpx

from jobsh.http import USER_AGENT, fetch


class HttpTest(unittest.TestCase):
    @patch("jobsh.http.httpx.stream")
    def test_fetch_sets_request_options_and_bounds_the_read(self, stream) -> None:
        response = stream.return_value.__enter__.return_value
        response.iter_bytes.return_value = [b"o", b"k"]

        self.assertEqual(fetch("https://example.com", timeout=3, limit=2), b"ok")

        stream.assert_called_once_with(
            "GET",
            "https://example.com",
            headers={"User-Agent": USER_AGENT},
            timeout=3,
            follow_redirects=True,
        )
        response.raise_for_status.assert_called_once_with()
        response.iter_bytes.assert_called_once_with(3)

    @patch("jobsh.http.httpx.stream")
    def test_fetch_rejects_oversized_response(self, stream) -> None:
        stream.return_value.__enter__.return_value.iter_bytes.return_value = [b"too"]

        with self.assertRaisesRegex(ValueError, "response exceeds 2 bytes"):
            fetch("https://example.com", timeout=3, limit=2)

    @patch("jobsh.http.httpx.stream", side_effect=httpx.ConnectError("offline"))
    def test_fetch_exposes_http_errors_as_os_errors(self, _stream) -> None:
        with self.assertRaisesRegex(OSError, "offline"):
            fetch("https://example.com", timeout=3)
