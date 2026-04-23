"""Tests for merge, diff_against_cloud, validation, and cloud.yml writeback."""

from __future__ import annotations

from pathlib import Path

import pytest

from sync_compiler.cloud import CloudDrive
from sync_compiler.loader import load_cloud, load_cloud_raw, load_main
from sync_compiler.models import Drive
from sync_compiler.registry import (
    apply_diff_to_cloud_doc,
    diff_against_cloud,
    merge,
    slugify,
    validate_registry,
)
from sync_compiler.writer import atomic_write_yaml, new_cloud_document

# ── merge ─────────────────────────────────────────────────────────────────────

class TestMerge:
    def test_with_cloud(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        cloud, _ = load_cloud(valid_dir / "arc.cloud.yml")  # type: ignore[misc]
        reg = merge(main, cloud)
        assert reg.org == "arc"
        assert len(reg.accounts) == 1
        assert len(reg.accounts[0].drives) == 3

    def test_without_cloud(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        reg = merge(main, None)
        assert reg.org == "arc"
        assert len(reg.accounts) == 1
        assert reg.accounts[0].drives == []

    def test_defaults_passthrough(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        reg = merge(main, None)
        assert reg.accounts[0].sync_defaults.schedule == "*:0/15"
        assert "--fast-list" in reg.accounts[0].sync_defaults.sync_flags


# ── slugify ───────────────────────────────────────────────────────────────────

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


# ── diff_against_cloud ────────────────────────────────────────────────────────

def _drive(
    id: str, cloud_name: str = "x", local_name: str = "x",
    enabled: bool = True, status: str | None = None,
) -> Drive:
    return Drive(
        id=id, cloud_name=cloud_name, local_name=local_name,
        enabled=enabled, overrides={}, description=None, status=status,  # type: ignore[arg-type]
    )


class TestDiff:
    def test_all_new(self):
        diff = diff_against_cloud(
            "drive", [],
            [CloudDrive(id="a", name="A"), CloudDrive(id="b", name="B")],
        )
        assert len(diff.new) == 2
        assert diff.missing == []

    def test_rename(self):
        known = [_drive("a", cloud_name="OldName", local_name="a")]
        diff = diff_against_cloud("drive", known, [CloudDrive(id="a", name="NewName")])
        assert diff.new == []
        assert len(diff.renamed) == 1
        assert diff.renamed[0][1].name == "NewName"

    def test_missing(self):
        known = [_drive("a", cloud_name="A", local_name="a")]
        diff = diff_against_cloud("drive", known, [])
        assert len(diff.missing) == 1
        assert diff.missing[0].id == "a"

    def test_missing_not_redetected_when_already_marked(self):
        known = [_drive("a", cloud_name="A", local_name="a", status="missing_from_cloud")]
        diff = diff_against_cloud("drive", known, [])
        # Already marked missing — not reported again
        assert diff.missing == []

    def test_reappeared(self):
        known = [_drive("a", cloud_name="A", local_name="a", status="missing_from_cloud")]
        diff = diff_against_cloud("drive", known, [CloudDrive(id="a", name="A")])
        assert len(diff.reappeared) == 1
        assert diff.missing == []

    def test_no_change(self):
        known = [_drive("a", cloud_name="A", local_name="a")]
        diff = diff_against_cloud("drive", known, [CloudDrive(id="a", name="A")])
        assert not diff.new and not diff.renamed and not diff.missing and not diff.reappeared


# ── Validation ────────────────────────────────────────────────────────────────

class TestValidation:
    def test_valid_fixture_passes(self, valid_dir):
        main, _ = load_main(valid_dir / "arc.yml")
        cloud, _ = load_cloud(valid_dir / "arc.cloud.yml")  # type: ignore[misc]
        result = validate_registry(
            main, cloud, valid_dir / "arc.yml", valid_dir / "arc.cloud.yml"
        )
        assert result.ok, [str(e) for e in result.errors]

    def test_missing_cloud_warns(self, valid_dir, tmp_path):
        main, _ = load_main(valid_dir / "arc.yml")
        fake_cloud_path = tmp_path / "arc.cloud.yml"
        result = validate_registry(main, None, valid_dir / "arc.yml", fake_cloud_path)
        assert result.ok
        assert len(result.warnings) == 1
        assert "does not exist" in result.warnings[0].message

    def test_org_mismatch(self, valid_dir, tmp_path):
        from sync_compiler.models import RegistryCloud
        main, _ = load_main(valid_dir / "arc.yml")
        bad_cloud = RegistryCloud.model_validate({
            "meta": {"version": "0.2"},
            "org": "cpf",
            "accounts": [],
        })
        result = validate_registry(
            main, bad_cloud, valid_dir / "arc.yml", tmp_path / "arc.cloud.yml"
        )
        assert not result.ok
        assert any("org mismatch" in str(e) for e in result.errors)

    def test_duplicate_local_name(self, valid_dir, tmp_path):
        from sync_compiler.models import RegistryCloud
        main, _ = load_main(valid_dir / "arc.yml")
        bad_cloud = RegistryCloud.model_validate({
            "meta": {"version": "0.2"},
            "org": "arc",
            "accounts": [{
                "remote_name": "drive",
                "drives": [
                    {"id": "a", "cloud_name": "A", "local_name": "dup", "enabled": True},
                    {"id": "b", "cloud_name": "B", "local_name": "dup", "enabled": True},
                ],
            }],
        })
        result = validate_registry(
            main, bad_cloud, valid_dir / "arc.yml", tmp_path / "arc.cloud.yml"
        )
        assert not result.ok
        assert any("local_name" in str(e) for e in result.errors)

    def test_duplicate_id(self, valid_dir, tmp_path):
        from sync_compiler.models import RegistryCloud
        main, _ = load_main(valid_dir / "arc.yml")
        bad_cloud = RegistryCloud.model_validate({
            "meta": {"version": "0.2"},
            "org": "arc",
            "accounts": [{
                "remote_name": "drive",
                "drives": [
                    {"id": "dup", "cloud_name": "A", "local_name": "a", "enabled": True},
                    {"id": "dup", "cloud_name": "B", "local_name": "b", "enabled": True},
                ],
            }],
        })
        result = validate_registry(
            main, bad_cloud, valid_dir / "arc.yml", tmp_path / "arc.cloud.yml"
        )
        assert not result.ok
        assert any("appears twice" in str(e) for e in result.errors)

    def test_cloud_references_unknown_account(self, valid_dir, tmp_path):
        from sync_compiler.models import RegistryCloud
        main, _ = load_main(valid_dir / "arc.yml")
        bad_cloud = RegistryCloud.model_validate({
            "meta": {"version": "0.2"},
            "org": "arc",
            "accounts": [{"remote_name": "nonexistent", "drives": []}],
        })
        result = validate_registry(
            main, bad_cloud, valid_dir / "arc.yml", tmp_path / "arc.cloud.yml"
        )
        assert not result.ok
        assert any("no matching entry" in str(e) for e in result.errors)

    def test_schedule_warning(self, valid_dir, tmp_path):
        """Schedules firing every 2 min should warn, not fail."""
        from sync_compiler.models import RegistryMain
        main_raw, _ = load_main(valid_dir / "arc.yml")
        # Tighten schedule by round-tripping via pydantic
        d = main_raw.model_dump()
        d["accounts"][0]["sync_defaults"]["schedule"] = "*:0/2"
        tight = RegistryMain.model_validate(d)
        result = validate_registry(
            tight, None, valid_dir / "arc.yml", tmp_path / "arc.cloud.yml"
        )
        assert result.ok  # Warning, not error
        assert any("5 minutes" in str(w) for w in result.warnings)


# ── apply_diff_to_cloud_doc + atomic writeback ────────────────────────────────

class TestWriteback:
    def test_round_trip_preserves_comments(self, tmp_path: Path, valid_dir: Path):
        import shutil
        src = valid_dir / "arc.cloud.yml"
        dst = tmp_path / "arc.cloud.yml"
        shutil.copy(src, dst)

        doc = load_cloud_raw(dst)
        atomic_write_yaml(dst, doc)

        reloaded = load_cloud_raw(dst)
        assert reloaded["org"] == "arc"
        assert len(reloaded["accounts"][0]["drives"]) == 3

    def test_apply_adds_new_drive(self, tmp_path: Path, valid_dir: Path):
        import shutil
        dst = tmp_path / "arc.cloud.yml"
        shutil.copy(valid_dir / "arc.cloud.yml", dst)

        doc = load_cloud_raw(dst)
        diff = diff_against_cloud(
            "drive",
            [
                _drive("0AM0lOfo8XiIBUk9PVA", "ARC Academy", "academy"),
                _drive("0ABO9zZb-4pBvUk9PVA", "Global Media", "global_media"),
                _drive("0AHW2VHH_fZemUk9PVA", "Global", "global", enabled=False),
            ],
            [
                CloudDrive(id="0AM0lOfo8XiIBUk9PVA", name="ARC Academy"),
                CloudDrive(id="0ABO9zZb-4pBvUk9PVA", name="Global Media"),
                CloudDrive(id="0AHW2VHH_fZemUk9PVA", name="Global"),
                CloudDrive(id="0NEW_ID", name="New Research"),
            ],
        )
        existing = {"academy", "global_media", "global"}
        apply_diff_to_cloud_doc(doc, [diff], existing, "2026-04-23T10:00:00Z", "sync-compile")
        atomic_write_yaml(dst, doc)

        reloaded, _ = load_cloud(dst)  # type: ignore[misc]
        drives = reloaded.accounts[0].drives
        assert len(drives) == 4
        new_drive = next(d for d in drives if d.id == "0NEW_ID")
        assert new_drive.enabled is False
        assert new_drive.local_name == "new_research"

    def test_apply_marks_missing(self, tmp_path: Path, valid_dir: Path):
        import shutil
        dst = tmp_path / "arc.cloud.yml"
        shutil.copy(valid_dir / "arc.cloud.yml", dst)

        doc = load_cloud_raw(dst)
        diff = diff_against_cloud(
            "drive",
            [_drive("0ABO9zZb-4pBvUk9PVA", "Global Media", "global_media")],
            [],
        )
        apply_diff_to_cloud_doc(
            doc, [diff], {"global_media"}, "2026-04-23T10:00:00Z", "sync-compile"
        )
        atomic_write_yaml(dst, doc)

        reloaded, _ = load_cloud(dst)  # type: ignore[misc]
        missing_drive = next(
            d for d in reloaded.accounts[0].drives if d.id == "0ABO9zZb-4pBvUk9PVA"
        )
        assert missing_drive.enabled is False
        assert missing_drive.status == "missing_from_cloud"

    def test_new_document_from_scratch(self, tmp_path: Path):
        dst = tmp_path / "new_org.cloud.yml"
        doc = new_cloud_document("new_org", "2026-04-23T10:00:00Z", "sync-compile")
        atomic_write_yaml(dst, doc)
        reloaded, _ = load_cloud(dst)  # type: ignore[misc]
        assert reloaded.org == "new_org"
        assert reloaded.accounts == []

    def test_uniquify_new_local_names(self, tmp_path: Path):
        """Two new drives with colliding slugs must produce distinct local_names."""
        dst = tmp_path / "arc.cloud.yml"
        doc = new_cloud_document("arc", "2026-04-23T10:00:00Z", "sync-compile")
        diff = diff_against_cloud(
            "drive", [],
            [CloudDrive(id="1", name="Data"), CloudDrive(id="2", name="Data")],
        )
        apply_diff_to_cloud_doc(doc, [diff], set(), "2026-04-23T10:00:00Z", "sync-compile")
        atomic_write_yaml(dst, doc)

        reloaded, _ = load_cloud(dst)  # type: ignore[misc]
        names = [d.local_name for d in reloaded.accounts[0].drives]
        assert len(set(names)) == 2, f"expected distinct local_names, got {names}"
