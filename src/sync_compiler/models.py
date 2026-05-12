"""
Pydantic models for sync-compiler v0.3.

Schema v0.3:
  <org>.yml        ->  RegistryMain      (sole source of truth — drives nested under accounts)
  <org>.cloud.yml  ->  SnapshotRegistry  (tool-written discovery snapshot in .compiled/)

Path fields are stored as plain strings (never pathlib.Path) — they refer to
Linux target paths and the tool runs on both Windows (dev) and Linux (prod).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LINUX_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
ORG_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
REMOTE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
LOCAL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
OCTAL_MODE_RE = re.compile(r"^[0-7]{3,5}$")


# ── Shared ────────────────────────────────────────────────────────────────────

class Meta(BaseModel):
    version: str
    stage: str | None = None
    last_modified: str | None = None
    last_modified_by: str | None = None
    description: str | None = None


# ── <org>.yml — sole human-edited source of truth ─────────────────────────────

class Drive(BaseModel):
    """A drive declared under an account in <org>.yml.

    `enabled` lives here (not in the snapshot) — this is the source of truth.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    cloud_name: str
    local_name: str
    enabled: bool
    overrides: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None

    @field_validator("id")
    @classmethod
    def id_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id must not be empty")
        return v

    @field_validator("local_name")
    @classmethod
    def local_name_valid(cls, v: str) -> str:
        if not LOCAL_NAME_RE.match(v):
            raise ValueError(
                f"'{v}' is not a valid local_name "
                "(lowercase alphanumeric + underscores + hyphens, <= 64 chars)"
            )
        return v


class Platform(BaseModel):
    """Per-org platform configuration."""

    rclone_user: str
    local_base: str
    rclone_config: str
    default_owner: str | None = None
    default_group: str | None = None
    default_mode: str | None = None

    @field_validator("rclone_user")
    @classmethod
    def rclone_user_valid(cls, v: str) -> str:
        if not LINUX_USERNAME_RE.match(v):
            raise ValueError(
                f"'{v}' is not a valid Linux username "
                "(lowercase, alphanumeric + underscores, <= 32 chars, must start with a letter)"
            )
        return v

    @field_validator("local_base", "rclone_config")
    @classmethod
    def absolute_path(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(f"must be an absolute path (start with '/'): got '{v}'")
        if ".." in v.split("/"):
            raise ValueError(f"must not contain '..': got '{v}'")
        return v

    @field_validator("default_mode")
    @classmethod
    def mode_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not OCTAL_MODE_RE.match(v):
            raise ValueError(
                f"'{v}' is not a valid octal mode string (e.g. '02770', '0770')"
            )
        return v


class Auth(BaseModel):
    """Provider auth configuration. v0.3: service_account (oauth deferred)."""

    model_config = ConfigDict(extra="allow")

    type: Literal["service_account", "oauth"]
    service_account_file: str | None = None
    impersonate: str | None = None

    @field_validator("service_account_file")
    @classmethod
    def path_absolute(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("/"):
            raise ValueError(f"service_account_file must be an absolute path: got '{v}'")
        return v


class SyncDefaults(BaseModel):
    """Per-account defaults applied to all drives unless overridden."""

    local_subdir: str
    schedule: str
    sync_flags: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)

    @field_validator("local_subdir")
    @classmethod
    def subdir_relative(cls, v: str) -> str:
        if not v:
            raise ValueError("local_subdir must not be empty")
        if v.startswith("/"):
            raise ValueError("local_subdir must be relative (not starting with '/')")
        if ".." in v.split("/"):
            raise ValueError("local_subdir must not contain '..'")
        return v

    @field_validator("schedule")
    @classmethod
    def schedule_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("schedule must not be empty")
        return v


class Account(BaseModel):
    """An account in <org>.yml — defaults + auth + nested drives."""

    remote_name: str
    provider: Literal["drive"]
    description: str | None = None
    auth: Auth
    sync_defaults: SyncDefaults
    additional_excludes: list[str] = Field(default_factory=list)
    drives: list[Drive] = Field(default_factory=list)

    @field_validator("remote_name")
    @classmethod
    def remote_name_valid(cls, v: str) -> str:
        if not REMOTE_NAME_RE.match(v):
            raise ValueError(
                f"'{v}' is not a valid remote_name "
                "(lowercase alphanumeric + underscores, must start with a letter)"
            )
        return v


class RcloneUser(BaseModel):
    """Entry in rclone_users[] — consumed by Ansible, validated lightly by sync-compile."""

    model_config = ConfigDict(extra="allow")

    user: str
    remote_name: str
    provider: str
    key_file: str | None = None
    impersonate: str | None = None


class RegistryMain(BaseModel):
    """The human-owned <org>.yml file (v0.3) — sole source of truth.

    Drives are nested under each account in `accounts[].drives`.
    """

    meta: Meta
    org: str
    rclone_users: list[RcloneUser] = Field(default_factory=list)
    platform: Platform
    accounts: list[Account]

    @field_validator("org")
    @classmethod
    def org_valid(cls, v: str) -> str:
        if not ORG_KEY_RE.match(v):
            raise ValueError(f"'{v}' is not a valid org key")
        return v

    @field_validator("accounts")
    @classmethod
    def accounts_nonempty_unique(cls, v: list[Account]) -> list[Account]:
        if not v:
            raise ValueError("accounts must not be empty")
        names = [a.remote_name for a in v]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate remote_name(s) in accounts: {sorted(dupes)}")
        return v


# ── <org>.cloud.yml — pure discovery snapshot ─────────────────────────────────

DriveStatus = Literal["new", "present", "renamed", "missing_from_cloud"]


class SnapshotDrive(BaseModel):
    """A drive entry in the discovery snapshot.

    Status-specific fields:
      new                -> suggested_local_name set
      renamed            -> cloud_name_was + cloud_name_now set
      missing_from_cloud -> cloud_name reflects last-known value from <org>.yml
      present            -> cloud_name matches <org>.yml exactly
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    cloud_name: str
    status: DriveStatus
    suggested_local_name: str | None = None
    cloud_name_was: str | None = None
    cloud_name_now: str | None = None


class SnapshotAccount(BaseModel):
    """An account in the snapshot — just the remote_name and drive inventory."""

    remote_name: str
    drives: list[SnapshotDrive] = Field(default_factory=list)


class SnapshotMeta(BaseModel):
    """Meta block of the snapshot — adds source-file hash for traceability."""

    version: str
    stage: str | None = None
    generated_at: str
    generated_by: str
    description: str | None = None
    source_yml_path: str
    source_yml_hash: str


class SnapshotRegistry(BaseModel):
    """The tool-owned <org>.cloud.yml — pure snapshot, never authoritative."""

    meta: SnapshotMeta
    org: str
    accounts: list[SnapshotAccount] = Field(default_factory=list)

    @field_validator("org")
    @classmethod
    def org_valid(cls, v: str) -> str:
        if not ORG_KEY_RE.match(v):
            raise ValueError(f"'{v}' is not a valid org key")
        return v


# ── Compiled plan (output dataclasses, plain structs) ─────────────────────────

@dataclass
class RcloneRemote:
    name: str
    type: str
    scope: str
    service_account_file: str | None
    impersonate: str | None
    team_drive: str


@dataclass
class LocalDirectory:
    path: str


@dataclass
class SyncInstance:
    name: str
    enabled: bool
    env_file_path: str | None = None
    env_vars: dict[str, str] | None = None
    timer_override_path: str | None = None
    schedule: str | None = None


@dataclass
class PlatformOut:
    rclone_user: str
    rclone_config_path: str
    default_owner: str | None
    default_group: str | None
    default_mode: str | None


@dataclass
class CompiledPlan:
    compiled_at: str
    compiler_version: str
    schema_version: str
    source_file: str
    source_hash: str
    org: str
    platform: PlatformOut
    rclone_remotes: list[RcloneRemote] = field(default_factory=list)
    local_directories: list[LocalDirectory] = field(default_factory=list)
    sync_instances: list[SyncInstance] = field(default_factory=list)
