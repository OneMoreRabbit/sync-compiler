"""
Cloud provider adapters.

v0.2 supports one provider: Google Drive via rclone. The adapter interface is
designed so that future providers (Dropbox, OneDrive) slot in with the same shape.

The adapter does not authenticate directly — it defers to rclone, which has already
been configured by Ansible with the entrypoint remote.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import Account
from .rclone import RcloneRunner


@dataclass
class CloudDrive:
    """A drive discovered in the cloud. Provider-agnostic shape."""

    id: str
    name: str
    description: str | None = None


class CloudProvider(Protocol):
    """Protocol implemented by each provider adapter."""

    def list_drives(self, account: Account) -> list[CloudDrive]: ...


class DriveProvider:
    """Google Drive provider — lists Shared Drives via `rclone backend drives`."""

    def __init__(self, runner: RcloneRunner, rclone_user: str, rclone_config: str) -> None:
        self._runner = runner
        self._rclone_user = rclone_user
        self._rclone_config = rclone_config

    def list_drives(self, account: Account) -> list[CloudDrive]:
        raw = self._runner.list_shared_drives(
            remote_name=account.remote_name,
            rclone_user=self._rclone_user,
            rclone_config=self._rclone_config,
        )
        drives: list[CloudDrive] = []
        for item in raw:
            drive_id = item.get("id") or item.get("Id") or ""
            name = item.get("name") or item.get("Name") or ""
            if not drive_id or not name:
                continue
            drives.append(CloudDrive(id=drive_id, name=name))
        return drives
