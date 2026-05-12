"""
Core compilation logic — pure functions, no I/O.

Reads drives from <org>.yml (RegistryMain) and emits a CompiledPlan suitable
for serialisation by emitter.emit().
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath

from .models import (
    Account,
    CompiledPlan,
    Drive,
    LocalDirectory,
    PlatformOut,
    RcloneRemote,
    RegistryMain,
    SyncDefaults,
    SyncInstance,
)

__version__ = "0.3.0"
SCHEMA_VERSION = "0.3"


# ── Override merge ────────────────────────────────────────────────────────────

def resolved_sync_defaults(
    defaults: SyncDefaults,
    overrides: dict,
    additional_excludes: list[str],
) -> SyncDefaults:
    """Apply per-drive overrides to the account's sync_defaults.

    Merge rules (unchanged from v0.2):
      - Scalars (schedule, local_subdir) -> override replaces default
      - Lists (sync_flags, exclude_patterns) -> union with defaults, stable order
      - additional_excludes (account-level) -> unioned into exclude_patterns
    """
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
    """Union preserving base order first, then extras not already seen."""
    seen: set[str] = set()
    result: list[str] = []
    for item in list(base) + list(extras):
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ── Artefact naming ───────────────────────────────────────────────────────────

def instance_name(org: str, drive: Drive) -> str:
    return f"{org}-{drive.local_name}"


def rclone_remote_name(account: Account, drive: Drive) -> str:
    return f"{account.remote_name}_{drive.local_name}"


def local_dir_path(registry: RegistryMain, account: Account, drive: Drive) -> str:
    """Full absolute POSIX path for the local sync target."""
    base = registry.platform.local_base
    subdir = account.sync_defaults.local_subdir
    return str(PurePosixPath(base) / subdir / drive.local_name)


ENV_FILE_DIR = "/etc/rclone-sync"
SYSTEMD_UNIT_DIR = "/etc/systemd/system"


def env_file_path(instance: str) -> str:
    return f"{ENV_FILE_DIR}/{instance}.env"


def timer_override_path(instance: str) -> str:
    return f"{SYSTEMD_UNIT_DIR}/rclone-sync@{instance}.timer.d/schedule.conf"


def env_vars(
    registry: RegistryMain,
    account: Account,
    drive: Drive,
    resolved: SyncDefaults,
) -> dict[str, str]:
    """Build the env-var dict baked into /etc/rclone-sync/<instance>.env."""
    sync_flags = " ".join(resolved.sync_flags)
    exclude_patterns = " ".join(f"--exclude={p}" for p in resolved.exclude_patterns)

    return {
        "RCLONE_USER": registry.platform.rclone_user,
        "REMOTE_NAME": rclone_remote_name(account, drive),
        "LOCAL_DEST": local_dir_path(registry, account, drive),
        "SYNC_FLAGS": sync_flags,
        "EXCLUDE_PATTERNS": exclude_patterns,
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def compile_plan(
    registry: RegistryMain,
    source_file: str,
    source_hash: str,
) -> CompiledPlan:
    """Compile <org>.yml into a CompiledPlan.

    Deterministic: same inputs produce byte-identical output after emission.
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
                    env_file_path=env_file_path(inst),
                    env_vars=env_vars(registry, account, drive, resolved),
                    timer_override_path=timer_override_path(inst),
                    schedule=resolved.schedule,
                ))
            else:
                instances.append(SyncInstance(name=inst, enabled=False))

    remotes.sort(key=lambda r: r.name)
    local_dirs.sort(key=lambda d: d.path)
    instances.sort(key=lambda i: i.name)

    return CompiledPlan(
        compiled_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        compiler_version=__version__,
        schema_version=SCHEMA_VERSION,
        source_file=source_file,
        source_hash=source_hash,
        org=registry.org,
        platform=platform_out,
        rclone_remotes=remotes,
        local_directories=local_dirs,
        sync_instances=instances,
    )
