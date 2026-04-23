"""
High-level operations called by the CLI (and by a future GUI).

Each operation returns a structured result object so callers can display
or serialise the outcome without re-running logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from . import loader
from .cloud import CloudDrive, CloudProvider
from .compiler import CompiledPlan, compile_plan
from .emitter import emit
from .models import RegistryCloud, RegistryMain
from .registry import (
    DiffResult,
    DriveDiff,
    ValidationResult,
    apply_diff_to_cloud_doc,
    diff_against_cloud,
    merge,
    validate_registry,
)
from .writer import atomic_write_yaml, new_cloud_document

# ── Result objects ────────────────────────────────────────────────────────────

@dataclass
class LoadedRegistry:
    """Bundle of everything the loader produces."""

    main: RegistryMain
    cloud: RegistryCloud | None
    main_path: Path
    cloud_path: Path
    main_hash: str
    cloud_hash: str | None


@dataclass
class ValidateResult:
    loaded: LoadedRegistry | None
    validation: ValidationResult


@dataclass
class CompileResult:
    loaded: LoadedRegistry
    validation: ValidationResult
    plan: CompiledPlan | None
    output_path: Path | None


@dataclass
class DiscoverResult:
    loaded: LoadedRegistry
    diff: DiffResult
    written: bool
    output_path: Path
    message: str = ""


# ── Provider factory (overridable in tests) ───────────────────────────────────

class ProviderFactory(Protocol):
    """Build a CloudProvider for a given registry. Replaced in tests with a mock."""

    def __call__(self, registry: RegistryMain) -> CloudProvider: ...


def default_provider_factory(registry: RegistryMain) -> CloudProvider:
    """Default factory: returns DriveProvider backed by the real rclone binary."""
    from .cloud import DriveProvider
    from .rclone import RcloneRunner

    return DriveProvider(
        runner=RcloneRunner(),
        rclone_user=registry.platform.rclone_user,
        rclone_config=registry.platform.rclone_config,
    )


# ── Load ──────────────────────────────────────────────────────────────────────

def load_registry(registry_dir: Path, org: str) -> LoadedRegistry:
    """Load <org>.yml and (if present) <org>.cloud.yml."""
    main_p = loader.main_path(registry_dir, org)
    cloud_p = loader.cloud_path(registry_dir, org)

    main, main_hash = loader.load_main(main_p)
    cloud_tuple = loader.load_cloud(cloud_p)
    if cloud_tuple is not None:
        cloud, cloud_hash = cloud_tuple
    else:
        cloud, cloud_hash = None, None

    return LoadedRegistry(
        main=main,
        cloud=cloud,
        main_path=main_p,
        cloud_path=cloud_p,
        main_hash=main_hash,
        cloud_hash=cloud_hash,
    )


# ── Validate ──────────────────────────────────────────────────────────────────

def validate(registry_dir: Path, org: str) -> ValidateResult:
    """Run schema + cross-reference validation. Offline."""
    loaded = load_registry(registry_dir, org)
    result = validate_registry(
        loaded.main, loaded.cloud, loaded.main_path, loaded.cloud_path
    )
    return ValidateResult(loaded=loaded, validation=result)


# ── Compile ───────────────────────────────────────────────────────────────────

def compile_for_org(
    registry_dir: Path,
    org: str,
    output: Path | None = None,
    fmt: str = "yaml",
    check_only: bool = False,
) -> CompileResult:
    """Validate and (unless check_only) emit the compiled plan."""
    loaded = load_registry(registry_dir, org)
    result = validate_registry(
        loaded.main, loaded.cloud, loaded.main_path, loaded.cloud_path
    )

    if not result.ok:
        return CompileResult(loaded=loaded, validation=result, plan=None, output_path=None)

    registry = merge(loaded.main, loaded.cloud)
    plan = compile_plan(
        registry=registry,
        source_paths={
            "main": str(loaded.main_path),
            "cloud": str(loaded.cloud_path) if loaded.cloud is not None else "",
        },
        source_hashes={
            "main": loaded.main_hash,
            "cloud": loaded.cloud_hash or "",
        },
    )

    if check_only:
        return CompileResult(loaded=loaded, validation=result, plan=plan, output_path=None)

    out = output or _default_output_path(registry_dir, org)
    emit(plan, out, fmt=fmt)
    return CompileResult(loaded=loaded, validation=result, plan=plan, output_path=out)


def _default_output_path(registry_dir: Path, org: str) -> Path:
    return registry_dir / ".compiled" / f"compiled_sync_plan_{org}.yml"


# ── Discover ──────────────────────────────────────────────────────────────────

def discover(
    registry_dir: Path,
    org: str,
    provider_factory: ProviderFactory | None = None,
    dry_run: bool = False,
) -> DiscoverResult:
    """Query cloud for drives, compute diff, optionally rewrite <org>.cloud.yml.

    The caller is responsible for user confirmation before calling with dry_run=False.
    """
    loaded = load_registry(registry_dir, org)
    factory = provider_factory or default_provider_factory
    provider = factory(loaded.main)

    result = DiffResult()

    for account in loaded.main.accounts:
        known_drives = []
        if loaded.cloud is not None:
            for ca in loaded.cloud.accounts:
                if ca.remote_name == account.remote_name:
                    known_drives = list(ca.drives)
                    break

        discovered: list[CloudDrive] = provider.list_drives(account)
        diff = diff_against_cloud(account.remote_name, known_drives, discovered)
        result.per_account[account.remote_name] = diff

    if not result.has_changes:
        return DiscoverResult(
            loaded=loaded,
            diff=result,
            written=False,
            output_path=loaded.cloud_path,
            message="no changes",
        )

    if dry_run:
        return DiscoverResult(
            loaded=loaded,
            diff=result,
            written=False,
            output_path=loaded.cloud_path,
            message="dry run",
        )

    # Collect all existing local_names across the registry to avoid slug collisions on new drives
    existing_locals: set[str] = set()
    if loaded.cloud is not None:
        for ca in loaded.cloud.accounts:
            for d in ca.drives:
                existing_locals.add(d.local_name)

    doc = loader.load_cloud_raw(loaded.cloud_path)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    editor = "sync-compile"

    if doc is None:
        doc = new_cloud_document(org, now_iso, editor)

    diffs_list: list[DriveDiff] = list(result.per_account.values())
    apply_diff_to_cloud_doc(doc, diffs_list, existing_locals, now_iso, editor)
    # Ensure org key is set correctly (new docs get PLACEHOLDER until filled)
    doc["org"] = org

    atomic_write_yaml(loaded.cloud_path, doc)

    return DiscoverResult(
        loaded=loaded,
        diff=result,
        written=True,
        output_path=loaded.cloud_path,
        message="written",
    )


# Expose for __init__ re-export
__all__ = [
    "CompileResult",
    "DiscoverResult",
    "LoadedRegistry",
    "ProviderFactory",
    "ValidateResult",
    "compile_for_org",
    "default_provider_factory",
    "discover",
    "load_registry",
    "validate",
]

# Silence unused-import warnings for `field` on some environments.
_ = field
