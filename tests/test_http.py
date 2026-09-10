import unittest
from unittest.mock import patch

import httpx

from jobsh.http import _retry_at, fetch


class HttpTest(unittest.TestCase):
    @patch("jobsh.http.time.time", return_value=100)
    @patch("jobsh.http.CLIENT.stream")
    def test_rate_limits_are_host_specific_and_handle_header_edge_cases(self, stream, clock):
        for status, header in ((503, None), (429, "-1"), (429, "9" * 400)):
            with self.subTest(status=status, header=header), patch.dict(_retry_at, {}, clear=True):
                clock.return_value = 100.0
                response = httpx.Response(
                    status, headers={} if header is None else {"Retry-After": header},
                    request=httpx.Request("GET", "https://limited.example/feed"),
                )
                stream.return_value.__enter__.return_value = response
                with self.assertRaises(OSError):
                    fetch("https://limited.example/feed", 3)
                stream.return_value.__enter__.return_value = httpx.Response(
                    200, content=b"ok", request=httpx.Request("GET", "https://other.example/feed"),
                )
                self.assertEqual(fetch("https://other.example/feed", 3), b"ok")
                clock.return_value = 159
                calls = stream.call_count
                with self.assertRaisesRegex(OSError, "cooldown"):
                    fetch("https://limited.example/feed", 3)
                self.assertEqual(stream.call_count, calls)

    @patch("jobsh.http.time.time", return_value=100)
    @patch("jobsh.http.CLIENT.stream")
    def test_retry_after_blocks_requests_until_deadline(self, stream, clock):
        for header in ("60", "Thu, 01 Jan 1970 00:02:40 GMT", "invalid"):
            with self.subTest(header=header), patch.dict(_retry_at, {}, clear=True):
                clock.return_value = 100
                response = httpx.Response(
                    429, headers={"Retry-After": header},
                    request=httpx.Request("GET", "https://example.com/feed"),
                )
                stream.return_value.__enter__.return_value = response
                with self.assertRaises(OSError):
                    fetch("https://example.com/feed", 3)
                calls = stream.call_count
                clock.return_value = 159
                with self.assertRaisesRegex(OSError, "cooldown"):
                    fetch("https://example.com/another-feed", 3)
                self.assertEqual(stream.call_count, calls)
                clock.return_value = 160
                stream.return_value.__enter__.return_value = httpx.Response(
                    200, content=b"ok", request=response.request,
                )
                self.assertEqual(fetch("https://example.com/feed", 3), b"ok")

    @patch("jobsh.http.CLIENT.stream")
    def test_fetch_sets_request_options_and_bounds_the_read(self, stream) -> None:
        response = stream.return_value.__enter__.return_value
        response.iter_bytes.return_value = [b"o", b"k"]

        self.assertEqual(fetch("https://example.com", timeout=3, limit=2), b"ok")

        stream.assert_called_once_with("GET", "https://example.com", timeout=3)
        response.raise_for_status.assert_called_once_with()
        response.iter_bytes.assert_called_once_with(3)

    @patch("jobsh.http.CLIENT.stream")
    def test_fetch_rejects_oversized_response(self, stream) -> None:
        stream.return_value.__enter__.return_value.iter_bytes.return_value = [b"too"]

        with self.assertRaisesRegex(ValueError, "response exceeds 2 bytes"):
            fetch("https://example.com", timeout=3, limit=2)

    @patch("jobsh.http.CLIENT.stream", side_effect=httpx.ConnectError("offline"))
    def test_fetch_exposes_http_errors_as_os_errors(self, _stream) -> None:
        with self.assertRaisesRegex(OSError, "offline"):
            fetch("https://example.com", timeout=3)
