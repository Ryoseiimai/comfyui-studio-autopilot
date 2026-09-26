"""`dry_run=1` のときにClaudeの代わりに動く決定論スタブ。

Claudeを呼ばず、決まった計画とoutboxを書くだけにして、配管全体
（bootstrap→(stub)→guard→executor→kpi→report→Drive同期）を無料で試せるようにする。

意図的な簡略化: 実際のPDCA判断（BACKLOGから何を選ぶか等）はしない。固定の
gpu_generateリクエスト1件だけをoutboxに置く（GPU_PROVIDERSが空なので必ず
「GPU未設定」でスキップされ、副作用が一切無い）。hf_fetch/drive_writeは
実ネットワーク・実Drive書き込みを伴うため、dry_runでは意図的に書かない。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ops.paths import LOG_MD, OUTBOX_DIR, STATE_DIR

STUB_OUTBOX_REQUEST = {
    "type": "gpu_generate",
    "workflow": {"note": "dry_run配管確認用のダミーワークフロー（実行はGPU未設定でスキップされる）"},
    "params": {"dry_run": True},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_stub_outbox(outbox_dir: Path) -> Path:
    outbox_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_dir / "0001_dry_run_gpu_generate.json"
    path.write_text(json.dumps(STUB_OUTBOX_REQUEST, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def append_log_entry(state_dir: Path) -> None:
    log_path = state_dir / LOG_MD
    entry = f"- {now_iso()} [dry_run] stub_agentで配管確認（gpu_generateを1件outboxに投入・実処理なし）\n"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(entry)


def run(state_dir: Path, outbox_dir: Path) -> dict:
    outbox_path = write_stub_outbox(outbox_dir)
    append_log_entry(state_dir)
    summary = {
        "cycle_at": now_iso(),
        "picked": ["dry_run配管確認"],
        "did": f"outboxに{outbox_path.name}を投入しLOGへ追記した",
        "needs_human": False,
    }
    return summary


def main() -> None:
    summary = run(STATE_DIR, OUTBOX_DIR)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
