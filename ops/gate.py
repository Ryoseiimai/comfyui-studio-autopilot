"""Scheduled Claude cooldown gate (standard library only)."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ops.paths import KPI_JSON, LOG_MD, STATE_DIR

AGENT_DEFAULTS = {
    "agent_success_count": 0,
    "agent_fail_count": 0,
    "last_agent_status": "",
    "last_agent_success_at": "",
    "last_failure_reason": "",
    "limit_reset_at": "",
    "last_failure_at": "",
}
LIMIT_REASON = "利用枠切れ"
# 前回成功からのクールダウンと、解除時刻が読めない利用枠切れの様子見に共用。
COOLDOWN = timedelta(hours=5)


def parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def is_limit_failure(text: str) -> bool:
    return bool(re.search(r"(?:hit|reached|exceeded).*?\blimit\b|\busage limit\b|\brate limit\b|利用枠切れ", text, re.I))


def parse_limit_reset(text: str, failed_at: datetime) -> str:
    """Return the first matching local wall time strictly after the failure, in UTC."""
    match = re.search(r"\bresets\s+(\d{1,2}):(\d{2})\s*(am|pm)\s*\(([^)]+)\)", text, re.I)
    if not match:
        return ""
    hour, minute = int(match[1]), int(match[2])
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        return ""
    try:
        zone = ZoneInfo(match[4].strip())
    except (ZoneInfoNotFoundError, ValueError):
        return ""
    hour = hour % 12 + (12 if match[3].lower() == "pm" else 0)
    failed_at = failed_at.astimezone(timezone.utc)
    local = failed_at.astimezone(zone)
    # Check both folds for DST fallback; discard nonexistent spring-forward times.
    for offset in range(3):
        day = local.date() + timedelta(days=offset)
        candidates = []
        for fold in (0, 1):
            wall = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone, fold=fold)
            utc = wall.astimezone(timezone.utc)
            if utc > failed_at and utc.astimezone(zone).replace(tzinfo=None) == wall.replace(tzinfo=None):
                candidates.append(utc)
        if candidates:
            return min(candidates).isoformat(timespec="seconds")
    return ""


def decide(kpi: dict, event_name: str, now: datetime) -> str:
    if event_name != "schedule":
        return ""
    last_success = parse_iso(kpi.get("last_agent_success_at", ""))
    if last_success and now - last_success < COOLDOWN:
        return "skip: 前回成功から5h未満"
    if is_limit_failure(kpi.get("last_failure_reason", "")):
        reset = parse_iso(kpi.get("limit_reset_at", ""))
        if reset:
            if now < reset:
                return f"skip: 枠解除待ち（{kpi['limit_reset_at']}）"
        else:
            # 解除時刻の文言を読めなかった場合も、直前の利用枠切れから5hは
            # 様子見する（読めないまま3時間おきに叩き続けて枠をさらに消費しない）。
            last_failure = parse_iso(kpi.get("last_failure_at", ""))
            if last_failure and now - last_failure < COOLDOWN:
                return "skip: 枠解除待ち（解除時刻不明・様子見）"
    return ""


def run(state_dir: Path, event_name: str, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    path = state_dir / KPI_JSON
    kpi = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    reason = decide(kpi, event_name, now)
    if reason:
        with (state_dir / LOG_MD).open("a", encoding="utf-8") as stream:
            stream.write(f"- {now.isoformat(timespec='seconds')} {reason}\n")
    return {"skip": bool(reason), "reason": reason}


def main() -> None:
    result = run(STATE_DIR, os.environ.get("GITHUB_EVENT_NAME", ""))
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        stream.write(f"skip={str(result['skip']).lower()}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
