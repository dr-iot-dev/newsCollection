"""Shared reader-facing editorial style constraints."""

import re
from unicodedata import normalize


def title_has_comparison_suffix(title: str) -> bool:
    return normalize("NFKC", title).rstrip(" \t\n。.?!").endswith("を比較")


# Only known grammatical endings are rewritten; quoted source expressions stay literal.
PLAIN_ENDINGS = {
    "ではありませんでした": "ではなかった",
    "ではありません": "ではない",
    "できませんでした": "できなかった",
    "ありませんでした": "なかった",
    "していませんでした": "していなかった",
    "ていませんでした": "ていなかった",
    "ていません": "ていない",
    "ていました": "ていた",
    "ています": "ている",
    "されています": "されている",
    "されていました": "されていた",
    "していました": "していた",
    "しています": "している",
    "していません": "していない",
    "できていません": "できていない",
    "整理しました": "整理した",
    "判断しません": "判断しない",
    "整理します": "整理する",
    "共通します": "共通する",
    "示します": "示す",
    "判断します": "判断する",
    "異なります": "異なる",
    "なります": "なる",
    "使います": "使う",
    "行います": "行う",
    "できます": "できる",
    "できました": "できた",
    "できません": "できない",
    "いえません": "いえない",
    "ありません": "ない",
    "あります": "ある",
    "されます": "される",
    "でした": "であった",
    "です": "である",
}
for action in (
    "提供",
    "導入",
    "利用",
    "記載",
    "表示",
    "検知",
    "通知",
    "測定",
    "搭載",
    "説明",
    "確認",
    "対応",
    "評価",
    "抜粋",
    "意味",
):
    PLAIN_ENDINGS[action + "します"] = action + "する"
    PLAIN_ENDINGS[action + "しました"] = action + "した"
    PLAIN_ENDINGS[action + "しません"] = action + "しない"
QUOTED_TEXT = re.compile(r"(「[^」]*」|『[^』]*』)")
ENDING_BOUNDARY = r"(?=[。\uff01\uff1f!?、,\n]|\s*(?:\||$)|が|ので|から|けれど)"
POLITE_ENDING = re.compile(r"(?:です|でした|ます|ました|ません(?:でした)?)" + ENDING_BOUNDARY)


def plain_style(text: str) -> str:
    parts = QUOTED_TEXT.split(text)
    for index in range(0, len(parts), 2):
        for polite, plain in sorted(PLAIN_ENDINGS.items(), key=lambda pair: -len(pair[0])):
            parts[index] = re.sub(re.escape(polite) + ENDING_BOUNDARY, plain, parts[index])
    return "".join(parts)


def has_polite_ending(text: str) -> bool:
    return bool(POLITE_ENDING.search(QUOTED_TEXT.sub("", text)))
