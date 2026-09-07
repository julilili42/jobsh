import httpx

USER_AGENT = "jobsh/0.1 (+https://github.com/julilili42/jobsh)"


def fetch(url: str, timeout: float, limit: int = 10_000_000) -> bytes:
    try:
        with httpx.stream(
            "GET",
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
        ) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes(min(64 * 1024, limit + 1)):
                data.extend(chunk)
                if len(data) > limit:
                    raise ValueError(f"response exceeds {limit} bytes")
        return bytes(data)
    except httpx.HTTPError as error:
        raise OSError(str(error)) from error
