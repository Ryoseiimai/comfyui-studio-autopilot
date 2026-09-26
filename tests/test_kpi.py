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

    result = kpi.compute_kpi(state_dir, notes_dir)

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
