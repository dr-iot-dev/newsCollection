"""Stable, category-wide art direction for new editorial featured images."""

import colorsys
import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageStyle:
    background: str
    dominant: str
    lighting: str
    texture: str


CATEGORY_STYLES = {
    "generative_ai": ImageStyle(
        "lavender #D8C2F0",
        "violet and plum #6935A2",
        "soft violet ambient light",
        "subtle flowing translucent layers",
    ),
    "edge_ai": ImageStyle(
        "peach #F7D2AA",
        "burnt orange and terracotta #BE5B1C",
        "warm amber directional light",
        "subtle angular layered planes",
    ),
    "iot_platform": ImageStyle(
        "sky blue #BFD9F1",
        "ocean blue #246DAB",
        "clear cool blue ambient light",
        "subtle connected circular ripples",
    ),
    "security": ImageStyle(
        "sage green #BCDCC4",
        "forest green #296645",
        "soft green ambient light",
        "subtle enclosing curved layers",
    ),
    "standards": ImageStyle(
        "warm stone gray #D1CDC4",
        "neutral graphite #555453",
        "neutral daylight without a blue cast",
        "subtle orderly grid and aligned planes",
    ),
}


def image_style(category: str) -> ImageStyle:
    if category in CATEGORY_STYLES:
        return CATEGORY_STYLES[category]
    # New category keys receive a repeatable whole-image palette, never the old blue default.
    hue = int.from_bytes(hashlib.sha256(category.encode()).digest()[:4], "big") % 360 / 360

    def color(lightness: float, saturation: float) -> str:
        rgb = colorsys.hls_to_rgb(hue, lightness, saturation)
        return "#" + "".join(f"{round(channel * 255):02X}" for channel in rgb)

    return ImageStyle(
        color(0.79, 0.55),
        color(0.39, 0.65),
        "ambient light tinted to the dominant palette",
        "subtle layered geometric texture",
    )


def category_art_direction(category: str) -> str:
    style = image_style(category)
    return (
        "Category art direction policy: category-colors-v1. "
        f"Use a {style.background} background and a {style.dominant} dominant palette. "
        f"Lighting: {style.lighting}. Background texture: {style.texture}. "
        "Make the category recognizable from the WHOLE image even at thumbnail size. "
        "Apply this palette to the broad backdrop, scene surfaces, shadows and ambient lighting; "
        "at least 70 percent of the visible image must read as this palette. "
        "Do not limit the category color to a small badge, border, icon or tiny accent. "
        "Keep objects legible with restrained neutral details; competing hues occupy at most "
        "10 percent of the image. Avoid a generic blue/teal technology look unless the selected "
        "category is iot_platform. Background textures stay abstract and secondary to the "
        "actual article theme; do not add unrelated objects or category logos. "
    )
