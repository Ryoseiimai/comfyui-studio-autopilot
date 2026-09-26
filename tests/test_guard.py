"""ops.guard の単体テスト（保護ファイル・シークレット検出・サイズ上限・work/隔離）。

git操作を含むため tmp_path に使い捨てのgitリポジトリを作って検証する
（本物のrepoには一切触らない）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ops import guard


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def _init_repo(repo_root: Path) -> None:
    _run(["git", "init", "-q"], repo_root)
    _run(["git", "config", "user.email", "test@example.com"], repo_root)
    _run(["git", "config", "user.name", "test"], repo_root)

    (repo_root / ".github" / "workflows").mkdir(parents=True)
    (repo_root / ".github" / "workflows" / "pdca.yml").write_text("name: pdca\n", encoding="utf-8")
    (repo_root / "ops").mkdir(parents=True)
    (repo_root / "ops" / "guard.py").write_text("# guard\n", encoding="utf-8")
    (repo_root / "ops" / "prompt.md").write_text("prompt\n", encoding="utf-8")
    (repo_root / "README.md").write_text("hello\n", encoding="utf-8")
    (repo_root / "GUARDRAILS.md").write_text("rules\n", encoding="utf-8")

    _run(["git", "add", "-A"], repo_root)
    _run(["git", "commit", "-q", "-m", "init"], repo_root)


def test_is_protected_path_pure():
    assert guard.is_protected_path(".github/workflows/pdca.yml")
    assert guard.is_protected_path("ops/guard.py")
    assert guard.is_protected_path("ops/executor.py")
    assert guard.is_protected_path("ops/report_extra.py")
    assert guard.is_protected_path("GUARDRAILS.md")
    assert not guard.is_protected_path("ops/prompt.md")
    assert not guard.is_protected_path("README.md")


def test_find_secret_matches_pure():
    assert guard.find_secret_matches("sk-ant-abcdefghijklmno") == ["sk-ant-"]
    assert guard.find_secret_matches("nothing here") == []
    hits = set(guard.find_secret_matches("ya29.abcdefghij refresh_token=1"))
    assert hits == {"ya29.", "refresh_token"}


def test_protected_workflow_change_is_reverted(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_repo(repo_root)

    (repo_root / ".github" / "workflows" / "pdca.yml").write_text("name: hacked\n", encoding="utf-8")

    report = guard.run(repo_root, tmp_path / "work")

    assert any(v["path"] == ".github/workflows/pdca.yml" for v in report["repo_violations"])
    assert (repo_root / ".github" / "workflows" / "pdca.yml").read_text(encoding="utf-8") == "name: pdca\n"


def test_guardrails_md_change_is_reverted(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_repo(repo_root)

    (repo_root / "GUARDRAILS.md").write_text("hacked rules\n", encoding="utf-8")

    report = guard.run(repo_root, tmp_path / "work")

    assert any(v["path"] == "GUARDRAILS.md" for v in report["repo_violations"])
    assert (repo_root / "GUARDRAILS.md").read_text(encoding="utf-8") == "rules\n"


def test_legit_change_is_kept(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_repo(repo_root)

    (repo_root / "README.md").write_text("hello world\n", encoding="utf-8")

    report = guard.run(repo_root, tmp_path / "work")

    assert report["repo_violations"] == []
    assert "README.md" in report["repo_allowed_changed"]
    assert (repo_root / "README.md").read_text(encoding="utf-8") == "hello world\n"


def test_secret_in_tracked_file_is_reverted(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_repo(repo_root)

    (repo_root / "README.md").write_text("token=sk-ant-abcdefghij1234567890\n", encoding="utf-8")

    report = guard.run(repo_root, tmp_path / "work")

    assert any(v["path"] == "README.md" for v in report["repo_violations"])
    assert (repo_root / "README.md").read_text(encoding="utf-8") == "hello\n"


def test_untracked_secret_file_is_deleted(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_repo(repo_root)

    (repo_root / "leaked.txt").write_text("refresh_token=abc\n", encoding="utf-8")

    report = guard.run(repo_root, tmp_path / "work")

    assert any(v["path"] == "leaked.txt" for v in report["repo_violations"])
    assert not (repo_root / "leaked.txt").exists()


def test_untracked_legit_new_file_is_kept(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_repo(repo_root)

    (repo_root / "ops" / "new_helper.py").write_text("x = 1\n", encoding="utf-8")

    report = guard.run(repo_root, tmp_path / "work")

    assert report["repo_violations"] == []
    assert (repo_root / "ops" / "new_helper.py").exists()


def test_oversized_file_is_reverted(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_repo(repo_root)

    big_text = "a" * (guard.MAX_CHANGED_FILE_BYTES + 1)
    (repo_root / "README.md").write_text(big_text, encoding="utf-8")

    report = guard.run(repo_root, tmp_path / "work")

    assert any(v["path"] == "README.md" for v in report["repo_violations"])
    assert (repo_root / "README.md").read_text(encoding="utf-8") == "hello\n"


def test_work_dir_secret_is_quarantined(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_repo(repo_root)

    work_root = tmp_path / "work"
    notes_dir = work_root / "state" / "notes"
    notes_dir.mkdir(parents=True)
    (notes_dir / "leak.md").write_text("-----BEGIN PRIVATE KEY-----\nabc\n", encoding="utf-8")
    (notes_dir / "fine.md").write_text("普通のメモ\n", encoding="utf-8")

    report = guard.run(repo_root, work_root)

    assert any(q["path"] == "work/state/notes/leak.md" for q in report["work_secret_quarantined"])
    assert not (notes_dir / "leak.md").exists()
    assert (notes_dir / "fine.md").exists()


def test_guard_own_audit_files_are_not_self_quarantined(tmp_path):
    """GUARD_LOG.md/guard_last_report.json は違反理由の診断文字列
    （例: "secret_pattern:refresh_token"）を含むため、2周目のwork/スキャンで
    自分自身を再検知して削除してしまわないことを確認する（実際に発生したバグの再現防止）。"""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_repo(repo_root)
    work_root = tmp_path / "work"

    # 1周目: 本物のシークレットらしきファイルで違反を1件起こし、GUARD_LOG.md等を作らせる
    notes_dir = work_root / "state" / "notes"
    notes_dir.mkdir(parents=True)
    (notes_dir / "leak.md").write_text("refresh_token=abc123\n", encoding="utf-8")
    first_report = guard.run(repo_root, work_root)
    assert len(first_report["work_secret_quarantined"]) == 1

    log_path = work_root / "state" / guard.GUARD_LOG_MD
    report_path = notes_dir / "guard_last_report.json"
    assert log_path.exists()
    assert report_path.exists()
    assert "refresh_token" in log_path.read_text(encoding="utf-8")

    # 2周目: 新しい違反は無い。GUARD_LOG.md/guard_last_report.json自身が消されないことを確認。
    second_report = guard.run(repo_root, work_root)
    assert second_report["work_secret_quarantined"] == []
    assert log_path.exists()
    assert report_path.exists()


def test_report_written_to_notes(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_repo(repo_root)

    work_root = tmp_path / "work"
    guard.run(repo_root, work_root)

    report_path = work_root / "state" / "notes" / "guard_last_report.json"
    assert report_path.exists()
