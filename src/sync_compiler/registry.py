"""
Registry operations for v0.3:

  - validate_registry()  - schema + cross-reference checks (single-file)
  - classify_drives()    - pure function comparing <org>.yml drives against cloud state
  - slugify()            - cloud_name -> local_name candidate

No merge logic — v0.3 has a single source of truth (<org>.yml). The snapshot
written by `discover` is built directly from classify_drives() output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .cloud import CloudDrive
from .errors import RegistryError, RegistryWarning
from .models import Drive, RegistryMain, SnapshotDrive

SLUG_RE = re.compile(r"[^a-z0-9]+")
SCHEMA_VERSION = "0.3"


# ── slugify ───────────────────────────────────────────────────────────────────

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

    Schema-level checks already ran in the pydantic models. Schema version
    enforcement happens in the loader. This layer handles inter-drive
    uniqueness and rclone-user cross-refs.
    """
    result = ValidationResult()

    # ── Uniqueness of id and local_name across ALL drives ────────────────────
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
                    f"'{seen_locals[drive.local_name]}', again at account '{account.remote_name}'. "
                    "local_name must be unique across all drives (systemd instance namespace)",
                    file=main_file,
                    field_name=f"accounts.{account.remote_name}.drives",
                )
            else:
                seen_locals[drive.local_name] = f"{account.remote_name}.{drive.id}"

            # WARN: duplicate cloud_name within an account
            if drive.cloud_name in cloud_names_in_account:
                result.warn(
                    f"account '{account.remote_name}' has two drives with cloud_name "
                    f"'{drive.cloud_name}' (ids {cloud_names_in_account[drive.cloud_name]} and "
                    f"{drive.id}) - valid but unusual; verify intent",
                    file=main_file,
                )
            else:
                cloud_names_in_account[drive.cloud_name] = drive.id

    # ── rclone_users cross-references ────────────────────────────────────────
    _validate_rclone_users(main, main_file, result)

    return result


def _validate_rclone_users(
    main: RegistryMain, main_file: Path, result: ValidationResult
) -> None:
    users = {ru.user for ru in main.rclone_users}
    user_remotes = {ru.remote_name for ru in main.rclone_users}

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
                f"'{account.sync_defaults.schedule}' runs more frequently than every "
                "5 minutes - may exceed API quotas",
                file=main_file,
            )


def _schedule_too_tight(schedule: str) -> bool:
    """Heuristic check for `*:0/N` schedules with N < 5."""
    m = re.fullmatch(r"\*:0/(\d+)", schedule.strip())
    if m:
        return int(m.group(1)) < 5
    return False


# ── Classify drives (discover's core logic) ───────────────────────────────────

@dataclass
class AccountClassification:
    """Per-account classification output: list of snapshot drives + counts."""

    remote_name: str
    drives: list[SnapshotDrive] = field(default_factory=list)
    new: int = 0
    present: int = 0
    renamed: int = 0
    missing_from_cloud: int = 0


@dataclass
class ClassificationResult:
    """Full classification across all accounts."""

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
        """True if anything diverges from <org>.yml (new/renamed/missing)."""
        return self.total_new + self.total_renamed + self.total_missing > 0


def classify_drives(
    account_remote_name: str,
    yml_drives: list[Drive],
    cloud_drives: list[CloudDrive],
    existing_local_names: set[str],
) -> AccountClassification:
    """Compare <org>.yml drives against cloud state; produce snapshot entries.

    `existing_local_names` is the set of local_names already in <org>.yml plus
    `suggested_local_name` values already assigned in this discover run — used
    to auto-uniquify suggestions so the human can copy-paste without collision.
    """
    yml_by_id = {d.id: d for d in yml_drives}
    cloud_by_id = {d.id: d for d in cloud_drives}

    out = AccountClassification(remote_name=account_remote_name)

    # Cloud drives: present, renamed, or new
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

    # <org>.yml drives not in cloud: missing
    for yid, yml_drive in yml_by_id.items():
        if yid not in cloud_by_id:
            out.drives.append(SnapshotDrive(
                id=yid,
                cloud_name=yml_drive.cloud_name,
                status="missing_from_cloud",
            ))
            out.missing_from_cloud += 1

    # Deterministic ordering: status group, then id within group
    status_order = {"new": 0, "renamed": 1, "missing_from_cloud": 2, "present": 3}
    out.drives.sort(key=lambda d: (status_order[d.status], d.id))
    return out
