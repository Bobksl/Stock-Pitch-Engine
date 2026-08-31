"""Module 4 — EDGAR HTTP client: rate-limited, disk-cached, fail-loud.

SEC access rules that shape this module:
- a descriptive User-Agent carrying contact info is REQUIRED (403 without it);
- automated traffic is capped at 10 requests/second, so we self-throttle to
  EDGAR_RPS (default 5) with a process-wide token gate.

Every response is written to EDGAR_CACHE_DIR keyed by sha256(url) with a JSON
sidecar recording where it came from. Cache-first means re-runs are offline,
deterministic and free — which is also what keeps the test suite network-free
and what makes an ingestion run reproducible months later (Audit G6).

Errors are raised, never swallowed: a half-fetched filing must not look like a
filing with missing facts.

CLI:  python -m src.edgar.client https://data.sec.gov/submissions/CIK0000789019.json
"""
import gzip
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from src.config import EDGAR_CACHE_DIR, EDGAR_RPS, EDGAR_USER_AGENT

# Transient at SEC: 403 is what they return when throttling an unfamiliar agent,
# so it is retried rather than treated as a hard authorisation failure.
RETRY_STATUSES = frozenset({403, 429, 500, 502, 503, 504})
MAX_ATTEMPTS = 5
BACKOFF_BASE_S = 1.0


class EdgarError(RuntimeError):
    """Any unrecoverable problem talking to EDGAR."""


class RateLimiter:
    """Process-wide minimum interval between requests."""

    def __init__(self, rps: float):
        self.min_interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> float:
        """Block until the next request is allowed; return the seconds slept."""
        with self._lock:
            now = time.monotonic()
            sleep_for = max(0.0, self._last + self.min_interval - now)
            if sleep_for:
                time.sleep(sleep_for)
            self._last = time.monotonic()
            return sleep_for


_limiter = RateLimiter(EDGAR_RPS)


def cache_path(url: str) -> Path:
    """Deterministic cache location for a URL (sharded to keep dirs small)."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return Path(EDGAR_CACHE_DIR) / digest[:2] / digest


def _http_get(url: str) -> tuple[bytes, str]:
    """One raw GET. Returns (body, content_type). Seam for tests to patch."""
    if not EDGAR_USER_AGENT:
        raise EdgarError(
            "EDGAR_USER_AGENT is unset. SEC requires a descriptive User-Agent with "
            "contact info, e.g. 'Jane Doe jane@example.com'. Set it in .env."
        )
    req = urllib.request.Request(url, headers={
        "User-Agent": EDGAR_USER_AGENT,
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return body, resp.headers.get("Content-Type", "")


def fetch(url: str, *, force: bool = False) -> bytes:
    """Cache-first GET with rate limiting and backoff. Returns the body bytes."""
    path = cache_path(url)
    if path.exists() and not force:
        return path.read_bytes()

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _limiter.wait()
        try:
            body, content_type = _http_get(url)
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                raise EdgarError(f"GET {url} failed with HTTP {e.code}") from e
        except urllib.error.URLError as e:
            last_error = e
            if attempt == MAX_ATTEMPTS:
                raise EdgarError(f"GET {url} failed: {e.reason}") from e
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            path.with_suffix(".meta.json").write_text(json.dumps({
                "url": url,
                "content_type": content_type,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }, indent=1), encoding="utf-8")
            return body

        time.sleep(BACKOFF_BASE_S * 2 ** (attempt - 1))

    raise EdgarError(f"GET {url} exhausted {MAX_ATTEMPTS} attempts: {last_error}")


def fetch_json(url: str, *, force: bool = False) -> dict:
    return json.loads(fetch(url, force=force))


def cache_meta(url: str) -> dict | None:
    """Provenance of a cached response, or None if it was never fetched."""
    meta = cache_path(url).with_suffix(".meta.json")
    return json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else None


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--force", action="store_true", help="ignore the cache and re-fetch")
    a = ap.parse_args()

    body = fetch(a.url, force=a.force)
    meta = cache_meta(a.url)
    print(f"{len(body):,} bytes  ->  {cache_path(a.url)}")
    print(f"content-type: {meta['content_type']}  fetched: {meta['fetched_at']}")
