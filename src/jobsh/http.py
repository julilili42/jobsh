import time
from atexit import register
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

USER_AGENT = "jobsh/0.1 (+https://github.com/julilili42/jobsh)"
CLIENT = httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True)
register(CLIENT.close)
_retry_at: dict[str, float] = {}


class HTTPStatusError(OSError):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


def fetch(url: str, timeout: float, limit: int = 10_000_000) -> bytes:
    if timeout <= 0 or limit < 1:
        raise ValueError("timeout and response limit must be > 0")
    origin = urlsplit(url).netloc.lower()
    if _retry_at.get(origin, 0) > time.time():
        raise OSError(f"Retry-After cooldown active for {origin}")
    try:
        with CLIENT.stream("GET", url, timeout=timeout) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes(min(64 * 1024, limit + 1)):
                data.extend(chunk)
                if len(data) > limit:
                    raise ValueError(f"response exceeds {limit} bytes")
        return bytes(data)
    except httpx.HTTPStatusError as error:
        if error.response.status_code in (429, 503):
            retry_after = error.response.headers.get("Retry-After", "60")
            now = time.time()
            try:
                delay = int(retry_after)
                if delay < 0:
                    raise ValueError("negative Retry-After")
                until = now + delay
            except OverflowError:
                until = float("inf")
            except ValueError:
                try:
                    until = parsedate_to_datetime(retry_after).timestamp()
                except (ValueError, TypeError, OverflowError):
                    until = now + 60
            _retry_at[origin] = max(_retry_at.get(origin, 0), now, until)
        raise HTTPStatusError(error.response.status_code, str(error)) from error
    except httpx.HTTPError as error:
        raise OSError(str(error)) from error
