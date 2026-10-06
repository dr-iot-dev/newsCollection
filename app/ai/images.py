"""Bounded, tool-free OpenAI Images adapter. Never retry a generation implicitly."""

import base64
import binascii
import json
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

import httpx
from PIL import Image, UnidentifiedImageError

from app.core.editorial import EditorialError

MAX_IMAGE_BYTES = 8_000_000


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    width: int
    height: int


def validate_image(data: bytes, size: str) -> GeneratedImage:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise EditorialError("AI_IMAGE_SIZE_INVALID", 503)
    try:
        with Image.open(BytesIO(data), formats=["JPEG"]) as image:
            width, height = image.size
            if f"{width}x{height}" != size:
                raise EditorialError("AI_IMAGE_DIMENSIONS_INVALID", 503)
            image.verify()
        # verify() alone does not fully decode JPEG scan data.
        with Image.open(BytesIO(data), formats=["JPEG"]) as image:
            image.load()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise EditorialError("AI_IMAGE_INVALID", 503) from None
    return GeneratedImage(data, width, height)


class ImageProvider(Protocol):
    def generate(self, *, model: str, prompt: str, size: str, quality: str) -> GeneratedImage: ...


class OpenAIImageProvider:
    def __init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self._api_key, self._transport = api_key, transport

    def generate(self, *, model: str, prompt: str, size: str, quality: str) -> GeneratedImage:
        try:
            with httpx.Client(
                transport=self._transport, trust_env=False, follow_redirects=False,
                timeout=httpx.Timeout(300, connect=5),
            ) as client, client.stream(
                "POST", "https://api.openai.com/v1/images/generations",
                headers={"Authorization": "Bearer " + self._api_key},
                json={"model": model, "prompt": prompt, "size": size, "quality": quality,
                      "n": 1, "output_format": "jpeg", "output_compression": 80,
                      "background": "opaque", "moderation": "auto"},
            ) as response:
                if response.status_code != 200:
                    raise EditorialError("AI_IMAGE_PROVIDER_REJECTED", 503)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 12_000_000:
                        raise EditorialError("AI_IMAGE_RESPONSE_TOO_LARGE", 503)
                result = json.loads(body)
                images = result.get("data", [])
                if len(images) != 1:
                    raise ValueError
                data = base64.b64decode(images[0]["b64_json"], validate=True)
                return validate_image(data, size)
        except httpx.HTTPError:
            raise EditorialError("AI_IMAGE_NETWORK_UNCERTAIN", 503) from None
        except (ValueError, KeyError, TypeError, binascii.Error):
            raise EditorialError("AI_IMAGE_RESPONSE_INVALID", 503) from None
