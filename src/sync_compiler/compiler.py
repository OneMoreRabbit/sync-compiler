"""
Core compilation logic — pure functions, no I/O.

v0.4 adds bisync sync_instances from agent_registry.yml.
Existing org-data sync entries gain explicit `mode: sync` (was implicit in v0.3).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath

from .models import (
    Account,
    AgentRecord,
    AgentRegistry,
    BisyncSurface,
    CompiledPlan,
    Drive,
    LocalDirectory,
    PlatformOut,
    RcloneRemote,
    RegistryMain,
    SyncDefaults,
    SyncInstance,
)
from .registry import resolve_surface_path

__version__ = "0.4.1"
SCHEMA_VERSION = "0.4"

# Baseline bisync flags. Compiler always includes these; conflict-resolve flags
# are added based on user's conflict_policy.
BISYNC_BASELINE_FLAGS = (
    "--resilient --recover --check-access --max-lock 5m"
)

# Bisync excludes (avoid syncing temp / .DS_Store / partial-download junk)
DEFAULT_BISYNC_EXCLUDES = ("*.tmp", ".DS_Store", ".partial.*")


# ── Override merge (org-data sync, unchanged from v0.3) ──────────────────────

def resolved_sync_defaults(
    defaults: SyncDefaults,
    overrides: dict,
    additional_excludes: list[str],
) -> SyncDefaults:
    schedule = overrides.get("schedule", defaults.schedule)
    local_subdir = overrides.get("local_subdir", defaults.local_subdir)
    sync_flags = _merge_list(defaults.sync_flags, overrides.get("sync_flags", []))
    exclude_patterns = _merge_list(defaults.exclude_patterns, overrides.get("exclude_patterns", []))
    exclude_patterns = _merge_list(exclude_patterns, additional_excludes)
    return SyncDefaults(
        local_subdir=local_subdir,
        schedule=schedule,
        sync_flags=sync_flags,
        exclude_patterns=exclude_patterns,
    )


def _merge_list(base: list[str], extras: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in list(base) + list(extras):
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# ── Artefact naming (org-data sync) ──────────────────────────────────────────

def instance_name(org: str, drive: Drive) -> str:
    return f"{org}-{drive.local_name}"


def rclone_remote_name(account: Account, drive: Drive) -> str:
    return f"{account.remote_name}_{drive.local_name}"


def local_dir_path(registry: RegistryMain, account: Account, drive: Drive) -> str:
    return str(
        PurePosixPath(registry.platform.local_base)
        / account.sync_defaults.local_subdir
        / drive.local_name
    )


SYNC_ENV_FILE_DIR = "/etc/rclone-sync"
BISYNC_ENV_FILE_DIR = "/etc/rclone-bisync"
SYSTEMD_UNIT_DIR = "/etc/systemd/system"


def sync_env_file_path(instance: str) -> str:
    return f"{SYNC_ENV_FILE_DIR}/{instance}.env"


def sync_timer_override_path(instance: str) -> str:
    return f"{SYSTEMD_UNIT_DIR}/rclone-sync@{instance}.timer.d/schedule.conf"


def bisync_env_file_path(instance: str) -> str:
    return f"{BISYNC_ENV_FILE_DIR}/{instance}.env"


def bisync_timer_override_path(instance: str) -> str:
    return f"{SYSTEMD_UNIT_DIR}/rclone-bisync@{instance}.timer.d/schedule.conf"


def env_vars(
    registry: RegistryMain,
    account: Account,
    drive: Drive,
    resolved: SyncDefaults,
) -> dict[str, str]:
    sync_flags = " ".join(resolved.sync_flags)
    exclude_patterns = " ".join(f"--exclude={p}" for p in resolved.exclude_patterns)
    return {
        "RCLONE_USER": registry.platform.rclone_user,
        "REMOTE_NAME": rclone_remote_name(account, drive),
        "LOCAL_DEST": local_dir_path(registry, account, drive),
        "SYNC_FLAGS": sync_flags,
        "EXCLUDE_PATTERNS": exclude_patterns,
    }


# ── Bisync (agent shares) ────────────────────────────────────────────────────

def bisync_instance_name(org: str, agent_name: str, surface: str) -> str:
    return f"{org}-{agent_name}-{surface}"


def conflict_resolve_flags(policy: str) -> str:
    """Map user-facing conflict_policy to rclone bisync flags."""
    if policy == "newer":
        return "--conflict-resolve=newer"
    if policy == "suffix":
        return "--conflict-resolve=newer --conflict-loser=pathname --conflict-suffix=.conflict"
    return "--conflict-resolve=newer"  # pragma: no cover — pydantic blocks this


def bisync_flags(surface: BisyncSurface) -> str:
    return f"{BISYNC_BASELINE_FLAGS} {conflict_resolve_flags(surface.conflict_policy)}"


def bisync_excludes() -> str:
    return " ".join(f"--exclude={p}" for p in DEFAULT_BISYNC_EXCLUDES)


def bisync_env_vars(
    registry: RegistryMain,
    agent: AgentRecord,
    surface_name: str,
    surface: BisyncSurface,
    local_path: str,
) -> dict[str, str]:
    """Build env file contents for an agent-bisync systemd instance.

    RCLONE_USER is the agent's own Linux user (so writes from cloud arrive
    with correct ownership). RCLONE_CONFIG points at the per-org rclone
    user's config (the agent reads it via group membership — Ansible owns
    making this readable).
    """
    return {
        "RCLONE_USER": agent.name,
        "RCLONE_CONFIG": registry.platform.rclone_config,
        "LOCAL_PATH": local_path,
        "REMOTE_PATH": surface.remote or "",
        "BISYNC_FLAGS": bisync_flags(surface),
        "EXCLUDE_PATTERNS": bisync_excludes(),
    }


def build_bisync_instances(
    registry: RegistryMain,
    agent_registry: AgentRegistry | None,
) -> list[SyncInstance]:
    """For every agent whose share_class.org matches this registry's org, emit
    one SyncInstance per enabled cloud_sync surface."""
    if agent_registry is None:
        return []

    target_org = registry.org
    instances: list[SyncInstance] = []

    for agent in agent_registry.agents:
        if agent.share_class is None:
            continue
        if agent.share_class.org != target_org:
            continue
        if agent.cloud_sync is None:
            continue

        for surface_key in ("scratch", "memory"):
            surf: BisyncSurface | None = getattr(agent.cloud_sync, surface_key)
            if surf is None:
                continue

            name = bisync_instance_name(target_org, agent.name, surface_key)
            local_path = resolve_surface_path(agent, surface_key)

            if not surf.enabled:
                # Disabled: skeleton entry so Ansible knows to stop the timer.
                instances.append(SyncInstance(name=name, enabled=False, mode="bisync"))
                continue

            assert local_path is not None  # share_class set + override-or-convention

            instances.append(SyncInstance(
                name=name,
                enabled=True,
                mode="bisync",
                env_file_path=bisync_env_file_path(name),
                env_vars=bisync_env_vars(registry, agent, surface_key, surf, local_path),
                timer_override_path=bisync_timer_override_path(name),
                schedule=surf.schedule,
            ))

    return instances


# ── Main entry point ──────────────────────────────────────────────────────────

def compile_plan(
    registry: RegistryMain,
    source_file: str,
    source_hash: str,
    agent_registry: AgentRegistry | None = None,
    agent_registry_path: str | None = None,
    agent_registry_hash: str | None = None,
) -> CompiledPlan:
    """Compile <org>.yml (+ agent_registry.yml) into a CompiledPlan.

    Deterministic: same inputs produce byte-identical output (modulo timestamp).
    """
    platform_out = PlatformOut(
        rclone_user=registry.platform.rclone_user,
        rclone_config_path=registry.platform.rclone_config,
        default_owner=registry.platform.default_owner,
        default_group=registry.platform.default_group,
        default_mode=registry.platform.default_mode,
    )

    remotes: list[RcloneRemote] = []
    local_dirs: list[LocalDirectory] = []
    instances: list[SyncInstance] = []

    # ── Org-data sync instances ──────────────────────────────────────────────
    for account in registry.accounts:
        for drive in account.drives:
            resolved = resolved_sync_defaults(
                account.sync_defaults,
                drive.overrides,
                account.additional_excludes,
            )
            inst = instance_name(registry.org, drive)

            if drive.enabled:
                remotes.append(RcloneRemote(
                    name=rclone_remote_name(account, drive),
                    type=account.provider,
                    scope="drive",
                    service_account_file=account.auth.service_account_file,
                    impersonate=account.auth.impersonate,
                    team_drive=drive.id,
                ))
                local_dirs.append(LocalDirectory(
                    path=local_dir_path(registry, account, drive),
                ))
                instances.append(SyncInstance(
                    name=inst,
                    enabled=True,
                    mode="sync",
                    env_file_path=sync_env_file_path(inst),
                    env_vars=env_vars(registry, account, drive, resolved),
                    timer_override_path=sync_timer_override_path(inst),
                    schedule=resolved.schedule,
                ))
            else:
                instances.append(SyncInstance(name=inst, enabled=False, mode="sync"))

    # ── Agent bisync instances ───────────────────────────────────────────────
    instances.extend(build_bisync_instances(registry, agent_registry))

    # Deterministic ordering
    remotes.sort(key=lambda r: r.name)
    local_dirs.sort(key=lambda d: d.path)
    instances.sort(key=lambda i: i.name)

    return CompiledPlan(
        compiled_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        compiler_version=__version__,
        schema_version=SCHEMA_VERSION,
        source_file=source_file,
        source_hash=source_hash,
        agent_registry_path=agent_registry_path,
        agent_registry_hash=agent_registry_hash,
        org=registry.org,
        platform=platform_out,
        rclone_remotes=remotes,
        local_directories=local_dirs,
        sync_instances=instances,
    )
