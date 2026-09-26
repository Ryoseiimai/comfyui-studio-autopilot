"""Claude実行後・決定論で強制するガード。

Claudeの自己申告や善意を信用せず、機械的に以下を強制する:
1. 保護パス（`.github/**`・`ops/guard*`・`ops/executor*`・`ops/report*`・
   `GUARDRAILS.md`）への変更 → 取り消す（git checkout / 削除）。
2. 差分および `work/` 配下にシークレットらしき文字列
   （`sk-ant-`・`ya29.`・`refresh_token`・`-----BEGIN ...-----`）が含まれる → 取り消す。
3. 変更後のファイルサイズが上限を超える → 取り消す。

違反はすべて `work/state/notes/guard_last_report.json`（毎回上書き）と
`work/state/GUARD_LOG.md`（違反があった時だけ追記）に記録する。

このスクリプト自身は常に exit 0 で終わる（違反は「取り消す」ことで対処し、
ジョブ全体を失敗させない。ジョブが失敗すると状態がDriveに戻らず、次の周回が
古い状態のまま動いてしまうため）。

意図的な簡略化: シークレット検出は固定の正規表現リストのみ（エントロピー計算などの
高度な検知は無い）。新しい形式の鍵が漏れても検知できない既知の限界があり、
本格対応するときは detect-secrets 等の専用ツールへの置き換えが入口。
保護対象は `.github/**`・`ops/guard*`・`ops/executor*`・`ops/report*`・
`GUARDRAILS.md` のみで、`tests/` 配下（例: `tests/test_guard.py` 自身）は対象外
（spec通りの範囲）。Claudeがテストを書き換えて弱体化させることの防止は未対応。
"""
from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ops.paths import GUARD_LOG_MD, REPO_ROOT, WORK_ROOT

PROTECTED_PATTERNS = (
    ".github/*",
    "ops/guard.py",
    "ops/guard_*",
    "ops/executor.py",
    "ops/executor_*",
    "ops/report.py",
    "ops/report_*",
    "GUARDRAILS.md",
)

# (パターン名, 正規表現) — 名前はレポートに残す用
SECRET_PATTERNS = (
    ("sk-ant-", re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}")),
    ("ya29.", re.compile(r"ya29\.[A-Za-z0-9_\-]{10,}")),
    ("refresh_token", re.compile(r"refresh_token")),
    ("-----BEGIN", re.compile(r"-----BEGIN [A-Z ]+-----")),
)

MAX_CHANGED_FILE_BYTES = 2 * 1024 * 1024  # 2MB（コードリポジトリなので十分大きい）
SECRET_SCAN_READ_LIMIT = 5 * 1024 * 1024  # 秘密スキャンで読む先頭バイト数の上限

# work/ 配下のシークレットスキャンで開かない拡張子（バイナリ・巨大想定）
BINARY_SKIP_EXTS = {
    ".safetensors", ".gguf", ".bin", ".pt", ".ckpt", ".onnx",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".zip",
}


def is_protected_path(rel_path: str) -> bool:
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in PROTECTED_PATTERNS)


def find_secret_matches(text: str) -> list[str]:
    """textに含まれるシークレットらしきパターン名を重複なしで返す（純粋関数）。"""
    hits = []
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            hits.append(name)
    return hits


def _read_head_text(path: Path, limit: int = SECRET_SCAN_READ_LIMIT) -> str:
    try:
        with path.open("rb") as f:
            raw = f.read(limit)
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return ""


def git_status_entries(repo_root: Path) -> list[tuple[str, str]]:
    """`git status --porcelain=v1` を解析して (status, rel_path) のリストを返す。"""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain=v1"],
        capture_output=True,
        text=True,
    )
    entries = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        status, rel_path = line[:2], line[3:]
        # rename( "R  old -> new" )は素のgit statusでは通常出ないが、念のため新パスを使う
        if " -> " in rel_path:
            rel_path = rel_path.split(" -> ", 1)[1]
        entries.append((status, rel_path))
    return entries


def check_file_violations(repo_root: Path, rel_path: str) -> list[str]:
    """1ファイルの違反理由リストを返す（無ければ空）。"""
    reasons: list[str] = []
    if is_protected_path(rel_path):
        reasons.append("protected_path")

    abs_path = repo_root / rel_path
    if abs_path.exists() and abs_path.is_file():
        size = abs_path.stat().st_size
        if size > MAX_CHANGED_FILE_BYTES:
            reasons.append(f"file_too_large:{size}")
        text = _read_head_text(abs_path)
        secret_hits = find_secret_matches(text)
        if secret_hits:
            reasons.append(f"secret_pattern:{','.join(secret_hits)}")
    return reasons


def revert_entry(repo_root: Path, status: str, rel_path: str) -> None:
    """1ファイルの変更を取り消す（未追跡なら削除、追跡済みならHEADへ復元）。"""
    abs_path = repo_root / rel_path
    if status.strip() == "??":
        if abs_path.exists():
            abs_path.unlink()
        return
    subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "--", rel_path],
        capture_output=True,
        text=True,
    )
    # checkout --ではHEADに存在しない新規追跡ファイル(git add済み等)は復元できず残ることが
    # あるため、まだ残っていれば削除で確実に取り消す。
    if abs_path.exists():
        check = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", rel_path],
            capture_output=True,
            text=True,
        )
        if check.returncode != 0:
            abs_path.unlink()


def check_repo_changes(repo_root: Path) -> dict:
    violations = []
    reverted = []
    allowed_changed = []
    for status, rel_path in git_status_entries(repo_root):
        reasons = check_file_violations(repo_root, rel_path)
        if reasons:
            revert_entry(repo_root, status, rel_path)
            violations.append({"path": rel_path, "status": status, "reasons": reasons})
            reverted.append(rel_path)
        else:
            allowed_changed.append(rel_path)
    return {
        "violations": violations,
        "reverted": reverted,
        "allowed_changed": allowed_changed,
    }


# guard自身の出力（state/notes/guard_last_report.json・state/GUARD_LOG.md）はスキャン対象外。
# これらは違反の「理由」としてパターン名（例: "secret_pattern:refresh_token"）を診断文字列
# として埋め込むため、除外しないと次回実行時に自分の記録を再検知して隔離（削除）してしまい、
# 「理由を残す」という目的そのものが自己破壊するバグになる（実際に発生し確認済み・要修正点）。
GUARD_OWN_RELATIVE_PATHS = {"state/notes/guard_last_report.json", f"state/{GUARD_LOG_MD}"}


def scan_work_dir_secrets(work_root: Path) -> list[dict]:
    """work/ 配下を再帰的に見てシークレットらしきファイルを隔離（削除）する。"""
    quarantined = []
    if not work_root.exists():
        return quarantined
    for path in sorted(work_root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(work_root))
        if rel in GUARD_OWN_RELATIVE_PATHS:
            continue
        if path.suffix.lower() in BINARY_SKIP_EXTS:
            continue
        text = _read_head_text(path)
        hits = find_secret_matches(text)
        if hits:
            quarantined.append({"path": f"work/{rel}", "reasons": [f"secret_pattern:{','.join(hits)}"]})
            path.unlink()
    return quarantined


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_report(report: dict, work_root: Path) -> None:
    """レポートを `work_root` 配下に書く（`ops.paths` のグローバル定数には依存しない。
    テストで別の work_root を渡しても正しい場所に書かれるようにするため）。"""
    state_dir = work_root / "state"
    notes_dir = state_dir / "notes"

    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "guard_last_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    total_violations = len(report["repo_violations"]) + len(report["work_secret_quarantined"])
    if total_violations == 0:
        return

    state_dir.mkdir(parents=True, exist_ok=True)
    log_path = state_dir / GUARD_LOG_MD
    if not log_path.exists():
        log_path.write_text("# GUARD_LOG\n\nガード違反があった周だけ追記される。\n\n", encoding="utf-8")

    lines = [f"## {report['checked_at']}"]
    for v in report["repo_violations"]:
        lines.append(f"- repo取り消し: `{v['path']}` ({', '.join(v['reasons'])})")
    for v in report["work_secret_quarantined"]:
        lines.append(f"- work隔離: `{v['path']}` ({', '.join(v['reasons'])})")
    lines.append("")
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def run(repo_root: Path, work_root: Path) -> dict:
    repo_result = check_repo_changes(repo_root)
    work_quarantined = scan_work_dir_secrets(work_root)
    report = {
        "checked_at": _now_iso(),
        "repo_violations": repo_result["violations"],
        "repo_reverted": repo_result["reverted"],
        "repo_allowed_changed": repo_result["allowed_changed"],
        "work_secret_quarantined": work_quarantined,
        "ok": True,
    }
    write_report(report, work_root)
    return report


def main() -> None:
    report = run(REPO_ROOT, WORK_ROOT)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
