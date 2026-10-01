import re
from decimal import Decimal


class EditorialError(Exception):
    def __init__(self, code: str, status: int = 409) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")
PHONE = re.compile(r"(?<!\d)(?:\+81[- ]?)?0\d{1,4}[- ]\d{1,4}[- ]\d{3,4}(?!\d)")
INJECTION = re.compile(
    r"ignore (?:all |previous |the )*(?:instructions|prompts)|system prompt|"
    r"(?:指示|命令).{0,10}(?:無視|上書き)|(?:API|秘密|secret).{0,10}(?:キー|key|開示)",
    re.I,
)
NUMBER = re.compile(r"\d+(?:[,.]\d+)*(?:%|\uff05)?")
NAME = re.compile(r"\b[A-Z][A-Za-z0-9_-]{2,}\b|株式会社[^\s、。]{2,30}")


def redact_contacts(text: str) -> str:
    # Length-preserving masks keep evidence offsets tied to the stored normalized body.
    for pattern in (EMAIL, PHONE):
        text = pattern.sub(lambda m: "*" * len(m[0]), text)
    return text


def numbers(text: str) -> set[str]:
    result = set()
    for match in NUMBER.finditer(text):
        value = match[0].replace(",", "").replace("\uff05", "%")
        suffix = "%" if value.endswith("%") else ""
        result.add(format(Decimal(value.rstrip("%")).normalize(), "f") + suffix)
    return result


def personal_data(text: str) -> bool:
    return bool(EMAIL.search(text) or PHONE.search(text))
