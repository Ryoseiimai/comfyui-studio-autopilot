"""ops.kpi の単体テスト（段階S0〜S6の判定・証拠ファイルの集計）。"""
from __future__ import annotations

import json

from ops import kpi


def test_increment_cycle_count(tmp_path):
    notes_dir = tmp_path / "notes"
    assert kpi.increment_cycle_count(notes_dir) == 1
    assert kpi.increment_cycle_count(notes_dir) == 2
    assert kpi.increment_cycle_count(notes_dir) == 3


def test_gather_evidence_defaults_to_zero_when_nothing_exists(tmp_path):
    state_dir = tmp_path / "state"
    notes_dir = tmp_path / "notes"
    state_dir.mkdir()
    notes_dir.mkdir()

    evidence = kpi.gather_evidence(state_dir, notes_dir)

    assert evidence["cycle_count"] == 0
    assert evidence["commercial_models"] == 0
    assert evidence["generated_images"] == 0
    assert evidence["quality_pass_samples"] == 0
    assert evidence["product_drafts"] == 0
    assert evidence["seller_registered_and_listed"] is False
    assert evidence["first_sale"] is False


def test_gather_evidence_counts_commercial_models_from_survey_and_fetched(tmp_path):
    state_dir = tmp_path / "state"
    notes_dir = tmp_path / "notes"
    state_dir.mkdir()
    notes_dir.mkdir()

    (state_dir / kpi.MODEL_LICENSE_SURVEY_JSON).write_text(
        json.dumps(
            [
                {"file": "a.safetensors", "category": "商用可"},
                {"file": "b.safetensors", "category": "要確認"},
                {"file": "c.safetensors", "category": "有料ライセンスで可"},
            ]
        ),
        encoding="utf-8",
    )
    (state_dir / "fetched_models.json").write_text(
        json.dumps([{"file": "d.safetensors"}]), encoding="utf-8"
    )

    evidence = kpi.gather_evidence(state_dir, notes_dir)
    # a, c(survey) + d(fetched) = 3件。bは要確認なので数えない。
    assert evidence["commercial_models"] == 3


def test_gather_evidence_counts_gpu_generate_successes(tmp_path):
    state_dir = tmp_path / "state"
    notes_dir = tmp_path / "notes"
    state_dir.mkdir()
    notes_dir.mkdir()

    log_lines = [
        json.dumps({"type": "gpu_generate", "ok": True}),
        json.dumps({"type": "gpu_generate", "ok": False}),
        json.dumps({"type": "hf_fetch", "ok": True}),
    ]
    (state_dir / "executor_log.jsonl").write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    evidence = kpi.gather_evidence(state_dir, notes_dir)
    assert evidence["generated_images"] == 1


def test_gather_evidence_reads_human_flags(tmp_path):
    state_dir = tmp_path / "state"
    notes_dir = tmp_path / "notes"
    state_dir.mkdir()
    notes_dir.mkdir()

    (state_dir / "human_flags.json").write_text(
        json.dumps({"seller_registered_and_listed": True, "first_sale": False}), encoding="utf-8"
    )

    evidence = kpi.gather_evidence(state_dir, notes_dir)
    assert evidence["seller_registered_and_listed"] is True
    assert evidence["first_sale"] is False


def test_evaluate_stage_all_false_is_s0_unachieved():
    counts = {
        "cycle_count": 0,
        "commercial_models": 0,
        "generated_images": 0,
        "quality_pass_samples": 0,
        "product_drafts": 0,
        "seller_registered_and_listed": False,
        "first_sale": False,
    }
    result = kpi.evaluate_stage(counts)
    assert result["stage"] == "S0"
    assert result["stages"]["S0"]["achieved"] is False


def test_evaluate_stage_progresses_sequentially_up_to_gap():
    counts = {
        "cycle_count": 1,
        "agent_success_count": 1,
        "commercial_models": 1,
        "generated_images": 1,
        "quality_pass_samples": 0,
        "product_drafts": 0,
        "seller_registered_and_listed": False,
        "first_sale": False,
    }
    result = kpi.evaluate_stage(counts)
    assert result["stage"] == "S2"
    assert result["stages"]["S0"]["achieved"] is True
    assert result["stages"]["S1"]["achieved"] is True
    assert result["stages"]["S2"]["achieved"] is True
    assert result["stages"]["S3"]["achieved"] is False


def test_evaluate_stage_does_not_skip_ahead_over_a_gap():
    # S1が未達なら、S2条件を満たしていてもS0止まり（順序を守る=先に飛ばない）
    counts = {
        "cycle_count": 1,
        "agent_success_count": 1,
        "commercial_models": 0,
        "generated_images": 1,
        "quality_pass_samples": 0,
        "product_drafts": 0,
        "seller_registered_and_listed": False,
        "first_sale": False,
    }
    result = kpi.evaluate_stage(counts)
    assert result["stage"] == "S0"


def test_evaluate_stage_reaches_s6_when_everything_achieved():
    counts = {
        "cycle_count": 10,
        "agent_success_count": 1,
        "commercial_models": 5,
        "generated_images": 20,
        "quality_pass_samples": 10,
        "product_drafts": 3,
        "seller_registered_and_listed": True,
        "first_sale": True,
    }
    result = kpi.evaluate_stage(counts)
    assert result["stage"] == "S6"


def test_compute_kpi_writes_generated_at_and_increments_cycle(tmp_path):
    state_dir = tmp_path / "state"
    notes_dir = tmp_path / "notes"
    state_dir.mkdir()
    notes_dir.mkdir()

    (state_dir / kpi.MODEL_LICENSE_SURVEY_JSON).write_text(
        json.dumps([{"file": "a.safetensors", "category": "商用可"}]), encoding="utf-8"
    )

    result = kpi.compute_kpi(state_dir, notes_dir, agent_status="success")

    assert result["generated_at"]
    assert result["counts"]["cycle_count"] == 1
    assert result["counts"]["commercial_models"] == 1
    assert result["stage"] == "S1"


def test_compute_kpi_without_increment_does_not_bump_cycle_count(tmp_path):
    state_dir = tmp_path / "state"
    notes_dir = tmp_path / "notes"
    state_dir.mkdir()
    notes_dir.mkdir()

    kpi.increment_cycle_count(notes_dir)
    result = kpi.compute_kpi(state_dir, notes_dir, increment=False)
    assert result["counts"]["cycle_count"] == 1


def test_legacy_cycle_count_does_not_achieve_s0(tmp_path):
    (tmp_path / "KPI.json").write_text(json.dumps({"counts": {"cycle_count": 99}}))
    result = kpi.compute_kpi(tmp_path, tmp_path / "notes")
    assert result["agent_success_count"] == 0
    assert result["agent_fail_count"] == 0
    assert result["last_agent_status"] == ""
    assert result["last_agent_success_at"] == ""
    assert result["last_failure_reason"] == ""
    assert result["limit_reset_at"] == ""
    assert not result["stages"]["S0"]["achieved"]


def test_failure_skip_success_sequence(tmp_path):
    from datetime import datetime, timezone
    now = datetime(2026, 9, 27, 0, 0, tzinfo=timezone.utc)
    def cycle(status, output=""):
        result = kpi.compute_kpi(tmp_path, tmp_path / "notes", agent_status=status,
                                 agent_output=output, now=now)
        (tmp_path / "KPI.json").write_text(json.dumps(result))
        return result
    failed = cycle("failure", "You've hit your session limit · resets 1:30am (UTC)")
    assert not failed["stages"]["S0"]["achieved"]
    assert failed["agent_fail_count"] == 1
    assert failed["last_failure_reason"] == "利用枠切れ"
    assert failed["limit_reset_at"] == "2026-09-27T01:30:00+00:00"
    skipped = cycle("skip")
    assert not skipped["stages"]["S0"]["achieved"]
    assert skipped["agent_success_count"] == 0
    assert skipped["agent_fail_count"] == 1
    assert skipped["last_agent_status"] == "skip"
    assert skipped["limit_reset_at"] == failed["limit_reset_at"]
    assert skipped["last_failure_reason"] == failed["last_failure_reason"]
    success = cycle("success")
    assert success["stages"]["S0"]["achieved"]
    assert success["agent_success_count"] == 1
    assert success["last_agent_success_at"] == now.isoformat(timespec="seconds")
    assert success["limit_reset_at"] == success["last_failure_reason"] == ""
    failed_again = cycle("failure", "overloaded with sensitive output")
    assert failed_again["stages"]["S0"]["achieved"]
    assert failed_again["agent_fail_count"] == 2
    assert failed_again["last_agent_success_at"] == success["last_agent_success_at"]
    assert failed_again["last_failure_reason"] == "Claude実行失敗"
    assert failed_again["counts"]["cycle_count"] == 4


def test_dashboard_displays_all_agent_fields(tmp_path):
    from ops.report import build_dashboard_markdown
    from ops.gate import AGENT_DEFAULTS
    result = kpi.compute_kpi(tmp_path, tmp_path / "notes", agent_status="failure")
    dashboard = build_dashboard_markdown(result, "", "なし", "")
    for key in AGENT_DEFAULTS:
        assert key in dashboard


def test_bootstrap_has_no_premature_human_request(tmp_path):
    from ops.bootstrap_state import ensure_default_state
    from ops.report import needs_human_is_active
    ensure_default_state(tmp_path)
    assert (tmp_path / "NEEDS_HUMAN.md").read_text() == "なし\n"
    assert not needs_human_is_active((tmp_path / "NEEDS_HUMAN.md").read_text())


def test_main_reads_capture_and_actual_agent_end_time(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(kpi, "STATE_DIR", state)
    monkeypatch.setattr(kpi, "NOTES_DIR", state / "notes")
    monkeypatch.setattr(kpi, "WORK_ROOT", tmp_path)
    monkeypatch.setenv("AGENT_OUTCOME", "failure")
    monkeypatch.setenv("AGENT_FINISHED_AT", "2026-09-27T01:29:59Z")
    (tmp_path / "claude_out.txt").write_text("You've hit your session limit · resets 1:30am (UTC)")
    kpi.main()
    result = json.loads((state / "KPI.json").read_text())
    assert result["limit_reset_at"] == "2026-09-27T01:30:00+00:00"
    assert result["agent_fail_count"] == 1
    monkeypatch.setenv("AGENT_OUTCOME", "skipped")
    monkeypatch.setenv("AGENT_FINISHED_AT", "")
    kpi.main()
    result = json.loads((state / "KPI.json").read_text())
    assert result["agent_fail_count"] == 1
    assert result["agent_success_count"] == 0
    assert result["last_agent_status"] == "skip"
    assert result["limit_reset_at"] == "2026-09-27T01:30:00+00:00"
