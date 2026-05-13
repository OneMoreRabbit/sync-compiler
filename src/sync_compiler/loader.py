"""
Loads the v0.4 sync registry from disk.

  <registry-dir>/sync/<org>.yml         -> RegistryMain
  <registry-dir>/.compiled/<org>.cloud.yml -> SnapshotRegistry
  <registry-dir>/agent_registry.yml     -> AgentRegistry (optional input for compile)

Fail-fast detection:
  - sync/<org>.cloud.yml exists (v0.2 layout) → fail with migration message
  - <org>.yml `meta.version` in {"0.2", "0.3"}  → fail with migration message
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError

from .errors import RegistryLoadError
from .models import AgentRegistry, RegistryMain, SnapshotRegistry

SUPPORTED_SCHEMA_VERSION = "0.4"

LEGACY_MIGRATION_MESSAGE = (
    "detected legacy sync-compile registry layout (v0.2 or v0.3).\n"
    "v0.4 requires meta.version: \"0.4\" on sync/<org>.yml and agent_registry.yml.\n\n"
    "To migrate manually:\n"
    "  1. If sync/<org>.cloud.yml exists, delete it. v0.3+ snapshots live in .compiled/.\n"
    "  2. Bump meta.version: \"0.4\" in sync/<org>.yml and in agent_registry.yml.\n"
    "  3. Optional: add `share_class` and/or `cloud_sync` blocks to agents in \n"
    "     agent_registry.yml to opt into agent-share bisync.\n"
    "  4. Re-run: sync-compile compile --org <name>."
)


# ── Path helpers ──────────────────────────────────────────────────────────────

def main_path(registry_dir: Path, org: str) -> Path:
    return registry_dir / "sync" / f"{org}.yml"


def snapshot_path(registry_dir: Path, org: str) -> Path:
    return registry_dir / ".compiled" / f"{org}.cloud.yml"


def legacy_v02_cloud_path(registry_dir: Path, org: str) -> Path:
    """v0.2 cloud.yml location — checked only for fail-fast detection."""
    return registry_dir / "sync" / f"{org}.cloud.yml"


def agent_registry_path(registry_dir: Path) -> Path:
    return registry_dir / "agent_registry.yml"


# ── YAML I/O ──────────────────────────────────────────────────────────────────

def _new_yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    return yaml


def _read(path: Path) -> tuple[bytes, str]:
    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise RegistryLoadError(f"File not found: {path}") from exc
    except PermissionError as exc:
        raise RegistryLoadError(f"Permission denied reading {path}: {exc}") from exc
    except OSError as exc:
        raise RegistryLoadError(f"Cannot read {path}: {exc}") from exc
    return content, hashlib.sha256(content).hexdigest()


def _parse(content: bytes, path: Path) -> Any:
    yaml = _new_yaml()
    try:
        data = yaml.load(content)
    except DuplicateKeyError as exc:
        raise RegistryLoadError(f"Duplicate key in {path}: {exc}") from exc
    except Exception as exc:
        raise RegistryLoadError(f"YAML parse error in {path}: {exc}") from exc

    if data is None:
        raise RegistryLoadError(f"File is empty or contains only comments: {path}")
    if not isinstance(data, dict):
        raise RegistryLoadError(
            f"{path}: expected a YAML mapping at top level, got {type(data).__name__}"
        )
    return data


# ── Legacy fail-fast detection ────────────────────────────────────────────────

def detect_legacy_residue(registry_dir: Path, org: str) -> str | None:
    """Return an error message if v0.2/v0.3 artefacts are present, else None.

    Three signals trigger detection:
      (a) sync/<org>.cloud.yml exists (v0.2 location — should be gone).
      (b) <org>.yml's meta.version is "0.2" or "0.3".
      (c) agent_registry.yml's meta.version is "0.2" or "0.3" (caught at agent load time too).
    """
    legacy_cloud = legacy_v02_cloud_path(registry_dir, org)
    if legacy_cloud.exists():
        return (
            f"{LEGACY_MIGRATION_MESSAGE}\n\n"
            f"Detected: {legacy_cloud} (should not exist in v0.4 — "
            f"delete after confirming snapshots live in .compiled/)."
        )

    main_p = main_path(registry_dir, org)
    if main_p.exists():
        try:
            content, _ = _read(main_p)
            data = _parse(content, main_p)
            meta = data.get("meta", {}) if isinstance(data, dict) else {}
            version = meta.get("version") if isinstance(meta, dict) else None
            if version in ("0.2", "0.3"):
                return (
                    f"{LEGACY_MIGRATION_MESSAGE}\n\n"
                    f"Detected: {main_p} has meta.version: \"{version}\". Bump to \"0.4\"."
                )
        except RegistryLoadError:
            pass

    return None


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_main(path: Path) -> tuple[RegistryMain, str]:
    """Load and validate <org>.yml. Required.

    Caller should run detect_legacy_residue first for a friendlier error.
    """
    content, sha = _read(path)
    data = _parse(content, path)
    try:
        reg = RegistryMain.model_validate(data)
    except Exception as exc:
        raise RegistryLoadError(f"{path}: schema error: {exc}") from exc

    if reg.meta.version != SUPPORTED_SCHEMA_VERSION:
        raise RegistryLoadError(
            f"{path}: meta.version is '{reg.meta.version}', expected "
            f"'{SUPPORTED_SCHEMA_VERSION}'.\n{LEGACY_MIGRATION_MESSAGE}"
        )

    return reg, sha


def load_snapshot(path: Path) -> tuple[SnapshotRegistry, str] | None:
    """Load and validate a discovery snapshot. None if absent."""
    if not path.exists():
        return None
    content, sha = _read(path)
    data = _parse(content, path)
    try:
        return SnapshotRegistry.model_validate(data), sha
    except Exception as exc:
        raise RegistryLoadError(f"{path}: schema error: {exc}") from exc


def load_agent_registry(path: Path) -> tuple[AgentRegistry, str] | None:
    """Load and validate agent_registry.yml. Returns None if absent.

    sync-compile only reads fields it cares about; extra fields (consumed by
    rbac-compile / other tools) are tolerated via extra=allow on the models.
    """
    if not path.exists():
        return None
    content, sha = _read(path)
    data = _parse(content, path)
    try:
        reg = AgentRegistry.model_validate(data)
    except Exception as exc:
        raise RegistryLoadError(f"{path}: schema error: {exc}") from exc

    if reg.meta.version != SUPPORTED_SCHEMA_VERSION:
        raise RegistryLoadError(
            f"{path}: meta.version is '{reg.meta.version}', expected "
            f"'{SUPPORTED_SCHEMA_VERSION}'.\n{LEGACY_MIGRATION_MESSAGE}"
        )

    return reg, sha
