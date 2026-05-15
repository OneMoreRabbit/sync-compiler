"""Tests for compile logic: override merge, env-var construction, mode, bisync, plan shape."""

from __future__ import annotations

from sync_compiler.compiler import (
    bisync_instance_name,
    compile_plan,
    conflict_resolve_flags,
    instance_name,
    resolved_sync_defaults,
)
from sync_compiler.loader import load_agent_registry, load_main
from sync_compiler.models import Drive, SyncDefaults

# ── Override merge ────────────────────────────────────────────────────────────

class TestResolvedSyncDefaults:
    def _defaults(self) -> SyncDefaults:
        return SyncDefaults(local_subdir="drive", schedule="*:0/15",
                            sync_flags=["--flag-a", "--flag-b"],
                            exclude_patterns=["*.tmp", ".DS_Store"])

    def test_no_overrides(self):
        r = resolved_sync_defaults(self._defaults(), {}, [])
        assert r.schedule == "*:0/15"

    def test_scalar_replace(self):
        r = resolved_sync_defaults(self._defaults(), {"schedule": "*:0/30"}, [])
        assert r.schedule == "*:0/30"

    def test_list_union(self):
        r = resolved_sync_defaults(self._defaults(), {"sync_flags": ["--flag-c"]}, [])
        assert r.sync_flags == ["--flag-a", "--flag-b", "--flag-c"]

    def test_additional_excludes(self):
        r = resolved_sync_defaults(self._defaults(), {}, ["archive/**"])
        assert r.exclude_patterns == ["*.tmp", ".DS_Store", "archive/**"]


# ── Naming + bisync flag helpers ──────────────────────────────────────────────

def _drive(local_name="academy") -> Drive:
    return Drive(id="0AM", cloud_name="ARC Academy", local_name=local_name,
                 enabled=True, overrides={}, description=None)


class TestNaming:
    def test_instance_name(self):
        assert instance_name("arc", _drive("academy")) == "arc-academy"

    def test_bisync_instance_name(self):
        assert bisync_instance_name("arc", "agent_x", "scratch") == "arc-agent_x-scratch"


class TestConflictResolveFlags:
    def test_newer(self):
        assert conflict_resolve_flags("newer") == "--conflict-resolve=newer"

    def test_suffix(self):
        flags = conflict_resolve_flags("suffix")
        assert "--conflict-resolve=newer" in flags
        assert "--conflict-loser=pathname" in flags
        assert "--conflict-suffix=.conflict" in flags


# ── Full plan compilation ────────────────────────────────────────────────────

def _load_arc(valid_dir):
    main, h = load_main(valid_dir / "arc.yml")
    agents_tuple = load_agent_registry(valid_dir / "agent_registry.yml")
    assert agents_tuple is not None
    agents, ah = agents_tuple
    return main, h, agents, ah


class TestCompilePlan:
    def test_org_data_part_unchanged(self, valid_dir):
        """The org-data portion of the plan should be the same as v0.3 (modulo mode field)."""
        main, h, agents, ah = _load_arc(valid_dir)
        plan = compile_plan(registry=main, source_file=str(valid_dir / "arc.yml"),
                            source_hash=h, agent_registry=agents,
                            agent_registry_path=str(valid_dir / "agent_registry.yml"),
                            agent_registry_hash=ah)
        assert len(plan.rclone_remotes) == 2  # academy + global_media enabled
        assert {r.name for r in plan.rclone_remotes} == {"drive_academy", "drive_global_media"}

    def test_all_instances_have_explicit_mode(self, valid_dir):
        """Every sync_instance must have mode set (default 'sync', new 'bisync')."""
        main, h, agents, ah = _load_arc(valid_dir)
        plan = compile_plan(registry=main, source_file="x", source_hash="y",
                            agent_registry=agents, agent_registry_path="z",
                            agent_registry_hash="w")
        modes = {i.mode for i in plan.sync_instances}
        assert modes == {"sync", "bisync"}
        for i in plan.sync_instances:
            assert i.mode in ("sync", "bisync")

    def test_bisync_instances_for_arc_agents(self, valid_dir):
        main, h, agents, ah = _load_arc(valid_dir)
        plan = compile_plan(registry=main, source_file="x", source_hash="y",
                            agent_registry=agents, agent_registry_path="z",
                            agent_registry_hash="w")
        bisync = [i for i in plan.sync_instances if i.mode == "bisync"]

        # agent_arc_research_mz: scratch (enabled) + memory (disabled) → 2 entries
        # agent_arc_finance_global: scratch + memory both enabled → 2 entries
        # agent_arc_quiet: no cloud_sync → 0 entries
        # agent_cpf_advisory: wrong org → 0 entries
        assert len(bisync) == 4
        names = {i.name for i in bisync}
        assert names == {
            "arc-agent_arc_research_mz-scratch",
            "arc-agent_arc_research_mz-memory",
            "arc-agent_arc_finance_global-scratch",
            "arc-agent_arc_finance_global-memory",
        }

    def test_bisync_env_vars(self, valid_dir):
        main, h, agents, ah = _load_arc(valid_dir)
        plan = compile_plan(registry=main, source_file="x", source_hash="y",
                            agent_registry=agents, agent_registry_path="z",
                            agent_registry_hash="w")
        research_scratch = next(i for i in plan.sync_instances
                                if i.name == "arc-agent_arc_research_mz-scratch")
        assert research_scratch.enabled is True
        assert research_scratch.env_vars is not None
        assert research_scratch.env_vars["RCLONE_USER"] == "agent_arc_research_mz"
        assert research_scratch.env_vars["LOCAL_PATH"] == (
            "/mnt/raid/arc/agents/agent_arc_research_mz/scratch/"
        )
        assert "drive_research_mz:Agents" in research_scratch.env_vars["REMOTE_PATH"]
        assert "--conflict-resolve=newer" in research_scratch.env_vars["BISYNC_FLAGS"]
        assert "--check-access" in research_scratch.env_vars["BISYNC_FLAGS"]

    def test_bisync_uses_rclone_bisync_paths(self, valid_dir):
        main, h, agents, ah = _load_arc(valid_dir)
        plan = compile_plan(registry=main, source_file="x", source_hash="y",
                            agent_registry=agents, agent_registry_path="z",
                            agent_registry_hash="w")
        finance_scratch = next(i for i in plan.sync_instances
                               if i.name == "arc-agent_arc_finance_global-scratch")
        assert finance_scratch.env_file_path is not None
        assert "/etc/rclone-bisync/" in finance_scratch.env_file_path
        assert finance_scratch.timer_override_path is not None
        assert "rclone-bisync@" in finance_scratch.timer_override_path

    def test_bisync_disabled_emits_skeleton(self, valid_dir):
        main, h, agents, ah = _load_arc(valid_dir)
        plan = compile_plan(registry=main, source_file="x", source_hash="y",
                            agent_registry=agents, agent_registry_path="z",
                            agent_registry_hash="w")
        # research_mz.memory has enabled: false
        research_mem = next(i for i in plan.sync_instances
                            if i.name == "arc-agent_arc_research_mz-memory")
        assert research_mem.enabled is False
        assert research_mem.mode == "bisync"
        assert research_mem.env_vars is None

    def test_suffix_conflict_policy(self, valid_dir):
        main, h, agents, ah = _load_arc(valid_dir)
        plan = compile_plan(registry=main, source_file="x", source_hash="y",
                            agent_registry=agents, agent_registry_path="z",
                            agent_registry_hash="w")
        finance_scratch = next(i for i in plan.sync_instances
                               if i.name == "arc-agent_arc_finance_global-scratch")
        assert "--conflict-suffix=.conflict" in finance_scratch.env_vars["BISYNC_FLAGS"]

    def test_no_agents_no_bisync(self, valid_dir):
        """Compile without agent_registry → only org-data instances, no bisync."""
        main, h = load_main(valid_dir / "arc.yml")
        plan = compile_plan(registry=main, source_file="x", source_hash="y")
        assert all(i.mode == "sync" for i in plan.sync_instances)

    def test_determinism(self, valid_dir):
        main, h, agents, ah = _load_arc(valid_dir)
        p1 = compile_plan(registry=main, source_file="x", source_hash="y",
                          agent_registry=agents)
        p2 = compile_plan(registry=main, source_file="x", source_hash="y",
                          agent_registry=agents)
        names1 = [i.name for i in p1.sync_instances]
        names2 = [i.name for i in p2.sync_instances]
        assert names1 == names2

    def test_sorted_output(self, valid_dir):
        main, h, agents, ah = _load_arc(valid_dir)
        plan = compile_plan(registry=main, source_file="x", source_hash="y",
                            agent_registry=agents)
        names = [i.name for i in plan.sync_instances]
        assert names == sorted(names)

    def test_meta_v04_with_agent_registry(self, valid_dir):
        main, h, agents, ah = _load_arc(valid_dir)
        plan = compile_plan(registry=main, source_file="/path/arc.yml", source_hash="abc",
                            agent_registry=agents,
                            agent_registry_path="/path/agent_registry.yml",
                            agent_registry_hash="def")
        assert plan.schema_version == "0.4"
        assert plan.source_file == "/path/arc.yml"
        assert plan.source_hash == "abc"
        assert plan.agent_registry_path == "/path/agent_registry.yml"
        assert plan.agent_registry_hash == "def"

    def test_accountless_top_org_bisync_only(self, valid_dir):
        """`top` has no accounts — plan has zero remotes/dirs, only agent bisync."""
        main, h = load_main(valid_dir / "top.yml")
        agents_tuple = load_agent_registry(valid_dir / "agent_registry.yml")
        assert agents_tuple is not None
        agents, ah = agents_tuple
        plan = compile_plan(registry=main, source_file="x", source_hash="y",
                            agent_registry=agents)
        # No org-data: zero remotes, zero local dirs.
        assert plan.rclone_remotes == []
        assert plan.local_directories == []
        # Only the top-org agent's bisync instance.
        assert len(plan.sync_instances) == 1
        inst = plan.sync_instances[0]
        assert inst.name == "top-agent_oversight-scratch"
        assert inst.mode == "bisync"
        assert inst.env_vars is not None
        assert inst.env_vars["RCLONE_USER"] == "agent_oversight"
        assert inst.env_vars["LOCAL_PATH"] == "/mnt/raid/top/agents/agent_oversight/scratch/"
