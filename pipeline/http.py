"""Tiny zero-dependency HTTP helper built on urllib.

Kept dependency-free on purpose: the daily pipeline must run under a bare Python
on whatever machine the scheduled task lives on, without a pip install step.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

# A browser-ish UA. Some ATS CDNs 403 the default python-urllib UA. No custom
# suffix — a self-identifying token would fingerprint every request as this
# scanner in the ATS providers' logs.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 30


class HttpError(Exception):
    """Raised when a request fails after all retries."""


def _request(url, *, method="GET", body=None, headers=None, timeout=DEFAULT_TIMEOUT,
             retries=3, backoff=2.0):
    """Perform an HTTP request, returning the decoded response body as text.

    Retries on network errors and 5xx / 429 with exponential backoff.
    """
    hdrs = {"User-Agent": _UA, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    data = None
    if body is not None:
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")

    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as e:
            last_err = e
            # Retry transient statuses only; fail fast on 4xx (except 429).
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
                continue
            raise HttpError(f"HTTP {e.code} for {url}: {e.reason}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
                continue
            raise HttpError(f"network error for {url}: {e}") from e
    raise HttpError(f"request failed for {url}: {last_err}")


def get_json(url, *, timeout=DEFAULT_TIMEOUT, retries=3, headers=None):
    """GET a URL and parse the response as JSON."""
    text = _request(url, method="GET", timeout=timeout, retries=retries, headers=headers)
    return json.loads(text)


def post_json(url, body, *, timeout=DEFAULT_TIMEOUT, retries=3, headers=None):
    """POST a JSON body to a URL and parse the response as JSON."""
    text = _request(url, method="POST", body=body, timeout=timeout, retries=retries,
                    headers=headers)
    return json.loads(text)
