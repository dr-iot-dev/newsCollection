"""Bounded diagnostics using schema field names and fixed messages, never rejected data."""

import math
from typing import Any

from pydantic import ValidationError

from app.contracts.base import ContractModel
from app.core.editorial import EditorialBatchError, EditorialError

MESSAGES = {
    "AXIS_PRODUCT_CHANGED": "元の製品名と提供元を変更しないでください。",
    "AXIS_PASSAGE_INVALID": "指定記事のevidence_passagesにあるpassage_idを選んでください。",
    "AXIS_DUPLICATE_QUESTION": "項目ID・名称・質問を重複させないでください。",
    "AXIS_SEARCH_NOT_SHARED": "2記事以上で検索できる共通項目にまとめてください。",
    "AXIS_LABEL_NOT_SEARCHABLE": "軸名は24文字以内の短い一般名詞とし、括弧や例示を外してください。",
    "AXIS_SEARCH_TERMS_INVALID": (
        "検索語は2文字以上とし、重複・括弧・検索式・広すぎる語を外してください。"
    ),
    "AXIS_SEARCH_TERM_UNGROUNDED": "各検索語が出現する原文の段落をevidenceに指定してください。",
    "AXIS_CELL_SET_INVALID": "固定した全候補項目に一つずつ回答してください。",
    "AXIS_UNKNOWN_WITH_VALUE": "unknownのanswer、conditions、evidenceを空にしてください。",
    "AXIS_CELL_UNGROUNDED": "回答と限定条件を原文引用で裏付けてください。",
    "AXIS_ASSESSMENT_SET_INVALID": "全候補項目の評価を一つずつ返してください。",
    "AXIS_SELECTION_SET_INVALID": "候補内の項目IDだけを重複なく選んでください。",
    "AXIS_SELECTION_UNSUPPORTED": (
        "過半数の根拠と質問適合・有用性・非重複の評価を満たす項目だけを選んでください。"
    ),
    "AXIS_REVIEW_SET_INVALID": "選定された項目だけを一つずつ検証してください。",
    "PAIR_GROUNDING_INVALID": "引用を指定資料の原文と一致させてください。",
    "PAIR_GROUNDING_AMBIGUOUS": "引用が複数箇所にあり、位置を確定できません。",
    "PAIR_TERM_NOT_GROUNDED": "labelかaliasを引用原文の語句と一致させてください。",
    "PAIR_OVERLAPPING_TERMS": "同義語を別の特徴語として数えないでください。",
    "PAIR_CATEGORY_NOT_GROUNDED": "初期資料で抽出済みの語と引用だけを選んでください。",
    "PAIR_GENERIC_TERM": "広報定型句を特徴語へ含めないでください。",
    "PAIR_KEYWORD_DISTINCTION_REQUIRED": (
        "各特徴語のdistinction_reasonに、指定カテゴリ内で区別できる具体的な技術・機能・用途と"
        "その原文根拠を説明してください。出現頻度やカテゴリ所属だけを採用理由にしないでください。"
    ),
    "PAIR_PRODUCT_UNGROUNDED": "製品名と提供元を同じ資料の原文で確認できません。",
    "PAIR_UNSUPPORTED_NUMBER": "特徴の数値を引用原文で確認できません。",
    "PAIR_CELL_COVERAGE_INVALID": "固定した全比較項目に一つずつ回答してください。",
    "PAIR_UNKNOWN_WITH_EVIDENCE": "未記載の回答は根拠を空にしてください。",
    "PAIR_REVIEW_AXES_INVALID": "成立した固定比較項目だけを検証結果へ含めてください。",
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
        "比較用の独立した見出しは省き、比較を本文に組み込んでください。"
    ),
    "DRAFT_COMPARISON_CONTENT_MISSING": "比較欄が確認済みの比較データと一致しません。",
    "DRAFT_PRICE_CONDITIONS_MISSING": "補助適用後の料金から補助条件が抜けています。",
    "DRAFT_CLAIM_ATTRIBUTION_MISSING": "宣伝・効果の表現に発表者への帰属がありません。",
    "DRAFT_NUMBER_UNSUPPORTED": "草稿の数値を検証済み事実で確認できません。",
    "DRAFT_ENTITY_UNSUPPORTED": "草稿の固有名詞を検証済み事実で確認できません。",
    "DRAFT_UNSAFE_CONTENT": "草稿に連絡先・HTML・直接記述されたURLが含まれています。",
    "VERIFIER_OUTPUT_SCOPE_INVALID": "検証対象・ポリシー・必須検証項目が一致しません。",
    "COMPARISON_REASON_PRODUCT_MISMATCH": (
        "reasonへ評価対象のcandidate_product_nameを明記し、"
        "元製品と候補の役割を取り違えないでください。"
    ),
    "COMPARISON_GROUNDING_INVALID": (
        "引用・範囲・事実ID・証拠IDを指定資料の原文と一致させてください。"
    ),
    "COMPARISON_OTHER_PRODUCT_GROUNDING": (
        "候補自身の事実だけを採否理由とセルへ参照してください。"
    ),
    "COMPARISON_JUDGMENT_UNSUPPORTED_NUMBER": (
        "分類判断へ根拠のない数値を追加しないでください。"
        "事実IDはfact_ids配列だけに置き、説明文にIDや項目数を記載しないでください。"
    ),
    "COMPARISON_PLAN_PRODUCT_MISMATCH": (
        "元製品名とその根拠を検証済みの唯一の製品事実に合わせてください。"
    ),
    "COMPARISON_QUESTION_SET_MISMATCH": (
        "固定計画の全質問へ一つずつ回答し、項目を削除しないでください。"
    ),
    "COMPARISON_UNKNOWN_WITH_EVIDENCE": (
        "未記載のセルは根拠を空にし、確認できる記載と区別してください。"
    ),
    "COMPARISON_CELL_GROUNDING_REQUIRED": (
        "未記載以外の回答には候補自身の確認済み事実と原文根拠が必要です。"
    ),
    "COMPARISON_CELL_CONDITION_LOST": (
        "引用事実の条件・地域・単位・通貨・帰属を回答またはconditionsへそのまま保持してください。"
    ),
    "COMPARISON_CELL_CONDITION_STATUS_INVALID": (
        "条件がある事実を一般対応とせず、条件付き・予定・比較不能に分類してください。"
    ),
    "COMPARISON_CELL_QUALIFIER_UNGROUNDED": (
        "プラン・版・地域・確認時点に原文で確認できない値を追加しないでください。"
    ),
    "COMPARISON_CELL_UNSUPPORTED_NUMBER": (
        "回答とconditionsの数値は引用原文で確認できるものに限定してください。"
    ),
    "COMPARISON_MISSING_QUESTIONS_MISMATCH": (
        "missing_question_keysには必須の未記載・比較不能の質問だけをすべて列挙してください。"
    ),
    "COMPARISON_REQUIRED_CONDITION_FAILED": (
        "用途・役割・利用者が不適合または必須回答が不足する場合は採用可能にしないでください。"
    ),
    "COMPARISON_REJECTED_ROLE_REQUIRED": (
        "用途や役割が不適合の場合は追加情報待ちではなく不適合にしてください。"
    ),
    "COMPARISON_REVIEW_FACT_REFERENCE_INVALID": (
        "独立検証では選定資料群に存在する事実IDだけを参照してください。"
    ),
    "COMPARISON_REVIEW_GROUNDING_REQUIRED": (
        "合格とする独立検証項目には確認した事実IDを示してください。"
    ),
    "AI_PROVIDER_ERROR": "AIサービスが正常なHTTP応答を返しませんでした。",
    "AI_RESPONSE_TOO_LARGE": "AI応答がサイズ上限を超えました。",
    "AI_RESPONSE_INCOMPLETE": "AI応答が完了していません。",
    "AI_REFUSAL": "AIサービスが回答を拒否しました。",
    "AI_PROVIDER_INVALID_RESPONSE": "AIサービスの応答を読み取れませんでした。",
}
MESSAGES.update(
    {
        "DISCOVERY_PRODUCT_SET_MISMATCH": "入力製品ごとに採用理由を対応させてください。",
        "DISCOVERY_FACT_REFERENCE_INVALID": "入力の検証済み事実IDだけを参照してください。",
        "DISCOVERY_UNSUPPORTED_NUMBER": MESSAGES["COMPARISON_JUDGMENT_UNSUPPORTED_NUMBER"],
        "DISCOVERY_OTHER_PRODUCT_GROUNDING": MESSAGES["COMPARISON_OTHER_PRODUCT_GROUNDING"],
        "DISCOVERY_REASON_IDENTITY_REQUIRED": "採用理由に自身のproduct事実IDが必要です。",
        "DISCOVERY_REASON_FUNCTION_REQUIRED": "採用理由に自身の機能・用途の事実IDも必要です。",
        "DISCOVERY_REASON_PRODUCT_MISMATCH": (
            "採用理由に、その資料自身のproduct事実のvalueにある製品名をそのまま明記してください。"
        ),
        "DISCOVERY_QUESTION_SUPPORT_REQUIRED": (
            "question_supportへ全質問と全製品の組み合わせを一つずつ記載してください。"
        ),
        "DISCOVERY_PROPOSED_MAJOR_UNSUPPORTED": (
            "主要項目には全製品の根拠付き回答が必要です。未記載を非対応へ変換しないでください。"
        ),
        "DISCOVERY_PROPOSED_MAJORITY_UNSUPPORTED": (
            "表示項目には異なる二つ以上の主発表の根拠付き回答が必要です。"
        ),
        "DISCOVERY_REASON_UNSUPPORTED_NUMBER": MESSAGES["COMPARISON_JUDGMENT_UNSUPPORTED_NUMBER"],
        "DISCOVERY_HYPOTHESIS_BUDGET_EXCEEDED": "仮説数上限を守ってください。",
        "DISCOVERY_QUESTION_SET_MISMATCH": MESSAGES["COMPARISON_QUESTION_SET_MISMATCH"],
        "DISCOVERY_UNKNOWN_WITH_EVIDENCE": MESSAGES["COMPARISON_UNKNOWN_WITH_EVIDENCE"],
        "DISCOVERY_CELL_GROUNDING_REQUIRED": MESSAGES["COMPARISON_CELL_GROUNDING_REQUIRED"],
        "DISCOVERY_CELL_UNSUPPORTED_NUMBER": MESSAGES["COMPARISON_CELL_UNSUPPORTED_NUMBER"],
        "DISCOVERY_CELL_QUALIFIER_UNGROUNDED": MESSAGES["COMPARISON_CELL_QUALIFIER_UNGROUNDED"],
        "DISCOVERY_CELL_CONDITION_LOST": MESSAGES["COMPARISON_CELL_CONDITION_LOST"],
        "DISCOVERY_CELL_CONDITION_STATUS_INVALID": MESSAGES[
            "COMPARISON_CELL_CONDITION_STATUS_INVALID"
        ],
        "DISCOVERY_MISSING_QUESTIONS_MISMATCH": MESSAGES["COMPARISON_MISSING_QUESTIONS_MISMATCH"],
        "DISCOVERY_REQUIRED_CONDITION_FAILED": MESSAGES["COMPARISON_REQUIRED_CONDITION_FAILED"],
        "DISCOVERY_REJECTED_ROLE_REQUIRED": MESSAGES["COMPARISON_REJECTED_ROLE_REQUIRED"],
        "DISCOVERY_REVIEW_REFERENCE_INVALID": MESSAGES["COMPARISON_REVIEW_FACT_REFERENCE_INVALID"],
        "DISCOVERY_REVIEW_GROUNDING_REQUIRED": MESSAGES["COMPARISON_REVIEW_GROUNDING_REQUIRED"],
    }
)

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
    if isinstance(exc, EditorialBatchError):
        return [
            diagnostic
            for error in exc.errors
            for diagnostic in validation_diagnostics(error, model_type, attempt)
        ][:20]
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
