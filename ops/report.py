"""Drive `PDCA/ダッシュボード.md`（実体は `work/state/ダッシュボード.md`）を毎周更新し、
1日1回（JST21時以降の最初の周）だけGitHub Issue「PDCA日報」に5行以内でコメントする。

事業の詳細（商品名・金額・個別のモデル名等）は日報コメントに書かない。段階・件数・
本人待ち有無と、詳細への案内（Driveのダッシュボード）だけ。詳細はダッシュボード
（Drive上・非公開）に書く。

意図的な簡略化: 「1日1回」の判定は `work/state/notes/last_daily_report_date.txt` に
書いたJST日付との比較のみ（同日に複数回21時を跨ぐケースは無い前提）。Issueが本人に
よって閉じられた場合、次に見つからなければ新規作成する（履歴は分断されるが、本人が
明示的に閉じた意思を優先する簡略化）。
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ops.paths import DASHBOARD_MD, GUARD_LOG_MD, LOG_MD, NEEDS_HUMAN_MD, NOTES_DIR, STATE_DIR

ISSUE_TITLE = "PDCA日報"
DAILY_REPORT_HOUR_JST = 21
LAST_DAILY_REPORT_MARKER = "last_daily_report_date.txt"


def _read_text(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8")


def _tail_lines(text: str, n: int) -> str:
    lines = [line for line in text.splitlines()]
    if not lines:
        return "(なし)"
    return "\n".join(lines[-n:])


def needs_human_is_active(text: str) -> bool:
    """NEEDS_HUMAN.mdが「本人待ちが実際にある」状態かを判定する（純粋関数）。"""
    meaningful = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("本人にしかできないことだけ"):
            continue
        meaningful.append(stripped)
    if not meaningful:
        return False
    return not (len(meaningful) == 1 and meaningful[0] == "なし")


def build_dashboard_markdown(kpi: dict, log_text: str, needs_human_text: str, guard_log_text: str) -> str:
    generated_at = kpi.get("generated_at", "")
    stage = kpi.get("stage", "?")
    counts = kpi.get("counts", {})

    lines = [
        "# ComfyUIスタジオ PDCA ダッシュボード",
        "",
        f"更新: {generated_at}",
        "",
        f"## 段階: {stage}",
        "",
        "| 段階 | 到達 | 根拠 |",
        "|---|---|---|",
    ]
    for name, info in kpi.get("stages", {}).items():
        mark = "○" if info.get("achieved") else "-"
        lines.append(f"| {name} | {mark} | {info.get('evidence', '')} |")

    lines += [
        "",
        "## 数値",
        "",
        "```json",
        json.dumps(counts, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 直近LOG",
        "",
        "```",
        _tail_lines(log_text, 20),
        "```",
        "",
        "## 本人待ち（NEEDS_HUMAN）",
        "",
        needs_human_text.strip() or "なし",
    ]

    if guard_log_text.strip():
        lines += ["", "## 直近のガード違反", "", "```", _tail_lines(guard_log_text, 20), "```"]

    lines.append("")
    return "\n".join(lines)


def build_daily_report_body(kpi: dict, needs_human_text: str) -> str:
    """5行以内・事業の詳細は書かない日報コメント本文。"""
    stage = kpi.get("stage", "?")
    counts = kpi.get("counts", {})
    has_human = "あり" if needs_human_is_active(needs_human_text) else "なし"
    lines = [
        f"段階: {stage}",
        (
            f"件数: 商用可モデル{counts.get('commercial_models', 0)}件"
            f"・生成{counts.get('generated_images', 0)}枚"
            f"・品質合格{counts.get('quality_pass_samples', 0)}枚"
        ),
        f"本人待ち: {has_human}",
        "詳細: Driveのダッシュボード（PDCA/ダッシュボード.md）参照",
    ]
    return "\n".join(lines)


def is_daily_report_due(notes_dir: Path, now_jst: datetime) -> bool:
    if now_jst.hour < DAILY_REPORT_HOUR_JST:
        return False
    marker_path = notes_dir / LAST_DAILY_REPORT_MARKER
    today_str = now_jst.strftime("%Y-%m-%d")
    if marker_path.exists() and marker_path.read_text(encoding="utf-8").strip() == today_str:
        return False
    return True


def mark_daily_report_done(notes_dir: Path, now_jst: datetime) -> None:
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / LAST_DAILY_REPORT_MARKER).write_text(now_jst.strftime("%Y-%m-%d"), encoding="utf-8")


# --- ghコマンド呼び出し（薄いラッパー） ---


def _run_gh(args: list[str]) -> dict:
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}


def find_or_create_daily_issue() -> str | None:
    list_result = _run_gh(
        ["issue", "list", "--search", ISSUE_TITLE, "--state", "open", "--json", "number,title"]
    )
    if list_result["ok"]:
        try:
            issues = json.loads(list_result["stdout"])
        except json.JSONDecodeError:
            issues = []
        for issue in issues:
            if issue.get("title") == ISSUE_TITLE:
                return str(issue["number"])

    create_result = _run_gh(
        [
            "issue",
            "create",
            "--title",
            ISSUE_TITLE,
            "--body",
            f"{ISSUE_TITLE}用スレッド。1日1回（JST21時以降の最初の周）ここに5行以内で自動コメントする。",
        ]
    )
    if not create_result["ok"]:
        return None
    output = create_result["stdout"].strip()
    if not output:
        return None
    url = output.splitlines()[-1]
    return url.rsplit("/", 1)[-1] if url else None


def post_daily_report(body: str) -> bool:
    issue_number = find_or_create_daily_issue()
    if not issue_number:
        return False
    result = _run_gh(["issue", "comment", issue_number, "--body", body])
    return result["ok"]


def run(
    state_dir: Path, notes_dir: Path, *, now_jst: datetime | None = None, post_daily: bool = True
) -> dict:
    """ダッシュボードを書き、`post_daily=True` のときだけ日報投稿の要否も見て投稿する。

    ワークフロー側では2回呼ぶ想定: (1) executor直後に `post_daily=False` でダッシュボードを
    Drive同期対象(work/state/)に確実に反映し、(2) PR/mergeまで終わった最後に
    `post_daily=True`（既定）で日報投稿を行う。日報の失敗が状態のDrive永続化を
    ブロックしないようにするための順序（「状態を戻す」を先、「報告」を後）。
    """
    kpi_path = state_dir / "KPI.json"
    kpi = json.loads(kpi_path.read_text(encoding="utf-8")) if kpi_path.exists() else {}
    log_text = _read_text(state_dir / LOG_MD)
    needs_human_text = _read_text(state_dir / NEEDS_HUMAN_MD)
    guard_log_text = _read_text(state_dir / GUARD_LOG_MD)

    dashboard = build_dashboard_markdown(kpi, log_text, needs_human_text, guard_log_text)
    (state_dir / DASHBOARD_MD).write_text(dashboard, encoding="utf-8")

    if not post_daily:
        return {"dashboard_written": True, "daily_report_due": None, "daily_posted": False}

    now_jst = now_jst or datetime.now(ZoneInfo("Asia/Tokyo"))
    was_due = is_daily_report_due(notes_dir, now_jst)
    daily_posted = False
    if was_due:
        body = build_daily_report_body(kpi, needs_human_text)
        daily_posted = post_daily_report(body)
        if daily_posted:
            mark_daily_report_done(notes_dir, now_jst)

    return {"dashboard_written": True, "daily_report_due": was_due, "daily_posted": daily_posted}


def main() -> None:
    import sys

    post_daily = "--dashboard-only" not in sys.argv[1:]
    result = run(STATE_DIR, NOTES_DIR, post_daily=post_daily)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
