"""CLI smoke tests + end-to-end through the operations layer."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from sync_compiler.cli import cli


def _invoke(args: list[str], input: str | None = None) -> tuple[int, str, str]:
    runner = CliRunner()
    result = runner.invoke(cli, args, input=input, catch_exceptions=False)
    stderr = getattr(result, "stderr", "") or ""
    return result.exit_code, result.stdout, stderr


class TestCompileCommand:
    def test_compile_produces_plan(self, registry_dir: Path):
        code, out, err = _invoke(["compile", "-r", str(registry_dir), "--org", "arc"])
        assert code == 0, f"stderr: {err}"
        output = registry_dir / ".compiled" / "compiled_sync_plan_arc.yml"
        assert output.exists()
        data = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert data["org"] == "arc"
        assert data["meta"]["schema_version"] == "0.3"
        assert "source_file" in data["meta"]
        assert "source_hash" in data["meta"]
        assert "source_files" not in data["meta"]  # v0.2 plural removed
        assert len(data["rclone_remotes"]) == 2
        assert len(data["sync_instances"]) == 3

    def test_check_does_not_write(self, registry_dir: Path):
        code, _, _ = _invoke(
            ["compile", "-r", str(registry_dir), "--org", "arc", "--check"]
        )
        assert code == 0
        assert not (registry_dir / ".compiled" / "compiled_sync_plan_arc.yml").exists()

    def test_v02_residue_fails_fast(self, v02_registry_dir: Path):
        code, _, err = _invoke(
            ["compile", "-r", str(v02_registry_dir), "--org", "arc"]
        )
        assert code == 2
        assert "v0.2" in err or "0.2" in err
        assert ".cloud.yml" in err

    def test_compile_without_org_fails(self, registry_dir: Path):
        code, _, err = _invoke(["compile", "-r", str(registry_dir)])
        assert code != 0
        assert "org" in err.lower()

    def test_output_path_override(self, registry_dir: Path, tmp_path: Path):
        custom = tmp_path / "custom_plan.yml"
        code, _, err = _invoke([
            "compile", "-r", str(registry_dir), "--org", "arc",
            "--output", str(custom),
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

    def test_validate_rejects_v02(self, v02_registry_dir: Path):
        code, _, err = _invoke(
            ["validate", "-r", str(v02_registry_dir), "--org", "arc"]
        )
        assert code == 2
        assert "v0.2" in err or "0.2" in err


class TestDiscoverCommand:
    def _patch_provider(self, monkeypatch, cloud_drives_payload):
        from sync_compiler import operations
        from sync_compiler.cloud import CloudDrive

        class FakeProvider:
            def list_drives(self, account):
                return [CloudDrive(**d) for d in cloud_drives_payload]

        monkeypatch.setattr(
            operations, "default_provider_factory", lambda reg: FakeProvider(),
        )

    def test_discover_dry_run_no_drift(self, registry_dir: Path, monkeypatch):
        self._patch_provider(monkeypatch, [
            {"id": "0AM0lOfo8XiIBUk9PVA", "name": "ARC Academy"},
            {"id": "0ABO9zZb-4pBvUk9PVA", "name": "Global Media"},
            {"id": "0AHW2VHH_fZemUk9PVA", "name": "Global"},
        ])
        code, out, _ = _invoke([
            "discover", "-r", str(registry_dir), "--org", "arc", "--dry-run",
        ])
        assert code == 0
        assert "3 present" in out or "no drift" in out
        # nothing written
        assert not (registry_dir / ".compiled" / "arc.cloud.yml").exists()

    def test_discover_detects_new_drive_dry_run(self, registry_dir: Path, monkeypatch):
        self._patch_provider(monkeypatch, [
            {"id": "0AM0lOfo8XiIBUk9PVA", "name": "ARC Academy"},
            {"id": "0ABO9zZb-4pBvUk9PVA", "name": "Global Media"},
            {"id": "0AHW2VHH_fZemUk9PVA", "name": "Global"},
            {"id": "0NEW", "name": "New Project"},
        ])
        code, out, _ = _invoke([
            "discover", "-r", str(registry_dir), "--org", "arc", "--dry-run",
        ])
        assert code == 0
        assert "New Project" in out
        assert "new_project" in out  # suggested_local_name
        assert "1 new" in out

    def test_discover_writes_with_yes(self, registry_dir: Path, monkeypatch):
        from sync_compiler.loader import load_snapshot
        self._patch_provider(monkeypatch, [
            {"id": "0AM0lOfo8XiIBUk9PVA", "name": "ARC Academy"},
            {"id": "0NEW", "name": "New Project"},
        ])
        code, _, _ = _invoke([
            "discover", "-r", str(registry_dir), "--org", "arc", "--yes",
        ])
        assert code == 0

        snap_path = registry_dir / ".compiled" / "arc.cloud.yml"
        assert snap_path.exists()
        snap, _ = load_snapshot(snap_path)  # type: ignore[misc]
        # 1 present (academy), 1 new (NEW), 2 missing (global, global_media)
        assert snap.org == "arc"
        statuses = [d.status for d in snap.accounts[0].drives]
        assert statuses.count("new") == 1
        assert statuses.count("missing_from_cloud") == 2
        assert statuses.count("present") == 1

    def test_discover_interactive_prompt_abort(self, registry_dir: Path, monkeypatch):
        """No --yes, user answers 'n' to confirmation -> exit 1, no write."""
        self._patch_provider(monkeypatch, [
            {"id": "0AM0lOfo8XiIBUk9PVA", "name": "ARC Academy"},
        ])
        code, out, _ = _invoke(
            ["discover", "-r", str(registry_dir), "--org", "arc"],
            input="n\n",
        )
        assert code == 1
        assert "abort" in out.lower()
        assert not (registry_dir / ".compiled" / "arc.cloud.yml").exists()

    def test_discover_interactive_prompt_accept(self, registry_dir: Path, monkeypatch):
        self._patch_provider(monkeypatch, [
            {"id": "0AM0lOfo8XiIBUk9PVA", "name": "ARC Academy"},
        ])
        code, _, _ = _invoke(
            ["discover", "-r", str(registry_dir), "--org", "arc"],
            input="y\n",
        )
        assert code == 0
        assert (registry_dir / ".compiled" / "arc.cloud.yml").exists()

    def test_discover_determinism(self, registry_dir: Path, monkeypatch):
        """Two discovers with same cloud state -> identical snapshot bodies."""
        self._patch_provider(monkeypatch, [
            {"id": "0AM0lOfo8XiIBUk9PVA", "name": "ARC Academy"},
            {"id": "0NEW", "name": "New Project"},
        ])
        snap = registry_dir / ".compiled" / "arc.cloud.yml"

        _invoke(["discover", "-r", str(registry_dir), "--org", "arc", "--yes"])
        body1 = _strip_meta(snap.read_text(encoding="utf-8"))

        _invoke(["discover", "-r", str(registry_dir), "--org", "arc", "--yes"])
        body2 = _strip_meta(snap.read_text(encoding="utf-8"))

        assert body1 == body2

    def test_discover_v02_residue_fails(self, v02_registry_dir: Path):
        code, _, err = _invoke(
            ["discover", "-r", str(v02_registry_dir), "--org", "arc", "--yes"]
        )
        assert code == 2
        assert "v0.2" in err or "0.2" in err


def _strip_meta(yaml_text: str) -> str:
    """Drop the volatile meta block (contains timestamp/hostname) for comparison."""
    lines = yaml_text.splitlines()
    out: list[str] = []
    in_meta = False
    for ln in lines:
        if ln.startswith("meta:"):
            in_meta = True
            continue
        if in_meta and (ln.startswith(" ") or ln.startswith("\t")):
            continue
        in_meta = False
        out.append(ln)
    return "\n".join(out)


class TestRootInvocation:
    def test_no_args_shows_help(self):
        code, out, _ = _invoke([])
        assert code == 0
        assert "compile" in out.lower()
