"""
Atomic round-trip writeback for <org>.cloud.yml.

Used by the `discover` command. ruamel.yaml preserves comments, key order, and
formatting; the write is done via tempfile + os.replace so a crash mid-write
cannot corrupt the registry.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


def _new_dumper() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 120  # type: ignore[assignment]
    return yaml


def atomic_write_yaml(path: Path, doc: Any) -> None:
    """Write `doc` to `path` atomically via tempfile + os.replace.

    The tempfile is created in the same directory as the target so the final
    rename is a cheap, atomic same-filesystem operation. If any step fails,
    the original file is untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml = _new_dumper()

    fd, tmpname = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            yaml.dump(doc, fh)
        os.replace(tmpname, path)
    except Exception:
        try:
            os.unlink(tmpname)
        except OSError:
            pass
        raise


def new_cloud_document(org: str, now_iso: str, editor: str) -> CommentedMap:
    """Build a brand-new <org>.cloud.yml document when none exists yet.

    Used by `discover` on first run.
    """
    doc = CommentedMap()
    meta = CommentedMap()
    meta["version"] = "0.2"
    meta["stage"] = "beta"
    meta["last_modified"] = now_iso
    meta["last_modified_by"] = editor
    meta["description"] = (
        f"{org} cloud sync registry - drive inventory (maintained by sync-compile)"
    )
    doc["meta"] = meta
    doc["org"] = org
    doc["accounts"] = CommentedSeq()
    return doc
