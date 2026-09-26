"""定数・置き場所の一元管理（x-model-harvester の lib/paths.py と同じ考え方）。

このrepoは public なので、事業の詳細・秘密は一切コミットしない。状態は全部
Google Drive（非公開）の `AI素材/ComfyUIスタジオ/PDCA/` に置き、ワークフローが
rclone で `work/state/` にコピーしてから読み書きする。`work/` は .gitignore 済みで
git には一切乗らない。
"""
from __future__ import annotations

import os
from pathlib import Path

# --- repo内の場所 ---
REPO_ROOT = Path(__file__).resolve().parent.parent
WORK_ROOT = REPO_ROOT / "work"
STATE_DIR = WORK_ROOT / "state"
NOTES_DIR = STATE_DIR / "notes"
CONTEXT_DIR = WORK_ROOT / "context"  # 読み取り専用の参考コピー（倉庫README・harvester state）
OUTBOX_DIR = WORK_ROOT / "outbox"  # Claude/stub_agentが書き、executorが消費するリクエスト

# --- Drive（rclone remote）---
DRIVE_REMOTE = "ryosei_google_drive"
DRIVE_STUDIO_BASE_DIR = "AI素材/ComfyUIスタジオ"
DRIVE_STUDIO_BASE = f"{DRIVE_REMOTE}:{DRIVE_STUDIO_BASE_DIR}"
DRIVE_PDCA_DIR = f"{DRIVE_STUDIO_BASE_DIR}/PDCA"
DRIVE_PDCA = f"{DRIVE_REMOTE}:{DRIVE_PDCA_DIR}"

# 参照専用（書かない）。harvesterの持ち物。
DRIVE_WAREHOUSE_BASE_DIR = "AI素材/ComfyUIモデル倉庫"
DRIVE_WAREHOUSE_BASE = f"{DRIVE_REMOTE}:{DRIVE_WAREHOUSE_BASE_DIR}"
DRIVE_WAREHOUSE_README = f"{DRIVE_WAREHOUSE_BASE}/README.md"
DRIVE_WAREHOUSE_STATE = f"{DRIVE_WAREHOUSE_BASE}/.state/harvester.json"

# 既存3モデル（読むだけ）
DRIVE_EXISTING_3MODELS_DIR = "AI素材/ComfyUIモデル(2026-09-10-comfyui-studio)"
DRIVE_EXISTING_3MODELS = f"{DRIVE_REMOTE}:{DRIVE_EXISTING_3MODELS_DIR}"

# ComfyUIのモデルディレクトリ構成（harvesterと共通）
MODEL_KINDS = (
    "checkpoints",
    "diffusion_models",
    "text_encoders",
    "vae",
    "loras",
    "upscale_models",
    "controlnet",
    "ipadapter",
    "other",
)

# --- 上限値（hf_fetch）---
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024 * 1024  # 1ファイル25GB
MONTHLY_FETCH_CAP_BYTES = 100 * 1024 * 1024 * 1024  # 合計の追加上限100GB/月

# --- 上限値（gpu_generate・GPUプロバイダ=Replicateに決定・司令塔指定2026-09-27）---
REPLICATE_MONTHLY_CAP_USD = 10.0  # 月$10
REPLICATE_PER_CYCLE_CAP_USD = 1.0  # 1周（=1回のexecutor実行）$1

# --- 状態ファイル名（work/state/ 配下 = Drive PDCA/ 配下と1:1）---
GOAL_MD = "GOAL.md"
KPI_JSON = "KPI.json"
BACKLOG_MD = "BACKLOG.md"
LOG_MD = "LOG.md"
NEEDS_HUMAN_MD = "NEEDS_HUMAN.md"
DASHBOARD_MD = "ダッシュボード.md"
FETCHED_MODELS_JSON = "fetched_models.json"
EXECUTOR_LOG_JSONL = "executor_log.jsonl"
GUARD_LOG_MD = "GUARD_LOG.md"
BUDGET_JSON = "budget.json"

DRY_RUN = os.environ.get("DRY_RUN") == "1"
