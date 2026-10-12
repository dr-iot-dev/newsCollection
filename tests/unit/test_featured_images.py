import base64
import json
from io import BytesIO

import httpx
import pytest
from PIL import Image

from app.ai.images import OpenAIImageProvider, validate_image
from app.core.editorial import EditorialError


def jpeg(size="1536x1024"):
    width, height = map(int, size.split("x"))
    out = BytesIO()
    Image.new("RGB", (width, height), "teal").save(out, format="JPEG")
    return out.getvalue()


class ImageProvider:
    def __init__(self):
        self.calls = []
        self.error = None

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise EditorialError(self.error)
        return validate_image(jpeg(kwargs["size"]), kwargs["size"])


def test_adapter_uses_bounded_jpeg_generation_and_checks_dimensions():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(jpeg()).decode()}]})

    provider = OpenAIImageProvider("fixture-key", transport=httpx.MockTransport(handler))
    image = provider.generate(
        model="gpt-image-1.5",
        prompt="A generic sensor illustration",
        size="1536x1024",
        quality="medium",
    )
    assert (image.width, image.height) == (1536, 1024)
    assert len(calls) == 1 and calls[0].url.path == "/v1/images/generations"
    payload = json.loads(calls[0].content)
    assert payload["n"] == 1 and payload["output_format"] == "jpeg"
    assert payload["quality"] == "medium" and payload["background"] == "opaque"
    with pytest.raises(EditorialError, match="AI_IMAGE_DIMENSIONS_INVALID"):
        validate_image(jpeg("1024x1024"), "1536x1024")
    with pytest.raises(EditorialError, match="AI_IMAGE_INVALID"):
        validate_image(b"not a picture", "1536x1024")


@pytest.mark.parametrize("failure", ["network", "rejected", "malformed", "oversized"])
def test_provider_failures_never_retry_or_expose_key(failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "network":
            raise httpx.ReadTimeout("sensitive-response", request=request)
        if failure == "rejected":
            return httpx.Response(403, json={"error": "sensitive-response"})
        if failure == "oversized":
            return httpx.Response(200, content=b"x" * 12_000_001)
        return httpx.Response(200, json={"data": [{"b64_json": "invalid-base64"}]})

    provider = OpenAIImageProvider("fixture-key", transport=httpx.MockTransport(handler))
    with pytest.raises(EditorialError) as exc:
        provider.generate(model="gpt-image-1.5", prompt="Context", size="1536x1024", quality="low")
    assert len(calls) == 1
    assert "fixture-key" not in str(exc.value) and "sensitive-response" not in str(exc.value)
