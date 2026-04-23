from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RegistryError:
    message: str
    file: Path | None = None
    line: int | None = None
    field: str | None = None

    def __str__(self) -> str:
        parts = []
        if self.file:
            loc = str(self.file)
            if self.line:
                loc += f" line {self.line}"
            parts.append(loc)
        if self.field:
            parts.append(f"field '{self.field}'")
        parts.append(self.message)
        return "\n  ".join(parts)


@dataclass
class RegistryWarning:
    message: str
    file: Path | None = None
    line: int | None = None

    def __str__(self) -> str:
        parts = []
        if self.file:
            loc = str(self.file)
            if self.line:
                loc += f" line {self.line}"
            parts.append(loc)
        parts.append(self.message)
        return "\n  ".join(parts)


class RegistryLoadError(Exception):
    """Raised when a registry file cannot be loaded or parsed."""


class CloudAPIError(Exception):
    """Raised when the cloud provider (via rclone) returns an error."""


class CompilerInternalError(Exception):
    """Raised on unexpected internal errors."""
