"""compiled-sync-plan 0.5 — folder scopes, oauth token reference, --max-delete.

Contract: components/sync-compile/docs/provides/compiled-sync-plan-v0_5.md
Design:   architecture/seat-data-sharing-design-v0_2.md §5
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from sync_compiler.compiler import compile_plan
from sync_compiler.errors import RegistryLoadError
from sync_compiler.loader import load_agent_registry, load_main
from sync_compiler.models import DEFAULT_MAX_DELETE, Auth, DriveFolder

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def job_registry(tmp_path: Path) -> Path:
    sync = tmp_path / "sync"
    sync.mkdir(parents=True)
    shutil.copy(FIXTURES / "valid" / "job.yml", sync / "job.yml")
    return sync / "job.yml"


def _bisync(plan, name_suffix: str):
    return next(i for i in plan.sync_instances if i.name.endswith(name_suffix))


# ── 3. --max-delete, on EVERY bisync ─────────────────────────────────────────

class TestMaxDelete:
    """The bound that closes the logged unbounded-delete defect."""

    def test_default_is_50_by_operator_ruling(self) -> None:
        assert DEFAULT_MAX_DELETE == 50

    def test_emitted_on_agent_surfaces(self, registry_dir: Path) -> None:
        """The existing agent scratch/memory jobs gain the bound too.

        Fails against 0.4: BISYNC_BASELINE_FLAGS carried no --max-delete at all.
        """
        reg, h = load_main(registry_dir / "sync" / "top.yml")
        agents, _ = load_agent_registry(registry_dir / "agent_registry.yml")
        plan = compile_plan(reg, "top.yml", h, agent_registry=agents)

        bisyncs = [i for i in plan.sync_instances
                   if i.mode == "bisync" and i.enabled and i.env_vars]
        assert bisyncs, "fixture should produce at least one agent bisync instance"
        for inst in bisyncs:
            assert "--max-delete 50" in inst.env_vars["BISYNC_FLAGS"]

    def test_emitted_on_folder_scope(self, job_registry: Path) -> None:
        reg, h = load_main(job_registry)
        plan = compile_plan(reg, "job.yml", h)
        assert "--max-delete 50" in _bisync(plan, "mico_data").env_vars["BISYNC_FLAGS"]

    def test_per_scope_override_wins(self, job_registry: Path) -> None:
        reg, h = load_main(job_registry)
        reg.drive_folders[0].max_delete = 5
        plan = compile_plan(reg, "job.yml", h)
        flags = _bisync(plan, "mico_data").env_vars["BISYNC_FLAGS"]
        assert "--max-delete 5" in flags
        assert "--max-delete 50" not in flags

    @pytest.mark.parametrize("bad", [-1, 0])
    def test_unlimited_and_zero_are_refused(self, bad: int) -> None:
        """-1 is rclone's 'unlimited' — the exact condition this field prevents."""
        with pytest.raises(ValidationError, match="max_delete must be at least 1"):
            DriveFolder(
                name="x", remote="r", folder="F",
                local_path="/mnt/raid/job/x", max_delete=bad,
            )


# ── 2. auth.type: oauth, by token FILE reference ─────────────────────────────

class TestOAuthTokenReference:

    def test_oauth_requires_token_file(self) -> None:
        with pytest.raises(ValidationError, match="requires token_file"):
            Auth(type="oauth")

    def test_oauth_rejects_service_account_file(self) -> None:
        with pytest.raises(ValidationError, match="must not set service_account_file"):
            Auth(type="oauth", token_file="/root/.kf/t.json",
                 service_account_file="/etc/rclone-sa/x.json")

    def test_service_account_rejects_token_file(self) -> None:
        with pytest.raises(ValidationError, match="must not set token_file"):
            Auth(type="service_account", service_account_file="/etc/rclone-sa/x.json",
                 token_file="/root/.kf/t.json")

    def test_token_file_must_be_absolute(self) -> None:
        with pytest.raises(ValidationError, match="token_file must be an absolute path"):
            Auth(type="oauth", token_file="relative/t.json")

    def test_remote_carries_token_file_not_service_account(self, job_registry: Path) -> None:
        reg, h = load_main(job_registry)
        plan = compile_plan(reg, "job.yml", h)
        remote = next(r for r in plan.rclone_remotes if r.name == "ojb_drive")
        assert remote.token_file == "/root/.kf/drive-token-ojb.json"
        assert remote.service_account_file is None

    def test_no_token_VALUE_ever_reaches_the_plan(self, job_registry: Path, tmp_path: Path) -> None:
        """A path is compiled; a secret is not. Guards the contract's promise."""
        token = tmp_path / "token.json"
        token.write_text('{"refresh_token": "SUPERSECRETVALUE"}')
        reg, h = load_main(job_registry)
        reg.accounts[0].auth.token_file = str(token)
        plan = compile_plan(reg, "job.yml", h)

        import json

        from sync_compiler.emitter import plan_to_dict

        assert "SUPERSECRETVALUE" not in json.dumps(plan_to_dict(plan))


# ── 1. Folder-shaped two-way scope ───────────────────────────────────────────

class TestFolderScope:

    def test_emits_one_bisync_instance(self, job_registry: Path) -> None:
        reg, h = load_main(job_registry)
        plan = compile_plan(reg, "job.yml", h)
        inst = _bisync(plan, "mico_data")
        assert inst.name == "job-mico_data"
        assert inst.mode == "bisync"
        assert inst.enabled is True
        assert inst.env_vars["LOCAL_PATH"] == "/mnt/raid/job/drive/mico_data"
        assert inst.env_vars["REMOTE_PATH"] == "ojb_drive:Mico Data"

    def test_runs_as_the_org_rclone_user_not_an_agent(self, job_registry: Path) -> None:
        """A folder scope belongs to the org, so ownership is the org's."""
        reg, h = load_main(job_registry)
        plan = compile_plan(reg, "job.yml", h)
        assert _bisync(plan, "mico_data").env_vars["RCLONE_USER"] == "rclone_job"

    def test_disabled_scope_is_a_skeleton(self, job_registry: Path) -> None:
        reg, h = load_main(job_registry)
        reg.drive_folders[0].enabled = False
        plan = compile_plan(reg, "job.yml", h)
        inst = _bisync(plan, "mico_data")
        assert inst.enabled is False
        assert inst.env_vars is None

    def test_unknown_account_is_refused_by_name(self, job_registry: Path) -> None:
        reg, h = load_main(job_registry)
        reg.drive_folders[0].remote = "nope"
        with pytest.raises(RegistryLoadError, match="which is not an account in org 'job'"):
            compile_plan(reg, "job.yml", h)

    def test_local_path_must_be_absolute(self) -> None:
        with pytest.raises(ValidationError, match="local_path must be an absolute path"):
            DriveFolder(name="x", remote="r", folder="F", local_path="relative/path")

    def test_local_directory_is_declared(self, job_registry: Path) -> None:
        reg, h = load_main(job_registry)
        plan = compile_plan(reg, "job.yml", h)
        assert any(d.path == "/mnt/raid/job/drive/mico_data" for d in plan.local_directories)

    def test_org_with_no_folder_scopes_is_unaffected(self, registry_dir_no_agents: Path) -> None:
        """0.4 registries keep compiling, and gain the delete bound for free."""
        reg, h = load_main(registry_dir_no_agents / "sync" / "arc.yml")
        plan = compile_plan(reg, "arc.yml", h)
        assert reg.drive_folders == []
        assert plan.schema_version == "0.5"
