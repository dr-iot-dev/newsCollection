import json
import re
import shutil
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
WORK=BASE/'work/c01-trial'
OUT=BASE/'outputs/C01-ai-selection-20261015'
OUT.mkdir(parents=True,exist_ok=True)
rows=json.loads((WORK/'ranking-all13.json').read_text(encoding='utf-8'))
seven=json.loads((WORK/'input-seven.json').read_text(encoding='utf-8'))
response=json.loads((WORK/'selection-response.json').read_text(encoding='utf-8'))
execution=json.loads((WORK/'selection-execution.json').read_text(encoding='utf-8'))
selection=(WORK/'selection-result.md').read_text(encoding='utf-8')
assert response['status']=='completed'
assert response['model']=='gpt-4.1-2025-04-14'
assert re.search(r'selection_status[：:]\s*ONE_SET',selection)
assert re.search(r'記事ID[：:]\s*F312, F584, F965',selection)
assert len(seven)==7 and len({a['article_id'] for a in seven})==7
assert [a['article_id'] for a in seven]==[a['article_id'] for a in rows[:7]]
assert [a['article_id'] for a in rows[:3]]==['F312','F584','F965']
assert sum(a['body_chars'] for a in seven)==17035
for name in ['selection-result.md','input-seven.json','input-seven.xml','ranking-all13.json','provenance.json','selection-execution.json']:
    shutil.copyfile(WORK/name,OUT/name)
shutil.copyfile(BASE/'work/c01-selection-prompt.txt',OUT/'selection-prompt.txt')
shutil.copyfile(BASE/'work/c01-generation-prompt.txt',OUT/'generation-prompt.txt')
primary=[a for ident in ['F312','F584','F965'] for a in seven if a['article_id']==ident]
generation_input={'cluster_id':'C01','set':'PRIMARY','desired_length':'情報量に応じた長さ','selection_result':selection,'sources':primary}
(OUT/'generation-input.json').write_text(json.dumps(generation_input,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
summary={'cluster_id':'C01','cluster_members':13,'k':7,'selection_model':response['model'],'selection_status':'ONE_SET','model_reported_eligible_set_count':1,'primary_article_ids':['F312','F584','F965'],'reserve_article_ids':None,'baseline_centroid_top3':['F312','F584','F965'],'selection_changed_from_baseline':False,'generation_performer':'current_chat_assistant','generation_status':'INAPPROPRIATE','generation_failed_condition':['G2'],'selection_evidence_defects':['G4','G5','G6'],'article_created':False,'fallback_used':False,'fallback_unavailable_reason':'Selector returned no reserve set','successful_selection_api_calls':1,'generation_api_calls':0,'usage':execution['usage'],'external_evaluation_performed':False,'score':None,'source_body_chars':17035,'experiment_limitations':['One cluster, one selector response only','All 35 combinations were requested; the model did not output a per-combination audit','Category granularity remains a semantic judgement; this run applies the strict category criterion from the supplied prompts','No latest source refresh, no expansion beyond centroid top seven']}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
labels={'F312':('Aterm 19000T12BE','家庭用Wi-Fi 7ルーター'),'F584':('HYBRID Wi-Fi 5G NC03','5G対応モバイルルーター。別売クレードルによる据え置き利用の記載あり'),'F965':('WXR9300BE6P','家庭用Wi-Fi 7ルーター'),'F042':('iGS03MP／iGS03MP-G','LTE・Wi-Fi・BLEゲートウェイ'),'F955':('WBE700','業務用Wi-Fi 7アクセスポイント'),'F690':('ACERA 332C／332P','IoT向けWi-Fi HaLowアクセスポイント'),'F289':('iG350B','産業向けLTE Cat.1 bisマイクロゲートウェイ')}
table=['| 重心順位 | 記事ID | コサイン類似度 | 対象 | 本文に基づく用途・カテゴリ |','| --- | --- | --- | --- | --- |']
for a in seven:
    title,category=labels[a['article_id']]
    table.append(f'| {a["centroid_rank"]} | {a["article_id"]} | {a["cosine_similarity"]:.6f} | [{title}]({a["url"]}) | {category} |')
report='''# C01：AIによる3記事選定と生成可否の評価

実施日：2026年10月15日（日本時間）

## 結果

GPT-4.1による選定を実行し、第一候補1組・予備候補なしという結果を得た。第一候補は従来の重心上位3件と同じF312・F584・F965だった。このチャットのアシスタントが、前回提示した生成指示の厳格なカテゴリ基準で再確認し、不適と判定した。予備候補がないため、比較記事本文を作成せず終了した。

これは「APIが実行できず未完了」ではなく、「選択モデルの候補を生成前の採否判定で不適とした」経路である。生成不適報告を最終出力として保存した。

| 工程 | 実施結果 |
| --- | --- |
| C01所属の確認 | 13記事 |
| 重心順位の計算 | 13記事の元の埋め込みを用いて再計算 |
| 選定への入力 | 重心に近い7記事、本文合計17,035文字 |
| 選択モデル | gpt-4.1-2025-04-14、temperature=0 |
| モデルの選定結果 | ONE_SET。第一候補F312・F584・F965、予備なし |
| 生成担当 | このチャットのアシスタント |
| 生成前判定 | INAPPROPRIATE |
| 予備への切替 | 予備がないため実施せず |
| 完成した比較記事 | 0本 |
| 別モデルでの評価・採点 | 実施せず。点数なし |

## 重心に近い7記事

'''+ '\n'.join(table)+'''

## GPT-4.1の選定内容

第一候補は「Wi-Fi 7対応ルータ（ホーム・モバイル）の機能・性能・セキュリティ比較」。想定読者は、家庭やビジネスで高性能なWi-Fi 7対応ルーターを導入したいユーザーとされた。NC03が据え置き利用にも対応するという記載を根拠に、ホームルーター2機種とモバイルルーター1機種を同じ比較候補にした。

モデルはG1〜G6をすべて満たすと説明し、適切な組の数を1とした。予備候補は、他の記事のカテゴリ・用途が異なることを理由に出さなかった。モデルの返答は修正せず、[選定結果の原文](selection-result.md)に保存した。

## 生成段階での判定

今回の指示では異なる具体的カテゴリを横断する比較を対象外とした。この厳格な基準を適用し、ホーム・モバイルを横断する候補を不適とした。NC03に据え置き利用の記載があることは認めた上での判断であり、家庭で利用できないという判定ではない。カテゴリの粒度には意味的な判断が含まれるため、この判定を製品一般の比較不可能性と解釈すべきではない。

また、モデルが示した比較根拠には、カテゴリ解釈とは独立した誤りがあった。

| 選択モデルの説明 | 本文との照合結果 |
| --- | --- |
| Atermの18,669Mbps、NC03の3.5Gbps、WXRの10GbpsからAtermが最速 | Wi-Fi、5G、有線ポートという異なる区間の速度。機種全体の性能順位は導けない |
| NC03のIOT認証・SIM冗長化をセキュリティ軸で並列比較 | 本文はIOT認証をJC-STAR相当のセキュリティ適合として説明していない |
| 最大接続台数・管理機能・価格は3記事で根拠を確認できる | 自身の根拠表に未記載があり、全対象の根拠がある必須共通軸としては数えられない |
| WXR9300BE6Pは2025年10月発売 | 本文からその発売日は確認できない。記事公開日や更新日との混同がある |

誤りをそのまま比較記事に引き継がず、本文を再読した生成担当の判断を[生成段階の不適報告](generation-result.md)に保存した。対象やテーマを変更して比較記事を作る処理、選択モデルの再実行、7記事を超える候補追加は行っていない。

## この試行から分かること

今回のC01ではAIによる選択は従来と同じ3記事になり、適切な2組の確保には至らなかった。選択モデルが全条件を合格と自己申告しても、比較の根拠が正しいとは限らない。生成前に元記事へ戻って判定する工程により、この候補の問題を検出した。

一方、単一クラスター・単一応答だけでAI選択全体の改善率を結論付けることはできない。全35通りの検討は指示したが、モデルは35通りそれぞれの判定を出力していない。「適切な組が1つ」という数はモデルの報告値であり、独立した全組み合わせ検証によって保証した数ではない。

## 入力と実行の記録

使用したのは既存C01に属する元記事本文、所属情報、元の埋め込みである。保存済み13記事の「タイトル＋空行＋本文」のハッシュを確認した。各埋め込みをL2正規化し、13記事の平均を正規化した重心とのコサイン類似度で順位を付けた。重心上位3件が従来のC01入力と一致することも確認した。

記事本文・埋め込み・所属情報をデータとして再利用したが、以前の比較記事・検証結果は今回の選択モデルへ渡していない。今回の7記事には段落番号を付け、全文を渡した。新たな公開記事の検索・取得は行っていない。前回提示した選択指示・生成指示を使用し、今回の結果を見て採否条件を改定していない。

選択APIは1回成功した。最初の通常権限での試行はDNS解決に失敗して接続前に終了したため、通信権限を取得して同じ要求を実行した。モデルへの二重送信は行っていない。入力14,885トークン、出力2,257トークン、合計17,142トークンだった。生成段階はこのチャットで実施し、生成用のAPIは呼び出していない。

- [機械可読の結果](summary.json)
- [入力7記事の本文と段落番号](input-seven.json)
- [13記事の重心順位](ranking-all13.json)
- [選択に使った指示](selection-prompt.txt)
- [生成に使った指示](generation-prompt.txt)
- [生成段階の入力3記事](generation-input.json)
- [API実行のモデル名・トークン数](selection-execution.json)
'''
(OUT/'report.md').write_text(report,encoding='utf-8')
assert 'INAPPROPRIATE' in (OUT/'generation-result.md').read_text(encoding='utf-8')
assert not (OUT/'article.md').exists()
print(json.dumps({'validated':True,'output_directory':str(OUT),'selection_status':'ONE_SET','generation_status':'INAPPROPRIATE','final_article_count':0,'files':sorted(p.name for p in OUT.iterdir())},ensure_ascii=False))
