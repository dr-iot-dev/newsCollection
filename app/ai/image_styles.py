"""Subtle category backgrounds with naturally colored editorial subjects."""

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
        "pale lavender #F3EDF9",
        "violet and plum #6935A2",
        "neutral daylight without a color cast",
        "subtle flowing translucent layers",
    ),
    "edge_ai": ImageStyle(
        "pale peach #FCF2E8",
        "burnt orange and terracotta #BE5B1C",
        "neutral daylight without a color cast",
        "subtle angular layered planes",
    ),
    "iot_platform": ImageStyle(
        "pale sky blue #EDF5FB",
        "ocean blue #246DAB",
        "neutral daylight without a color cast",
        "subtle connected circular ripples",
    ),
    "security": ImageStyle(
        "pale sage green #EFF7F1",
        "forest green #296645",
        "neutral daylight without a color cast",
        "subtle enclosing curved layers",
    ),
    "standards": ImageStyle(
        "pale warm stone gray #F5F3EF",
        "neutral graphite #555453",
        "neutral daylight without a color cast",
        "subtle orderly grid and aligned planes",
    ),
}


def image_style(category: str) -> ImageStyle:
    if category in CATEGORY_STYLES:
        return CATEGORY_STYLES[category]
    # New category keys receive a repeatable subtle background palette, never the old blue default.
    hue = int.from_bytes(hashlib.sha256(category.encode()).digest()[:4], "big") % 360 / 360

    def color(lightness: float, saturation: float) -> str:
        rgb = colorsys.hls_to_rgb(hue, lightness, saturation)
        return "#" + "".join(f"{round(channel * 255):02X}" for channel in rgb)

    return ImageStyle(
        color(0.96, 0.20),
        color(0.60, 0.25),
        "neutral daylight without a color cast",
        "subtle layered geometric texture",
    )


def category_art_direction(category: str) -> str:
    style = image_style(category)
    return (
        "Category art direction policy: category-colors-v2. "
        f"Use a very light, low-saturation {style.background} tint only in the background. "
        f"The category accent {style.dominant} may appear sparingly in background decoration. "
        f"Lighting: {style.lighting}. Background texture: {style.texture}. "
        "Keep foreground people and objects in natural colors: realistic skin, hair, clothing, "
        "neutral silver or charcoal equipment, and varied material colors. "
        "Never apply the category tint to people, foreground surfaces, shadows or scene lighting. "
        "Do not use a monochrome palette or an overall color cast. "
        "The background stays quiet and secondary to the article theme. "
        "Do not add unrelated objects or category logos. "
    )
