from datetime import datetime, timedelta, timezone
import json

import pytest

from ops import gate

NOW = datetime(2026, 9, 27, 0, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("elapsed,skipped", [(4.99, True), (5, False), (6, False)])
def test_success_cooldown(elapsed, skipped):
    kpi = {"last_agent_success_at": (NOW - timedelta(hours=elapsed)).isoformat()}
    assert bool(gate.decide(kpi, "schedule", NOW)) is skipped


def test_manual_always_runs():
    kpi = {"last_agent_success_at": NOW.isoformat(), "last_failure_reason": gate.LIMIT_REASON,
           "limit_reset_at": (NOW + timedelta(hours=1)).isoformat()}
    assert gate.decide(kpi, "workflow_dispatch", NOW) == ""


def test_limit_wait_survives_skip_and_expires_at_boundary():
    kpi = {"last_agent_status": "skip", "last_failure_reason": gate.LIMIT_REASON,
           "limit_reset_at": (NOW + timedelta(hours=1)).isoformat()}
    assert gate.decide(kpi, "schedule", NOW) == "skip: 枠解除待ち（2026-09-27T01:30:00+00:00）"
    assert gate.decide(kpi, "schedule", NOW + timedelta(hours=1)) == ""
    kpi["last_failure_reason"] = "Claude実行失敗"
    assert gate.decide(kpi, "schedule", NOW) == ""


@pytest.mark.parametrize("kpi", [{}, {"last_agent_success_at": "bad", "limit_reset_at": "bad"},
                                    {"last_agent_success_at": "2026-09-27T00:30:00"}])
def test_old_or_invalid_timestamps(kpi):
    assert gate.decide(kpi, "schedule", NOW) == ""


def test_run_appends_one_line(tmp_path):
    (tmp_path / "KPI.json").write_text(json.dumps({"last_agent_success_at": NOW.isoformat()}))
    log = tmp_path / "LOG.md"
    log.write_text("previous\n")
    assert gate.run(tmp_path, "schedule", now=NOW)["skip"] is True
    assert log.read_text().splitlines() == ["previous", "- 2026-09-27T00:30:00+00:00 skip: 前回成功から5h未満"]
    gate.run(tmp_path, "workflow_dispatch", now=NOW)
    assert len(log.read_text().splitlines()) == 2


@pytest.mark.parametrize("message,failed_at,expected", [
    ("You've hit your session limit · resets 1:30am (UTC)", NOW, "2026-09-27T01:30:00+00:00"),
    ("resets 12:30pm (Asia/Tokyo)", NOW, "2026-09-27T03:30:00+00:00"),
    ("resets 12:30am (UTC)", NOW, "2026-09-28T00:30:00+00:00"),
    ("resets 1:30AM (UTC)", NOW + timedelta(hours=2), "2026-09-28T01:30:00+00:00"),
    ("resets 12:30pm (Asia/Tokyo)", NOW + timedelta(hours=4), "2026-09-28T03:30:00+00:00"),
    ("resets 1:30am (America/New_York)", datetime(2026, 11, 1, 5, 45, tzinfo=timezone.utc), "2026-11-01T06:30:00+00:00"),
    ("resets 2:30am (America/New_York)", datetime(2026, 3, 8, 6, tzinfo=timezone.utc), "2026-03-09T06:30:00+00:00"),
])
def test_parse_reset(message, failed_at, expected):
    assert gate.parse_limit_reset(message, failed_at) == expected


@pytest.mark.parametrize("message", ["overloaded", "resets 13:30pm (UTC)", "resets 1:60am (UTC)",
                                     "resets 1:30am (Unknown/Zone)"])
def test_invalid_reset(message):
    assert gate.parse_limit_reset(message, NOW) == ""
