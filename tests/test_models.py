"""Schema validation tests on pydantic models (v0.4)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sync_compiler.models import (
    AgentRecord,
    Auth,
    BisyncSurface,
    Drive,
    Platform,
    RegistryMain,
    ShareClass,
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


# ── Auth ──────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_service_account(self):
        a = Auth.model_validate({"type": "service_account",
                                 "service_account_file": "/etc/sa.json"})
        assert a.type == "service_account"

    def test_bad_type(self):
        with pytest.raises(ValidationError):
            Auth.model_validate({"type": "basic"})

    def test_relative_sa_file(self):
        with pytest.raises(ValidationError):
            Auth.model_validate({"type": "service_account",
                                 "service_account_file": "relative.json"})


# ── Drive ─────────────────────────────────────────────────────────────────────

class TestDrive:
    def _valid(self) -> dict:
        return {"id": "0AM", "cloud_name": "ARC Academy",
                "local_name": "academy", "enabled": True}

    def test_valid(self):
        d = Drive.model_validate(self._valid())
        assert d.enabled is True

    def test_uppercase_local_name(self):
        with pytest.raises(ValidationError):
            Drive.model_validate({**self._valid(), "local_name": "Academy"})

    def test_empty_id(self):
        with pytest.raises(ValidationError):
            Drive.model_validate({**self._valid(), "id": "   "})


# ── SyncDefaults ──────────────────────────────────────────────────────────────

class TestSyncDefaults:
    def test_valid(self):
        sd = SyncDefaults.model_validate({"local_subdir": "drive", "schedule": "*:0/15"})
        assert sd.sync_flags == []

    def test_absolute_subdir(self):
        with pytest.raises(ValidationError):
            SyncDefaults.model_validate({"local_subdir": "/drive", "schedule": "*:0/15"})


# ── ShareClass / BisyncSurface ────────────────────────────────────────────────

class TestShareClass:
    def test_valid(self):
        sc = ShareClass.model_validate({
            "org": "arc", "grade": 3, "vertical": "tech", "scope": "mz",
        })
        assert sc.org == "arc"

    def test_invalid_org(self):
        with pytest.raises(ValidationError):
            ShareClass.model_validate({
                "org": "BadOrg", "grade": 3, "vertical": "tech", "scope": "mz",
            })


class TestBisyncSurface:
    def test_default_enabled(self):
        s = BisyncSurface.model_validate({})
        assert s.enabled is True
        assert s.conflict_policy == "newer"
        assert s.schedule == "*:0/1"

    def test_remote_missing_separator(self):
        with pytest.raises(ValidationError):
            BisyncSurface.model_validate({"remote": "no_separator"})

    def test_invalid_conflict_policy(self):
        with pytest.raises(ValidationError):
            BisyncSurface.model_validate({"conflict_policy": "delete"})


# ── AgentRecord ───────────────────────────────────────────────────────────────

class TestAgentRecord:
    def test_minimal(self):
        a = AgentRecord.model_validate({"name": "agent_x"})
        assert a.share_class is None
        assert a.cloud_sync is None
        assert a.sub_agents == []

    def test_invalid_name(self):
        with pytest.raises(ValidationError):
            AgentRecord.model_validate({"name": "BadName"})

    def test_sub_agent_main_reserved(self):
        with pytest.raises(ValidationError):
            AgentRecord.model_validate({"name": "a", "sub_agents": ["main"]})

    def test_sub_agent_invalid_chars(self):
        with pytest.raises(ValidationError):
            AgentRecord.model_validate({"name": "a", "sub_agents": ["Bad-Name"]})

    def test_sub_agent_duplicate(self):
        with pytest.raises(ValidationError):
            AgentRecord.model_validate({"name": "a", "sub_agents": ["x", "x"]})

    def test_tolerates_extra_fields(self):
        """rbac-compile owns fields like `access`, `description` — sync-compile ignores."""
        a = AgentRecord.model_validate({
            "name": "agent_x",
            "description": "hi",
            "access": [{"org": "arc", "grade": 0, "vertical": "any", "scope": "global"}],
            "local_user": "agent_x",
        })
        assert a.name == "agent_x"


# ── SnapshotDrive ─────────────────────────────────────────────────────────────

class TestSnapshotDrive:
    def test_status_new(self):
        d = SnapshotDrive.model_validate({"id": "x", "cloud_name": "X", "status": "new",
                                          "suggested_local_name": "x"})
        assert d.status == "new"

    def test_unknown_status(self):
        with pytest.raises(ValidationError):
            SnapshotDrive.model_validate({"id": "x", "cloud_name": "X", "status": "weird"})


# ── RegistryMain loading from fixture ─────────────────────────────────────────

def test_registry_main_loads_fixture(valid_dir):
    from sync_compiler.loader import load_main
    main, _ = load_main(valid_dir / "arc.yml")
    assert main.org == "arc"
    assert main.meta.version == "0.4"
    assert len(main.accounts[0].drives) == 3


def test_agent_registry_loads_fixture(valid_dir):
    from sync_compiler.loader import load_agent_registry
    result = load_agent_registry(valid_dir / "agent_registry.yml")
    assert result is not None
    reg, _ = result
    assert len(reg.agents) == 4
    research = next(a for a in reg.agents if a.name == "agent_arc_research_mz")
    assert research.share_class is not None
    assert research.share_class.org == "arc"
    assert research.cloud_sync is not None
    assert research.cloud_sync.scratch is not None
    assert research.cloud_sync.scratch.enabled is True


def test_snapshot_loads_minimal():
    s = SnapshotRegistry.model_validate({
        "meta": {"version": "0.4", "generated_at": "2026-05-13T00:00:00Z",
                 "generated_by": "test", "source_yml_path": "/tmp/arc.yml",
                 "source_yml_hash": "sha256:abc"},
        "org": "arc",
        "accounts": [],
    })
    assert s.org == "arc"


def test_duplicate_remote_name_rejected():
    with pytest.raises(ValidationError):
        RegistryMain.model_validate({
            "meta": {"version": "0.4"},
            "org": "arc",
            "platform": {"rclone_user": "rclone_arc", "local_base": "/mnt/raid/arc",
                         "rclone_config": "/var/lib/rclone/rclone.conf"},
            "accounts": [
                {"remote_name": "drive", "provider": "drive",
                 "auth": {"type": "service_account", "service_account_file": "/x.json"},
                 "sync_defaults": {"local_subdir": "drive", "schedule": "*:0/15"}},
                {"remote_name": "drive", "provider": "drive",
                 "auth": {"type": "service_account", "service_account_file": "/x.json"},
                 "sync_defaults": {"local_subdir": "drive", "schedule": "*:0/15"}},
            ],
        })
