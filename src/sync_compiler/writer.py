"""
Atomic write helpers for <org>.cloud.yml snapshots.

v0.3 simplification: the snapshot is fully tool-owned and regenerated each
discover run. No round-trip preservation of human comments / formatting is
needed — the file is treated as ephemeral output, like compiled_sync_plan_*.yml.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO


def _new_dumper() -> YAML:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 120  # type: ignore[assignment]
    return yaml


def dump_yaml(data: Any) -> str:
    """Serialise `data` to a YAML string with our standard formatting."""
    yaml = _new_dumper()
    stream = StringIO()
    yaml.dump(data, stream)
    return stream.getvalue()


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` via tempfile + os.replace.

    Tempfile lives in the same directory as the target so the final rename is
    atomic on a single filesystem. Parent directory created if absent.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmpname = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmpname, path)
    except Exception:
        try:
            os.unlink(tmpname)
        except OSError:
            pass
        raise


def atomic_write_yaml(path: Path, data: Any) -> None:
    """Render `data` as YAML and atomic-write it to `path`."""
    atomic_write_text(path, dump_yaml(data))
