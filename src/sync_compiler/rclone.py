"""
Thin wrapper around the rclone CLI.

Pulled out into its own module so it can be mocked in tests without stubbing
subprocess globally. `RcloneRunner` is the seam for dependency injection.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any

from .errors import CloudAPIError


@dataclass
class RcloneRunner:
    """Run rclone as a given user. Inject a test double to mock subprocess."""

    rclone_binary: str = "/usr/bin/rclone"
    sudo_binary: str = "/usr/bin/sudo"

    def version(self) -> str:
        """Return rclone version string. Raises CloudAPIError on failure."""
        proc = self._run([self.rclone_binary, "version"])
        return proc.stdout.strip().splitlines()[0] if proc.stdout else ""

    def config_show(self, remote_name: str, rclone_user: str, rclone_config: str) -> str:
        """Return `rclone config show <remote>` output. Raises CloudAPIError on failure."""
        cmd = self._sudo_prefix(rclone_user) + [
            self.rclone_binary,
            "--config",
            rclone_config,
            "config",
            "show",
            remote_name,
        ]
        proc = self._run(cmd)
        return proc.stdout

    def list_shared_drives(
        self, remote_name: str, rclone_user: str, rclone_config: str
    ) -> list[dict[str, Any]]:
        """Run `rclone backend drives <remote>:` and return the parsed JSON list."""
        cmd = self._sudo_prefix(rclone_user) + [
            self.rclone_binary,
            "--config",
            rclone_config,
            "backend",
            "drives",
            f"{remote_name}:",
        ]
        proc = self._run(cmd)
        stdout = proc.stdout.strip()
        if not stdout:
            return []
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise CloudAPIError(
                f"Could not parse rclone backend output as JSON: {exc}\n"
                f"First 200 chars: {stdout[:200]!r}"
            ) from exc
        if not isinstance(data, list):
            raise CloudAPIError(
                f"Expected JSON list from rclone backend drives, got {type(data).__name__}"
            )
        return data

    def _sudo_prefix(self, rclone_user: str) -> list[str]:
        """Prefix for running as a specific user via sudo. Empty if running as self."""
        return [self.sudo_binary, "-u", rclone_user, "-H"]

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise CloudAPIError(
                f"Command not found: {cmd[0]} — is rclone installed?"
            ) from exc

        if proc.returncode != 0:
            raise CloudAPIError(
                f"Command failed (exit {proc.returncode}): {shlex.join(cmd)}\n"
                f"{proc.stderr.strip()}"
            )
        return proc
