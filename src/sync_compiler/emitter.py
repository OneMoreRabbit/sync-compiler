"""
Serialises a CompiledPlan to YAML or JSON via atomic write.

The plan is already fully sorted and resolved by the compiler — emitter just
serialises. Atomic via tempfile + os.replace.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import CompiledPlan, SyncInstance
from .writer import atomic_write_text, dump_yaml


def plan_to_dict(plan: CompiledPlan) -> dict:
    """Convert CompiledPlan to a nested dict matching the v0.3 schema."""
    return {
        "meta": {
            "compiled_at": plan.compiled_at,
            "compiler_version": plan.compiler_version,
            "schema_version": plan.schema_version,
            "source_file": plan.source_file,
            "source_hash": plan.source_hash,
        },
        "org": plan.org,
        "platform": asdict(plan.platform),
        "rclone_remotes": [asdict(r) for r in plan.rclone_remotes],
        "local_directories": [asdict(d) for d in plan.local_directories],
        "sync_instances": [_instance_to_dict(i) for i in plan.sync_instances],
    }


def _instance_to_dict(i: SyncInstance) -> dict:
    """Emit SyncInstance; elide optional fields when the instance is disabled."""
    d: dict = {"name": i.name, "enabled": i.enabled}
    if i.enabled:
        d["env_file_path"] = i.env_file_path
        d["env_vars"] = dict(i.env_vars or {})
        d["timer_override_path"] = i.timer_override_path
        d["schedule"] = i.schedule
    return d


def emit(plan: CompiledPlan, output_path: Path, fmt: str = "yaml") -> None:
    """Serialise the plan and atomic-write it to `output_path`."""
    data = plan_to_dict(plan)
    if fmt == "json":
        text = json.dumps(data, indent=2)
    else:
        text = dump_yaml(data)
    atomic_write_text(output_path, text)
