"""
Registry operations for v0.4:

  - validate_registry()    - schema + cross-reference checks on <org>.yml
  - validate_agent_sync()  - cross-reference checks on agents that sync into this org
  - classify_drives()      - pure function comparing <org>.yml drives against cloud state
  - resolve_surface_path() - shared agent-share path derivation
  - slugify() / uniquify() - cloud_name → local_name helpers
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .cloud import CloudDrive
from .errors import RegistryError, RegistryWarning
from .models import (
    AgentRecord,
    AgentRegistry,
    Drive,
    RegistryMain,
    SnapshotDrive,
)

SLUG_RE = re.compile(r"[^a-z0-9]+")
SCHEMA_VERSION = "0.4"
SURFACES = ("configs", "memory", "sessions", "scratch")
BISYNC_SURFACES = ("scratch", "memory")


# ── slugify / uniquify ────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    """Slug a cloud_name into a valid local_name candidate."""
    lowered = name.lower().strip()
    slug = SLUG_RE.sub("_", lowered).strip("_")
    if not slug:
        slug = "unnamed"
    if not slug[0].isalnum():
        slug = "x" + slug
    return slug[:64]


def uniquify(candidate: str, taken: set[str]) -> str:
    """Return `candidate` with a numeric suffix if it's already in `taken`."""
    if candidate not in taken:
        return candidate
    for i in range(2, 10000):
        name = f"{candidate}_{i}"
        if name not in taken:
            return name
    return f"{candidate}_x"  # pragma: no cover — defensive


# ── Agent surface path derivation (shared with rbac-compile by replication) ──

def resolve_surface_path(agent: AgentRecord, surface: str) -> str | None:
    """Resolve the on-disk path for one surface of one agent.

    surface ∈ {'configs', 'memory', 'sessions', 'scratch'}
    Returns the canonicalised path with trailing slash. None if `share_class`
    is unset (agent has no home, can't compute conventional path).
    """
    if surface not in SURFACES:
        raise ValueError(f"unknown surface '{surface}'; valid: {SURFACES}")

    # Override wins
    if agent.shares is not None:
        override = getattr(agent.shares, surface, None)
        if override:
            return _canonicalise(override)

    if agent.share_class is None:
        return None

    org = agent.share_class.org
    base = PurePosixPath("/mnt/raid") / org / "agents" / agent.name
    return str(base / surface) + "/"


def _canonicalise(path: str) -> str:
    """Strip trailing-slash inconsistency; ensure single trailing slash."""
    p = PurePosixPath(path)
    out = str(p)
    if not out.endswith("/"):
        out += "/"
    return out


# ── Validation ────────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    errors: list[RegistryError] = field(default_factory=list)
    warnings: list[RegistryWarning] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def error(
        self,
        message: str,
        file: Path | None = None,
        line: int | None = None,
        field_name: str | None = None,
    ) -> None:
        self.errors.append(RegistryError(message=message, file=file, line=line, field=field_name))

    def warn(self, message: str, file: Path | None = None, line: int | None = None) -> None:
        self.warnings.append(RegistryWarning(message=message, file=file, line=line))


def validate_registry(main: RegistryMain, main_file: Path) -> ValidationResult:
    """Cross-reference + semantic validation on <org>.yml.

    Schema-level checks already ran in pydantic. Schema version enforced by loader.
    This layer handles inter-drive uniqueness and rclone-user cross-refs.
    """
    result = ValidationResult()

    # Uniqueness of id and local_name across ALL drives
    seen_ids: dict[str, str] = {}
    seen_locals: dict[str, str] = {}
    for account in main.accounts:
        cloud_names_in_account: dict[str, str] = {}
        for drive in account.drives:
            context = f"{account.remote_name}.{drive.local_name}"

            if drive.id in seen_ids:
                result.error(
                    f"drive id '{drive.id}' appears twice: first at '{seen_ids[drive.id]}', "
                    f"again at '{context}'",
                    file=main_file,
                    field_name=f"accounts.{account.remote_name}.drives",
                )
            else:
                seen_ids[drive.id] = context

            if drive.local_name in seen_locals:
                result.error(
                    f"local_name '{drive.local_name}' appears twice: first at "
                    f"'{seen_locals[drive.local_name]}', again at account "
                    f"'{account.remote_name}'. local_name must be unique across all drives.",
                    file=main_file,
                    field_name=f"accounts.{account.remote_name}.drives",
                )
            else:
                seen_locals[drive.local_name] = f"{account.remote_name}.{drive.id}"

            if drive.cloud_name in cloud_names_in_account:
                result.warn(
                    f"account '{account.remote_name}' has two drives with cloud_name "
                    f"'{drive.cloud_name}' (ids {cloud_names_in_account[drive.cloud_name]} and "
                    f"{drive.id}) - valid but unusual; verify intent",
                    file=main_file,
                )
            else:
                cloud_names_in_account[drive.cloud_name] = drive.id

    _validate_rclone_users(main, main_file, result)
    return result


def _validate_rclone_users(
    main: RegistryMain, main_file: Path, result: ValidationResult
) -> None:
    users = {ru.user for ru in main.rclone_users}
    # remote_name is optional on RcloneUser (bisync-only orgs omit it) — drop None.
    user_remotes = {ru.remote_name for ru in main.rclone_users if ru.remote_name}

    if main.platform.rclone_user not in users:
        result.error(
            f"platform.rclone_user '{main.platform.rclone_user}' does not match any user in "
            f"rclone_users[]. Known users: {sorted(users) or '(none)'}",
            file=main_file,
            field_name="platform.rclone_user",
        )

    for account in main.accounts:
        if account.remote_name not in user_remotes:
            result.warn(
                f"account '{account.remote_name}' has no matching remote_name in "
                f"rclone_users[] - Ansible may not have provisioned the entrypoint remote",
                file=main_file,
            )

        if _schedule_too_tight(account.sync_defaults.schedule):
            result.warn(
                f"account '{account.remote_name}' schedule "
                f"'{account.sync_defaults.schedule}' runs more frequently than every 5 minutes "
                "- may exceed API quotas",
                file=main_file,
            )


def _schedule_too_tight(schedule: str) -> bool:
    m = re.fullmatch(r"\*:0/(\d+)", schedule.strip())
    if m:
        return int(m.group(1)) < 5
    return False


def validate_agent_sync(
    agent_registry: AgentRegistry | None,
    target_org: str,
    agent_registry_file: Path | None,
) -> ValidationResult:
    """Validate agents whose share_class.org matches `target_org` for sync purposes.

    Catches the cases sync-compile cares about:
      - cloud_sync set but share_class missing
      - cloud_sync surface enabled but `remote:` missing
      - cloud_sync keys other than scratch/memory (warn)
    """
    result = ValidationResult()
    if agent_registry is None:
        return result

    for agent in agent_registry.agents:
        if agent.cloud_sync is None:
            continue

        # Warn on unsupported surface keys
        extra = set(agent.cloud_sync.model_dump(exclude_none=False).keys()) - {"scratch", "memory"}
        # `model_dump` returns model fields; `extra="allow"` extras land in __pydantic_extra__
        if agent.cloud_sync.model_extra:
            extra |= set(agent.cloud_sync.model_extra.keys())
        for k in sorted(extra):
            if k in ("sessions", "configs"):
                result.warn(
                    f"agent '{agent.name}' has cloud_sync.{k} - this surface is never "
                    "synced; entry will be ignored",
                    file=agent_registry_file,
                )
            elif k not in ("scratch", "memory"):
                result.warn(
                    f"agent '{agent.name}' has unknown cloud_sync.{k} - ignored",
                    file=agent_registry_file,
                )

        # share_class required when cloud_sync is set
        if agent.share_class is None:
            result.error(
                f"agent '{agent.name}' has cloud_sync but no share_class - cannot determine "
                "which compiled plan to emit into",
                file=agent_registry_file,
                field_name=f"agents[{agent.name}].share_class",
            )
            continue

        # Only validate agents belonging to this target_org
        if agent.share_class.org != target_org:
            continue

        for surface_key in ("scratch", "memory"):
            surf = getattr(agent.cloud_sync, surface_key)
            if surf is None:
                continue
            if surf.enabled and not surf.remote:
                result.error(
                    f"agent '{agent.name}' cloud_sync.{surface_key}.enabled is true but "
                    "remote is missing",
                    file=agent_registry_file,
                    field_name=f"agents[{agent.name}].cloud_sync.{surface_key}.remote",
                )

    return result


# ── Classify drives (discover) — unchanged from v0.3 ──────────────────────────

@dataclass
class AccountClassification:
    remote_name: str
    drives: list[SnapshotDrive] = field(default_factory=list)
    new: int = 0
    present: int = 0
    renamed: int = 0
    missing_from_cloud: int = 0


@dataclass
class ClassificationResult:
    per_account: dict[str, AccountClassification] = field(default_factory=dict)

    @property
    def total_new(self) -> int:
        return sum(a.new for a in self.per_account.values())

    @property
    def total_present(self) -> int:
        return sum(a.present for a in self.per_account.values())

    @property
    def total_renamed(self) -> int:
        return sum(a.renamed for a in self.per_account.values())

    @property
    def total_missing(self) -> int:
        return sum(a.missing_from_cloud for a in self.per_account.values())

    @property
    def has_drift(self) -> bool:
        return self.total_new + self.total_renamed + self.total_missing > 0


def classify_drives(
    account_remote_name: str,
    yml_drives: list[Drive],
    cloud_drives: list[CloudDrive],
    existing_local_names: set[str],
) -> AccountClassification:
    """Compare <org>.yml drives against cloud state; produce snapshot entries."""
    yml_by_id = {d.id: d for d in yml_drives}
    cloud_by_id = {d.id: d for d in cloud_drives}

    out = AccountClassification(remote_name=account_remote_name)

    for cid, cloud_drive in cloud_by_id.items():
        yml_drive = yml_by_id.get(cid)
        if yml_drive is None:
            suggestion = uniquify(slugify(cloud_drive.name), existing_local_names)
            existing_local_names.add(suggestion)
            out.drives.append(SnapshotDrive(
                id=cid,
                cloud_name=cloud_drive.name,
                status="new",
                suggested_local_name=suggestion,
            ))
            out.new += 1
        elif yml_drive.cloud_name != cloud_drive.name:
            out.drives.append(SnapshotDrive(
                id=cid,
                cloud_name=cloud_drive.name,
                status="renamed",
                cloud_name_was=yml_drive.cloud_name,
                cloud_name_now=cloud_drive.name,
            ))
            out.renamed += 1
        else:
            out.drives.append(SnapshotDrive(
                id=cid,
                cloud_name=cloud_drive.name,
                status="present",
            ))
            out.present += 1

    for yid, yml_drive in yml_by_id.items():
        if yid not in cloud_by_id:
            out.drives.append(SnapshotDrive(
                id=yid,
                cloud_name=yml_drive.cloud_name,
                status="missing_from_cloud",
            ))
            out.missing_from_cloud += 1

    status_order = {"new": 0, "renamed": 1, "missing_from_cloud": 2, "present": 3}
    out.drives.sort(key=lambda d: (status_order[d.status], d.id))
    return out
