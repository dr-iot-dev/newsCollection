# Extraction計画：AI・IoT記事のDB検索と記事別カウント

更新日：2026-10-13。詳細は[Extraction仕様](extraction-word-count-spec-20261012.md)を参照。

AIまたはIoTの一覧だけを収集し、指定103語をタイトルに含む記事を本文取得より前に除外する。通過記事のタイトル・本文冒頭でAI／IoTの分野を確認し、会社概要などの見出し以降を分野判定から外す。対象記事をSQLite DBへ保存し、除外後200件以上を確保してからDiscovery候補語をSQL検索する。

記事の読込み・対象件数・検索・カウントのすべてにタイトル除外と分野フラグを適用する。既存記事も再判定し、以前の一般記事は検索対象から外す。候補のlabel・aliasesをOR検索し、COUNT(DISTINCT concept_id)とCOUNT(DISTINCT term)で数える。一致ゼロを含む対象記事について、記事・分野・候補数・語数・含んでいる語を表で示す。値・根拠・条件の抽出やAIによる意味判定は行わない。

現在は1707件を判定し、1507件を除外、200件を対象として同じ50候補で再集計した。[実記事の結果](extraction-word-count-results-20261012.md)、[対象記事の表](../.local/extraction-word-count-20261012/counts.md)、[除外理由](../.local/extraction-word-count-20261012/excluded-articles.md)を保存した。最低対象件数200を緩和していない。
