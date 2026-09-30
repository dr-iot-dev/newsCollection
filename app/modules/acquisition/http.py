"""Bounded HTTPS requests with DNS pinning and no persistent credentials or cookies."""

import ipaddress
import re
import socket
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from queue import Empty, Queue
from random import SystemRandom
from urllib.parse import parse_qsl, urljoin, urlsplit

import httpx

SAFE_HEADERS = frozenset(
    {
        "content-type",
        "content-length",
        "content-encoding",
        "etag",
        "last-modified",
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "x-poll-interval",
        "link",
    }
)
SECRET_QUERY = re.compile(r"authorization|cookie|password|secret|token|api[_-]?key", re.I)
Resolver = Callable[[str], list[str]]
_HOST_LOCK = threading.Lock()
_HOST_STATE: dict[str, tuple[threading.Lock, float]] = {}


class CollectionError(Exception):
    def __init__(self, code: str, *, retry_at: datetime | None = None) -> None:
        super().__init__(code)  # Never interpolate response bodies, URLs, or credentials.
        self.code = code
        self.retry_at = retry_at


def resolve_host(host: str) -> list[str]:
    try:
        return list(
            {str(record[4][0]) for record in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        )
    except OSError:
        raise CollectionError("DNS_ERROR") from None


def public_address(address: str) -> bool:
    try:
        value = ipaddress.ip_address(address)
    except ValueError:
        return False
    return value.is_global and not value.is_multicast and not value.is_reserved


class URLPolicy:
    def __init__(self, allowed_hosts: Iterable[str]) -> None:
        self.allowed_hosts = frozenset(
            host.lower().encode("idna").decode() for host in allowed_hosts
        )

    def validate(self, value: str) -> httpx.URL:
        try:
            parsed = urlsplit(value)
            url = httpx.URL(value)
            host = url.host.lower()
            if (
                parsed.scheme != "https"
                or not host
                or len(value) > 4096
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in (None, 443)
                or host not in self.allowed_hosts
                or any(SECRET_QUERY.search(key) for key, _ in parse_qsl(parsed.query))
                or any(ord(character) < 32 for character in value)
            ):
                raise CollectionError("URL_BLOCKED") from None
            try:
                ipaddress.ip_address(host)
            except ValueError:
                if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
                    raise CollectionError("URL_BLOCKED") from None
            else:
                if not public_address(host):
                    raise CollectionError("URL_BLOCKED") from None
            return url.copy_with(fragment=None)
        except (ValueError, httpx.InvalidURL):
            raise CollectionError("URL_BLOCKED") from None


class PinnedTransport(httpx.BaseTransport):
    """Dial only the validated IP; preserve the original HTTPS hostname for TLS/SNI."""

    def __init__(
        self,
        policy: URLPolicy,
        *,
        resolver: Resolver = resolve_host,
        inner: httpx.BaseTransport | None = None,
    ) -> None:
        self.policy = policy
        self.resolver = resolver
        # IP-based pool keys must not reuse TLS connections across different original hosts.
        self.inner = inner or httpx.HTTPTransport(
            retries=0, trust_env=False, limits=httpx.Limits(max_keepalive_connections=0)
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = self.policy.validate(str(request.url))
        addresses = self.resolver(url.host)
        if not addresses or not all(public_address(address) for address in addresses):
            raise CollectionError("DNS_ADDRESS_BLOCKED")
        headers = request.headers.copy()
        headers["Host"] = url.netloc.decode("ascii")
        extensions = {**request.extensions, "sni_hostname": url.host}
        deadline = extensions.get("acquisition_deadline")
        if deadline is not None:
            remaining = float(deadline) - time.monotonic()
            if remaining <= 0:
                raise CollectionError("TOTAL_TIMEOUT")
            extensions["timeout"] = {
                key: min(value, remaining) if value is not None else remaining
                for key, value in extensions.get("timeout", {}).items()
            }
        pinned = httpx.Request(
            request.method,
            url.copy_with(host=addresses[0]),
            headers=headers,
            stream=request.stream,
            extensions=extensions,
        )
        return self.inner.handle_request(pinned)

    def close(self) -> None:
        self.inner.close()


@dataclass(frozen=True)
class FetchResponse:
    requested_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    fetched_at: datetime


def retry_time(headers: dict[str, str], now: datetime) -> datetime | None:
    candidates: list[datetime] = []
    value = headers.get("retry-after", "")
    if value:
        try:
            candidates.append(now + timedelta(seconds=max(0, int(value))))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
                candidates.append(parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed)
            except (ValueError, TypeError, OverflowError):
                pass
    if headers.get("x-ratelimit-remaining") == "0":
        try:
            candidates.append(datetime.fromtimestamp(int(headers["x-ratelimit-reset"]), UTC))
        except (KeyError, ValueError, OverflowError, OSError):
            pass
    return max(candidates) if candidates else None


class SafeHttpClient:
    def __init__(
        self,
        *,
        allowed_hosts: Iterable[str],
        user_agent: str,
        timeout_seconds: float = 20,
        max_response_bytes: int = 5_242_880,
        min_delay_seconds: float = 3,
        resolver: Resolver = resolve_host,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        total_timeout_seconds: float = 30,
    ) -> None:
        self.policy = URLPolicy(allowed_hosts)
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.min_delay_seconds = min_delay_seconds
        self.sleep = sleep
        self.total_timeout_seconds = total_timeout_seconds
        self.client = httpx.Client(
            transport=PinnedTransport(self.policy, resolver=resolver, inner=transport),
            trust_env=False,
            follow_redirects=False,
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
        )

    def close(self) -> None:
        self.client.close()

    def _pace(self, host: str, deadline: float) -> None:
        with _HOST_LOCK:
            lock, _ = _HOST_STATE.setdefault(host, (threading.Lock(), 0.0))
        # Shared in-process host pacing; the scheduler polls sources serially.
        with lock:
            _, previous = _HOST_STATE[host]
            wait = max(0.0, previous + self.min_delay_seconds - time.monotonic())
            if time.monotonic() + wait >= deadline:
                raise CollectionError("TOTAL_TIMEOUT")
            if wait:
                self.sleep(wait)
            _HOST_STATE[host] = (lock, time.monotonic())

    def get(
        self,
        value: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResponse:
        # A daemon bounds DNS and slow trickle responses as well as socket operations.
        # The worker only performs GETs; it never touches the database or source cursor.
        deadline = time.monotonic() + self.total_timeout_seconds
        outcomes: Queue[FetchResponse | CollectionError] = Queue(maxsize=1)

        def fetch() -> None:
            try:
                outcomes.put(
                    self._get(
                        value,
                        etag=etag,
                        last_modified=last_modified,
                        headers=headers,
                        deadline=deadline,
                    )
                )
            except CollectionError as exc:
                outcomes.put(exc)
            except Exception:
                outcomes.put(CollectionError("HTTP_PROTOCOL_ERROR"))

        threading.Thread(target=fetch, daemon=True).start()
        try:
            outcome = outcomes.get(timeout=max(0, deadline - time.monotonic()))
        except Empty:
            raise CollectionError("TOTAL_TIMEOUT") from None
        if isinstance(outcome, CollectionError):
            raise outcome from None
        return outcome

    def _get(
        self,
        value: str,
        *,
        etag: str | None,
        last_modified: str | None,
        headers: dict[str, str] | None,
        deadline: float,
    ) -> FetchResponse:
        requested = str(self.policy.validate(value))
        current = requested
        request_headers = dict(headers or {})
        if etag:
            request_headers["If-None-Match"] = etag
        if last_modified:
            request_headers["If-Modified-Since"] = last_modified
        redirects = 0
        attempts = 0
        while True:
            url = self.policy.validate(current)
            self._pace(url.host, deadline)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CollectionError("TOTAL_TIMEOUT")
            self.client.cookies.clear()
            try:
                with self.client.stream(
                    "GET",
                    current,
                    headers=request_headers,
                    extensions={"acquisition_deadline": deadline},
                    timeout=httpx.Timeout(
                        min(self.timeout_seconds, remaining), connect=min(5, remaining)
                    ),
                ) as response:
                    if time.monotonic() >= deadline:
                        raise CollectionError("TOTAL_TIMEOUT")
                    now = datetime.now(UTC)
                    safe_headers = {
                        key: val for key, val in response.headers.items() if key in SAFE_HEADERS
                    }
                    status = response.status_code
                    if status in {301, 302, 303, 307, 308}:
                        if redirects >= 5 or "location" not in response.headers:
                            raise CollectionError("REDIRECT_LIMIT")
                        next_url = self.policy.validate(
                            urljoin(current, response.headers["location"])
                        )
                        if next_url.host != url.host:
                            request_headers = {
                                key: val
                                for key, val in request_headers.items()
                                if key.lower() not in {"authorization", "cookie"}
                            }
                        current = str(next_url)
                        redirects += 1
                        continue
                    limited = status == 429 or (
                        status == 403
                        and (
                            "retry-after" in safe_headers
                            or safe_headers.get("x-ratelimit-remaining") == "0"
                        )
                    )
                    if limited or status in {502, 503, 504}:
                        target = retry_time(safe_headers, now)
                        if limited and target is None:
                            target = now + timedelta(minutes=1)
                        delay = (
                            max(0.0, (target - now).total_seconds())
                            if target
                            else (2**attempts + SystemRandom().uniform(0, 0.5))
                        )
                        if attempts >= 3 or delay > 5 or time.monotonic() + delay >= deadline:
                            raise CollectionError(
                                "RATE_LIMITED" if limited else "HTTP_RETRYABLE",
                                retry_at=target or now + timedelta(minutes=1),
                            )
                        attempts += 1
                        self.sleep(delay)
                        continue
                    if status not in {200, 304}:
                        raise CollectionError(f"HTTP_{status}")
                    try:
                        declared = int(safe_headers.get("content-length", "0"))
                    except ValueError:
                        raise CollectionError("INVALID_CONTENT_LENGTH") from None
                    if declared > self.max_response_bytes:
                        raise CollectionError("RESPONSE_TOO_LARGE")
                    body = bytearray()
                    for chunk in response.iter_bytes(chunk_size=65536):
                        if len(body) + len(chunk) > self.max_response_bytes:
                            raise CollectionError("RESPONSE_TOO_LARGE")
                        if time.monotonic() >= deadline:
                            raise CollectionError("TOTAL_TIMEOUT")
                        body.extend(chunk)
                    return FetchResponse(requested, current, status, safe_headers, bytes(body), now)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempts >= 3 or time.monotonic() >= deadline:
                    raise CollectionError("NETWORK_ERROR") from None
                attempts += 1
                self.sleep(min(2 ** (attempts - 1), max(0, deadline - time.monotonic())))
            except httpx.HTTPError:
                raise CollectionError("HTTP_PROTOCOL_ERROR") from None
            finally:
                self.client.cookies.clear()
