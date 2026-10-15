# モデル別コスト

APIが返した使用量に、2026年10月15日に確認した公開Standard単価を適用したUSD換算額。請求書上の確定額とは区別する。

| 工程 | モデル | 呼出数 | 入力 | キャッシュ読込 | キャッシュ書込 | 出力 | 推論（出力内数） | 費用 USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| selection | text-embedding-3-small | 696 | 1815850 | 0 | 0 | 0 | 0 | 0.036317 |
| selection | gpt-4.1-2025-04-14 | 31 | 936826 | 0 | 0 | 23304 | 0 | 2.060084 |
| generation_verification | gpt-6.1-sol | 18 | 145079 | 37280 | 107748 | 28280 | 3411 | 0.556000 |
| generation_verification | gpt-6-astra | 8 | 103455 | 12705 | 90726 | 4776 | 2608 | 1.385820 |

今回の生成・検証: **$1.941820**。
前段の埋め込み・選定を含む合計: **$4.038221**。

キャッシュ済み・書込トークンを通常入力から差し引いて各単価を適用する。推論トークンは出力トークンに含まれるため二重加算しない。Sol/Astraで入力が272,000トークンを超えた呼び出しには公式の長文追加料金を適用する。

失敗・不正応答でも使用量が返った呼び出しを含める。使用量を確認できない呼び出しは費用未確定として残し、0ドルとはみなさない。税・為替・個別契約割引は含めない。
費用未確定の呼出数: 1。

初回生成・検証・修正・再検証別と各呼び出しの計算結果は`costs.json`、原使用量は`api-calls.jsonl`を参照。

公式単価: [gpt-6.1-sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [gpt-6-astra](https://developers.openai.com/api/docs/models/gpt-6-astra), [gpt-4.1-2025-04-14](https://developers.openai.com/api/docs/models/gpt-4.1), [text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small)