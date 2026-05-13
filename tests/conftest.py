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
    """Writable copy of fixtures shaped like a real ~/registry/ tree.

    Layout:
        <tmp_path>/sync/arc.yml
        <tmp_path>/agent_registry.yml
    """
    sync = tmp_path / "sync"
    sync.mkdir(parents=True)
    shutil.copy(valid_dir / "arc.yml", sync / "arc.yml")
    shutil.copy(valid_dir / "agent_registry.yml", tmp_path / "agent_registry.yml")
    return tmp_path


@pytest.fixture
def registry_dir_no_agents(tmp_path: Path, valid_dir: Path) -> Path:
    """Registry without agent_registry.yml — for back-compat / minimal-input tests."""
    sync = tmp_path / "sync"
    sync.mkdir(parents=True)
    shutil.copy(valid_dir / "arc.yml", sync / "arc.yml")
    return tmp_path


@pytest.fixture
def legacy_v02_registry_dir(tmp_path: Path) -> Path:
    """Registry shaped like v0.2 — should trigger fail-fast."""
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
accounts: []
""",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def v03_registry_dir(tmp_path: Path) -> Path:
    """Registry shaped like v0.3 — should trigger fail-fast on v0.4 tools."""
    sync = tmp_path / "sync"
    sync.mkdir(parents=True)
    (sync / "arc.yml").write_text(
        """meta:
  version: "0.3"
org: arc
rclone_users:
  - {user: rclone_arc, remote_name: drive, provider: drive, key_file: x.json, impersonate: x@y.z}
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
    return tmp_path
