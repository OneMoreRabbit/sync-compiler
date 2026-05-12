"""Tests for pure compilation logic: override merge, env-var construction, full plan."""

from __future__ import annotations

from sync_compiler.compiler import (
    compile_plan,
    env_file_path,
    instance_name,
    resolved_sync_defaults,
    timer_override_path,
)
from sync_compiler.loader import load_main
from sync_compiler.models import Drive, SyncDefaults

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
        r = resolved_sync_defaults(self._defaults(), {"sync_flags": ["--flag-a", "--flag-c"]}, [])
        assert r.sync_flags == ["--flag-a", "--flag-b", "--flag-c"]

    def test_additional_excludes_union(self):
        r = resolved_sync_defaults(self._defaults(), {}, ["archive/**"])
        assert r.exclude_patterns == ["*.tmp", ".DS_Store", "archive/**"]

    def test_exclude_override_and_additional(self):
        r = resolved_sync_defaults(
            self._defaults(), {"exclude_patterns": ["*.bak"]}, ["archive/**"],
        )
        assert r.exclude_patterns == ["*.tmp", ".DS_Store", "*.bak", "archive/**"]


# ── Naming helpers ────────────────────────────────────────────────────────────

def _drive(local_name="academy") -> Drive:
    return Drive(
        id="0AM", cloud_name="ARC Academy", local_name=local_name,
        enabled=True, overrides={}, description=None,
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
        main, h = load_main(valid_dir / "arc.yml")
        plan = compile_plan(registry=main, source_file=str(valid_dir / "arc.yml"), source_hash=h)

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

    def test_meta_has_singular_source_fields(self, valid_dir):
        main, h = load_main(valid_dir / "arc.yml")
        plan = compile_plan(registry=main, source_file="/path/to/arc.yml", source_hash="abc")
        assert plan.source_file == "/path/to/arc.yml"
        assert plan.source_hash == "abc"
        assert plan.schema_version == "0.3"

    def test_disabled_drive_omitted_from_remotes_and_dirs(self, valid_dir):
        main, h = load_main(valid_dir / "arc.yml")
        plan = compile_plan(registry=main, source_file="x", source_hash="y")
        assert not any(r.name == "drive_global" for r in plan.rclone_remotes)
        assert not any(d.path.endswith("/global") for d in plan.local_directories)

    def test_env_vars_populated(self, valid_dir):
        main, h = load_main(valid_dir / "arc.yml")
        plan = compile_plan(registry=main, source_file="x", source_hash="y")
        academy = next(i for i in plan.sync_instances if i.name == "arc-academy")
        assert academy.env_vars is not None
        assert academy.env_vars["RCLONE_USER"] == "rclone_arc"
        assert academy.env_vars["REMOTE_NAME"] == "drive_academy"
        assert academy.env_vars["LOCAL_DEST"] == "/mnt/raid/arc/drive/academy"
        assert "--fast-list" in academy.env_vars["SYNC_FLAGS"]
        assert "--exclude=archive/**" in academy.env_vars["EXCLUDE_PATTERNS"]

    def test_sorted_output(self, valid_dir):
        main, h = load_main(valid_dir / "arc.yml")
        plan = compile_plan(registry=main, source_file="x", source_hash="y")
        assert [r.name for r in plan.rclone_remotes] == sorted(r.name for r in plan.rclone_remotes)
        assert [d.path for d in plan.local_directories] == sorted(
            d.path for d in plan.local_directories
        )
        assert [i.name for i in plan.sync_instances] == sorted(
            i.name for i in plan.sync_instances
        )

    def test_null_platform_defaults_passthrough(self, valid_dir):
        main, h = load_main(valid_dir / "arc.yml")
        plan = compile_plan(registry=main, source_file="x", source_hash="y")
        assert plan.platform.default_owner is None
        assert plan.platform.default_group is None
        assert plan.platform.default_mode is None

    def test_determinism_of_structure(self, valid_dir):
        main, h = load_main(valid_dir / "arc.yml")
        p1 = compile_plan(registry=main, source_file="x", source_hash="y")
        p2 = compile_plan(registry=main, source_file="x", source_hash="y")
        assert [r.name for r in p1.rclone_remotes] == [r.name for r in p2.rclone_remotes]
        dirs1 = [d.path for d in p1.local_directories]
        dirs2 = [d.path for d in p2.local_directories]
        assert dirs1 == dirs2
        assert [i.name for i in p1.sync_instances] == [i.name for i in p2.sync_instances]
