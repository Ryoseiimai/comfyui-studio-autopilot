"""Drive `PDCA/`（ローカルでは `work/state/`）の初期状態を作る。

初回実行時（Driveにまだ何も無い）でもClaude/stub_agentが必ず読める状態を用意するため、
LLMにフォーマット任せにせず決定論的なPythonで作る。既に存在するファイルは上書きしない
（2周目以降、Claudeが書いたBACKLOGの並び順やLOGの追記を消さないため）。
"""
from __future__ import annotations

import json
from pathlib import Path

from ops.gate import AGENT_DEFAULTS
from ops.paths import BACKLOG_MD, GOAL_MD, KPI_JSON, LOG_MD, NEEDS_HUMAN_MD, STATE_DIR

GOAL_MD_DEFAULT = """# GOAL

## 北極星
売り物に使ってよい（商用可）モデルだけで作ったAI画像作品で、初売上を立てる
（Patreon／DLsite）。全年齢（SFW）から。

## 段階（S0〜S6・順番に積む）
- S0: エンジンが無人で回る（Claudeの周が1回以上成功する）
- S1: 商用可モデルが倉庫にそろう（全年齢イラスト向けに最低限使えるセットができる）
- S2: クラウドで1枚生成できる（GPUプロバイダ経由でComfyUIワークフローが1枚通る）
- S3: 品質基準合格のサンプルN枚（Claudeの画像チェック採点表で合格したものが十分な枚数）
- S4: 企画・出品下書き（Patreon/DLsite向けの企画案・価格帯・出品文の下書きができる）
- S5: 本人の販売者登録・出品（本人にしかできない操作。AIは下書きを渡すだけ）
- S6: 初売上（実際に1件売れる）

## 制約
- `GUARDRAILS.md` を必ず守る（お金・外部発信・商用利用・作品内容・秘密）。
- このrepoはpublic。事業の詳細・秘密は一切コミットしない（状態は全部Drive）。
"""

KPI_JSON_DEFAULT: dict = {
    **AGENT_DEFAULTS,
    "generated_at": None,
    "stage": "S0",
    "stages": {},
    "counts": {},
    "note": "ops/kpi.py が毎周自動で上書きする。初期値はダミー。",
}

BACKLOG_MD_DEFAULT = """# BACKLOG

優先順（上が先）。完了したら `[x]` にして下に残す（消さない）。

- [ ] 1. 倉庫の既存モデル（Qwen-Image Q6_K gguf・qwen_2.5_vl_7b_fp8・qwen_image_vae・
      MiniMax-H3）の商用可否を元のライセンス文で確かめて一覧化する。
      対象: `AI素材/ComfyUIモデル(2026-09-10-comfyui-studio)/` の
      `diffusion_models/Qwen_Image-Q6_K.gguf` ・
      `text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors` ・
      `vae/qwen_image_vae.safetensors`、および
      `AI素材/ComfyUIモデル倉庫/checkpoints/` の MiniMax-H3系ファイル
      （倉庫READMEでは現在「要確認」）。結果は `work/state/model_license_survey.json`
      に `[{"file": "...", "category": "商用可|商用不可|有料ライセンスで可|要確認",
      "basis": "...", "source_url": "..."}]` 形式で保存する（S1のKPI集計対象）。
- [ ] 2. 全年齢イラスト向けの商用可モデル候補を調べ、`work/outbox/` の `hf_fetch` で
      倉庫（`AI素材/ComfyUIモデル倉庫/`）へ取得する。ライセンス根拠（HFのcardData等）を
      候補選定メモに残す。
- [ ] 3. クラウドGPUの実行コード。GPUプロバイダは **Replicate に決定**（司令塔調査
      2026-09-27。理由: デビットカード対応・前払い残高がそのまま上限・ComfyUIワークフロー
      のAPI実行ガイドあり）。`ops/executor.py`の`handle_gpu_generate`で実装済み
      （`REPLICATE_API_TOKEN`が無い間は「GPU未設定」でスキップ・予算は月$10・1周$1）。
      第一候補モデル: FLUX.1 schnell（Apache-2.0）／SDXL（OpenRAIL++）／
      Qwen-Image（Apache-2.0・要裏取り）。**FLUX.1 devは非商用ライセンスのため使わない**。
      ワークフローJSON（ComfyUI API形式）の具体的な組み立てとテスト（モック）を進める。
      本人作業（Replicate登録＋デビットで$10入金）は実際に1枚作るコードとモックテストがmerge済みになってから
      NEEDS_HUMANに出す。APIトークンのSecret登録はAI側で行う。
- [ ] 4. 品質基準とClaudeの画像チェック採点表を作る（全年齢・実在人物や既存キャラの
      排除チェックを含む）。
- [ ] 5. 全年齢AIイラストの売れ筋・価格帯（DLsite/Patreon）を調査し、企画案3つを
      `work/state/notes/` にまとめる。
"""

LOG_MD_DEFAULT = """# LOG

1周ごとに末尾へ追記する（5行以内・古い記録は消さない）。

"""

NEEDS_HUMAN_MD_DEFAULT = "なし\n"


def ensure_default_state(state_dir: Path) -> list[str]:
    """state_dir 配下に既定ファイルが無ければ作る。作成したファイル名のリストを返す。"""
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "notes").mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    defaults = {
        GOAL_MD: GOAL_MD_DEFAULT,
        BACKLOG_MD: BACKLOG_MD_DEFAULT,
        LOG_MD: LOG_MD_DEFAULT,
        NEEDS_HUMAN_MD: NEEDS_HUMAN_MD_DEFAULT,
    }
    for filename, content in defaults.items():
        target = state_dir / filename
        if not target.exists():
            target.write_text(content, encoding="utf-8")
            created.append(filename)

    kpi_target = state_dir / KPI_JSON
    if not kpi_target.exists():
        kpi_target.write_text(
            json.dumps(KPI_JSON_DEFAULT, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        created.append(KPI_JSON)

    return created


def main() -> None:
    created = ensure_default_state(STATE_DIR)
    if created:
        print(f"bootstrap_state: created {created}")
    else:
        print("bootstrap_state: already initialized, nothing to do")


if __name__ == "__main__":
    main()
