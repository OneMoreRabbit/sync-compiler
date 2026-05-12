"""Tests for classify_drives, validation, slugify, and v0.2 detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from sync_compiler.cloud import CloudDrive
from sync_compiler.errors import RegistryLoadError
from sync_compiler.loader import (
    detect_v02_residue,
    load_main,
    snapshot_path,
)
from sync_compiler.models import Drive
from sync_compiler.registry import (
    classify_drives,
    slugify,
    uniquify,
    validate_registry,
)

# ── slugify / uniquify ────────────────────────────────────────────────────────

class TestSlugify:
    @pytest.mark.parametrize("name,expected", [
        ("ARC Academy", "arc_academy"),
        ("Global Media", "global_media"),
        ("Finance 2026", "finance_2026"),
        ("  trim  ", "trim"),
        ("---dashes---", "dashes"),
        ("!!", "unnamed"),
    ])
    def test_slugify(self, name, expected):
        assert slugify(name) == expected


class TestUniquify:
    def test_unused(self):
        assert uniquify("foo", set()) == "foo"

    def test_taken_appends_suffix(self):
        assert uniquify("foo", {"foo"}) == "foo_2"

    def test_multiple_taken(self):
        assert uniquify("foo", {"foo", "foo_2", "foo_3"}) == "foo_4"


# ── classify_drives ───────────────────────────────────────────────────────────

def _drive(id: str, cloud_name: str = "x", local_name: str = "x", enabled: bool = True) -> Drive:
    return Drive(
        id=id, cloud_name=cloud_name, local_name=local_name,
        enabled=enabled, overrides={}, description=None,
    )


class TestClassify:
    def test_all_present(self):
        yml = [_drive("a", "A", "a"), _drive("b", "B", "b")]
        cloud = [CloudDrive(id="a", name="A"), CloudDrive(id="b", name="B")]
        result = classify_drives("drive", yml, cloud, existing_local_names={"a", "b"})
        assert result.present == 2
        assert result.new == 0
        assert result.renamed == 0
        assert result.missing_from_cloud == 0

    def test_new_gets_suggested_name(self):
        yml = []
        cloud = [CloudDrive(id="z", name="New Project")]
        result = classify_drives("drive", yml, cloud, existing_local_names=set())
        assert result.new == 1
        assert result.drives[0].status == "new"
        assert result.drives[0].suggested_local_name == "new_project"

    def test_new_collision_uniquifies(self):
        yml = [_drive("a", "Existing", "new_project")]
        cloud = [
            CloudDrive(id="a", name="Existing"),
            CloudDrive(id="z", name="New Project"),
        ]
        existing = {"new_project"}
        result = classify_drives("drive", yml, cloud, existing_local_names=existing)
        new_entry = next(d for d in result.drives if d.status == "new")
        assert new_entry.suggested_local_name == "new_project_2"

    def test_multiple_new_with_same_slug_uniquify(self):
        cloud = [
            CloudDrive(id="x", name="Data"),
            CloudDrive(id="y", name="Data"),
        ]
        result = classify_drives("drive", [], cloud, existing_local_names=set())
        new_names = [d.suggested_local_name for d in result.drives if d.status == "new"]
        assert set(new_names) == {"data", "data_2"}

    def test_renamed(self):
        yml = [_drive("a", "Old Name", "alias")]
        cloud = [CloudDrive(id="a", name="New Name")]
        result = classify_drives("drive", yml, cloud, existing_local_names={"alias"})
        assert result.renamed == 1
        entry = result.drives[0]
        assert entry.cloud_name_was == "Old Name"
        assert entry.cloud_name_now == "New Name"

    def test_missing(self):
        yml = [_drive("a", "A", "a")]
        cloud = []
        result = classify_drives("drive", yml, cloud, existing_local_names={"a"})
        assert result.missing_from_cloud == 1
        entry = result.drives[0]
        assert entry.status == "missing_from_cloud"
        assert entry.cloud_name == "A"  # last-known from <org>.yml

    def test_ordering_is_deterministic(self):
        cloud = [
            CloudDrive(id="z", name="Z"),
            CloudDrive(id="a", name="A"),
        ]
        result = classify_drives("drive", [], cloud, existing_local_names=set())
        # Both new -> sorted by id within the "new" group
        ids = [d.id for d in result.drives]
        assert ids == ["a", "z"]


# ── Validation ────────────────────────────────────────────────────────────────

class TestValidation:
    def test_valid_fixture_passes(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        result = validate_registry(main, valid_dir / "arc.yml")
        assert result.ok, [str(e) for e in result.errors]

    def test_duplicate_local_name(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        # Force a collision by post-hoc mutation
        main.accounts[0].drives[0].local_name = main.accounts[0].drives[1].local_name
        result = validate_registry(main, valid_dir / "arc.yml")
        assert not result.ok
        assert any("local_name" in str(e) for e in result.errors)

    def test_duplicate_id(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        main.accounts[0].drives[0].id = main.accounts[0].drives[1].id
        result = validate_registry(main, valid_dir / "arc.yml")
        assert not result.ok
        assert any("appears twice" in str(e) for e in result.errors)

    def test_duplicate_cloud_name_warns(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        main.accounts[0].drives[0].cloud_name = main.accounts[0].drives[1].cloud_name
        result = validate_registry(main, valid_dir / "arc.yml")
        # Still ok (no error), but a warning emitted
        assert result.ok
        assert any("cloud_name" in str(w) for w in result.warnings)

    def test_unknown_rclone_user_fails(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        main.platform.rclone_user = "ghost"
        result = validate_registry(main, valid_dir / "arc.yml")
        assert not result.ok
        assert any("rclone_user" in str(e) for e in result.errors)

    def test_tight_schedule_warns(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        main.accounts[0].sync_defaults.schedule = "*:0/2"
        result = validate_registry(main, valid_dir / "arc.yml")
        assert result.ok
        assert any("5 minutes" in str(w) for w in result.warnings)


# ── v0.2 detection ────────────────────────────────────────────────────────────

class TestV02Detection:
    def test_v02_cloud_yml_present(self, v02_registry_dir: Path):
        msg = detect_v02_residue(v02_registry_dir, "arc")
        assert msg is not None
        assert "v0.2" in msg or "v0.3" in msg
        assert ".cloud.yml" in msg

    def test_v03_registry_passes(self, registry_dir: Path):
        msg = detect_v02_residue(registry_dir, "arc")
        assert msg is None

    def test_load_main_rejects_v02_version(self, tmp_path: Path):
        sync = tmp_path / "sync"
        sync.mkdir()
        (sync / "arc.yml").write_text("""meta:
  version: "0.2"
org: arc
platform:
  rclone_user: rclone_arc
  local_base: /mnt/raid/arc
  rclone_config: /var/lib/rclone/rclone.conf
accounts:
  - remote_name: drive
    provider: drive
    auth: {type: service_account, service_account_file: /etc/sa.json}
    sync_defaults: {local_subdir: drive, schedule: "*:0/15"}
""", encoding="utf-8")
        with pytest.raises(RegistryLoadError):
            load_main(sync / "arc.yml")


# ── snapshot_path ─────────────────────────────────────────────────────────────

def test_snapshot_path_in_compiled(tmp_path: Path):
    p = snapshot_path(tmp_path, "arc")
    assert p == tmp_path / ".compiled" / "arc.cloud.yml"
