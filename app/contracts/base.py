from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def reject_nul(value: Any) -> None:
    if isinstance(value, str) and "\x00" in value:
        raise ValueError("NUL is not allowed in contract text")
    if isinstance(value, (list, tuple)):
        for part in value:
            reject_nul(part)
    if isinstance(value, dict):
        for key, part in value.items():
            reject_nul(key)
            reject_nul(part)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="after")
    @classmethod
    def database_safe_text(cls, value: Any) -> Any:
        reject_nul(value)
        return value
