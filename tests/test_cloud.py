"""Tests for the Cloud provider adapter and rclone subprocess wrapper (mocked)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from sync_compiler.cloud import DriveProvider
from sync_compiler.errors import CloudAPIError
from sync_compiler.loader import load_main
from sync_compiler.rclone import RcloneRunner

# ── DriveProvider (runner mocked) ─────────────────────────────────────────────

class _FakeRunner:
    """Stand-in for RcloneRunner — returns canned JSON."""

    def __init__(self, payload: list[dict[str, Any]] | Exception) -> None:
        self._payload = payload
        self.last_call: tuple[str, str, str] | None = None

    def list_shared_drives(
        self, remote_name: str, rclone_user: str, rclone_config: str
    ) -> list[dict[str, Any]]:
        self.last_call = (remote_name, rclone_user, rclone_config)
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class TestDriveProvider:
    def test_list_drives_parses_payload(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        runner = _FakeRunner([
            {"id": "0AM", "name": "Academy"},
            {"id": "0BN", "name": "Global"},
        ])
        provider = DriveProvider(
            runner=runner,  # type: ignore[arg-type]
            rclone_user="rclone_arc",
            rclone_config="/var/lib/rclone/rclone.conf",
        )
        drives = provider.list_drives(main.accounts[0])
        assert len(drives) == 2
        assert drives[0].id == "0AM"
        assert drives[0].name == "Academy"
        assert runner.last_call == ("drive", "rclone_arc", "/var/lib/rclone/rclone.conf")

    def test_ignores_entries_missing_id_or_name(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        runner = _FakeRunner([
            {"id": "0AM", "name": "Valid"},
            {"id": "0BN"},          # missing name -> skipped
            {"name": "Orphan"},     # missing id -> skipped
        ])
        provider = DriveProvider(
            runner=runner,  # type: ignore[arg-type]
            rclone_user="rclone_arc",
            rclone_config="/x",
        )
        drives = provider.list_drives(main.accounts[0])
        assert len(drives) == 1
        assert drives[0].id == "0AM"

    def test_propagates_cloud_api_error(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        runner = _FakeRunner(CloudAPIError("boom"))
        provider = DriveProvider(
            runner=runner,  # type: ignore[arg-type]
            rclone_user="rclone_arc",
            rclone_config="/x",
        )
        with pytest.raises(CloudAPIError):
            provider.list_drives(main.accounts[0])


# ── RcloneRunner (subprocess patched) ─────────────────────────────────────────

class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestRcloneRunner:
    def test_list_shared_drives_parses_json(self, monkeypatch):
        payload = [{"id": "0AM", "name": "Academy"}]
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _FakeCompleted(0, stdout=json.dumps(payload))

        monkeypatch.setattr("sync_compiler.rclone.subprocess.run", fake_run)
        runner = RcloneRunner()
        drives = runner.list_shared_drives("drive", "rclone_arc", "/etc/rclone.conf")
        assert drives == payload
        assert any("drives" in arg for arg in calls[0])
        assert "drive:" in calls[0]

    def test_nonzero_exit_raises(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return _FakeCompleted(3, stdout="", stderr="permission denied")

        monkeypatch.setattr("sync_compiler.rclone.subprocess.run", fake_run)
        runner = RcloneRunner()
        with pytest.raises(CloudAPIError) as exc_info:
            runner.list_shared_drives("drive", "rclone_arc", "/etc/rclone.conf")
        assert "permission denied" in str(exc_info.value)

    def test_invalid_json_raises(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return _FakeCompleted(0, stdout="not json")

        monkeypatch.setattr("sync_compiler.rclone.subprocess.run", fake_run)
        runner = RcloneRunner()
        with pytest.raises(CloudAPIError) as exc_info:
            runner.list_shared_drives("drive", "rclone_arc", "/etc/rclone.conf")
        assert "JSON" in str(exc_info.value)

    def test_non_list_json_raises(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return _FakeCompleted(0, stdout='{"not": "a list"}')

        monkeypatch.setattr("sync_compiler.rclone.subprocess.run", fake_run)
        runner = RcloneRunner()
        with pytest.raises(CloudAPIError) as exc_info:
            runner.list_shared_drives("drive", "rclone_arc", "/etc/rclone.conf")
        assert "list" in str(exc_info.value)

    def test_empty_stdout_returns_empty_list(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return _FakeCompleted(0, stdout="")

        monkeypatch.setattr("sync_compiler.rclone.subprocess.run", fake_run)
        runner = RcloneRunner()
        assert runner.list_shared_drives("drive", "rclone_arc", "/etc/rclone.conf") == []

    def test_binary_not_found(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("no such binary")

        monkeypatch.setattr("sync_compiler.rclone.subprocess.run", fake_run)
        runner = RcloneRunner()
        with pytest.raises(CloudAPIError) as exc_info:
            runner.version()
        assert "not found" in str(exc_info.value).lower()
