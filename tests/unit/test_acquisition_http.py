import gzip
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.modules.acquisition.http import (
    CollectionError,
    SafeHttpClient,
    URLPolicy,
    retry_time,
)


def client(handler: object, *, hosts: list[str] | None = None, limit: int = 1024) -> SafeHttpClient:
    return SafeHttpClient(
        allowed_hosts=hosts or ["news.example"],
        user_agent="TestNewsBot/1.0",
        min_delay_seconds=0,
        max_response_bytes=limit,
        resolver=lambda _: ["93.184.216.34"],
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://news.example/feed",
        "https://localhost/feed",
        "https://127.0.0.1/feed",
        "https://[::1]/feed",
        "https://169.254.169.254/latest/meta-data/",
        "https://news.example:8443/feed",
        "https://user:password@news.example/feed",
        "https://evil.example/feed",
        "https://news.example/feed?api_token=secret",
        "https://news.example/\nfeed",
    ],
)
def test_forbidden_url_never_reaches_transport(url: str) -> None:
    calls: list[httpx.Request] = []
    http = client(lambda request: calls.append(request) or httpx.Response(200))
    try:
        with pytest.raises(CollectionError, match="URL_BLOCKED"):
            http.get(url)
        assert calls == []
    finally:
        http.close()


@pytest.mark.parametrize(
    "addresses",
    [
        ["10.0.0.1"],
        ["::ffff:127.0.0.1"],
        ["169.254.169.254"],
        ["93.184.216.34", "192.168.1.1"],
        [],
        ["not-an-ip"],
    ],
)
def test_private_or_mixed_dns_answers_are_rejected(addresses: list[str]) -> None:
    calls: list[httpx.Request] = []
    http = SafeHttpClient(
        allowed_hosts=["news.example"],
        user_agent="TestNewsBot/1.0",
        min_delay_seconds=0,
        resolver=lambda _: addresses,
        transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200)),
    )
    try:
        with pytest.raises(CollectionError, match="DNS_ADDRESS_BLOCKED"):
            http.get("https://news.example/feed")
        assert not calls
    finally:
        http.close()


def test_dns_is_pinned_and_https_hostname_preserved() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "news.example"
        assert request.extensions["sni_hostname"] == "news.example"
        assert request.headers["if-none-match"] == '"old"'
        assert request.headers["if-modified-since"] == "Wed, 30 Sep 2026 00:00:00 GMT"
        return httpx.Response(304, headers={"ETag": '"old"'})

    http = client(handler)
    try:
        response = http.get(
            "https://news.example/feed",
            etag='"old"',
            last_modified="Wed, 30 Sep 2026 00:00:00 GMT",
        )
        assert response.status_code == 304
        assert response.final_url == "https://news.example/feed"
    finally:
        http.close()


def test_redirect_dns_rebinding_is_blocked() -> None:
    calls: list[httpx.Request] = []
    answers = iter([["93.184.216.34"], ["127.0.0.1"]])
    http = SafeHttpClient(
        allowed_hosts=["news.example"],
        user_agent="TestNewsBot/1.0",
        min_delay_seconds=0,
        resolver=lambda _: next(answers),
        transport=httpx.MockTransport(
            lambda request: calls.append(request)
            or httpx.Response(
                302,
                headers={"Location": "/redirected"},
            )
        ),
    )
    try:
        with pytest.raises(CollectionError, match="DNS_ADDRESS_BLOCKED"):
            http.get("https://news.example/feed")
        assert len(calls) == 1
    finally:
        http.close()


def test_redirect_rechecks_allowed_hosts() -> None:
    calls: list[httpx.Request] = []
    http = client(
        lambda request: calls.append(request)
        or httpx.Response(
            302,
            headers={"Location": "https://evil.example/steal"},
        )
    )
    try:
        with pytest.raises(CollectionError, match="URL_BLOCKED"):
            http.get("https://news.example/feed")
        assert len(calls) == 1
    finally:
        http.close()


def test_credentials_and_cookies_do_not_cross_redirect_or_persist() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                302,
                headers={
                    "Location": "https://other.example/feed",
                    "Set-Cookie": "session=secret",
                },
            )
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        return httpx.Response(
            200,
            headers={
                "Content-Type": "text/xml",
                "Set-Cookie": "session=secret",
                "Authorization": "Bearer private",
                "X-Api-Token": "private",
            },
            content=b"<rss/>",
        )

    http = client(handler, hosts=["news.example", "other.example"])
    try:
        response = http.get("https://news.example/feed", headers={"Authorization": "Bearer secret"})
        assert response.headers == {"content-type": "text/xml", "content-length": "6"}
        assert not http.client.cookies
    finally:
        http.close()


@pytest.mark.parametrize("compressed", [False, True])
def test_decoded_size_limit(compressed: bool) -> None:
    data = b"x" * 4096
    http = client(
        lambda _: httpx.Response(
            200,
            content=gzip.compress(data) if compressed else data,
            headers={"Content-Encoding": "gzip"} if compressed else {},
        )
    )
    try:
        with pytest.raises(CollectionError, match="RESPONSE_TOO_LARGE"):
            http.get("https://news.example/feed")
    finally:
        http.close()


def test_short_retry_after_then_success() -> None:
    calls: list[httpx.Request] = []
    sleeps: list[float] = []
    http = client(
        lambda request: calls.append(request)
        or httpx.Response(
            503 if len(calls) == 1 else 200,
            headers={"Retry-After": "2"},
            content=b"ok",
        )
    )
    http.sleep = sleeps.append
    try:
        assert http.get("https://news.example/feed").body == b"ok"
        assert len(calls) == 2
        assert sleeps == [2]
    finally:
        http.close()


@pytest.mark.parametrize("status", [403, 429])
def test_long_rate_limit_is_deferred_without_inline_retry(status: int) -> None:
    calls: list[httpx.Request] = []
    reset = datetime.now(UTC) + timedelta(hours=1)
    http = client(
        lambda request: calls.append(request)
        or httpx.Response(
            status,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(reset.timestamp())),
            },
        )
    )
    try:
        with pytest.raises(CollectionError, match="RATE_LIMITED") as captured:
            http.get("https://news.example/feed")
        assert captured.value.retry_at is not None
        assert len(calls) == 1
        assert "news.example" not in str(captured.value)
    finally:
        http.close()


@pytest.mark.parametrize(("status", "expected"), [(503, 4), (404, 1)])
def test_retry_limit_and_no_retry_for_not_found(status: int, expected: int) -> None:
    calls: list[httpx.Request] = []
    http = client(
        lambda request: calls.append(request)
        or httpx.Response(
            status,
            headers={"Retry-After": "0"},
        )
    )
    try:
        with pytest.raises(CollectionError):
            http.get("https://news.example/feed")
        assert len(calls) == expected
    finally:
        http.close()


def test_retry_after_http_date() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    assert retry_time({"retry-after": "Wed, 30 Sep 2026 01:00:00 GMT"}, now) == (
        now + timedelta(hours=1)
    )
    assert retry_time({"retry-after": "garbage"}, now) is None
    assert str(URLPolicy(["news.example"]).validate("https://news.example/feed#ignored")) == (
        "https://news.example/feed"
    )


def test_total_timeout_includes_stalled_dns() -> None:
    import threading
    import time

    finished = threading.Event()
    calls: list[httpx.Request] = []

    def slow_dns(_: str) -> list[str]:
        finished.wait(timeout=1)
        return ["93.184.216.34"]

    http = SafeHttpClient(
        allowed_hosts=["news.example"],
        user_agent="TestNewsBot/1.0",
        min_delay_seconds=0,
        resolver=slow_dns,
        transport=httpx.MockTransport(
            lambda request: calls.append(request) or httpx.Response(200),
        ),
        total_timeout_seconds=0.05,
    )
    try:
        started = time.monotonic()
        with pytest.raises(CollectionError, match="TOTAL_TIMEOUT"):
            http.get("https://news.example/feed")
        assert time.monotonic() - started < 0.5
    finally:
        finished.set()
        http.close()
    assert not calls
