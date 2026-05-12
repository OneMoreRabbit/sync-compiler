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
    """
    sync = tmp_path / "sync"
    sync.mkdir(parents=True)
    shutil.copy(valid_dir / "arc.yml", sync / "arc.yml")
    return tmp_path


@pytest.fixture
def v02_registry_dir(tmp_path: Path) -> Path:
    """A registry shaped like the v0.2 layout — should trigger fail-fast."""
    sync = tmp_path / "sync"
    sync.mkdir(parents=True)
    (sync / "arc.yml").write_text(
        """meta:
  version: "0.2"
org: arc
platform:
  rclone_user: rclone_arc
  local_base: /mnt/raid/arc
  rclone_config: /var/lib/rclone/rclone.conf
accounts:
  - remote_name: drive
    provider: drive
    auth: {type: service_account, service_account_file: /etc/sa.json}
    sync_defaults: {local_subdir: drive, schedule: "*:0/15"}
""",
        encoding="utf-8",
    )
    (sync / "arc.cloud.yml").write_text(
        """meta:
  version: "0.2"
org: arc
accounts:
  - remote_name: drive
    drives: []
""",
        encoding="utf-8",
    )
    return tmp_path
