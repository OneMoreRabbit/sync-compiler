"""Schema validation tests on pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sync_compiler.models import (
    Auth,
    Drive,
    Platform,
    RegistryCloud,
    RegistryMain,
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

    def test_rclone_user_must_be_linux_name(self):
        with pytest.raises(ValidationError):
            Platform.model_validate({**self._valid_kwargs(), "rclone_user": "BadUser"})

    def test_relative_path_rejected(self):
        with pytest.raises(ValidationError):
            Platform.model_validate({**self._valid_kwargs(), "local_base": "relative/path"})

    def test_parent_traversal_rejected(self):
        with pytest.raises(ValidationError):
            Platform.model_validate({**self._valid_kwargs(), "local_base": "/mnt/../etc"})

    def test_valid_mode(self):
        p = Platform.model_validate({**self._valid_kwargs(), "default_mode": "02770"})
        assert p.default_mode == "02770"

    def test_invalid_mode(self):
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


# ── Drive ─────────────────────────────────────────────────────────────────────

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
        assert d.status is None

    def test_invalid_local_name_uppercase(self):
        with pytest.raises(ValidationError):
            Drive.model_validate({**self._valid(), "local_name": "Academy"})

    def test_invalid_local_name_space(self):
        with pytest.raises(ValidationError):
            Drive.model_validate({**self._valid(), "local_name": "aca demy"})

    def test_status_accepted(self):
        d = Drive.model_validate({**self._valid(), "status": "missing_from_cloud"})
        assert d.status == "missing_from_cloud"

    def test_status_invalid(self):
        with pytest.raises(ValidationError):
            Drive.model_validate({**self._valid(), "status": "unknown"})

    def test_empty_id(self):
        with pytest.raises(ValidationError):
            Drive.model_validate({**self._valid(), "id": "   "})


# ── SyncDefaults ──────────────────────────────────────────────────────────────

class TestSyncDefaults:
    def test_valid(self):
        sd = SyncDefaults.model_validate({
            "local_subdir": "drive",
            "schedule": "*:0/15",
        })
        assert sd.sync_flags == []

    def test_absolute_subdir_rejected(self):
        with pytest.raises(ValidationError):
            SyncDefaults.model_validate({"local_subdir": "/drive", "schedule": "*:0/15"})

    def test_parent_subdir_rejected(self):
        with pytest.raises(ValidationError):
            SyncDefaults.model_validate({"local_subdir": "../drive", "schedule": "*:0/15"})


# ── RegistryMain / RegistryCloud loading ──────────────────────────────────────

def test_registry_main_loads_fixture(valid_dir):
    from sync_compiler.loader import load_main
    main, _ = load_main(valid_dir / "arc.yml")
    assert main.org == "arc"
    assert main.platform.rclone_user == "rclone_arc"
    assert len(main.accounts) == 1
    assert main.accounts[0].remote_name == "drive"


def test_registry_cloud_loads_fixture(valid_dir):
    from sync_compiler.loader import load_cloud
    result = load_cloud(valid_dir / "arc.cloud.yml")
    assert result is not None
    cloud, _ = result
    assert cloud.org == "arc"
    assert len(cloud.accounts) == 1
    assert len(cloud.accounts[0].drives) == 3


def test_missing_cloud_returns_none(tmp_path):
    from sync_compiler.loader import load_cloud
    assert load_cloud(tmp_path / "does_not_exist.yml") is None


def test_duplicate_remote_name_rejected():
    with pytest.raises(ValidationError):
        RegistryMain.model_validate({
            "meta": {"version": "0.2"},
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


def test_registry_cloud_accepts_empty_accounts():
    rc = RegistryCloud.model_validate({"meta": {"version": "0.2"}, "org": "arc", "accounts": []})
    assert rc.accounts == []
