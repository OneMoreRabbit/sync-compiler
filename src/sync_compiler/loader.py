"""
Loads the v0.3 sync registry from disk.

Single source of truth:  <registry-dir>/sync/<org>.yml         -> RegistryMain
Discovery snapshot:       <registry-dir>/.compiled/<org>.cloud.yml -> SnapshotRegistry

v0.2 layout detection:
  - meta.version == "0.2" on <org>.yml             -> fail with migration instructions
  - sync/<org>.cloud.yml present (v0.2 location)   -> fail with migration instructions
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError

from .errors import RegistryLoadError
from .models import RegistryMain, SnapshotRegistry

SUPPORTED_SCHEMA_VERSION = "0.3"

V02_MIGRATION_MESSAGE = (
    "detected sync-compile v0.2 registry layout. "
    "v0.3 requires drives to live in <org>.yml under each account; the cloud.yml "
    "becomes a pure discovery snapshot in .compiled/.\n\n"
    "To migrate manually:\n"
    "  1. For each drive in sync/<org>.cloud.yml you want active:\n"
    "       copy the drive entry under the matching account in sync/<org>.yml\n"
    "       under a new `drives:` key.\n"
    "  2. Set `enabled: true` on each drive you want active.\n"
    "  3. Bump `meta.version: \"0.3\"` in sync/<org>.yml.\n"
    "  4. Delete sync/<org>.cloud.yml (it now lives in .compiled/ as a snapshot,\n"
    "     written by `sync-compile discover`).\n"
    "  5. Re-run: sync-compile compile --org <name>"
)


# ── Path helpers ──────────────────────────────────────────────────────────────

def main_path(registry_dir: Path, org: str) -> Path:
    return registry_dir / "sync" / f"{org}.yml"


def snapshot_path(registry_dir: Path, org: str) -> Path:
    """v0.3 snapshot location: .compiled/<org>.cloud.yml."""
    return registry_dir / ".compiled" / f"{org}.cloud.yml"


def legacy_v02_cloud_path(registry_dir: Path, org: str) -> Path:
    """v0.2 cloud.yml location — checked only for fail-fast detection."""
    return registry_dir / "sync" / f"{org}.cloud.yml"


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


# ── v0.2 fail-fast detection ──────────────────────────────────────────────────

def detect_v02_residue(registry_dir: Path, org: str) -> str | None:
    """Return an error message if v0.2 artefacts are present, else None.

    Two signals trigger detection:
      (a) sync/<org>.cloud.yml exists (v0.2 location — should be gone in v0.3).
      (b) <org>.yml's meta.version is exactly "0.2".

    Both are caught so the operator gets a clear message regardless of which
    half of the migration they've started.
    """
    legacy_cloud = legacy_v02_cloud_path(registry_dir, org)
    if legacy_cloud.exists():
        return (
            f"{V02_MIGRATION_MESSAGE}\n\n"
            f"Detected: {legacy_cloud} (this file should not exist in v0.3 — "
            f"delete it after migrating drives into {main_path(registry_dir, org)})."
        )

    main_p = main_path(registry_dir, org)
    if main_p.exists():
        try:
            content, _ = _read(main_p)
            data = _parse(content, main_p)
            meta = data.get("meta", {}) if isinstance(data, dict) else {}
            version = meta.get("version") if isinstance(meta, dict) else None
            if version == "0.2":
                return (
                    f"{V02_MIGRATION_MESSAGE}\n\n"
                    f"Detected: {main_p} has meta.version: \"0.2\". Bump to \"0.3\" "
                    "after adding `drives:` lists under each account."
                )
        except RegistryLoadError:
            # parse errors get raised normally by load_main downstream
            pass

    return None


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_main(path: Path) -> tuple[RegistryMain, str]:
    """Load and validate <org>.yml. Required.

    Caller is responsible for v0.2 detection (call detect_v02_residue first).
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
            f"'{SUPPORTED_SCHEMA_VERSION}'.\n{V02_MIGRATION_MESSAGE}"
        )

    return reg, sha


def load_snapshot(path: Path) -> tuple[SnapshotRegistry, str] | None:
    """Load and validate a discovery snapshot. Returns None if the file is absent.

    The snapshot is not required for any command — `compile` ignores it entirely,
    and `discover` overwrites it. This loader exists for tooling that inspects
    the snapshot (tests, future GUI).
    """
    if not path.exists():
        return None
    content, sha = _read(path)
    data = _parse(content, path)
    try:
        return SnapshotRegistry.model_validate(data), sha
    except Exception as exc:
        raise RegistryLoadError(f"{path}: schema error: {exc}") from exc
