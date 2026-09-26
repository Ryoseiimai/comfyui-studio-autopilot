"""ops.executor の単体テスト（許可リスト・上限・ライセンス拒否・予算台帳）。

ネットワーク・rclone・実Replicate呼び出しは全てmonkeypatchでモックする
（実アクセスは一切しない）。
"""
from __future__ import annotations

import json

from ops import executor


# --- 純粋関数 ---


def test_parse_hf_file_url_accepts_direct_file():
    parsed = executor.parse_hf_file_url("https://huggingface.co/org/repo/resolve/main/model.safetensors")
    assert parsed == ("org/repo", "model.safetensors")


def test_parse_hf_file_url_rejects_repo_url():
    assert executor.parse_hf_file_url("https://huggingface.co/org/repo") is None


def test_parse_hf_file_url_rejects_non_hf_host():
    assert executor.parse_hf_file_url("https://evil.example.com/resolve/main/x") is None


def test_guess_model_kind():
    assert executor.guess_model_kind("foo_vae.safetensors") == "vae"
    assert executor.guess_model_kind("some_lora.safetensors") == "loras"
    assert executor.guess_model_kind("random_checkpoint.safetensors") == "checkpoints"
    assert executor.guess_model_kind("weird.bin") == "other"


def test_sum_month_bytes():
    fetched = [
        {"fetched_at": "2026-09-01T00:00:00+00:00", "size_bytes": 100},
        {"fetched_at": "2026-09-15T00:00:00+00:00", "size_bytes": 200},
        {"fetched_at": "2026-08-01T00:00:00+00:00", "size_bytes": 999},
    ]
    assert executor.sum_month_bytes(fetched, "2026-09") == 300


def test_evaluate_hf_fetch_policy_rejects_bad_url():
    decision = executor.evaluate_hf_fetch_policy(
        url="https://huggingface.co/org/repo", size_bytes=1000, license_category="商用可", month_used_bytes=0
    )
    assert decision["allowed"] is False


def test_evaluate_hf_fetch_policy_rejects_non_commercial_license():
    decision = executor.evaluate_hf_fetch_policy(
        url="https://huggingface.co/org/repo/resolve/main/f.safetensors",
        size_bytes=1000,
        license_category="商用不可",
        month_used_bytes=0,
    )
    assert decision["allowed"] is False
    assert "ライセンス" in decision["reason"]


def test_evaluate_hf_fetch_policy_rejects_unconfirmed_license():
    decision = executor.evaluate_hf_fetch_policy(
        url="https://huggingface.co/org/repo/resolve/main/f.safetensors",
        size_bytes=1000,
        license_category="要確認",
        month_used_bytes=0,
    )
    assert decision["allowed"] is False


def test_evaluate_hf_fetch_policy_rejects_oversized_file():
    decision = executor.evaluate_hf_fetch_policy(
        url="https://huggingface.co/org/repo/resolve/main/f.safetensors",
        size_bytes=executor.MAX_FILE_SIZE_BYTES + 1,
        license_category="商用可",
        month_used_bytes=0,
    )
    assert decision["allowed"] is False
    assert "25GB" in decision["reason"]


def test_evaluate_hf_fetch_policy_rejects_monthly_cap():
    decision = executor.evaluate_hf_fetch_policy(
        url="https://huggingface.co/org/repo/resolve/main/f.safetensors",
        size_bytes=1024,
        license_category="有料ライセンスで可",
        month_used_bytes=executor.MONTHLY_FETCH_CAP_BYTES,
    )
    assert decision["allowed"] is False
    assert "100GB" in decision["reason"]


def test_evaluate_hf_fetch_policy_allows_commercial_ok():
    decision = executor.evaluate_hf_fetch_policy(
        url="https://huggingface.co/org/repo/resolve/main/f.safetensors",
        size_bytes=1024,
        license_category="商用可",
        month_used_bytes=0,
    )
    assert decision["allowed"] is True


def test_evaluate_drive_write_policy_allows_studio_path():
    decision = executor.evaluate_drive_write_policy("work/state/notes/x.md", "AI素材/ComfyUIスタジオ/notes/x.md")
    assert decision["allowed"] is True


def test_evaluate_drive_write_policy_rejects_outside_studio():
    decision = executor.evaluate_drive_write_policy(
        "work/state/notes/x.md", "AI素材/ComfyUIモデル倉庫/checkpoints/x.safetensors"
    )
    assert decision["allowed"] is False


def test_evaluate_drive_write_policy_rejects_outside_work():
    decision = executor.evaluate_drive_write_policy("../secret.env", "AI素材/ComfyUIスタジオ/x")
    assert decision["allowed"] is False


def test_evaluate_gpu_generate_policy_rejects_monthly_cap():
    decision = executor.evaluate_gpu_generate_policy(estimated_cost_usd=0.5, month_spent_usd=9.8, cycle_spent_usd=0)
    assert decision["allowed"] is False
    assert "月間予算" in decision["reason"]


def test_evaluate_gpu_generate_policy_rejects_per_cycle_cap():
    decision = executor.evaluate_gpu_generate_policy(estimated_cost_usd=0.5, month_spent_usd=0, cycle_spent_usd=0.7)
    assert decision["allowed"] is False
    assert "1周" in decision["reason"]


def test_evaluate_gpu_generate_policy_allows_within_budget():
    decision = executor.evaluate_gpu_generate_policy(estimated_cost_usd=0.1, month_spent_usd=0, cycle_spent_usd=0)
    assert decision["allowed"] is True


# --- ハンドラ（外部呼び出しはmonkeypatchでモック） ---


def test_handle_gpu_generate_skips_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    result = executor.handle_gpu_generate(
        {"type": "gpu_generate", "workflow": {"x": 1}}, tmp_path / "budget.json", {"spent_usd": 0.0}
    )
    assert result == {"ok": False, "skipped": True, "reason": "GPU未設定"}


def test_handle_gpu_generate_mocked_success(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "fake-token")

    def fake_request(method, url, token, json_body=None):
        if method == "POST":
            return {"status_code": 201, "data": {"urls": {"get": "https://api.replicate.com/v1/predictions/abc"}}}
        return {
            "status_code": 200,
            "data": {"status": "succeeded", "output": ["ok.png"], "metrics": {"predict_time": 10}},
        }

    monkeypatch.setattr(executor, "_replicate_request", fake_request)
    monkeypatch.setattr(executor, "_sleep", lambda seconds: None)

    budget_path = tmp_path / "budget.json"
    cycle_budget = {"spent_usd": 0.0}
    result = executor.handle_gpu_generate({"type": "gpu_generate", "workflow": {"x": 1}}, budget_path, cycle_budget)

    assert result["ok"] is True
    assert result["output"] == ["ok.png"]
    assert cycle_budget["spent_usd"] > 0
    saved = json.loads(budget_path.read_text(encoding="utf-8"))
    assert saved["spent_this_month_usd"] > 0


def test_handle_gpu_generate_rejects_over_cycle_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "fake-token")
    budget_path = tmp_path / "budget.json"
    cycle_budget = {"spent_usd": 5.0}
    result = executor.handle_gpu_generate({"type": "gpu_generate", "workflow": {"x": 1}}, budget_path, cycle_budget)
    assert result["ok"] is False
    assert "1周" in result["reason"]


def test_handle_gpu_generate_requires_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "fake-token")
    result = executor.handle_gpu_generate({"type": "gpu_generate"}, tmp_path / "budget.json", {"spent_usd": 0.0})
    assert result["ok"] is False


def test_handle_drive_write_rejects_outside_allowlist(tmp_path):
    repo_root = tmp_path
    (repo_root / "work").mkdir()
    (repo_root / "work" / "x.md").write_text("hi", encoding="utf-8")
    result = executor.handle_drive_write(
        {"local_path": "work/x.md", "drive_subpath": "AI素材/ComfyUIモデル倉庫/x.md"}, repo_root
    )
    assert result["ok"] is False


def test_handle_drive_write_missing_local_file(tmp_path):
    result = executor.handle_drive_write(
        {"local_path": "work/does_not_exist.md", "drive_subpath": "AI素材/ComfyUIスタジオ/x.md"}, tmp_path
    )
    assert result["ok"] is False


def test_handle_drive_write_calls_rclone(tmp_path, monkeypatch):
    repo_root = tmp_path
    (repo_root / "work").mkdir()
    (repo_root / "work" / "x.md").write_text("hi", encoding="utf-8")

    calls = []
    monkeypatch.setattr(
        executor,
        "_run_rclone",
        lambda args: calls.append(args) or {"ok": True, "stdout": "", "stderr": ""},
    )

    result = executor.handle_drive_write(
        {"local_path": "work/x.md", "drive_subpath": "AI素材/ComfyUIスタジオ/x.md"}, repo_root
    )
    assert result["ok"] is True
    assert calls[0][0] == "copyto"


def test_handle_hf_fetch_rejects_bad_license(monkeypatch, tmp_path):
    monkeypatch.setattr(executor, "resolve_hf_license", lambda repo_id: {"category": "要確認", "basis": "-"})
    result = executor.handle_hf_fetch({"url": "https://huggingface.co/org/repo/resolve/main/f.safetensors"}, [], tmp_path)
    assert result["ok"] is False
    assert "ライセンス" in result["reason"]


def test_handle_hf_fetch_downloads_and_uploads_when_allowed(monkeypatch, tmp_path):
    monkeypatch.setattr(executor, "resolve_hf_license", lambda repo_id: {"category": "商用可", "basis": "apache-2.0"})
    monkeypatch.setattr(executor, "_http_head_content_length", lambda url: 1024)

    def fake_download(url, dest_path):
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"x" * 1024)
        return 1024

    monkeypatch.setattr(executor, "_download_stream", fake_download)
    uploads = []
    monkeypatch.setattr(
        executor,
        "upload_via_rclone",
        lambda local_path, target: uploads.append((str(local_path), target)) or {"ok": True},
    )

    fetched_list: list[dict] = []
    result = executor.handle_hf_fetch(
        {"url": "https://huggingface.co/org/repo/resolve/main/f.safetensors"}, fetched_list, tmp_path
    )
    assert result["ok"] is True
    assert len(fetched_list) == 1
    assert fetched_list[0]["license_category"] == "商用可"
    assert uploads[0][1].endswith("/checkpoints/f.safetensors")
    assert not (tmp_path / "tmp_download" / "f.safetensors").exists()


def test_handle_hf_fetch_upload_failure_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(executor, "resolve_hf_license", lambda repo_id: {"category": "商用可", "basis": "apache-2.0"})
    monkeypatch.setattr(executor, "_http_head_content_length", lambda url: 1024)

    def fake_download(url, dest_path):
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"x" * 1024)
        return 1024

    monkeypatch.setattr(executor, "_download_stream", fake_download)
    monkeypatch.setattr(executor, "upload_via_rclone", lambda local_path, target: {"ok": False, "stderr": "boom"})

    result = executor.handle_hf_fetch(
        {"url": "https://huggingface.co/org/repo/resolve/main/f.safetensors"}, [], tmp_path
    )
    assert result["ok"] is False
    assert "rclone失敗" in result["reason"]
    # 失敗時もローカルの一時ファイルは残さない
    assert not (tmp_path / "tmp_download" / "f.safetensors").exists()


# --- process_outbox（統合的な配線の確認） ---


def test_process_outbox_handles_unknown_type_and_logs(tmp_path):
    outbox_dir = tmp_path / "outbox"
    outbox_dir.mkdir()
    (outbox_dir / "0001.json").write_text(json.dumps({"type": "delete_everything"}), encoding="utf-8")

    results = executor.process_outbox(
        outbox_dir,
        tmp_path,
        tmp_path / "work",
        tmp_path / "fetched_models.json",
        tmp_path / "executor_log.jsonl",
        tmp_path / "budget.json",
    )
    assert len(results) == 1
    assert results[0]["ok"] is False
    assert "未知のリクエスト種別" in results[0]["reason"]

    log_lines = (tmp_path / "executor_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 1


def test_process_outbox_with_no_requests_is_noop(tmp_path):
    results = executor.process_outbox(
        tmp_path / "no_such_outbox",
        tmp_path,
        tmp_path / "work",
        tmp_path / "fetched_models.json",
        tmp_path / "executor_log.jsonl",
        tmp_path / "budget.json",
    )
    assert results == []
