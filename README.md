# comfyui-studio-autopilot

PCが閉じていても、GitHub Actions上でClaude（sonnet）が6時間おきにPlan→Do→Check→Actを
1周し、ComfyUIスタジオの北極星（**商用可モデルだけで作ったAI画像作品で初売上を立てる。
Patreon／DLsite。全年齢から**）に向けて少しずつ前へ進める自走エンジン。

このrepoは **public**。事業の詳細・秘密は一切コミットしない。状態・計画・ログは全部
Google Drive（非公開）の `AI素材/ComfyUIスタジオ/PDCA/` に置く。

## 仕組み図

```
GitHub Actions cron (6時間おき, publicリポなので分は無料) ／ workflow_dispatch
   │
   ▼
.github/workflows/pdca.yml
   │
   ├─ 1. Driveから状態を取得（PDCA/ → work/state/、倉庫README/harvester stateは
   │      読み取り専用で work/context/ へ）
   │
   ├─ 2. ops/bootstrap_state.py … 初回のみGOAL/BACKLOG/LOG/NEEDS_HUMAN/KPIの既定値を作る
   │
   ├─ 3. rclone.confを削除 → Claude実行（ops/prompt.md、dry_run時はops/stub_agent.py）
   │      env は CLAUDE_CODE_OAUTH_TOKEN と USER だけ。Driveの鍵は渡さない。
   │
   ├─ 4. ops/guard.py … Claude実行後・決定論で強制。保護パス・シークレット・サイズ上限
   │      違反はすべて取り消す（ジョブは失敗させない）
   │
   ├─ 5. rclone.confを復元 → ops/executor.py … work/outbox/*.json を許可リストだけで実行
   │      (drive_write / hf_fetch / gpu_generate=Replicate)
   │
   ├─ 6. ops/kpi.py → ops/report.py --dashboard-only … KPI.json・ダッシュボードを更新
   │
   ├─ 7. 状態をDriveへ戻す（work/state/ → PDCA/）
   │
   ├─ 8. コード変更があればブランチ→PR→テスト合格ならその場でsquash merge
   │
   └─ 9. ops/report.py … JST21時以降・1日1回だけIssue「PDCA日報」に5行以内でコメント
```

## 保存先（すべてGoogle Drive・非公開）

- 状態: `ryosei_google_drive:AI素材/ComfyUIスタジオ/PDCA/`
  （`GOAL.md`・`KPI.json`・`BACKLOG.md`・`LOG.md`・`NEEDS_HUMAN.md`・
  `ダッシュボード.md`・`fetched_models.json`・`budget.json`・`executor_log.jsonl`・
  `GUARD_LOG.md`・`notes/`）
- 参照専用（書かない）: `ryosei_google_drive:AI素材/ComfyUIモデル倉庫/`
  （x-model-harvesterの持ち物。README.mdと`.state/harvester.json`は書かない）
- 既存3モデル（参照専用）: `ryosei_google_drive:AI素材/ComfyUIモデル(2026-09-10-comfyui-studio)/`

## 必要なSecrets（GitHub リポジトリ Settings > Secrets and variables > Actions）

| Secret名 | 何のためか | 無いとどうなるか |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code をサブスク枠で無人実行 | 未設定だとClaude実行ステップが失敗する（`claude setup-token`で発行） |
| `RCLONE_CONFIG` | Google Driveへの状態の読み書き（rclone設定ファイルの中身そのまま） | 未設定だと状態の取得・保存ができない |
| `REPLICATE_API_TOKEN`（任意） | GPU生成（`gpu_generate`）をReplicate経由で実行 | 未設定なら`gpu_generate`は常に「GPU未設定」でスキップ（実害なし） |

## 初回セットアップ手順

1. このrepoを `ghp` で個人GitHub（Ryoseiimai）に **public** で作成し、push する。
2. 上表のSecretsを登録する。
3. Drive側に `AI素材/ComfyUIスタジオ/PDCA/` が無ければ、初回実行が
   `ops/bootstrap_state.py` で自動的に作る。
4. `workflow_dispatch` で `dry_run=1` を1回実行して疎通確認する（Claudeを呼ばず
   `ops/stub_agent.py` が代わりに動くため無料）。
5. 問題なければ `dry_run=0`（本番）で実行、または6時間おきのcronに任せる。

## 止め方

```bash
ghp workflow disable pdca -R Ryoseiimai/comfyui-studio-autopilot
```

再開は `ghp workflow enable pdca -R Ryoseiimai/comfyui-studio-autopilot`。

## 動作確認（ローカル）

```bash
cd ~/dev/2026-09-27-comfyui-studio-autopilot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
```

## 段階（S0〜S6・`ops/kpi.py`が証拠ファイルの実在で判定）

| 段階 | 内容 | 判定に使う証拠ファイル |
|---|---|---|
| S0 | エンジンが無人で回る | `work/state/notes/cycle_count.json`（このスクリプトの起動回数） |
| S1 | 商用可モデルが倉庫にそろう | `model_license_survey.json` + `fetched_models.json` |
| S2 | クラウドで1枚生成できる | `executor_log.jsonl` のgpu_generate成功 |
| S3 | 品質基準合格のサンプルN枚 | `quality_samples.json` |
| S4 | 企画・出品下書き | `product_drafts.json` |
| S5 | 本人の販売者登録・出品 | `human_flags.json`（本人が手で書く） |
| S6 | 初売上 | `human_flags.json`（本人が手で書く） |

## 既知の限界

- **シークレット検出は固定の正規表現リストのみ**（`sk-ant-`・`ya29.`・`refresh_token`・
  `-----BEGIN`）。エントロピー計算等の高度な検知は無い。新しい形式の鍵は検知できない。
  本格対応するときは detect-secrets 等の専用ツールへの置き換えが入口
  （`ops/guard.py`）。
- **保護対象は`.github/**`・`ops/guard*`・`ops/executor*`・`ops/report*`・
  `GUARDRAILS.md`のみ**（spec通り）。`tests/`配下は対象外のため、Claudeが自分の
  テストを書き換えて弱体化させることの防止は未対応（`ops/guard.py`）。
- **hf_fetchの月間上限はUTCの年月で判定**（JSTとのズレは最大数時間分。100GBという
  大きい上限に対しては実害が小さいと判断した簡略化。`ops/executor.py`）。
- **Replicateの実コストは近似値**。`metrics.predict_time`×`REPLICATE_HARDWARE_USD_PER_SEC`
  （未検証の見積もり値・環境変数で上書き可）で近似し、取れない場合は固定見積もり
  `REPLICATE_ESTIMATED_COST_USD`を使う。本格対応するときはReplicateのusage/billing
  APIから実額を取得する処理に置き換えるのが入口。使用する具体モデル
  （`REPLICATE_COMFYUI_MODEL`、既定`fofr/any-comfyui-workflow`）の入出力スキーマも
  実行前にReplicateのモデルページで要確認（未検証の前提・`ops/executor.py`）。
- **KPI.jsonはClaudeが手で編集しない**。`ops/kpi.py`が証拠ファイルの実在から毎周
  自動再計算する設計（自己申告でKPIが上がらないようにするための意図的な役割分担）。
- **日報Issueが本人に閉じられた場合**、次に見つからなければ新規作成する
  （履歴は分断されるが、本人が明示的に閉じた意思を優先する簡略化・`ops/report.py`）。
- **GitHub cronの遅延**: 数時間遅れることがある前提で6時間間隔にしている。急ぎたい
  場合は`workflow_dispatch`で手動実行する。
- **PR同時実行の競合**: `concurrency: group: pdca`で直列化しているため、人間が同時に
  mainへ手で push するケースの競合は考慮していない。

## ファイル構成

| ファイル | 役割 |
|---|---|
| `.github/workflows/pdca.yml` | cron 6時間おき＋workflow_dispatch |
| `GUARDRAILS.md` | 保護ファイル。お金・外部発信・商用利用・作品内容・秘密のルール |
| `ops/prompt.md` | PDCAエージェント（Claude）への指示 |
| `ops/paths.py` | 定数・置き場所の一元管理 |
| `ops/bootstrap_state.py` | Drive状態の初期値を決定論的に作る（無ければ作る・上書きしない） |
| `ops/guard.py` | Claude実行後の決定論ガード（保護パス・シークレット・サイズ上限） |
| `ops/executor.py` | 許可リスト実行器（drive_write / hf_fetch / gpu_generate=Replicate） |
| `ops/kpi.py` | 段階S0〜S6と数値の自動判定 |
| `ops/report.py` | Driveダッシュボード更新＋1日1回のIssue日報 |
| `ops/stub_agent.py` | dry_run時にClaudeの代わりに動く決定論スタブ |
| `lib/license.py` | 商用利用可否の4区分判定（x-model-harvesterから移植） |
| `tests/` | 単体テスト（guard/executor/kpi/license） |
