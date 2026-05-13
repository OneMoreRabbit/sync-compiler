"""
High-level operations called by the CLI (and by a future GUI).
"""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from . import loader
from .cloud import CloudDrive, CloudProvider
from .compiler import CompiledPlan, compile_plan
from .emitter import emit
from .errors import RegistryLoadError
from .models import (
    AgentRegistry,
    RegistryMain,
    SnapshotAccount,
    SnapshotMeta,
    SnapshotRegistry,
)
from .registry import (
    AccountClassification,
    ClassificationResult,
    ValidationResult,
    classify_drives,
    validate_agent_sync,
    validate_registry,
)
from .writer import atomic_write_yaml, dump_yaml

SCHEMA_VERSION = "0.4"


# ── Result objects ────────────────────────────────────────────────────────────

@dataclass
class LoadedRegistry:
    main: RegistryMain
    main_path: Path
    main_hash: str
    snapshot_path: Path
    agents: AgentRegistry | None
    agents_path: Path | None
    agents_hash: str | None


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
    classification: ClassificationResult
    snapshot: SnapshotRegistry | None
    snapshot_yaml: str = ""
    written: bool = False
    output_path: Path = field(default_factory=Path)
    message: str = ""


# ── Provider factory ──────────────────────────────────────────────────────────

class ProviderFactory(Protocol):
    def __call__(self, registry: RegistryMain) -> CloudProvider: ...


def default_provider_factory(registry: RegistryMain) -> CloudProvider:
    from .cloud import DriveProvider
    from .rclone import RcloneRunner

    return DriveProvider(
        runner=RcloneRunner(),
        rclone_user=registry.platform.rclone_user,
        rclone_config=registry.platform.rclone_config,
    )


# ── Load ──────────────────────────────────────────────────────────────────────

def load_registry(registry_dir: Path, org: str) -> LoadedRegistry:
    """Load <org>.yml and (if present) agent_registry.yml. Fail fast on legacy layouts."""
    legacy = loader.detect_legacy_residue(registry_dir, org)
    if legacy:
        raise RegistryLoadError(legacy)

    main_p = loader.main_path(registry_dir, org)
    main, main_hash = loader.load_main(main_p)

    agents_p = loader.agent_registry_path(registry_dir)
    agents_tuple = loader.load_agent_registry(agents_p)
    if agents_tuple is not None:
        agents, agents_hash = agents_tuple
        agents_path = agents_p
    else:
        agents, agents_hash, agents_path = None, None, None

    return LoadedRegistry(
        main=main,
        main_path=main_p,
        main_hash=main_hash,
        snapshot_path=loader.snapshot_path(registry_dir, org),
        agents=agents,
        agents_path=agents_path,
        agents_hash=agents_hash,
    )


# ── Validate ──────────────────────────────────────────────────────────────────

def validate(registry_dir: Path, org: str) -> ValidateResult:
    loaded = load_registry(registry_dir, org)
    result = validate_registry(loaded.main, loaded.main_path)
    agent_result = validate_agent_sync(loaded.agents, loaded.main.org, loaded.agents_path)
    result.errors.extend(agent_result.errors)
    result.warnings.extend(agent_result.warnings)
    return ValidateResult(loaded=loaded, validation=result)


# ── Compile ───────────────────────────────────────────────────────────────────

def _default_output_path(registry_dir: Path, org: str) -> Path:
    return registry_dir / ".compiled" / f"compiled_sync_plan_{org}.yml"


def compile_for_org(
    registry_dir: Path,
    org: str,
    output: Path | None = None,
    fmt: str = "yaml",
    check_only: bool = False,
) -> CompileResult:
    loaded = load_registry(registry_dir, org)
    result = validate_registry(loaded.main, loaded.main_path)
    agent_result = validate_agent_sync(loaded.agents, loaded.main.org, loaded.agents_path)
    result.errors.extend(agent_result.errors)
    result.warnings.extend(agent_result.warnings)

    if not result.ok:
        return CompileResult(loaded=loaded, validation=result, plan=None, output_path=None)

    plan = compile_plan(
        registry=loaded.main,
        source_file=str(loaded.main_path),
        source_hash=loaded.main_hash,
        agent_registry=loaded.agents,
        agent_registry_path=str(loaded.agents_path) if loaded.agents_path else None,
        agent_registry_hash=loaded.agents_hash,
    )

    if check_only:
        return CompileResult(loaded=loaded, validation=result, plan=plan, output_path=None)

    out = output or _default_output_path(registry_dir, org)
    emit(plan, out, fmt=fmt)
    return CompileResult(loaded=loaded, validation=result, plan=plan, output_path=out)


# ── Discover (unchanged from v0.3) ────────────────────────────────────────────

def _build_snapshot(
    loaded: LoadedRegistry,
    classification: ClassificationResult,
) -> SnapshotRegistry:
    return SnapshotRegistry(
        meta=SnapshotMeta(
            version=SCHEMA_VERSION,
            stage="beta",
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            generated_by=f"sync-compile/{SCHEMA_VERSION} on {socket.gethostname()}",
            description=(
                "Discovery snapshot - DO NOT EDIT. "
                "Regenerate via: sync-compile discover --org <name>"
            ),
            source_yml_path=str(loaded.main_path),
            source_yml_hash=f"sha256:{loaded.main_hash}",
        ),
        org=loaded.main.org,
        accounts=[
            SnapshotAccount(remote_name=acc.remote_name, drives=list(acc.drives))
            for acc in classification.per_account.values()
        ],
    )


def _snapshot_to_dict(snapshot: SnapshotRegistry) -> dict:
    return {
        "meta": snapshot.meta.model_dump(exclude_none=True),
        "org": snapshot.org,
        "accounts": [
            {
                "remote_name": acc.remote_name,
                "drives": [
                    {k: v for k, v in d.model_dump().items() if v is not None}
                    for d in acc.drives
                ],
            }
            for acc in snapshot.accounts
        ],
    }


def _classify_all(
    loaded: LoadedRegistry,
    provider: CloudProvider,
) -> ClassificationResult:
    result = ClassificationResult()
    existing_local_names: set[str] = {
        d.local_name for account in loaded.main.accounts for d in account.drives
    }

    for account in loaded.main.accounts:
        cloud_drives: list[CloudDrive] = provider.list_drives(account)
        cls: AccountClassification = classify_drives(
            account_remote_name=account.remote_name,
            yml_drives=list(account.drives),
            cloud_drives=cloud_drives,
            existing_local_names=existing_local_names,
        )
        result.per_account[account.remote_name] = cls
    return result


def discover_classify(
    registry_dir: Path,
    org: str,
    provider_factory: ProviderFactory | None = None,
) -> DiscoverResult:
    loaded = load_registry(registry_dir, org)
    factory = provider_factory or default_provider_factory
    provider = factory(loaded.main)

    classification = _classify_all(loaded, provider)
    snapshot = _build_snapshot(loaded, classification)
    snapshot_yaml = dump_yaml(_snapshot_to_dict(snapshot))

    return DiscoverResult(
        loaded=loaded,
        classification=classification,
        snapshot=snapshot,
        snapshot_yaml=snapshot_yaml,
        written=False,
        output_path=loaded.snapshot_path,
        message="classified",
    )


def discover_write(
    result: DiscoverResult,
    output: Path | None = None,
) -> DiscoverResult:
    out = output or result.output_path
    if result.snapshot is None:
        raise RuntimeError("discover_write called without classification")
    atomic_write_yaml(out, _snapshot_to_dict(result.snapshot))
    return DiscoverResult(
        loaded=result.loaded,
        classification=result.classification,
        snapshot=result.snapshot,
        snapshot_yaml=result.snapshot_yaml,
        written=True,
        output_path=out,
        message="written",
    )


__all__ = [
    "CompileResult",
    "DiscoverResult",
    "LoadedRegistry",
    "ProviderFactory",
    "ValidateResult",
    "compile_for_org",
    "default_provider_factory",
    "discover_classify",
    "discover_write",
    "load_registry",
    "validate",
]
