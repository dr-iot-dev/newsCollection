"""Fixed-origin, bounded WordPress REST adapter using Application Passwords."""

import ipaddress
import json
import socket
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.contracts.wordpress_v1 import WordPressPayloadV1
from app.core.editorial import EditorialError


def validate_base_url(value: str) -> str:
    try:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.port not in (None, 443)
            or url.query
            or url.fragment
            or "\\" in value
            or any(ord(c) <= 32 for c in value)
            or url.hostname.endswith((".local", ".internal", ".localhost"))
            or url.hostname == "localhost"
        ):
            raise ValueError
        try:
            ipaddress.ip_address(url.hostname)
        except ValueError:
            pass
        else:
            raise ValueError
        if any(part in {".", ".."} for part in url.path.split("/")) or "%" in url.path:
            raise ValueError
        host = url.hostname.encode("idna").decode("ascii").lower()
        return urlunsplit(("https", host, url.path.rstrip("/"), "", ""))
    except ValueError:
        raise EditorialError("WORDPRESS_HTTPS_URL_REQUIRED", 422) from None


class WordPressTransport(httpx.BaseTransport):
    def __init__(self, host: str) -> None:
        self.host = host
        self.inner = httpx.HTTPTransport(
            retries=0, trust_env=False, limits=httpx.Limits(max_keepalive_connections=0)
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.scheme != "https" or request.url.host != self.host:
            raise EditorialError("WORDPRESS_ORIGIN_BLOCKED", 502)
        try:
            addresses = {
                str(row[4][0])
                for row in socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
            }
        except OSError:
            raise EditorialError("WORDPRESS_DNS_ERROR", 502) from None
        if not addresses or any(
            not ipaddress.ip_address(a).is_global
            or ipaddress.ip_address(a).is_multicast
            or ipaddress.ip_address(a).is_reserved
            for a in addresses
        ):
            raise EditorialError("WORDPRESS_DNS_BLOCKED", 502)
        headers = request.headers.copy()
        headers["Host"] = request.url.netloc.decode("ascii")
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=sorted(addresses)[0]),
            headers=headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": self.host},
        )
        return self.inner.handle_request(pinned)

    def close(self) -> None:
        self.inner.close()


class WordPressClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = validate_base_url(base_url)
        if not username.strip() or not password.strip() or ":" in username:
            raise EditorialError("WORDPRESS_CREDENTIALS_REQUIRED", 422)
        self.username, self.password = username, password
        self.transport, self.sleep = transport, sleep

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        # Writes are never automatically replayed: a 5xx can occur after remote commit.
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            transport = self.transport or WordPressTransport(urlsplit(self.base_url).hostname or "")
            try:
                with (
                    httpx.Client(
                        transport=transport,
                        auth=httpx.BasicAuth(self.username, self.password),
                        follow_redirects=False,
                        trust_env=False,
                        timeout=20,
                    ) as client,
                    client.stream(
                        method, self.base_url + "/wp-json/wp/v2/posts" + path, **kwargs
                    ) as response,
                ):
                    if response.status_code in {429, 500, 502, 503, 504}:
                        if attempt + 1 < attempts:
                            try:
                                delay = float(response.headers.get("Retry-After", "1"))
                            except ValueError:
                                delay = 1
                            if delay > 30:
                                raise EditorialError("WORDPRESS_RETRY_LATER", 503)
                            self.sleep(max(0, delay))
                            continue
                        raise EditorialError("WORDPRESS_REMOTE_UNAVAILABLE", 503)
                    if response.status_code not in {200, 201}:
                        raise EditorialError("WORDPRESS_REQUEST_REJECTED", 502)
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 1000000:
                            raise EditorialError("WORDPRESS_RESPONSE_TOO_LARGE", 502)
                        chunks.append(chunk)
                    return json.loads(b"".join(chunks))
            except httpx.HTTPError:
                raise EditorialError("WORDPRESS_NETWORK_UNCERTAIN", 503) from None
            except (ValueError, UnicodeError):
                raise EditorialError("WORDPRESS_RESPONSE_INVALID", 502) from None
        raise EditorialError("WORDPRESS_REMOTE_UNAVAILABLE", 503)

    def checked_post(self, result: Any) -> dict[str, Any]:
        if (
            not isinstance(result, dict)
            or type(result.get("id")) is not int
            or result["id"] <= 0
            or result.get("type") != "post"
            or not isinstance(result.get("link"), str)
        ):
            raise EditorialError("WORDPRESS_RESPONSE_INVALID", 502)
        if (
            result.get("status") not in {"draft", "pending", "private", "publish", "future"}
            or not isinstance(result.get("slug"), str)
            or not isinstance(result.get("modified_gmt"), str)
            or any(
                not isinstance(result.get(k), dict) or not isinstance(result[k].get("raw"), str)
                for k in ("title", "content", "excerpt")
            )
            or any(
                not isinstance(result.get(k), list)
                or any(type(v) is not int or v <= 0 for v in result[k])
                for k in ("categories", "tags")
            )
        ):
            raise EditorialError("WORDPRESS_RESPONSE_INVALID", 502)
        try:
            link = urlsplit(result["link"])
        except ValueError:
            raise EditorialError("WORDPRESS_REMOTE_LINK_INVALID", 502) from None
        origin = urlsplit(self.base_url)
        if link.scheme != "https" or link.netloc != origin.netloc or link.username or link.password:
            raise EditorialError("WORDPRESS_REMOTE_LINK_INVALID", 502)
        return result

    def find(self, slug: str) -> dict[str, Any] | None:
        result = self.request(
            "GET",
            "",
            params={
                "slug": slug,
                "context": "edit",
                "status": "draft,pending,private,publish,future",
                "per_page": 100,
            },
        )
        if not isinstance(result, list):
            raise EditorialError("WORDPRESS_RESPONSE_INVALID", 502)
        if len(result) > 1:
            raise EditorialError("WORDPRESS_RECONCILE_CONFLICT")
        return self.checked_post(result[0]) if result else None

    def get(self, post_id: str) -> dict[str, Any]:
        if not post_id.isdecimal() or int(post_id) <= 0:
            raise EditorialError("WORDPRESS_POST_ID_INVALID")
        return self.checked_post(self.request("GET", "/" + post_id, params={"context": "edit"}))

    def create_draft(self, payload: WordPressPayloadV1) -> dict[str, Any]:
        payload = WordPressPayloadV1.model_validate(payload.model_dump())
        return self.checked_post(self.request("POST", "", json=payload.model_dump(mode="json")))

    def publish(self, post_id: str) -> dict[str, Any]:
        if not post_id.isdecimal() or int(post_id) <= 0:
            raise EditorialError("WORDPRESS_POST_ID_INVALID")
        return self.checked_post(self.request("POST", "/" + post_id, json={"status": "publish"}))
