"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def valid_dir() -> Path:
    """Absolute path to the `valid` fixture directory (read-only)."""
    return FIXTURES / "valid"


@pytest.fixture
def registry_dir(tmp_path: Path, valid_dir: Path) -> Path:
    """A writable copy of the valid fixtures, shaped like a real ~/registry/ tree.

    Layout:
        <tmp_path>/sync/arc.yml
        <tmp_path>/sync/arc.cloud.yml
    """
    sync = tmp_path / "sync"
    sync.mkdir(parents=True)
    shutil.copy(valid_dir / "arc.yml", sync / "arc.yml")
    shutil.copy(valid_dir / "arc.cloud.yml", sync / "arc.cloud.yml")
    return tmp_path


@pytest.fixture
def registry_dir_no_cloud(tmp_path: Path, valid_dir: Path) -> Path:
    """Like registry_dir but without arc.cloud.yml (first-run state)."""
    sync = tmp_path / "sync"
    sync.mkdir(parents=True)
    shutil.copy(valid_dir / "arc.yml", sync / "arc.yml")
    return tmp_path
