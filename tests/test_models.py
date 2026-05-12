"""Schema validation tests on pydantic models (v0.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sync_compiler.models import (
    Auth,
    Drive,
    Platform,
    RegistryMain,
    SnapshotDrive,
    SnapshotRegistry,
    SyncDefaults,
)

# ── Platform ──────────────────────────────────────────────────────────────────

class TestPlatform:
    def _valid_kwargs(self) -> dict[str, str]:
        return {
            "rclone_user": "rclone_arc",
            "local_base": "/mnt/raid/arc",
            "rclone_config": "/var/lib/rclone/rclone.conf",
        }

    def test_valid(self):
        p = Platform.model_validate(self._valid_kwargs())
        assert p.rclone_user == "rclone_arc"
        assert p.default_owner is None

    def test_bad_username(self):
        with pytest.raises(ValidationError):
            Platform.model_validate({**self._valid_kwargs(), "rclone_user": "BadUser"})

    def test_relative_path_rejected(self):
        with pytest.raises(ValidationError):
            Platform.model_validate({**self._valid_kwargs(), "local_base": "relative/path"})

    def test_parent_traversal_rejected(self):
        with pytest.raises(ValidationError):
            Platform.model_validate({**self._valid_kwargs(), "local_base": "/mnt/../etc"})

    def test_mode_valid(self):
        p = Platform.model_validate({**self._valid_kwargs(), "default_mode": "02770"})
        assert p.default_mode == "02770"

    def test_mode_invalid(self):
        with pytest.raises(ValidationError):
            Platform.model_validate({**self._valid_kwargs(), "default_mode": "9999"})


# ── Auth ──────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_service_account(self):
        a = Auth.model_validate({
            "type": "service_account",
            "service_account_file": "/etc/rclone-sa/arc.json",
        })
        assert a.type == "service_account"

    def test_bad_type(self):
        with pytest.raises(ValidationError):
            Auth.model_validate({"type": "basic"})

    def test_relative_sa_file(self):
        with pytest.raises(ValidationError):
            Auth.model_validate({
                "type": "service_account",
                "service_account_file": "relative.json",
            })


# ── Drive (now under accounts in <org>.yml) ───────────────────────────────────

class TestDrive:
    def _valid(self) -> dict:
        return {
            "id": "0AM0lOfo8XiIBUk9PVA",
            "cloud_name": "ARC Academy",
            "local_name": "academy",
            "enabled": True,
        }

    def test_valid(self):
        d = Drive.model_validate(self._valid())
        assert d.enabled is True

    def test_uppercase_local_name(self):
        with pytest.raises(ValidationError):
            Drive.model_validate({**self._valid(), "local_name": "Academy"})

    def test_space_in_local_name(self):
        with pytest.raises(ValidationError):
            Drive.model_validate({**self._valid(), "local_name": "aca demy"})

    def test_empty_id(self):
        with pytest.raises(ValidationError):
            Drive.model_validate({**self._valid(), "id": "   "})

    def test_status_field_rejected(self):
        """v0.3: status no longer lives on Drive (it's snapshot-only)."""
        with pytest.raises(ValidationError):
            Drive.model_validate({**self._valid(), "status": "missing_from_cloud"})


# ── SnapshotDrive ─────────────────────────────────────────────────────────────

class TestSnapshotDrive:
    def test_status_new(self):
        d = SnapshotDrive.model_validate({
            "id": "x", "cloud_name": "X", "status": "new",
            "suggested_local_name": "x",
        })
        assert d.status == "new"

    def test_status_renamed(self):
        d = SnapshotDrive.model_validate({
            "id": "x", "cloud_name": "X New", "status": "renamed",
            "cloud_name_was": "X Old", "cloud_name_now": "X New",
        })
        assert d.cloud_name_was == "X Old"

    def test_unknown_status_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotDrive.model_validate({
                "id": "x", "cloud_name": "X", "status": "weird",
            })

    def test_enabled_field_rejected(self):
        """v0.3 snapshot has no `enabled` field."""
        with pytest.raises(ValidationError):
            SnapshotDrive.model_validate({
                "id": "x", "cloud_name": "X", "status": "new", "enabled": True,
            })


# ── SyncDefaults ──────────────────────────────────────────────────────────────

class TestSyncDefaults:
    def test_valid(self):
        sd = SyncDefaults.model_validate({"local_subdir": "drive", "schedule": "*:0/15"})
        assert sd.sync_flags == []

    def test_absolute_subdir(self):
        with pytest.raises(ValidationError):
            SyncDefaults.model_validate({"local_subdir": "/drive", "schedule": "*:0/15"})

    def test_parent_subdir(self):
        with pytest.raises(ValidationError):
            SyncDefaults.model_validate({"local_subdir": "../drive", "schedule": "*:0/15"})


# ── RegistryMain loading ──────────────────────────────────────────────────────

def test_registry_main_loads_fixture(valid_dir):
    from sync_compiler.loader import load_main
    main, _ = load_main(valid_dir / "arc.yml")
    assert main.org == "arc"
    assert main.platform.rclone_user == "rclone_arc"
    assert len(main.accounts) == 1
    assert main.accounts[0].remote_name == "drive"
    assert len(main.accounts[0].drives) == 3


def test_duplicate_remote_name_rejected():
    with pytest.raises(ValidationError):
        RegistryMain.model_validate({
            "meta": {"version": "0.3"},
            "org": "arc",
            "platform": {
                "rclone_user": "rclone_arc",
                "local_base": "/mnt/raid/arc",
                "rclone_config": "/var/lib/rclone/rclone.conf",
            },
            "accounts": [
                {
                    "remote_name": "drive",
                    "provider": "drive",
                    "auth": {"type": "service_account", "service_account_file": "/x.json"},
                    "sync_defaults": {"local_subdir": "drive", "schedule": "*:0/15"},
                },
                {
                    "remote_name": "drive",
                    "provider": "drive",
                    "auth": {"type": "service_account", "service_account_file": "/x.json"},
                    "sync_defaults": {"local_subdir": "drive", "schedule": "*:0/15"},
                },
            ],
        })


def test_snapshot_loads_minimal():
    s = SnapshotRegistry.model_validate({
        "meta": {
            "version": "0.3",
            "generated_at": "2026-05-12T00:00:00Z",
            "generated_by": "test",
            "source_yml_path": "/tmp/arc.yml",
            "source_yml_hash": "sha256:abc",
        },
        "org": "arc",
        "accounts": [],
    })
    assert s.org == "arc"
