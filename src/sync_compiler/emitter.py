"""
Writes the compiled sync plan to disk (YAML or JSON).

The plan is already fully sorted and resolved by the compiler — the emitter just
serialises. Parent directories are created if missing. Writes go through a
tempfile + os.replace so a failed write cannot leave a partial file.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO

from .models import CompiledPlan


def _plan_to_dict(plan: CompiledPlan) -> dict[str, object]:
    """Convert CompiledPlan to a nested dict matching the schema in the brief."""
    return {
        "meta": {
            "compiled_at": plan.compiled_at,
            "compiler_version": plan.compiler_version,
            "schema_version": plan.schema_version,
            "source_files": dict(plan.source_files),
            "source_hashes": dict(plan.source_hashes),
        },
        "org": plan.org,
        "platform": asdict(plan.platform),
        "rclone_remotes": [asdict(r) for r in plan.rclone_remotes],
        "local_directories": [asdict(d) for d in plan.local_directories],
        "sync_instances": [_instance_to_dict(i) for i in plan.sync_instances],
    }


def _instance_to_dict(i: object) -> dict[str, object]:
    """Emit SyncInstance with optional fields elided when the instance is disabled."""
    from .models import SyncInstance
    assert isinstance(i, SyncInstance)
    d: dict[str, object] = {"name": i.name, "enabled": i.enabled}
    if i.enabled:
        d["env_file_path"] = i.env_file_path
        d["env_vars"] = dict(i.env_vars or {})
        d["timer_override_path"] = i.timer_override_path
        d["schedule"] = i.schedule
    return d


def emit(plan: CompiledPlan, output_path: Path, fmt: str = "yaml") -> None:
    """Serialise the plan and atomically write it to `output_path`."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = _plan_to_dict(plan)

    if fmt == "json":
        text = json.dumps(data, indent=2)
    else:
        yaml = YAML()
        yaml.default_flow_style = False
        yaml.width = 120  # type: ignore[assignment]
        stream = StringIO()
        yaml.dump(data, stream)
        text = stream.getvalue()

    _atomic_write_text(output_path, text)


def _atomic_write_text(path: Path, text: str) -> None:
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
