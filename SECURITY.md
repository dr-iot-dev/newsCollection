# Security policy

脆弱性や秘密情報の混入を見つけた場合は公開Issueへ書かず、運用責任者へ非公開で連絡してください。

- APIキー、Application Password、Cookieを設定YAML・DB本文・ログ・Gitへ保存しない。
- 本番の資格情報は環境変数または組織のsecret managerから注入する。
- Web取得はHTTPS、許可ホスト、robots.txt、利用規約、SSRF検査をすべて通過させる。
- `approved` でないソースを収集しない。
