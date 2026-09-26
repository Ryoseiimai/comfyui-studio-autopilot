"""依頼（`work/outbox/*.json`）を許可リストで実行する決定論的な実行器。

Claude（PDCAエージェント）は直接ネットワークダウンロードやDrive書き込みをしない。
必ずここを経由させ、以下の許可リストだけを機械的に実行する:

- `drive_write`: `work/` 配下のファイルを `AI素材/ComfyUIスタジオ/**` にだけ書ける。
- `hf_fetch`: huggingface.co の直ファイルURLのみ。ライセンスは `lib/license.py` で判定し
  「商用可」「有料ライセンスで可」以外は拒否。1ファイル25GB・月間合計100GBの上限。
- `gpu_generate`: GPUプロバイダは **Replicate** に決定済み（司令塔指定 2026-09-27。理由:
  デビットカード対応・前払い残高がそのまま上限・ComfyUIワークフローのAPI実行ガイドあり）。
  Secret `REPLICATE_API_TOKEN` が無い間は「GPU未設定」で必ずスキップする。予算は
  `work/state/budget.json`（Drive `PDCA/budget.json`）で管理し、月$10・1周$1を超える
  依頼は自動拒否する（送信・公開・決済・アカウント作成を行う経路はここには存在しない）。

全依頼の結果を `work/state/executor_log.jsonl` に1行1件で追記する。

意図的な簡略化:
- 月間上限は UTC の年月（YYYY-MM）で判定する（JSTとのズレは最大でも数時間分で、
  100GBという大きい上限に対しては実害が小さいと判断した簡略化）。
- HEADリクエストの `Content-Length` が無い/信用できない場合に備え、ダウンロード中も
  ストリームで25GB上限を強制する（二重チェック）。
- Replicateの実コストはbilling APIを別途叩かないと厳密には取れない。ここでは
  `metrics.predict_time`（秒）×`REPLICATE_HARDWARE_USD_PER_SEC`（環境変数で上書き可・
  既定値は未検証の見積もり）で近似し、取れない場合は固定見積もり
  `REPLICATE_ESTIMATED_COST_USD` を使う。本格対応するときはReplicateのusage/billing
  APIから実額を取得する処理に置き換えるのが入口。使用する具体モデル
  （`REPLICATE_COMFYUI_MODEL`、既定 `fofr/any-comfyui-workflow`）の入出力スキーマも
  実行前にReplicateのモデルページで要確認（未検証の前提で実装している既知の限界）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from lib.license import CATEGORY_OK, CATEGORY_PAID, resolve_hf_license
from ops.paths import (
    BUDGET_JSON,
    DRIVE_REMOTE,
    DRIVE_STUDIO_BASE_DIR,
    DRIVE_WAREHOUSE_BASE,
    EXECUTOR_LOG_JSONL,
    FETCHED_MODELS_JSON,
    MAX_FILE_SIZE_BYTES,
    MODEL_KINDS,
    MONTHLY_FETCH_CAP_BYTES,
    OUTBOX_DIR,
    REPLICATE_MONTHLY_CAP_USD,
    REPLICATE_PER_CYCLE_CAP_USD,
    REPO_ROOT,
    STATE_DIR,
    WORK_ROOT,
)

ALLOWED_HF_CATEGORIES = {CATEGORY_OK, CATEGORY_PAID}
HF_FILE_URL_RE = re.compile(r"^https://huggingface\.co/([^/]+/[^/]+)/resolve/[^/]+/(.+)$")
DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024  # 8MB

# --- Replicate（gpu_generate）---
REPLICATE_API_BASE = "https://api.replicate.com/v1"
# 検証していない前提（要確認）。fofr/any-comfyui-workflow はComfyUIのAPI形式ワークフロー
# JSONを workflow_json 入力で受け取れる公開モデルという認識だが、実行前にReplicateの
# モデルページで入出力スキーマを必ず確認すること。
REPLICATE_COMFYUI_MODEL = os.environ.get("REPLICATE_COMFYUI_MODEL", "fofr/any-comfyui-workflow")
REPLICATE_ESTIMATED_COST_USD = float(os.environ.get("REPLICATE_ESTIMATED_COST_USD", "0.10"))
REPLICATE_HARDWARE_USD_PER_SEC = float(os.environ.get("REPLICATE_HARDWARE_USD_PER_SEC", "0.0011"))
REPLICATE_POLL_INTERVAL_SEC = 3
REPLICATE_POLL_TIMEOUT_SEC = 600
REPLICATE_TERMINAL_STATUSES = ("succeeded", "failed", "canceled")


class ExecutorError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_month_key(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")


def parse_hf_file_url(url: str) -> tuple[str, str] | None:
    """`https://huggingface.co/<org>/<repo>/resolve/<rev>/<path>` のみ許可し、
    (repo_id, path_in_repo) を返す。それ以外はNone。"""
    match = HF_FILE_URL_RE.match(url.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def guess_model_kind(filename: str) -> str:
    lower = filename.lower()
    if "vae" in lower:
        return "vae"
    if "lora" in lower:
        return "loras"
    if "controlnet" in lower or "control_net" in lower:
        return "controlnet"
    if "ipadapter" in lower or "ip_adapter" in lower or "ip-adapter" in lower:
        return "ipadapter"
    if "upscal" in lower or "esrgan" in lower:
        return "upscale_models"
    if "text_encoder" in lower or "clip" in lower or "t5" in lower:
        return "text_encoders"
    if "diffusion" in lower or "unet" in lower:
        return "diffusion_models"
    if lower.endswith((".safetensors", ".gguf", ".ckpt")):
        return "checkpoints"
    return "other"


def sum_month_bytes(fetched_list: list[dict], month_key: str) -> int:
    total = 0
    for item in fetched_list:
        fetched_at = item.get("fetched_at", "")
        size_bytes = item.get("size_bytes") or 0
        if fetched_at.startswith(month_key):
            total += size_bytes
    return total


def evaluate_hf_fetch_policy(
    *, url: str, size_bytes: int | None, license_category: str, month_used_bytes: int
) -> dict:
    """hf_fetchを許可するかのネットワークなし純粋判定。"""
    if parse_hf_file_url(url) is None:
        return {
            "allowed": False,
            "reason": "huggingface.coの直ファイルURL（/resolve/<rev>/<path>）のみ許可",
        }
    if license_category not in ALLOWED_HF_CATEGORIES:
        return {
            "allowed": False,
            "reason": f"ライセンス区分「{license_category}」は不可（商用可/有料ライセンスで可のみ）",
        }
    if size_bytes is not None and size_bytes > MAX_FILE_SIZE_BYTES:
        return {"allowed": False, "reason": f"1ファイル25GB上限超過（{size_bytes}バイト）"}
    if size_bytes is not None and month_used_bytes + size_bytes > MONTHLY_FETCH_CAP_BYTES:
        return {
            "allowed": False,
            "reason": f"月間100GB上限超過（既に{month_used_bytes}バイト使用済み）",
        }
    return {"allowed": True, "reason": None}


def evaluate_drive_write_policy(local_path: str, drive_subpath: str) -> dict:
    """drive_writeを許可するかのネットワークなし純粋判定。"""
    if not local_path or not local_path.startswith("work/"):
        return {"allowed": False, "reason": "local_pathはwork/配下のみ許可"}
    if ".." in Path(local_path).parts:
        return {"allowed": False, "reason": "パストラバーサル(..)は禁止"}
    allowed_prefix = f"{DRIVE_STUDIO_BASE_DIR}/"
    if not (drive_subpath == DRIVE_STUDIO_BASE_DIR or drive_subpath.startswith(allowed_prefix)):
        return {"allowed": False, "reason": f"drive_subpathは{allowed_prefix}配下のみ許可"}
    if ".." in Path(drive_subpath).parts:
        return {"allowed": False, "reason": "パストラバーサル(..)は禁止"}
    return {"allowed": True, "reason": None}


def evaluate_gpu_generate_policy(
    *, estimated_cost_usd: float, month_spent_usd: float, cycle_spent_usd: float
) -> dict:
    """gpu_generateを許可するかのネットワークなし純粋判定（予算台帳ゲート）。"""
    if month_spent_usd + estimated_cost_usd > REPLICATE_MONTHLY_CAP_USD:
        return {
            "allowed": False,
            "reason": f"月間予算${REPLICATE_MONTHLY_CAP_USD:.2f}上限超過（既に${month_spent_usd:.2f}使用）",
        }
    if cycle_spent_usd + estimated_cost_usd > REPLICATE_PER_CYCLE_CAP_USD:
        return {
            "allowed": False,
            "reason": f"1周${REPLICATE_PER_CYCLE_CAP_USD:.2f}上限超過（この周で既に${cycle_spent_usd:.2f}使用）",
        }
    return {"allowed": True, "reason": None}


# --- 外部呼び出しの薄いラッパー（テストではここをmonkeypatchする） ---


def _run_rclone(args: list[str]) -> dict:
    result = subprocess.run(["rclone", *args], capture_output=True, text=True)
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}


def _http_head_content_length(url: str) -> int | None:
    import requests

    try:
        resp = requests.head(url, allow_redirects=True, timeout=30)
        length = resp.headers.get("Content-Length")
        return int(length) if length is not None else None
    except Exception:
        return None


def _download_stream(url: str, dest_path: Path) -> int:
    import requests

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with dest_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > MAX_FILE_SIZE_BYTES:
                    raise ExecutorError(f"ダウンロード中に25GB上限超過: {url}")
                f.write(chunk)
    return downloaded


def upload_via_rclone(local_path: Path, drive_target: str) -> dict:
    return _run_rclone(["copyto", str(local_path), drive_target])


def _replicate_request(method: str, url: str, token: str, json_body: dict | None = None) -> dict:
    import requests

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = requests.request(method, url, headers=headers, json=json_body, timeout=60)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    return {"status_code": resp.status_code, "data": data}


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _replicate_poll_until_done(
    get_url: str,
    token: str,
    *,
    interval: float = REPLICATE_POLL_INTERVAL_SEC,
    timeout: float = REPLICATE_POLL_TIMEOUT_SEC,
) -> dict:
    start = time.monotonic()
    while True:
        result = _replicate_request("GET", get_url, token)
        data = result["data"]
        if data.get("status") in REPLICATE_TERMINAL_STATUSES:
            return data
        if time.monotonic() - start > timeout:
            return {"status": "timeout"}
        _sleep(interval)


# --- 予算台帳（gpu_generate・Replicate）---


def load_budget(path: Path) -> dict:
    month = current_month_key()
    default = {"month": month, "spent_this_month_usd": 0.0, "entries": []}
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    if not isinstance(data, dict) or data.get("month") != month:
        return default
    return data


def save_budget(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --- リクエストハンドラ ---


def handle_drive_write(req: dict, repo_root: Path) -> dict:
    local_path = req.get("local_path", "")
    drive_subpath = req.get("drive_subpath", "")
    decision = evaluate_drive_write_policy(local_path, drive_subpath)
    if not decision["allowed"]:
        return {"ok": False, "reason": decision["reason"]}

    abs_local = repo_root / local_path
    if not abs_local.exists() or not abs_local.is_file():
        return {"ok": False, "reason": f"local_pathが存在しない: {local_path}"}

    drive_target = f"{DRIVE_REMOTE}:{drive_subpath}"
    upload_result = upload_via_rclone(abs_local, drive_target)
    if not upload_result["ok"]:
        return {"ok": False, "reason": f"rclone失敗: {upload_result['stderr'][:300]}"}
    return {"ok": True, "drive_path": drive_target}


def handle_hf_fetch(req: dict, fetched_list: list[dict], work_dir: Path) -> dict:
    url = req.get("url", "")
    parsed = parse_hf_file_url(url)
    if parsed is None:
        return {
            "ok": False,
            "reason": "huggingface.coの直ファイルURL（/resolve/<rev>/<path>）のみ許可",
        }
    repo_id, path_in_repo = parsed
    filename = path_in_repo.rsplit("/", 1)[-1]

    license_result = resolve_hf_license(repo_id)
    category = license_result["category"]
    size_bytes = _http_head_content_length(url)
    month_key = current_month_key()
    month_used = sum_month_bytes(fetched_list, month_key)

    decision = evaluate_hf_fetch_policy(
        url=url, size_bytes=size_bytes, license_category=category, month_used_bytes=month_used
    )
    if not decision["allowed"]:
        return {"ok": False, "reason": decision["reason"], "license": license_result}

    kind = req.get("kind")
    if kind not in MODEL_KINDS:
        kind = guess_model_kind(filename)

    local_path = work_dir / "tmp_download" / filename
    try:
        actual_size = _download_stream(url, local_path)
        drive_target = f"{DRIVE_WAREHOUSE_BASE}/{kind}/{filename}"
        upload_result = upload_via_rclone(local_path, drive_target)
        if not upload_result["ok"]:
            return {"ok": False, "reason": f"rclone失敗: {upload_result['stderr'][:300]}"}
    except ExecutorError as e:
        return {"ok": False, "reason": str(e)}
    finally:
        if local_path.exists():
            local_path.unlink()

    record = {
        "file": filename,
        "repo_id": repo_id,
        "url": url,
        "kind": kind,
        "size_bytes": actual_size,
        "license_category": category,
        "license_basis": license_result.get("basis"),
        "drive_path": drive_target,
        "fetched_at": now_iso(),
    }
    fetched_list.append(record)
    return {"ok": True, "record": record}


def handle_gpu_generate(req: dict, budget_path: Path, cycle_budget: dict) -> dict:
    """Replicate経由でComfyUIワークフローを実行する。`REPLICATE_API_TOKEN`が無い間は
    常に「GPU未設定」でスキップする（司令塔がプロバイダをReplicateに決定・2026-09-27）。"""
    token = os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        return {"ok": False, "skipped": True, "reason": "GPU未設定"}

    workflow = req.get("workflow")
    if not workflow:
        return {"ok": False, "reason": "workflowが指定されていない"}
    params = req.get("params") or {}

    budget = load_budget(budget_path)
    decision = evaluate_gpu_generate_policy(
        estimated_cost_usd=REPLICATE_ESTIMATED_COST_USD,
        month_spent_usd=budget.get("spent_this_month_usd", 0.0),
        cycle_spent_usd=cycle_budget.get("spent_usd", 0.0),
    )
    if not decision["allowed"]:
        return {"ok": False, "reason": decision["reason"]}

    create = _replicate_request(
        "POST",
        f"{REPLICATE_API_BASE}/models/{REPLICATE_COMFYUI_MODEL}/predictions",
        token,
        {"input": {"workflow_json": json.dumps(workflow), **params}},
    )
    if create["status_code"] not in (200, 201):
        return {"ok": False, "reason": f"Replicate作成失敗: status={create['status_code']}"}

    get_url = (create["data"].get("urls") or {}).get("get")
    if not get_url:
        return {"ok": False, "reason": "Replicateの応答にポーリングURLが無い"}

    final = _replicate_poll_until_done(get_url, token)
    status = final.get("status")
    predict_time = (final.get("metrics") or {}).get("predict_time")
    if isinstance(predict_time, (int, float)):
        actual_cost = predict_time * REPLICATE_HARDWARE_USD_PER_SEC
    else:
        actual_cost = REPLICATE_ESTIMATED_COST_USD

    cycle_budget["spent_usd"] = cycle_budget.get("spent_usd", 0.0) + actual_cost
    budget["spent_this_month_usd"] = budget.get("spent_this_month_usd", 0.0) + actual_cost
    budget.setdefault("entries", []).append(
        {"at": now_iso(), "status": status, "cost_usd": actual_cost, "predict_time_sec": predict_time}
    )
    save_budget(budget_path, budget)

    if status != "succeeded":
        return {"ok": False, "reason": f"Replicate実行が{status}", "cost_usd": actual_cost}
    return {"ok": True, "output": final.get("output"), "cost_usd": actual_cost, "predict_time_sec": predict_time}


def dispatch(
    req: dict,
    *,
    repo_root: Path,
    work_dir: Path,
    fetched_list: list[dict],
    budget_path: Path,
    cycle_budget: dict,
) -> dict:
    req_type = req.get("type")
    if req_type == "drive_write":
        return handle_drive_write(req, repo_root)
    if req_type == "hf_fetch":
        return handle_hf_fetch(req, fetched_list, work_dir)
    if req_type == "gpu_generate":
        return handle_gpu_generate(req, budget_path, cycle_budget)
    return {"ok": False, "reason": f"未知のリクエスト種別: {req_type!r}"}


# --- I/Oヘルパー ---


def load_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def save_json_list(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_outbox_requests(outbox_dir: Path) -> list[tuple[str, dict]]:
    if not outbox_dir.exists():
        return []
    entries = []
    for path in sorted(outbox_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {"type": "invalid", "error": "JSONオブジェクトではない"}
        except (OSError, json.JSONDecodeError) as e:
            data = {"type": "invalid", "error": str(e)}
        entries.append((path.name, data))
    return entries


def process_outbox(
    outbox_dir: Path,
    repo_root: Path,
    work_dir: Path,
    fetched_models_path: Path,
    log_path: Path,
    budget_path: Path,
) -> list[dict]:
    fetched_list = load_json_list(fetched_models_path)
    cycle_budget: dict = {"spent_usd": 0.0}  # 1回のexecutor実行=1周ぶんのReplicate予算
    results = []
    for name, req in load_outbox_requests(outbox_dir):
        result = dispatch(
            req,
            repo_root=repo_root,
            work_dir=work_dir,
            fetched_list=fetched_list,
            budget_path=budget_path,
            cycle_budget=cycle_budget,
        )
        record = {"request_file": name, "type": req.get("type"), "at": now_iso(), **result}
        results.append(record)
        append_jsonl(log_path, record)
    save_json_list(fetched_models_path, fetched_list)
    return results


def main() -> None:
    results = process_outbox(
        OUTBOX_DIR,
        REPO_ROOT,
        WORK_ROOT,
        STATE_DIR / FETCHED_MODELS_JSON,
        STATE_DIR / EXECUTOR_LOG_JSONL,
        STATE_DIR / BUDGET_JSON,
    )
    print(json.dumps({"processed": len(results), "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
