"""段階（S0〜S6）と数値をJSONで出す（決定論・証拠ファイルの実在で判定する）。

Claudeの自己申告（LOG.mdに「できた」と書くだけ）ではKPIを上げない。必ず対応する
証拠ファイルの実在・件数で判定する。これにより、エージェントが数字を盛っても
KPI.jsonは動かない（信頼性の担保）。

段階の定義（`work/state/GOAL.md` と対応）:
- S0 エンジンが無人で回る … Claudeの成功回数（agent_success_count）>= 1
- S1 商用可モデルが倉庫にそろう … `model_license_survey.json`の商用可/有料ライセンスで可
  件数 + `fetched_models.json`の件数（executorが商用可否ゲート済みなので全件加算可） >= 1
- S2 クラウドで1枚生成できる … `executor_log.jsonl`のgpu_generate成功 >= 1
- S3 品質基準合格のサンプルN枚 … `quality_samples.json`のpassed件数 >= 10
- S4 企画・出品下書き … `product_drafts.json`の件数 >= 3
- S5 本人の販売者登録・出品 … `human_flags.json`の`seller_registered_and_listed`
- S6 初売上 … `human_flags.json`の`first_sale`

S5・S6は本人にしかできないため、`work/state/human_flags.json` に人手で
`{"seller_registered_and_listed": true}` 等を書くまでFalseのまま。

意図的な簡略化: 各しきい値（MIN_COMMERCIAL_MODELS等）は初期の仮値。プロジェクトが
進んだら司令塔・本人がこのファイル冒頭の定数を実情に合わせて上げるのが本格対応の入口。
月次カウント等の時刻はUTC基準（`ops/executor.py`と同じ簡略化）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ops.gate import AGENT_DEFAULTS, LIMIT_REASON, is_limit_failure, parse_iso, parse_limit_reset

from ops.paths import (
    EXECUTOR_LOG_JSONL,
    FETCHED_MODELS_JSON,
    KPI_JSON,
    NOTES_DIR,
    STATE_DIR,
    WORK_ROOT,
)

MIN_COMMERCIAL_MODELS = 1
MIN_QUALITY_SAMPLES = 10
MIN_PRODUCT_DRAFTS = 3

STAGE_ORDER = ("S0", "S1", "S2", "S3", "S4", "S5", "S6")

MODEL_LICENSE_SURVEY_JSON = "model_license_survey.json"
QUALITY_SAMPLES_JSON = "quality_samples.json"
PRODUCT_DRAFTS_JSON = "product_drafts.json"
HUMAN_FLAGS_JSON = "human_flags.json"
CYCLE_COUNT_JSON = "cycle_count.json"

COMMERCIAL_CATEGORIES = {"商用可", "有料ライセンスで可"}


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def increment_cycle_count(notes_dir: Path) -> int:
    """このスクリプトが起動した回数（失敗・skipを含む総実行数）を1増やして返す。"""
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = notes_dir / CYCLE_COUNT_JSON
    data = _load_json(path, {"count": 0})
    new_count = int(data.get("count", 0)) + 1
    path.write_text(json.dumps({"count": new_count}, ensure_ascii=False) + "\n", encoding="utf-8")
    return new_count


def gather_evidence(state_dir: Path, notes_dir: Path) -> dict:
    """証拠ファイルを読んで生の数値・件数を集める（I/Oあり）。"""
    survey = _load_json(state_dir / MODEL_LICENSE_SURVEY_JSON, [])
    survey_commercial = [
        item for item in survey if isinstance(item, dict) and item.get("category") in COMMERCIAL_CATEGORIES
    ]
    fetched = _load_json(state_dir / FETCHED_MODELS_JSON, [])
    executor_log = _load_jsonl(state_dir / EXECUTOR_LOG_JSONL)
    gpu_success = [
        r for r in executor_log if r.get("type") == "gpu_generate" and r.get("ok") is True
    ]
    quality_samples = _load_json(state_dir / QUALITY_SAMPLES_JSON, [])
    quality_pass = [s for s in quality_samples if isinstance(s, dict) and s.get("passed") is True]
    product_drafts = _load_json(state_dir / PRODUCT_DRAFTS_JSON, [])
    human_flags = _load_json(state_dir / HUMAN_FLAGS_JSON, {})
    cycle_data = _load_json(notes_dir / CYCLE_COUNT_JSON, {"count": 0})

    return {
        "cycle_count": int(cycle_data.get("count", 0)),
        "commercial_models": len(survey_commercial) + (len(fetched) if isinstance(fetched, list) else 0),
        "generated_images": len(gpu_success),
        "quality_pass_samples": len(quality_pass),
        "product_drafts": len(product_drafts) if isinstance(product_drafts, list) else 0,
        "seller_registered_and_listed": bool(human_flags.get("seller_registered_and_listed", False)),
        "first_sale": bool(human_flags.get("first_sale", False)),
    }


def evaluate_stage(counts: dict) -> dict:
    """集めた数値から各段階のachieved/evidenceと、到達している最高段階を返す（純粋関数）。"""
    checks = {
        "S0": (counts.get("agent_success_count", 0) >= 1,
               f"agent_success_count={counts.get('agent_success_count', 0)}（要1以上）"),
        "S1": (
            counts["commercial_models"] >= MIN_COMMERCIAL_MODELS,
            f"commercial_models={counts['commercial_models']}（要{MIN_COMMERCIAL_MODELS}以上）",
        ),
        "S2": (
            counts["generated_images"] >= 1,
            f"generated_images={counts['generated_images']}（要1以上）",
        ),
        "S3": (
            counts["quality_pass_samples"] >= MIN_QUALITY_SAMPLES,
            f"quality_pass_samples={counts['quality_pass_samples']}（要{MIN_QUALITY_SAMPLES}以上）",
        ),
        "S4": (
            counts["product_drafts"] >= MIN_PRODUCT_DRAFTS,
            f"product_drafts={counts['product_drafts']}（要{MIN_PRODUCT_DRAFTS}以上）",
        ),
        "S5": (
            counts["seller_registered_and_listed"],
            "human_flags.json の seller_registered_and_listed（本人操作待ち）",
        ),
        "S6": (counts["first_sale"], "human_flags.json の first_sale（本人操作待ち）"),
    }

    stages = {name: {"achieved": achieved, "evidence": evidence} for name, (achieved, evidence) in checks.items()}

    stage = "S0" if not checks["S0"][0] else "S0"
    for name in STAGE_ORDER:
        if checks[name][0]:
            stage = name
        else:
            break

    return {"stage": stage, "stages": stages}


def compute_kpi(
    state_dir: Path, notes_dir: Path, *, increment: bool = True,
    agent_status: str | None = None, agent_output: str = "",
    now: datetime | None = None,
) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    previous = _load_json(state_dir / KPI_JSON, {})
    agent = {key: previous.get(key, default) for key, default in AGENT_DEFAULTS.items()}
    if agent_status is not None:
        if agent_status not in ("success", "failure", "skip"):
            raise ValueError(f"Unknown agent status: {agent_status}")
        agent["last_agent_status"] = agent_status
        if agent_status == "success":
            agent["agent_success_count"] += 1
            agent["last_agent_success_at"] = now.isoformat(timespec="seconds")
            agent["last_failure_reason"] = ""
            agent["limit_reset_at"] = ""
        elif agent_status == "failure":
            agent["agent_fail_count"] += 1
            limited = is_limit_failure(agent_output)
            # Persist only a fixed category, never arbitrary output containing secrets.
            agent["last_failure_reason"] = LIMIT_REASON if limited else "Claude実行失敗"
            agent["limit_reset_at"] = parse_limit_reset(agent_output, now) if limited else ""

    if increment:
        increment_cycle_count(notes_dir)
    counts = gather_evidence(state_dir, notes_dir)
    counts["agent_success_count"] = agent["agent_success_count"]
    counts["agent_fail_count"] = agent["agent_fail_count"]
    result = evaluate_stage(counts)
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        **agent,
        "stage": result["stage"],
        "stages": result["stages"],
        "counts": counts,
    }


def main() -> None:
    outcome = os.environ.get("AGENT_OUTCOME", "skipped")
    status = {"success": "success", "failure": "failure"}.get(outcome, "skip")
    output_path = WORK_ROOT / "claude_out.txt"
    output = output_path.read_text(encoding="utf-8", errors="replace") if output_path.exists() else ""
    kpi = compute_kpi(
        STATE_DIR, NOTES_DIR, agent_status=status, agent_output=output,
        now=parse_iso(os.environ.get("AGENT_FINISHED_AT", "")),
    )
    (STATE_DIR / KPI_JSON).write_text(
        json.dumps(kpi, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"stage": kpi["stage"], "counts": kpi["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
