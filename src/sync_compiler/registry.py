"""
Registry operations: merging the two input files, diffing against cloud state,
applying diffs to the ruamel document for writeback, and cross-reference validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .cloud import CloudDrive
from .errors import RegistryError, RegistryWarning
from .models import (
    Account,
    AccountCloud,
    Drive,
    Registry,
    RegistryCloud,
    RegistryMain,
)

SLUG_RE = re.compile(r"[^a-z0-9]+")


# ── Merge ─────────────────────────────────────────────────────────────────────

def merge(main: RegistryMain, cloud: RegistryCloud | None) -> Registry:
    """Merge the two registry files into a single in-memory Registry.

    If `cloud` is None, every account has an empty drive list (pre-discovery state).
    If `cloud` references an account name not in `main`, it is silently ignored here —
    validation will flag it as an error.
    """
    cloud_accounts_by_name: dict[str, AccountCloud] = {}
    if cloud is not None:
        cloud_accounts_by_name = {a.remote_name: a for a in cloud.accounts}

    merged_accounts: list[Account] = []
    for main_acc in main.accounts:
        cloud_acc = cloud_accounts_by_name.get(main_acc.remote_name)
        drives = list(cloud_acc.drives) if cloud_acc else []
        merged_accounts.append(
            Account(
                remote_name=main_acc.remote_name,
                provider=main_acc.provider,
                description=main_acc.description,
                auth=main_acc.auth,
                sync_defaults=main_acc.sync_defaults,
                additional_excludes=list(main_acc.additional_excludes),
                drives=drives,
            )
        )

    return Registry(
        meta_main=main.meta,
        meta_cloud=cloud.meta if cloud else None,
        org=main.org,
        rclone_users=list(main.rclone_users),
        platform=main.platform,
        accounts=merged_accounts,
    )


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

    def merge(self, other: ValidationResult) -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


SCHEMA_VERSION = "0.2"


def validate_registry(
    main: RegistryMain,
    cloud: RegistryCloud | None,
    main_file: Path,
    cloud_file: Path,
) -> ValidationResult:
    """Cross-reference and semantic validation.

    Schema-level checks already ran in the pydantic models; this layer handles
    consistency across the two files and within the combined set of drives.
    Collects all errors before returning.
    """
    result = ValidationResult()

    # ── Schema version ────────────────────────────────────────────────────────
    if main.meta.version != SCHEMA_VERSION:
        result.error(
            f"schema version mismatch: expected '{SCHEMA_VERSION}', got '{main.meta.version}'",
            file=main_file,
            field_name="meta.version",
        )
    if cloud is not None and cloud.meta.version != SCHEMA_VERSION:
        result.error(
            f"schema version mismatch: expected '{SCHEMA_VERSION}', got '{cloud.meta.version}'",
            file=cloud_file,
            field_name="meta.version",
        )

    # ── cloud.yml absent ──────────────────────────────────────────────────────
    if cloud is None:
        result.warn(
            f"{cloud_file.name} does not exist; compile will produce an empty drive inventory. "
            f"Run `sync-compile discover --org {main.org}` to create it.",
            file=cloud_file,
        )
        # Further cross-file checks are a no-op when there's no cloud file.
        _validate_rclone_users(main, main_file, result)
        return result

    # ── org keys must match ───────────────────────────────────────────────────
    if cloud.org != main.org:
        result.error(
            f"org mismatch: {main_file.name} declares org='{main.org}' but "
            f"{cloud_file.name} declares org='{cloud.org}'",
            file=cloud_file,
            field_name="org",
        )

    # ── cloud accounts must reference existing main accounts ──────────────────
    main_account_names = {a.remote_name for a in main.accounts}
    for ca in cloud.accounts:
        if ca.remote_name not in main_account_names:
            result.error(
                f"account '{ca.remote_name}' in {cloud_file.name} has no matching "
                f"entry in {main_file.name}. Known accounts: {sorted(main_account_names)}",
                file=cloud_file,
                field_name=f"accounts.{ca.remote_name}",
            )

    # ── uniqueness of id and local_name across all drives ─────────────────────
    seen_ids: dict[str, str] = {}      # id -> "account.local_name"
    seen_locals: dict[str, str] = {}   # local_name -> "account.id"
    for ca in cloud.accounts:
        for drive in ca.drives:
            context = f"{ca.remote_name}.{drive.local_name}"
            if drive.id in seen_ids:
                result.error(
                    f"drive id '{drive.id}' appears twice: first at '{seen_ids[drive.id]}', "
                    f"again at '{context}'",
                    file=cloud_file,
                    field_name=f"accounts.{ca.remote_name}.drives",
                )
            else:
                seen_ids[drive.id] = context

            if drive.local_name in seen_locals:
                result.error(
                    f"local_name '{drive.local_name}' appears twice: first at "
                    f"'{seen_locals[drive.local_name]}', again at account '{ca.remote_name}'. "
                    "local_name must be unique across all drives (systemd instance namespace)",
                    file=cloud_file,
                    field_name=f"accounts.{ca.remote_name}.drives",
                )
            else:
                seen_locals[drive.local_name] = f"{ca.remote_name}.{drive.id}"

            if drive.status == "missing_from_cloud":
                result.warn(
                    f"drive '{drive.local_name}' (id={drive.id}) is marked missing_from_cloud. "
                    "If this is expected, consider removing it from the registry.",
                    file=cloud_file,
                )

    # ── rclone_users cross-references ─────────────────────────────────────────
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

    # Schedule sanity warnings
    for account in main.accounts:
        if _schedule_too_tight(account.sync_defaults.schedule):
            result.warn(
                f"account '{account.remote_name}' schedule '{account.sync_defaults.schedule}' "
                "runs more frequently than every 5 minutes - may exceed API quotas",
                file=main_file,
            )


def _schedule_too_tight(schedule: str) -> bool:
    """Heuristic check for schedules firing more than every 5 minutes.

    Only looks at the common `*:0/N` form. Other forms are not flagged.
    """
    m = re.fullmatch(r"\*:0/(\d+)", schedule.strip())
    if m:
        return int(m.group(1)) < 5
    return False


# ── Diff against cloud state ──────────────────────────────────────────────────

@dataclass
class DriveDiff:
    account: str
    new: list[CloudDrive] = field(default_factory=list)
    renamed: list[tuple[Drive, CloudDrive]] = field(default_factory=list)  # (existing, cloud)
    missing: list[Drive] = field(default_factory=list)
    reappeared: list[Drive] = field(default_factory=list)


@dataclass
class DiffResult:
    per_account: dict[str, DriveDiff] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        return any(
            d.new or d.renamed or d.missing or d.reappeared
            for d in self.per_account.values()
        )


def diff_against_cloud(
    account_name: str,
    known: list[Drive],
    discovered: list[CloudDrive],
) -> DriveDiff:
    """Compute the diff between known (registry) drives and discovered (cloud) drives."""
    diff = DriveDiff(account=account_name)
    known_by_id = {d.id: d for d in known}
    discovered_by_id = {d.id: d for d in discovered}

    for cid, cloud_drive in discovered_by_id.items():
        existing = known_by_id.get(cid)
        if existing is None:
            diff.new.append(cloud_drive)
        else:
            if existing.cloud_name != cloud_drive.name:
                diff.renamed.append((existing, cloud_drive))
            if existing.status == "missing_from_cloud":
                diff.reappeared.append(existing)

    for kid, existing in known_by_id.items():
        if kid not in discovered_by_id and existing.status != "missing_from_cloud":
            diff.missing.append(existing)

    return diff


def slugify(name: str) -> str:
    """Slug a cloud_name into a valid local_name candidate."""
    lowered = name.lower().strip()
    slug = SLUG_RE.sub("_", lowered).strip("_")
    if not slug:
        slug = "unnamed"
    if not slug[0].isalnum():
        slug = "x" + slug
    return slug[:64]


# ── Apply diff to a ruamel document ───────────────────────────────────────────

def apply_diff_to_cloud_doc(
    doc: CommentedMap | None,
    diffs: list[DriveDiff],
    existing_local_names: set[str],
    now_iso: str,
    editor: str,
) -> CommentedMap:
    """Mutate a ruamel cloud.yml document (or create a new one) to reflect the diff.

    - NEW drives are appended to their account's drives[] with enabled: false.
    - RENAMED drives get their cloud_name updated in place.
    - MISSING drives get enabled: false + status: missing_from_cloud.
    - REAPPEARED drives have their status field removed.
    Updates meta.last_modified / last_modified_by.

    Returns the (possibly newly created) document, ready for atomic_write_yaml().
    """
    from .writer import new_cloud_document

    if doc is None:
        # Organisation comes from the first diff's account — caller should pass a non-empty list
        doc = new_cloud_document("PLACEHOLDER", now_iso, editor)
        # Caller fills in `org` after this — see operations.discover

    if "accounts" not in doc or doc["accounts"] is None:
        doc["accounts"] = CommentedSeq()

    accounts_seq: CommentedSeq = doc["accounts"]
    # Build account-name -> account-map index
    account_maps: dict[str, CommentedMap] = {}
    for entry in accounts_seq:
        if isinstance(entry, dict) and "remote_name" in entry:
            account_maps[entry["remote_name"]] = entry

    for diff in diffs:
        account_map = account_maps.get(diff.account)
        if account_map is None:
            account_map = CommentedMap()
            account_map["remote_name"] = diff.account
            account_map["drives"] = CommentedSeq()
            accounts_seq.append(account_map)
            account_maps[diff.account] = account_map

        if "drives" not in account_map or account_map["drives"] is None:
            account_map["drives"] = CommentedSeq()
        drives_seq: CommentedSeq = account_map["drives"]

        # Index drives by id for in-place updates
        drive_by_id: dict[str, CommentedMap] = {
            d["id"]: d for d in drives_seq if isinstance(d, dict) and "id" in d
        }

        # NEW: append with enabled: false
        for cloud_drive in diff.new:
            candidate = slugify(cloud_drive.name)
            local_name = _uniquify(candidate, existing_local_names)
            existing_local_names.add(local_name)

            entry = CommentedMap()
            entry["id"] = cloud_drive.id
            entry["cloud_name"] = cloud_drive.name
            entry["local_name"] = local_name
            entry["enabled"] = False
            if cloud_drive.description:
                entry["description"] = cloud_drive.description
            drives_seq.append(entry)

        # RENAMED: update cloud_name in place
        for existing, cloud_drive in diff.renamed:
            target = drive_by_id.get(existing.id)
            if target is not None:
                target["cloud_name"] = cloud_drive.name

        # MISSING: set enabled: false + status: missing_from_cloud
        for existing in diff.missing:
            target = drive_by_id.get(existing.id)
            if target is not None:
                target["enabled"] = False
                target["status"] = "missing_from_cloud"

        # REAPPEARED: clear status
        for existing in diff.reappeared:
            target = drive_by_id.get(existing.id)
            if target is not None and "status" in target:
                del target["status"]

    # Update meta
    if "meta" in doc and isinstance(doc["meta"], dict):
        doc["meta"]["last_modified"] = now_iso
        doc["meta"]["last_modified_by"] = editor

    return doc


def _uniquify(candidate: str, taken: set[str]) -> str:
    if candidate not in taken:
        return candidate
    for i in range(2, 10000):
        name = f"{candidate}_{i}"
        if name not in taken:
            return name
    return f"{candidate}_x"  # pragma: no cover — defensive


# Silence unused-import warnings for `Any` on some environments.
_ = Any
