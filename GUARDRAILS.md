# GUARDRAILS

このファイルと `.github/**`・`ops/guard*`・`ops/executor*`・`ops/report*` は保護対象。
Claude（PDCAエージェント）は絶対にこれらを書き換えない。書き換えても `ops/guard.py` が
実行後に検出し、その変更を強制的に取り消してログに残す（Claudeの自己申告を信用しない）。

## 1. お金
- 支払い・課金サービスの新規契約・購入をしない（本人にしかできない）。
- GPU（Replicate）の費用は実行器（`ops/executor.py`）の予算台帳
  （`work/state/budget.json` / Drive `PDCA/budget.json`）の範囲内だけ:
  **月$10・1周（1回のexecutor実行）$1が上限**。超える依頼は自動拒否する。
  `REPLICATE_API_TOKEN` が未登録の間は費用が発生する経路自体が動かない
  （常に「GPU未設定」でスキップ）。
- クレジットカード情報・決済情報を入力・保存・送信しない。デビットカードの登録・入金は
  本人がReplicateの画面で直接行う（AIは代行しない）。

## 2. 外部への発信
- 公開・出品・投稿・メッセージ送信・アカウント作成をしない。
- Patreon/DLsiteへの出品は本人が最後に押す。AIは下書きを作るところまで。
- この禁止は「ルールを守る」だけでなく構造的に保証する: `ops/executor.py` が実行できる
  リクエスト種別は `drive_write` / `hf_fetch` / `gpu_generate` の3つだけで、送信・投稿・
  決済・アカウント作成を行う実行経路はコード上に存在しない（Claudeが依頼しても実行できない）。

## 3. 商用利用
- 売り物に使うのは「商用可」判定のモデルだけ（`lib/license.py` の4区分判定）。
- 「有料ライセンスで可」は本人の購入待ち。買うまでは商用作品に使わない。
- 「要確認」は使わない。

## 4. 作品の内容
- 全年齢（SFW）のみ。
- 実在の人物・既存キャラクター/ブランド/ロゴ・未成年に見える人物の性的表現は作らない。

## 5. 秘密
- トークン・APIキー・OAuthトークン等を表示・ログ出力・ファイル保存・コミットしない。
- 自分の保護ファイル・ワークフロー（このファイル・`.github/**`・`ops/guard*`・
  `ops/executor*`・`ops/report*`）を書き換えない。

## 6. できること（Claudeの作業範囲）
- repo内の非保護ファイルの編集（コード・`ops/prompt.md`・`work/state/notes/` の調査メモ等）。
- WebSearch / WebFetch による調査。
- `work/outbox/*.json` を書いて実行器（`ops/executor.py`）にDrive書き込み・モデル取得・
  GPU生成を依頼する（実行器が許可リスト・ライセンス・上限で機械的に判定する）。
- `work/state/BACKLOG.md` の並べ替え、`work/state/LOG.md` への追記（1周5行以内）、
  本人にしかできないことだけ `work/state/NEEDS_HUMAN.md`（有効1件まで）。

技術的な強制（保護パス・シークレット検出・ファイルサイズ上限）は `ops/guard.py` が
Claude実行後に機械的に行う。詳細はそのファイルのdocstring参照。
