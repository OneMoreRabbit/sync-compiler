"""
Pydantic models for sync-compiler.

Registry files (two per org):
  <org>.yml        ->  RegistryMain    (platform, accounts with sync defaults but no drives)
  <org>.cloud.yml  ->  RegistryCloud   (drive inventory, rewritten by `discover`)

The `Registry` model is the merged in-memory view used by the compiler and validator.

Path fields are stored as plain strings (never pathlib.Path) because they refer to
Linux target paths, and this tool runs on both Windows (dev) and Linux (prod).
"""

from __future__ import annotations

import re
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


# ── <org>.yml: human-owned intent ─────────────────────────────────────────────

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
    """Provider auth configuration. v0.2: service_account or oauth (latter deferred)."""

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


class AccountMain(BaseModel):
    """An account as declared in <org>.yml — defaults + auth, no drives yet."""

    remote_name: str
    provider: Literal["drive"]
    description: str | None = None
    auth: Auth
    sync_defaults: SyncDefaults
    additional_excludes: list[str] = Field(default_factory=list)

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
    """Entry in rclone_users[] — consumed by Ansible, declared here so sync-compile
    can validate cross-references. Extra fields tolerated (Ansible may read more)."""

    model_config = ConfigDict(extra="allow")

    user: str
    remote_name: str
    provider: str
    key_file: str | None = None
    impersonate: str | None = None


class RegistryMain(BaseModel):
    """The human-owned <org>.yml file."""

    meta: Meta
    org: str
    rclone_users: list[RcloneUser] = Field(default_factory=list)
    platform: Platform
    accounts: list[AccountMain]

    @field_validator("org")
    @classmethod
    def org_valid(cls, v: str) -> str:
        if not ORG_KEY_RE.match(v):
            raise ValueError(f"'{v}' is not a valid org key")
        return v

    @field_validator("accounts")
    @classmethod
    def accounts_nonempty(cls, v: list[AccountMain]) -> list[AccountMain]:
        if not v:
            raise ValueError("accounts must not be empty")
        names = [a.remote_name for a in v]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate remote_name(s) in accounts: {sorted(dupes)}")
        return v


# ── <org>.cloud.yml: tool-owned drive inventory ───────────────────────────────

class Drive(BaseModel):
    """A single cloud drive in the inventory."""

    model_config = ConfigDict(extra="forbid")

    id: str
    cloud_name: str
    local_name: str
    enabled: bool
    overrides: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None
    status: Literal["missing_from_cloud"] | None = None

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


class AccountCloud(BaseModel):
    """An account as declared in <org>.cloud.yml — just remote_name + drives."""

    remote_name: str
    drives: list[Drive] = Field(default_factory=list)


class RegistryCloud(BaseModel):
    """The tool-owned <org>.cloud.yml file."""

    meta: Meta
    org: str
    accounts: list[AccountCloud] = Field(default_factory=list)

    @field_validator("org")
    @classmethod
    def org_valid(cls, v: str) -> str:
        if not ORG_KEY_RE.match(v):
            raise ValueError(f"'{v}' is not a valid org key")
        return v


# ── Merged registry (in-memory only) ──────────────────────────────────────────

class Account(BaseModel):
    """Merged view of an account: main config + drive inventory."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    remote_name: str
    provider: str
    description: str | None
    auth: Auth
    sync_defaults: SyncDefaults
    additional_excludes: list[str]
    drives: list[Drive]


class Registry(BaseModel):
    """Merged registry: RegistryMain + (optional) RegistryCloud."""

    meta_main: Meta
    meta_cloud: Meta | None
    org: str
    rclone_users: list[RcloneUser]
    platform: Platform
    accounts: list[Account]


# ── CompiledPlan (output) ─────────────────────────────────────────────────────
# Plain dataclasses — no validation needed since they are produced internally
# and only ever serialized out. Using dataclasses keeps the emitter simple.

from dataclasses import dataclass, field  # noqa: E402


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
    source_files: dict[str, str]
    source_hashes: dict[str, str]
    org: str
    platform: PlatformOut
    rclone_remotes: list[RcloneRemote] = field(default_factory=list)
    local_directories: list[LocalDirectory] = field(default_factory=list)
    sync_instances: list[SyncInstance] = field(default_factory=list)
