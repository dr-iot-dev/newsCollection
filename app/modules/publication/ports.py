from typing import Any, Protocol

from app.contracts.wordpress_v1 import WordPressPayloadV1


class PublicationPort(Protocol):
    def find(self, slug: str) -> dict[str, Any] | None: ...

    def get(self, post_id: str) -> dict[str, Any]: ...

    def create_draft(self, payload: WordPressPayloadV1) -> dict[str, Any]: ...

    def publish(self, post_id: str) -> dict[str, Any]: ...

    def trash(self, post_id: str) -> dict[str, Any]: ...

    def find_media(self, slug: str) -> dict[str, Any] | None: ...

    def get_media(self, media_id: str) -> dict[str, Any]: ...

    def upload_image(
        self,
        image: bytes,
        *,
        filename: str,
        slug: str,
        title: str,
        alt_text: str,
        caption: str,
        post_id: str,
    ) -> dict[str, Any]: ...

    def set_featured_media(
        self,
        post_id: str,
        media_id: str,
        *,
        content: str | None = None,
    ) -> dict[str, Any]: ...
