# 記事群Fの高密度コア抽出

実施日：2026-10-13。保存済み記事群Fの126記事・1,536次元ベクトルに、L2正規化、UMAP、HDBSCAN、クラスタ内コア選択を適用した。記事の再取得やOpenAI APIによる再埋め込みは行わない。

## 入力と手順

入力は[保存済みarticle-values.json](../.local/article-group-f-distances-20261013/article-values.json)の各記事のvalue。記事ID・タイトル・URL・一致候補数をそのまま引き継ぐ。モデル・次元の一致とIDの一意性を検証し、非有限値・ゼロベクトルは拒否する。入力ファイルのSHA-256を記録し、元ファイルを変更しない。

1. 各ベクトルをfloat64でL2正規化。既に正規化済みでも再計算する。
2. UMAP：metric='cosine'、n_components=15、n_neighbors=15、min_dist=0.0、random_state=42、n_jobs=1。
3. 縮約座標にHDBSCAN：metric='euclidean'、min_cluster_size=5、min_samples=5、cluster_selection_method='leaf'、approx_min_span_tree=False、core_dist_n_jobs=1。labels_=-1はノイズとし、どのコアにも含めない。
4. 各クラスタで、元の正規化済み1,536次元ベクトルの平均を再びL2正規化した重心を求める。元ベクトルと重心の内積をコサイン類似度とする。
5. 次の2種類の候補をそれぞれ残し、その共通部分を今回のコアとする。条件を満たさないクラスタにはコアを強制的に作らない。
   - 確率による候補：probabilities_の上位3件のうち0.9以上。同確率なら重心との類似度降順、その後記事ID順。
   - 重心による候補：元空間の重心とのコサイン類似度の上位3件。同類似度なら記事ID順。

主解析の条件は結果を見る前に固定した。クラスタIDは含まれる最小F ID順にC01〜C05とする。HDBSCANが返した元ラベルも記録する。

[UMAP公式のクラスタリング解説](https://umap-learn.readthedocs.io/en/latest/clustering.html)に沿ってクラスタ用の多次元縮約と小さいmin_distを使用し、[HDBSCAN公式のパラメータ説明](https://hdbscan.readthedocs.io/en/latest/parameter_selection.html)にある細かいクラスタの選択方法leafを採用した。近傍数15に加え、30でも解析して影響を記録する。

## 主解析の結果

| 項目 | 結果 |
| --- | ---: |
| 入力記事群F | 126 |
| 元の次元数 → UMAP次元数 | 1,536 → 15 |
| クラスタ数 | 5 |
| クラスタに所属する記事 | 68 |
| ノイズ | 58 |
| 確率による候補 | 15 |
| 重心による候補 | 15 |
| 両方に入るコア | 8 |

| クラスタ | 記事数 | コア記事ID（重心に近い順） | クラスタ内平均コサイン類似度 | コア内平均コサイン類似度 |
| --- | ---: | --- | ---: | ---: |
| C01 | 15 | F015 | 0.4991 | —（1記事） |
| C02 | 20 | F003 | 0.5500 | —（1記事） |
| C03 | 5 | F011、F026、F059 | 0.5787 | 0.6152 |
| C04 | 14 | F041 | 0.5131 | —（1記事） |
| C05 | 14 | F051、F027 | 0.5578 | 0.6596 |

コア8記事のprobabilities_はすべて1.0。一方、複数記事を含むコアの元空間でのペア類似度は0.5690〜0.6608である。帰属確率1.0は内容の一致率100%を意味しない。[HDBSCAN APIの定義](https://hdbscan.readthedocs.io/en/latest/api.html)では、所属クラスタへの帰属の強さを表す値である。

UMAPは元空間の密度を厳密に保存する手法ではないので、縮約空間の密度クラスタと元空間の類似度を併記する。内容の正解ラベルを付与しておらず、意味的な純度を測定・保証した結果ではない。元記事の保存タイトルには「NEWS RELEASE」や一部文字化けを含むものがあり、推測による補正は行わない。

## 条件変更の確認

主解析とは別に一つの条件だけ変更した6解析を実行した。主解析を最も見栄えのよい結果に差し替えない。ARIはノイズを含む全126記事の分類との一致度であり、純度の評価値ではない。

| 主解析からの変更 | クラスタ数 | ノイズ数 | コア数 | 主解析とのARI |
| --- | ---: | ---: | ---: | ---: |
| random_state=7 | 4 | 47 | 5 | 0.4200 |
| random_state=21 | 4 | 46 | 5 | 0.4093 |
| n_components=10 | 5 | 78 | 9 | 0.4492 |
| n_components=20 | 4 | 47 | 4 | 0.4528 |
| n_neighbors=30 | 4 | 72 | 8 | 0.3018 |
| min_cluster_size=8（min_samples=5を維持） | 4 | 48 | 7 | 0.7503 |

C03のコア3記事の全ペアは6回すべてで同じ非ノイズクラスタに所属した。C05のF051とF027は6回中5回。単独コアはペアの安定性を計算できない。同クラスタへの再所属だけで内容の純度やクラスタ分割の安定性が保証されるわけではない。

## 保存成果物

- [cores.html](../.local/article-group-f-cores-20261013/cores.html)：クラスタ概要と省スペースの記事表。タイトルは1行表示、マウスを置くかクリックすると全文を確認できる。コア／確率候補／重心候補／全クラスタ／ノイズ／全記事を切り替え、IDとタイトルで検索できる。
- [cores.md](../.local/article-group-f-cores-20261013/cores.md)、[cores.csv](../.local/article-group-f-cores-20261013/cores.csv)、[cores.json](../.local/article-group-f-cores-20261013/cores.json)：コア8記事のタイトル・元URL・帰属確率・重心類似度・順位。
- [article-clusters.json](../.local/article-group-f-cores-20261013/article-clusters.json)、[article-clusters.csv](../.local/article-group-f-cores-20261013/article-clusters.csv)：ノイズを含む全126記事の所属と候補選択フラグ。
- [clusters.json](../.local/article-group-f-cores-20261013/clusters.json)：各クラスタの全記事ID、元空間の正規化重心ベクトル、persistence、コアのペア類似度と条件変更での再所属割合。
- [normalized-vectors.npz](../.local/article-group-f-cores-20261013/normalized-vectors.npz)：F IDと正規化済み元ベクトル。np.load(..., allow_pickle=False)で読める。
- [reduced-vectors.json](../.local/article-group-f-cores-20261013/reduced-vectors.json)：全126記事の15次元UMAP座標。
- [sensitivity.json](../.local/article-group-f-cores-20261013/sensitivity.json)：条件変更6回の条件、全記事のラベル、コアID、主解析とのARI。
- [summary.json](../.local/article-group-f-cores-20261013/summary.json)、[validation.json](../.local/article-group-f-cores-20261013/validation.json)、[requirements-executed.txt](../.local/article-group-f-cores-20261013/requirements-executed.txt)：条件、入力ハッシュ、件数、実行ライブラリ版、独立検証結果。

## 再実行

クラスタリング用の任意依存を導入してから、外部APIを使用せずに実行する。umap-learn=0.5.12、hdbscan=0.8.44。推移的依存を含む今回の実行版はrequirements-executed.txtに記録した。バージョン・乱数シード・入力を固定して比較する。

```powershell
pip install ".[clustering]"
news-weave extraction cores --vectors .local/article-group-f-distances-20261013/article-values.json --output .local/article-group-f-cores-20261013 --n-components 15 --n-neighbors 15 --min-cluster-size 5 --min-samples 5 --core-top-n 3 --core-min-probability 0.9 --random-state 42
```

--no-sensitivityで主解析のみ実行できる。--core-top-nと--core-min-probabilityでコア選択条件を変更できる。HDBSCANは縮約座標へのユークリッド距離、重心計算は元ベクトルへのコサイン類似度と分けて扱う。

## 検証

既知の3群に分かれた合成ベクトルへのUMAP→HDBSCAN統合テスト、ゼロ・非有限値・重複ID・メタデータ不整合の拒否、ノイズと確率の低い記事の除外、両コア条件の共通部分、元空間の重心計算、HTML文字列の安全性を確認した。新規9件と距離処理9件の関連テスト18件、Ruff、変更3Pythonモジュールのmypyが通過。

実データは全126記事の一意な所属、ノイズ58記事、コア8記事、正規化、15次元座標、CSV件数、元入力の不変を独立確認した。全重心とコアのペア類似度を保存ベクトルから別途再計算し、最大差7.8e-16。正規化誤差は最大2.3e-16。コアが2つの上位リストの共通部分であることと、条件変更6回のコア再所属割合も照合した。
