"""CLI smoke tests + end-to-end through the operations layer."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from sync_compiler.cli import cli


def _invoke(args: list[str]) -> tuple[int, str, str]:
    runner = CliRunner()
    result = runner.invoke(cli, args, catch_exceptions=False)
    stderr = getattr(result, "stderr", "") or ""
    return result.exit_code, result.stdout, stderr


class TestCompileCommand:
    def test_compile_produces_plan(self, registry_dir: Path):
        code, out, err = _invoke([
            "compile", "-r", str(registry_dir), "--org", "arc",
        ])
        assert code == 0, f"stderr: {err}"
        output = registry_dir / ".compiled" / "compiled_sync_plan_arc.yml"
        assert output.exists()
        data = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert data["org"] == "arc"
        assert data["meta"]["schema_version"] == "0.2"
        assert len(data["rclone_remotes"]) == 2
        assert len(data["sync_instances"]) == 3

    def test_check_does_not_write(self, registry_dir: Path):
        code, _, _ = _invoke([
            "compile", "-r", str(registry_dir), "--org", "arc", "--check",
        ])
        assert code == 0
        assert not (registry_dir / ".compiled" / "compiled_sync_plan_arc.yml").exists()

    def test_compile_with_missing_cloud_succeeds(self, registry_dir_no_cloud: Path):
        code, out, err = _invoke([
            "compile", "-r", str(registry_dir_no_cloud), "--org", "arc",
        ])
        assert code == 0, f"stderr: {err}"
        output = registry_dir_no_cloud / ".compiled" / "compiled_sync_plan_arc.yml"
        assert output.exists()
        data = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert data["sync_instances"] == []
        assert "does not exist" in err

    def test_compile_without_org_fails(self, registry_dir: Path):
        code, _, err = _invoke(["compile", "-r", str(registry_dir)])
        assert code != 0
        assert "org" in err.lower()

    def test_output_path_override(self, registry_dir: Path, tmp_path: Path):
        custom = tmp_path / "custom_plan.yml"
        code, _, err = _invoke([
            "compile", "-r", str(registry_dir), "--org", "arc", "--output", str(custom),
        ])
        assert code == 0, err
        assert custom.exists()

    def test_json_format(self, registry_dir: Path, tmp_path: Path):
        import json
        custom = tmp_path / "plan.json"
        code, _, err = _invoke([
            "compile", "-r", str(registry_dir), "--org", "arc",
            "--format", "json", "--output", str(custom),
        ])
        assert code == 0, err
        data = json.loads(custom.read_text(encoding="utf-8"))
        assert data["org"] == "arc"


class TestValidateCommand:
    def test_validate_passes(self, registry_dir: Path):
        code, _, _ = _invoke(["validate", "-r", str(registry_dir), "--org", "arc"])
        assert code == 0

    def test_validate_rejects_bad_schema(self, registry_dir: Path):
        """Tamper with schema version to trigger failure."""
        main = registry_dir / "sync" / "arc.yml"
        text = main.read_text(encoding="utf-8").replace('version: "0.2"', 'version: "0.9"', 1)
        main.write_text(text, encoding="utf-8")

        code, _, err = _invoke(["validate", "-r", str(registry_dir), "--org", "arc"])
        assert code == 1
        assert "schema version mismatch" in err or "0.9" in err


class TestDiscoverCommand:
    def test_discover_dry_run_no_changes(
        self, registry_dir: Path, monkeypatch,
    ):
        """When cloud returns exactly the drives already in the registry, no-op."""
        from sync_compiler import operations
        from sync_compiler.cloud import CloudDrive

        class FakeProvider:
            def list_drives(self, account):
                return [
                    CloudDrive(id="0AM0lOfo8XiIBUk9PVA", name="ARC Academy"),
                    CloudDrive(id="0ABO9zZb-4pBvUk9PVA", name="Global Media"),
                    CloudDrive(id="0AHW2VHH_fZemUk9PVA", name="Global"),
                ]

        monkeypatch.setattr(
            operations, "default_provider_factory", lambda reg: FakeProvider(),
        )

        code, out, _ = _invoke([
            "discover", "-r", str(registry_dir), "--org", "arc", "--dry-run",
        ])
        assert code == 0
        assert "No changes" in out or "no changes" in out.lower()

    def test_discover_detects_new_drive(
        self, registry_dir: Path, monkeypatch,
    ):
        from sync_compiler import operations
        from sync_compiler.cloud import CloudDrive

        class FakeProvider:
            def list_drives(self, account):
                return [
                    CloudDrive(id="0AM0lOfo8XiIBUk9PVA", name="ARC Academy"),
                    CloudDrive(id="0ABO9zZb-4pBvUk9PVA", name="Global Media"),
                    CloudDrive(id="0AHW2VHH_fZemUk9PVA", name="Global"),
                    CloudDrive(id="0NEW", name="New Project"),
                ]

        monkeypatch.setattr(
            operations, "default_provider_factory", lambda reg: FakeProvider(),
        )

        code, out, _ = _invoke([
            "discover", "-r", str(registry_dir), "--org", "arc", "--dry-run",
        ])
        assert code == 0
        assert "New Project" in out
        assert "NEW" in out.upper()

    def test_discover_writes_with_yes(self, registry_dir: Path, monkeypatch):
        from sync_compiler import operations
        from sync_compiler.cloud import CloudDrive
        from sync_compiler.loader import load_cloud

        class FakeProvider:
            def list_drives(self, account):
                return [
                    CloudDrive(id="0AM0lOfo8XiIBUk9PVA", name="ARC Academy"),
                    CloudDrive(id="0ABO9zZb-4pBvUk9PVA", name="Global Media"),
                    CloudDrive(id="0AHW2VHH_fZemUk9PVA", name="Global"),
                    CloudDrive(id="0NEW", name="New Project"),
                ]

        monkeypatch.setattr(
            operations, "default_provider_factory", lambda reg: FakeProvider(),
        )

        code, _, _ = _invoke([
            "discover", "-r", str(registry_dir), "--org", "arc", "--yes",
        ])
        assert code == 0

        cloud_path = registry_dir / "sync" / "arc.cloud.yml"
        reloaded, _ = load_cloud(cloud_path)  # type: ignore[misc]
        assert len(reloaded.accounts[0].drives) == 4
        new_drive = next(d for d in reloaded.accounts[0].drives if d.id == "0NEW")
        assert new_drive.enabled is False

    def test_discover_from_scratch(self, registry_dir_no_cloud: Path, monkeypatch):
        """With no cloud.yml, discover creates one from cloud state."""
        from sync_compiler import operations
        from sync_compiler.cloud import CloudDrive
        from sync_compiler.loader import load_cloud

        class FakeProvider:
            def list_drives(self, account):
                return [CloudDrive(id="0AM0lOfo8XiIBUk9PVA", name="ARC Academy")]

        monkeypatch.setattr(
            operations, "default_provider_factory", lambda reg: FakeProvider(),
        )

        code, _, _ = _invoke([
            "discover", "-r", str(registry_dir_no_cloud), "--org", "arc", "--yes",
        ])
        assert code == 0

        cloud_path = registry_dir_no_cloud / "sync" / "arc.cloud.yml"
        assert cloud_path.exists()
        reloaded, _ = load_cloud(cloud_path)  # type: ignore[misc]
        assert reloaded.org == "arc"
        assert len(reloaded.accounts[0].drives) == 1
        assert reloaded.accounts[0].drives[0].enabled is False


class TestRootInvocation:
    def test_no_args_shows_help(self):
        code, out, _ = _invoke([])
        assert code == 0
        assert "compile" in out.lower()
