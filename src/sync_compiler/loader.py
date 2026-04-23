"""
Loads the sync registry YAML files from disk.

Two files per org:
  <registry-dir>/sync/<org>.yml         -> RegistryMain (required)
  <registry-dir>/sync/<org>.cloud.yml   -> RegistryCloud (optional — may not exist yet)

Returns parsed model instances + SHA-256 hashes of each file.
Uses ruamel.yaml for parse errors with line numbers. For <org>.cloud.yml,
also retains the raw ruamel document so `discover` can round-trip-edit it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError

from .errors import RegistryLoadError
from .models import RegistryCloud, RegistryMain


def _sync_dir(registry_dir: Path) -> Path:
    return registry_dir / "sync"


def main_path(registry_dir: Path, org: str) -> Path:
    return _sync_dir(registry_dir) / f"{org}.yml"


def cloud_path(registry_dir: Path, org: str) -> Path:
    return _sync_dir(registry_dir) / f"{org}.cloud.yml"


def _new_yaml() -> YAML:
    """A YAML instance configured for loading with line-number preservation."""
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


def load_main(path: Path) -> tuple[RegistryMain, str]:
    """Load and validate <org>.yml. Required."""
    content, sha = _read(path)
    data = _parse(content, path)
    try:
        return RegistryMain.model_validate(data), sha
    except Exception as exc:
        raise RegistryLoadError(f"{path}: schema error: {exc}") from exc


def load_cloud(path: Path) -> tuple[RegistryCloud, str] | None:
    """Load and validate <org>.cloud.yml. Returns None if the file doesn't exist.

    Raises RegistryLoadError for any other failure (permissions, parse, schema).
    """
    if not path.exists():
        return None
    content, sha = _read(path)
    data = _parse(content, path)
    try:
        return RegistryCloud.model_validate(data), sha
    except Exception as exc:
        raise RegistryLoadError(f"{path}: schema error: {exc}") from exc


def load_cloud_raw(path: Path) -> Any:
    """Load <org>.cloud.yml as a ruamel round-trip document (preserves comments/formatting).

    Used by `discover` for atomic writeback. Returns None if file doesn't exist.
    """
    if not path.exists():
        return None
    content, _ = _read(path)
    return _parse(content, path)
