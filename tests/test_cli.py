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
        assert data["meta"]["schema_version"] == "0.4"
        assert "agent_registry_path" in data["meta"]
        assert "agent_registry_hash" in data["meta"]

        # 3 org-data instances (academy + global_media + disabled global)
        # + 4 agent bisync instances (research_mz × 2, finance_global × 2)
        assert len(data["sync_instances"]) == 7
        modes = {i["mode"] for i in data["sync_instances"]}
        assert modes == {"sync", "bisync"}

    def test_no_agent_registry_still_compiles(self, registry_dir_no_agents: Path):
        code, _, err = _invoke(["compile", "-r", str(registry_dir_no_agents), "--org", "arc"])
        assert code == 0, f"stderr: {err}"
        output = registry_dir_no_agents / ".compiled" / "compiled_sync_plan_arc.yml"
        data = yaml.safe_load(output.read_text(encoding="utf-8"))
        # No agent_registry → no bisync entries → 3 sync instances only
        assert all(i["mode"] == "sync" for i in data["sync_instances"])
        assert len(data["sync_instances"]) == 3
        assert "agent_registry_path" not in data["meta"]

    def test_check_does_not_write(self, registry_dir: Path):
        code, _, _ = _invoke(["compile", "-r", str(registry_dir), "--org", "arc", "--check"])
        assert code == 0
        assert not (registry_dir / ".compiled" / "compiled_sync_plan_arc.yml").exists()

    def test_legacy_v02_fails_fast(self, legacy_v02_registry_dir: Path):
        code, _, err = _invoke(["compile", "-r", str(legacy_v02_registry_dir), "--org", "arc"])
        assert code == 2
        assert "0.4" in err or "legacy" in err.lower()

    def test_legacy_v03_fails_fast(self, v03_registry_dir: Path):
        code, _, err = _invoke(["compile", "-r", str(v03_registry_dir), "--org", "arc"])
        assert code == 2
        assert "0.3" in err or "0.4" in err

    def test_compile_without_org_fails(self, registry_dir: Path):
        code, _, err = _invoke(["compile", "-r", str(registry_dir)])
        assert code != 0


class TestValidateCommand:
    def test_validate_passes(self, registry_dir: Path):
        code, _, _ = _invoke(["validate", "-r", str(registry_dir), "--org", "arc"])
        assert code == 0

    def test_validate_rejects_legacy(self, v03_registry_dir: Path):
        code, _, err = _invoke(["validate", "-r", str(v03_registry_dir), "--org", "arc"])
        assert code == 2


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
        code, out, _ = _invoke(["discover", "-r", str(registry_dir), "--org", "arc", "--dry-run"])
        assert code == 0
        assert not (registry_dir / ".compiled" / "arc.cloud.yml").exists()

    def test_discover_writes_with_yes(self, registry_dir: Path, monkeypatch):
        from sync_compiler.loader import load_snapshot
        self._patch_provider(monkeypatch, [
            {"id": "0AM0lOfo8XiIBUk9PVA", "name": "ARC Academy"},
            {"id": "0NEW", "name": "New Project"},
        ])
        code, _, _ = _invoke(["discover", "-r", str(registry_dir), "--org", "arc", "--yes"])
        assert code == 0
        snap_path = registry_dir / ".compiled" / "arc.cloud.yml"
        assert snap_path.exists()
        snap, _ = load_snapshot(snap_path)  # type: ignore[misc]
        assert snap.org == "arc"


class TestRootInvocation:
    def test_no_args_shows_help(self):
        code, out, _ = _invoke([])
        assert code == 0
        assert "compile" in out.lower()
