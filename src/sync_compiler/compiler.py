"""
Core compilation logic — pure functions, no I/O.

Transforms a validated Registry into a CompiledPlan ready for emission to YAML
or JSON. All output fields are resolved here, including override-merge and
env-var string construction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from .models import (
    Account,
    CompiledPlan,
    Drive,
    LocalDirectory,
    PlatformOut,
    RcloneRemote,
    Registry,
    SyncDefaults,
    SyncInstance,
)

__version__ = "0.2.0"
SCHEMA_VERSION = "0.2"


# ── Override merge ────────────────────────────────────────────────────────────

def resolved_sync_defaults(
    defaults: SyncDefaults,
    overrides: dict[str, Any],
    additional_excludes: list[str],
) -> SyncDefaults:
    """Apply per-drive overrides to the account's sync_defaults.

    Merge rules:
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
    """systemd instance identifier: '<org>-<local_name>'."""
    return f"{org}-{drive.local_name}"


def rclone_remote_name(account: Account, drive: Drive) -> str:
    """rclone remote block name: '<account.remote_name>_<drive.local_name>'."""
    return f"{account.remote_name}_{drive.local_name}"


def local_dir_path(registry: Registry, account: Account, drive: Drive) -> str:
    """Full absolute POSIX path for the local sync target."""
    base = registry.platform.local_base
    subdir = account.sync_defaults.local_subdir
    # Use PurePosixPath to always produce forward slashes, even on Windows dev machines.
    return str(PurePosixPath(base) / subdir / drive.local_name)


ENV_FILE_DIR = "/etc/rclone-sync"
SYSTEMD_UNIT_DIR = "/etc/systemd/system"


def env_file_path(instance: str) -> str:
    return f"{ENV_FILE_DIR}/{instance}.env"


def timer_override_path(instance: str) -> str:
    return f"{SYSTEMD_UNIT_DIR}/rclone-sync@{instance}.timer.d/schedule.conf"


# ── Env var construction ──────────────────────────────────────────────────────

def env_vars(
    registry: Registry,
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


# ── Main compilation entry point ──────────────────────────────────────────────

def compile_plan(
    registry: Registry,
    source_paths: dict[str, str],
    source_hashes: dict[str, str],
) -> CompiledPlan:
    """Compile the merged registry into a CompiledPlan.

    Deterministic: same inputs produce byte-identical output after emission.
    Sorting happens here; the emitter does no additional reordering.
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

            inst_name = instance_name(registry.org, drive)

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
                    name=inst_name,
                    enabled=True,
                    env_file_path=env_file_path(inst_name),
                    env_vars=env_vars(registry, account, drive, resolved),
                    timer_override_path=timer_override_path(inst_name),
                    schedule=resolved.schedule,
                ))
            else:
                # Disabled: minimal instance entry so Ansible knows to stop the timer.
                instances.append(SyncInstance(
                    name=inst_name,
                    enabled=False,
                ))

    # Deterministic ordering
    remotes.sort(key=lambda r: r.name)
    local_dirs.sort(key=lambda d: d.path)
    instances.sort(key=lambda i: i.name)

    return CompiledPlan(
        compiled_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        compiler_version=__version__,
        schema_version=SCHEMA_VERSION,
        source_files=source_paths,
        source_hashes=source_hashes,
        org=registry.org,
        platform=platform_out,
        rclone_remotes=remotes,
        local_directories=local_dirs,
        sync_instances=instances,
    )
