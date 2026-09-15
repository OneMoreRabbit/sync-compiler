"""Tests for classify_drives, validation, slugify, path resolution, and legacy detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from sync_compiler.cloud import CloudDrive
from sync_compiler.errors import RegistryLoadError
from sync_compiler.loader import (
    detect_legacy_residue,
    load_agent_registry,
    load_main,
    snapshot_path,
)
from sync_compiler.models import AgentRecord, Drive
from sync_compiler.registry import (
    classify_drives,
    resolve_surface_path,
    slugify,
    uniquify,
    validate_agent_sync,
    validate_registry,
)

# ── slugify / uniquify ────────────────────────────────────────────────────────

class TestSlugify:
    @pytest.mark.parametrize("name,expected", [
        ("ARC Academy", "arc_academy"),
        ("Global Media", "global_media"),
        ("  trim  ", "trim"),
        ("!!", "unnamed"),
    ])
    def test_slugify(self, name, expected):
        assert slugify(name) == expected


class TestUniquify:
    def test_unused(self):
        assert uniquify("foo", set()) == "foo"

    def test_taken(self):
        assert uniquify("foo", {"foo"}) == "foo_2"

    def test_multiple_taken(self):
        assert uniquify("foo", {"foo", "foo_2", "foo_3"}) == "foo_4"


# ── resolve_surface_path ──────────────────────────────────────────────────────

class TestResolveSurfacePath:
    # ADR-0010 §7: the three hot surfaces resolve under the declared beaver mount;
    # `configs/` deliberately does not move.

    def test_hot_surface_uses_declared_mount_base(self):
        a = AgentRecord.model_validate({
            "name": "agent_x",
            "share_class": {"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        })
        assert resolve_surface_path(a, "scratch", "/mnt/agent-hosts/otter/arc") == \
            "/mnt/agent-hosts/otter/arc/agent_x/scratch/"

    def test_hot_surface_top_org(self):
        a = AgentRecord.model_validate({
            "name": "agent_oversight",
            "share_class": {"org": "top", "grade": 0, "vertical": "any", "scope": "global"},
        })
        assert resolve_surface_path(a, "memory", "/mnt/agent-hosts/otter/top") == \
            "/mnt/agent-hosts/otter/top/agent_oversight/memory/"

    def test_all_three_hot_surfaces_move(self):
        a = AgentRecord.model_validate({
            "name": "agent_x",
            "share_class": {"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        })
        for surface in ("memory", "sessions", "scratch"):
            assert resolve_surface_path(a, surface, "/mnt/agent-hosts/otter/arc") == \
                f"/mnt/agent-hosts/otter/arc/agent_x/{surface}/"

    def test_configs_does_not_move(self):
        """`configs/` keeps the historic beaver shape -- secrets and TLS resolve
        through it, and ADR-0010 §7 records the asymmetry as deliberate."""
        a = AgentRecord.model_validate({
            "name": "agent_x",
            "share_class": {"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        })
        assert resolve_surface_path(a, "configs", "/mnt/agent-hosts/otter/arc") == \
            "/mnt/raid/arc/agents/agent_x/configs/"

    def test_configs_needs_no_mount_base(self):
        """configs does not move, so it must resolve with no root declared at all."""
        a = AgentRecord.model_validate({
            "name": "agent_x",
            "share_class": {"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        })
        assert resolve_surface_path(a, "configs") == "/mnt/raid/arc/agents/agent_x/configs/"

    def test_missing_mount_base_raises_rather_than_guessing(self):
        """No default: a guessed root is a plausible path to the wrong machine."""
        a = AgentRecord.model_validate({
            "name": "agent_x",
            "share_class": {"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        })
        with pytest.raises(RegistryLoadError) as exc:
            resolve_surface_path(a, "scratch")
        msg = str(exc.value)
        assert "agent_mount_base" in msg
        assert "agent_x" in msg and "arc" in msg      # names what failed
        assert "sync/arc.yml" in msg                  # and where to fix it

    def test_trailing_slash_on_base_is_tolerated(self):
        a = AgentRecord.model_validate({
            "name": "agent_x",
            "share_class": {"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        })
        assert resolve_surface_path(a, "scratch", "/mnt/agent-hosts/otter/arc/") == \
            "/mnt/agent-hosts/otter/arc/agent_x/scratch/"

    def test_override(self):
        a = AgentRecord.model_validate({
            "name": "agent_x",
            "share_class": {"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
            "shares": {"scratch": "/custom/path/scratch"},
        })
        assert resolve_surface_path(a, "scratch") == "/custom/path/scratch/"

    def test_no_share_class_returns_none(self):
        a = AgentRecord.model_validate({"name": "agent_x"})
        assert resolve_surface_path(a, "scratch") is None

    def test_unknown_surface_raises(self):
        a = AgentRecord.model_validate({"name": "agent_x"})
        with pytest.raises(ValueError):
            resolve_surface_path(a, "weird")


# ── classify_drives ───────────────────────────────────────────────────────────

def _drive(id: str, cloud_name: str = "x", local_name: str = "x", enabled: bool = True) -> Drive:
    return Drive(id=id, cloud_name=cloud_name, local_name=local_name,
                 enabled=enabled, overrides={}, description=None)


class TestClassify:
    def test_all_present(self):
        yml = [_drive("a", "A", "a"), _drive("b", "B", "b")]
        cloud = [CloudDrive(id="a", name="A"), CloudDrive(id="b", name="B")]
        result = classify_drives("drive", yml, cloud, existing_local_names={"a", "b"})
        assert result.present == 2

    def test_new_with_suggestion(self):
        result = classify_drives("drive", [], [CloudDrive(id="z", name="New Project")],
                                 existing_local_names=set())
        assert result.new == 1
        assert result.drives[0].suggested_local_name == "new_project"

    def test_new_collision_uniquifies(self):
        result = classify_drives(
            "drive",
            [_drive("a", "Existing", "new_project")],
            [CloudDrive(id="a", name="Existing"), CloudDrive(id="z", name="New Project")],
            existing_local_names={"new_project"},
        )
        new_entry = next(d for d in result.drives if d.status == "new")
        assert new_entry.suggested_local_name == "new_project_2"

    def test_renamed(self):
        result = classify_drives(
            "drive",
            [_drive("a", "Old", "alias")],
            [CloudDrive(id="a", name="New")],
            existing_local_names={"alias"},
        )
        assert result.renamed == 1

    def test_missing(self):
        result = classify_drives("drive", [_drive("a", "A", "a")], [],
                                 existing_local_names={"a"})
        assert result.missing_from_cloud == 1


# ── Validation: <org>.yml ─────────────────────────────────────────────────────

class TestValidation:
    def test_valid_fixture_passes(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        result = validate_registry(main, valid_dir / "arc.yml")
        assert result.ok, [str(e) for e in result.errors]

    def test_duplicate_local_name(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        main.accounts[0].drives[0].local_name = main.accounts[0].drives[1].local_name
        result = validate_registry(main, valid_dir / "arc.yml")
        assert not result.ok

    def test_duplicate_id(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        main.accounts[0].drives[0].id = main.accounts[0].drives[1].id
        result = validate_registry(main, valid_dir / "arc.yml")
        assert not result.ok

    def test_unknown_rclone_user(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        main.platform.rclone_user = "ghost"
        result = validate_registry(main, valid_dir / "arc.yml")
        assert not result.ok


# ── Validation: agent_registry.yml ────────────────────────────────────────────

class TestValidateAgentSync:
    def test_fixture_passes(self, valid_dir):
        result_main, _ = load_main(valid_dir / "arc.yml")
        agents_tuple = load_agent_registry(valid_dir / "agent_registry.yml")
        assert agents_tuple is not None
        agents, _ = agents_tuple
        result = validate_agent_sync(agents, "arc", valid_dir / "agent_registry.yml")
        assert result.ok, [str(e) for e in result.errors]

    def test_cloud_sync_without_share_class(self):
        from sync_compiler.models import AgentRegistry
        reg = AgentRegistry.model_validate({
            "meta": {"version": "0.4"},
            "agents": [
                {"name": "agent_x",
                 "cloud_sync": {"scratch": {"remote": "x:y"}}},
            ],
        })
        result = validate_agent_sync(reg, "arc", None)
        assert not result.ok
        assert any("share_class" in str(e) for e in result.errors)

    def test_enabled_without_remote_fails(self):
        from sync_compiler.models import AgentRegistry
        reg = AgentRegistry.model_validate({
            "meta": {"version": "0.4"},
            "agents": [
                {"name": "agent_x",
                 "share_class": {"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
                 "cloud_sync": {"scratch": {"enabled": True}}},  # no remote
            ],
        })
        result = validate_agent_sync(reg, "arc", None)
        assert not result.ok
        assert any("remote" in str(e) for e in result.errors)

    def test_other_org_ignored(self, valid_dir):
        """Agents from other orgs should not be validated against this org's compile."""
        agents_tuple = load_agent_registry(valid_dir / "agent_registry.yml")
        agents, _ = agents_tuple  # type: ignore[misc]
        # CPF agent in fixture; validating for arc should not error on cpf agent's setup
        result = validate_agent_sync(agents, "arc", valid_dir / "agent_registry.yml")
        assert result.ok

    def test_sessions_warns(self):
        from sync_compiler.models import AgentRegistry
        reg = AgentRegistry.model_validate({
            "meta": {"version": "0.4"},
            "agents": [
                {"name": "agent_x",
                 "share_class": {"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
                 "cloud_sync": {"sessions": {"enabled": True, "remote": "x:y"}}},
            ],
        })
        result = validate_agent_sync(reg, "arc", None)
        assert result.ok  # warning, not error
        assert any("sessions" in str(w) for w in result.warnings)


# ── Legacy detection ──────────────────────────────────────────────────────────

class TestLegacyDetection:
    def test_v02_cloud_yml(self, legacy_v02_registry_dir: Path):
        msg = detect_legacy_residue(legacy_v02_registry_dir, "arc")
        assert msg is not None
        assert ".cloud.yml" in msg

    def test_v03_meta_version(self, v03_registry_dir: Path):
        msg = detect_legacy_residue(v03_registry_dir, "arc")
        assert msg is not None
        assert "0.3" in msg

    def test_v04_passes(self, registry_dir: Path):
        msg = detect_legacy_residue(registry_dir, "arc")
        assert msg is None

    def test_load_main_rejects_v03(self, v03_registry_dir: Path):
        with pytest.raises(RegistryLoadError):
            load_main(v03_registry_dir / "sync" / "arc.yml")


def test_snapshot_path_in_compiled(tmp_path: Path):
    assert snapshot_path(tmp_path, "arc") == tmp_path / ".compiled" / "arc.cloud.yml"
