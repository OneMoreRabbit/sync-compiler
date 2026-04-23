"""Tests for pure compilation logic: override merge, env-var construction, full plan."""

from __future__ import annotations

from sync_compiler.compiler import (
    compile_plan,
    env_file_path,
    instance_name,
    resolved_sync_defaults,
    timer_override_path,
)
from sync_compiler.loader import load_cloud, load_main
from sync_compiler.models import Drive, SyncDefaults
from sync_compiler.registry import merge

# ── resolved_sync_defaults (override merge) ───────────────────────────────────

class TestResolvedSyncDefaults:
    def _defaults(self) -> SyncDefaults:
        return SyncDefaults(
            local_subdir="drive",
            schedule="*:0/15",
            sync_flags=["--flag-a", "--flag-b"],
            exclude_patterns=["*.tmp", ".DS_Store"],
        )

    def test_no_overrides(self):
        r = resolved_sync_defaults(self._defaults(), {}, [])
        assert r.schedule == "*:0/15"
        assert r.sync_flags == ["--flag-a", "--flag-b"]

    def test_scalar_override_replaces(self):
        r = resolved_sync_defaults(self._defaults(), {"schedule": "*:0/30"}, [])
        assert r.schedule == "*:0/30"

    def test_list_override_unions(self):
        r = resolved_sync_defaults(self._defaults(), {"sync_flags": ["--flag-c"]}, [])
        assert r.sync_flags == ["--flag-a", "--flag-b", "--flag-c"]

    def test_list_override_dedupes(self):
        """Override items already in defaults don't duplicate."""
        r = resolved_sync_defaults(self._defaults(), {"sync_flags": ["--flag-a", "--flag-c"]}, [])
        assert r.sync_flags == ["--flag-a", "--flag-b", "--flag-c"]

    def test_additional_excludes_union(self):
        r = resolved_sync_defaults(self._defaults(), {}, ["archive/**"])
        assert r.exclude_patterns == ["*.tmp", ".DS_Store", "archive/**"]

    def test_exclude_override_and_additional(self):
        r = resolved_sync_defaults(
            self._defaults(),
            {"exclude_patterns": ["*.bak"]},
            ["archive/**"],
        )
        assert r.exclude_patterns == ["*.tmp", ".DS_Store", "*.bak", "archive/**"]


# ── Artefact naming ───────────────────────────────────────────────────────────

def _drive(local_name="academy", id="0AM", cloud_name="ARC Academy", enabled=True) -> Drive:
    return Drive(
        id=id, cloud_name=cloud_name, local_name=local_name,
        enabled=enabled, overrides={}, description=None, status=None,  # type: ignore[arg-type]
    )


class TestNaming:
    def test_instance_name(self):
        assert instance_name("arc", _drive("academy")) == "arc-academy"

    def test_env_file_path(self):
        assert env_file_path("arc-academy") == "/etc/rclone-sync/arc-academy.env"

    def test_timer_override_path(self):
        assert timer_override_path("arc-academy") == (
            "/etc/systemd/system/rclone-sync@arc-academy.timer.d/schedule.conf"
        )


# ── Full plan compilation from fixture ────────────────────────────────────────

class TestCompilePlan:
    def test_plan_from_fixture(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        cloud, _ = load_cloud(valid_dir / "arc.cloud.yml")  # type: ignore[misc]
        registry = merge(main, cloud)

        plan = compile_plan(
            registry=registry,
            source_paths={"main": "x", "cloud": "y"},
            source_hashes={"main": "a", "cloud": "b"},
        )

        # Two drives enabled -> 2 remotes, 2 dirs
        assert len(plan.rclone_remotes) == 2
        assert {r.name for r in plan.rclone_remotes} == {"drive_academy", "drive_global_media"}
        assert len(plan.local_directories) == 2

        # Three drives total -> 3 instances (one disabled)
        assert len(plan.sync_instances) == 3
        disabled = [i for i in plan.sync_instances if not i.enabled]
        assert len(disabled) == 1
        assert disabled[0].name == "arc-global"
        assert disabled[0].env_vars is None

    def test_disabled_drive_still_in_sync_instances(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        cloud, _ = load_cloud(valid_dir / "arc.cloud.yml")  # type: ignore[misc]
        plan = compile_plan(
            registry=merge(main, cloud),
            source_paths={"main": "x", "cloud": "y"},
            source_hashes={"main": "a", "cloud": "b"},
        )
        # Disabled drive contributes to sync_instances but not rclone_remotes/local_directories
        disabled_name = "arc-global"
        assert any(i.name == disabled_name for i in plan.sync_instances)
        assert not any(r.name == "drive_global" for r in plan.rclone_remotes)
        assert not any(d.path.endswith("/global") for d in plan.local_directories)

    def test_env_vars_populated(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        cloud, _ = load_cloud(valid_dir / "arc.cloud.yml")  # type: ignore[misc]
        plan = compile_plan(
            registry=merge(main, cloud),
            source_paths={"main": "x", "cloud": "y"},
            source_hashes={"main": "a", "cloud": "b"},
        )
        academy = next(i for i in plan.sync_instances if i.name == "arc-academy")
        assert academy.env_vars is not None
        assert academy.env_vars["RCLONE_USER"] == "rclone_arc"
        assert academy.env_vars["REMOTE_NAME"] == "drive_academy"
        assert academy.env_vars["LOCAL_DEST"] == "/mnt/raid/arc/drive/academy"
        assert "--fast-list" in academy.env_vars["SYNC_FLAGS"]
        # additional_excludes in fixture is "archive/**"
        assert "--exclude=archive/**" in academy.env_vars["EXCLUDE_PATTERNS"]

    def test_sorted_output(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        cloud, _ = load_cloud(valid_dir / "arc.cloud.yml")  # type: ignore[misc]
        plan = compile_plan(
            registry=merge(main, cloud),
            source_paths={"main": "x", "cloud": "y"},
            source_hashes={"main": "a", "cloud": "b"},
        )
        remote_names = [r.name for r in plan.rclone_remotes]
        assert remote_names == sorted(remote_names)
        dir_paths = [d.path for d in plan.local_directories]
        assert dir_paths == sorted(dir_paths)
        instance_names = [i.name for i in plan.sync_instances]
        assert instance_names == sorted(instance_names)

    def test_null_platform_defaults_passthrough(self, valid_dir):
        """Absent default_owner/group/mode -> null in compiled plan."""
        main, _ = load_main(valid_dir / "arc.yml")
        cloud, _ = load_cloud(valid_dir / "arc.cloud.yml")  # type: ignore[misc]
        plan = compile_plan(
            registry=merge(main, cloud),
            source_paths={"main": "x", "cloud": "y"},
            source_hashes={"main": "a", "cloud": "b"},
        )
        assert plan.platform.default_owner is None
        assert plan.platform.default_group is None
        assert plan.platform.default_mode is None

    def test_empty_registry_empty_plan(self, valid_dir):
        """No cloud.yml => zero drives => zero artefacts."""
        main, _ = load_main(valid_dir / "arc.yml")
        plan = compile_plan(
            registry=merge(main, None),
            source_paths={"main": "x", "cloud": ""},
            source_hashes={"main": "a", "cloud": ""},
        )
        assert plan.rclone_remotes == []
        assert plan.local_directories == []
        assert plan.sync_instances == []

    def test_determinism(self, valid_dir):
        """Compiling twice produces the same artefact structure."""
        main, _ = load_main(valid_dir / "arc.yml")
        cloud, _ = load_cloud(valid_dir / "arc.cloud.yml")  # type: ignore[misc]
        registry = merge(main, cloud)
        plan1 = compile_plan(
            registry=registry,
            source_paths={"main": "x", "cloud": "y"},
            source_hashes={"main": "a", "cloud": "b"},
        )
        plan2 = compile_plan(
            registry=registry,
            source_paths={"main": "x", "cloud": "y"},
            source_hashes={"main": "a", "cloud": "b"},
        )
        # Artefact lists identical (compiled_at differs by wall clock)
        assert [r.name for r in plan1.rclone_remotes] == [r.name for r in plan2.rclone_remotes]
        dirs1 = [d.path for d in plan1.local_directories]
        dirs2 = [d.path for d in plan2.local_directories]
        assert dirs1 == dirs2
        assert [i.name for i in plan1.sync_instances] == [i.name for i in plan2.sync_instances]
