"""P0.2 — EDGAR client: caching, rate limiting, backoff, fail-loud behaviour.

Network-free by construction: every test patches the single HTTP seam
(client._http_get). If a test here ever touches the network, that is the bug.
"""
import time
import urllib.error

import pytest

from src.edgar import client


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Isolated cache dir; no test may touch the real one."""
    monkeypatch.setattr(client, "EDGAR_CACHE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def no_sleep(monkeypatch):
    """Collapse backoff and throttle sleeps so retry tests run instantly."""
    monkeypatch.setattr(client.time, "sleep", lambda s: None)


URL = "https://data.sec.gov/submissions/CIK0000789019.json"


def test_cache_path_is_deterministic_and_sharded(cache):
    p1, p2 = client.cache_path(URL), client.cache_path(URL)
    assert p1 == p2
    assert p1.parent.name == p1.name[:2]          # sharded by first byte of the digest
    assert client.cache_path(URL + "x") != p1


def test_fetch_writes_body_and_provenance_sidecar(cache, no_sleep, monkeypatch):
    monkeypatch.setattr(client, "_http_get", lambda url: (b'{"cik":789019}', "application/json"))

    body = client.fetch(URL)

    assert body == b'{"cik":789019}'
    meta = client.cache_meta(URL)
    assert meta["url"] == URL
    assert meta["bytes"] == 14
    # sha256 of the body, hand-checked below against hashlib in the same run
    import hashlib
    assert meta["sha256"] == hashlib.sha256(b'{"cik":789019}').hexdigest()


def test_second_fetch_is_served_from_cache(cache, no_sleep, monkeypatch):
    calls = []

    def once(url):
        calls.append(url)
        return b"payload", "text/html"

    monkeypatch.setattr(client, "_http_get", once)

    assert client.fetch(URL) == b"payload"
    assert client.fetch(URL) == b"payload"
    assert len(calls) == 1, "cache hit must not issue a second request"


def test_force_bypasses_the_cache(cache, no_sleep, monkeypatch):
    bodies = iter([b"v1", b"v2"])
    monkeypatch.setattr(client, "_http_get", lambda url: (next(bodies), "text/html"))

    assert client.fetch(URL) == b"v1"
    assert client.fetch(URL) == b"v1"
    assert client.fetch(URL, force=True) == b"v2"


def test_fetch_json_parses(cache, no_sleep, monkeypatch):
    monkeypatch.setattr(client, "_http_get", lambda url: (b'{"cik": 789019}', "application/json"))
    assert client.fetch_json(URL) == {"cik": 789019}


def _http_error(code):
    return urllib.error.HTTPError(URL, code, "boom", {}, None)


def test_retries_throttling_then_succeeds(cache, no_sleep, monkeypatch):
    attempts = []

    def flaky(url):
        attempts.append(url)
        if len(attempts) < 3:
            raise _http_error(429)
        return b"ok", "text/html"

    monkeypatch.setattr(client, "_http_get", flaky)

    assert client.fetch(URL) == b"ok"
    assert len(attempts) == 3


def test_gives_up_after_max_attempts(cache, no_sleep, monkeypatch):
    attempts = []

    def always_throttled(url):
        attempts.append(url)
        raise _http_error(503)

    monkeypatch.setattr(client, "_http_get", always_throttled)

    with pytest.raises(client.EdgarError):
        client.fetch(URL)
    assert len(attempts) == client.MAX_ATTEMPTS


def test_non_retryable_status_fails_immediately(cache, no_sleep, monkeypatch):
    attempts = []

    def not_found(url):
        attempts.append(url)
        raise _http_error(404)

    monkeypatch.setattr(client, "_http_get", not_found)

    with pytest.raises(client.EdgarError, match="404"):
        client.fetch(URL)
    assert len(attempts) == 1, "404 is not transient; retrying it wastes the rate budget"


def test_failed_fetch_leaves_no_cache_entry(cache, no_sleep, monkeypatch):
    monkeypatch.setattr(client, "_http_get", lambda url: (_ for _ in ()).throw(_http_error(500)))

    with pytest.raises(client.EdgarError):
        client.fetch(URL)
    assert not client.cache_path(URL).exists()
    assert client.cache_meta(URL) is None


def test_missing_user_agent_raises_before_any_request(monkeypatch):
    monkeypatch.setattr(client, "EDGAR_USER_AGENT", "")
    with pytest.raises(client.EdgarError, match="EDGAR_USER_AGENT"):
        client._http_get(URL)


def test_rate_limiter_enforces_minimum_interval():
    limiter = client.RateLimiter(rps=50)          # 20 ms apart
    limiter.wait()                                # first call is free
    start = time.monotonic()
    limiter.wait()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.015, f"second call came {elapsed * 1000:.1f} ms after the first"


def test_rate_limiter_disabled_when_rps_is_zero():
    assert client.RateLimiter(rps=0).min_interval == 0.0
