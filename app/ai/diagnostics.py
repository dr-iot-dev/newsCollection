"""Bounded diagnostics using schema field names and fixed messages, never rejected data."""

import math
from typing import Any

from pydantic import ValidationError

from app.contracts.base import ContractModel
from app.core.editorial import EditorialError

MESSAGES = {
    "FACT_EVIDENCE_AMBIGUOUS": "根拠文が本文内の複数箇所に一致し、位置を確定できません。",
    "FACT_EVIDENCE_MISMATCH": "指定した本文範囲と根拠文が一致しません。",
    "FACT_PERSONAL_DATA": "根拠・値・主語に個人の連絡先が含まれています。",
    "FACT_SUBJECT_UNSUPPORTED": "主語を収集本文で確認できません。",
    "FACT_NUMBER_UNSUPPORTED": "値の数値を根拠文で確認できません。",
    "FACT_DATE_UNSUPPORTED": "根拠の日付形式を確認できません。",
    "FACT_DATE_INVALID": "根拠の日付が実在する日付ではありません。",
    "FACT_DATE_PRECISION_MISMATCH": "値または日付の精度が根拠と一致しません。",
    "FACT_DATE_PRECISION_REQUIRED": "日付の精度の指定が必要です。",
    "FACT_VALUE_UNSUPPORTED": "値を根拠文で確認できません。",
    "FACT_QUALIFIER_UNSUPPORTED": "単位・地域・条件・帰属を根拠文で確認できません。",
    "FACT_CURRENCY_UNSUPPORTED": "通貨を根拠文で確認できません。",
    "FACT_CLAIM_CONTEXT_MISSING": "性能・安全性の主張には帰属と条件が必要です。",
    "PROMPT_INJECTION_SUSPECTED": "本文に指示の上書きを疑う表現があります。",
    "ARTICLE_PACKAGE_FACTS_MISSING": "草稿生成に必要な検証済み事実が揃っていません。",
    "DRAFT_FACT_REFERENCE_INVALID": "段落が未登録の事実を参照しています。",
    "DRAFT_TITLE_TOO_LONG": (
        "タイトルは製品・サービスの種類と原稿の観点を示し、60文字以内にしてください。"
    ),
    "DRAFT_TITLE_REDUNDANT_SUFFIX": "タイトル末尾の「を比較」は省略してください。",
    "DRAFT_COMPARISON_SECTION_FORBIDDEN": (
        "比較用の独立した見出しは省き、"
        "比較を本文に組み込んでください。"
    ),
    "DRAFT_COMPARISON_CONTENT_MISSING": "比較欄が確認済みの比較データと一致しません。",
    "DRAFT_PRICE_CONDITIONS_MISSING": "補助適用後の料金から補助条件が抜けています。",
    "DRAFT_CLAIM_ATTRIBUTION_MISSING": "宣伝・効果の表現に発表者への帰属がありません。",
    "DRAFT_NUMBER_UNSUPPORTED": "草稿の数値を検証済み事実で確認できません。",
    "DRAFT_ENTITY_UNSUPPORTED": "草稿の固有名詞を検証済み事実で確認できません。",
    "DRAFT_UNSAFE_CONTENT": "草稿に連絡先・HTML・直接記述されたURLが含まれています。",
    "VERIFIER_OUTPUT_SCOPE_INVALID": "検証対象・ポリシー・必須検証項目が一致しません。",
    "AI_PROVIDER_ERROR": "AIサービスが正常なHTTP応答を返しませんでした。",
    "AI_RESPONSE_TOO_LARGE": "AI応答がサイズ上限を超えました。",
    "AI_RESPONSE_INCOMPLETE": "AI応答が完了していません。",
    "AI_REFUSAL": "AIサービスが回答を拒否しました。",
    "AI_PROVIDER_INVALID_RESPONSE": "AIサービスの応答を読み取れませんでした。",
}
SCHEMA_MESSAGES = {
    "missing": "必須項目がありません。",
    "extra_forbidden": "許可されていない項目があります。",
    "literal_error": "許可された選択肢ではありません。",
    "string_type": "文字列が必要です。",
    "int_type": "整数が必要です。",
    "int_parsing": "整数として読み取れません。",
    "float_type": "数値が必要です。",
    "float_parsing": "数値として読み取れません。",
    "greater_than": "値が下限以下です。",
    "greater_than_equal": "値が下限を下回っています。",
    "less_than": "値が上限以上です。",
    "less_than_equal": "値が上限を超えています。",
    "string_too_short": "文字数が最小文字数を下回っています。",
    "string_too_long": "文字数が最大文字数を超えています。",
    "too_short": "項目数が最小件数を下回っています。",
    "too_long": "項目数が最大件数を超えています。",
    "uuid_parsing": "UUID形式ではありません。",
    "tuple_type": "配列が必要です。",
    "model_type": "オブジェクトが必要です。",
}


def validation_diagnostics(
    exc: ValidationError | EditorialError | ValueError,
    model_type: type[ContractModel],
    attempt: int,
) -> list[dict[str, Any]]:
    fields: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            fields.update(node.get("properties", {}))
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(model_type.model_json_schema())

    def safe_path(path: Any) -> list[str | int]:
        return [
            part
            if isinstance(part, str) and part in fields
            else part
            if type(part) is int and 0 <= part <= 1_000_000
            else "*"
            for part in path[:20]
        ]

    if isinstance(exc, ValidationError):
        details = []
        for error in exc.errors(include_url=False, include_input=False)[:20]:
            kind = error["type"] if error["type"] in SCHEMA_MESSAGES else "schema_error"
            limits = {
                key: value
                for key, value in (error.get("ctx") or {}).items()
                if key in {"gt", "ge", "lt", "le", "min_length", "max_length"}
                and type(value) in {int, float}
                and abs(value) <= 1_000_000
                and math.isfinite(value)
            }
            details.append(
                {
                    "code": "AI_SCHEMA_INVALID",
                    "condition": kind,
                    "message": SCHEMA_MESSAGES.get(kind, "応答が指定された形式に一致しません。"),
                    "path": safe_path(error["loc"]),
                    "limits": limits,
                    "attempt": attempt,
                }
            )
        return details
    if isinstance(exc, EditorialError) and exc.code in MESSAGES:
        return [
            {
                "code": exc.code,
                "message": MESSAGES[exc.code],
                "path": safe_path(exc.path),
                "attempt": attempt,
            }
        ]
    return [
        {
            "code": "AI_VALIDATION_ERROR",
            "message": "応答を検証できませんでした。",
            "path": [],
            "attempt": attempt,
        }
    ]
