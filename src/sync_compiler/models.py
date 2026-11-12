"""
Pydantic models for sync-compiler v0.4.

v0.4 changes:
  - sync_instances gains explicit `mode: sync | bisync`.
  - New input `agent_registry.yml` (read by sync-compile for agent-share bisync).
  - Top-level agents are agents of a regular org named `top` — no special case.

Schema v0.4:
  <org>.yml             ->  RegistryMain      (sole source of truth for sync drives)
  <org>.cloud.yml       ->  SnapshotRegistry  (tool-written discovery snapshot, .compiled/)
  agent_registry.yml    ->  AgentRegistry     (read for share_class.org + cloud_sync)

Path fields are plain strings (never pathlib.Path) — Linux paths on a Windows dev host.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

LINUX_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
ORG_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
REMOTE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
LOCAL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SUB_AGENT_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
OCTAL_MODE_RE = re.compile(r"^[0-7]{3,5}$")


# ── Shared ────────────────────────────────────────────────────────────────────

class Meta(BaseModel):
    version: str
    stage: str | None = None
    last_modified: str | None = None
    last_modified_by: str | None = None
    description: str | None = None


# ── <org>.yml — sync drives source of truth ───────────────────────────────────

class Drive(BaseModel):
    """A cloud drive declared under an account in <org>.yml.

    `enabled` lives here — this is the source of truth.
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
    # ADR-0010 §7: beaver's mount of the agent host's export, for this org --
    # `/mnt/agent-hosts/<host>/<org>`. memory/sessions/scratch resolve under it;
    # `configs/` does NOT move and stays under the historic /mnt/raid shape.
    # Optional because an org with no agent surfaces needs no such root (§11 1.6:
    # a value governing nothing is not declared). NEVER defaulted: it names the
    # host whose disk holds the data, and a plausible value would be a path to
    # the wrong machine (§11 1.11 -- a target never takes a plausible default).
    agent_mount_base: str | None = None
    default_owner: str | None = None
    default_group: str | None = None
    default_mode: str | None = None

    @field_validator("rclone_user")
    @classmethod
    def rclone_user_valid(cls, v: str) -> str:
        if not LINUX_USERNAME_RE.match(v):
            raise ValueError(
                f"'{v}' is not a valid Linux username "
                "(lowercase alphanumeric + underscores, <= 32 chars)"
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

    @field_validator("agent_mount_base")
    @classmethod
    def agent_mount_base_valid(cls, v: str | None) -> str | None:
        """Same path rules as local_base, but absence is legal (see the field note)."""
        if v is None:
            return v
        if not v.startswith("/"):
            raise ValueError(f"must be an absolute path (start with '/'): got '{v}'")
        if ".." in v.split("/"):
            raise ValueError(f"must not contain '..': got '{v}'")
        return v.rstrip("/")

    @field_validator("default_mode")
    @classmethod
    def mode_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not OCTAL_MODE_RE.match(v):
            raise ValueError(f"'{v}' is not a valid octal mode (e.g. '02770')")
        return v


class Auth(BaseModel):
    """Provider auth. v0.5 makes `oauth` real, by token FILE REFERENCE.

    A personal org's Google account cannot use a service account, so v0.5 names
    a token file path on the fileserver. sync-compile never reads its contents:
    no token value reaches a compiled plan, a log, or the vault.
    """

    model_config = ConfigDict(extra="allow")

    type: Literal["service_account", "oauth"]
    service_account_file: str | None = None
    token_file: str | None = None
    impersonate: str | None = None

    @field_validator("service_account_file", "token_file")
    @classmethod
    def path_absolute(cls, v: str | None, info: ValidationInfo) -> str | None:
        if v is not None and not v.startswith("/"):
            raise ValueError(f"{info.field_name} must be an absolute path: got '{v}'")
        return v

    @model_validator(mode="after")
    def credential_matches_type(self) -> Auth:
        """Exactly the credential the type calls for — never both, never neither.

        A missing credential is not defaulted: it names the file the compiler
        tells Ansible to authenticate with, and a plausible default would point
        at the wrong account's token (constitution §11 1.11).
        """
        if self.type == "service_account":
            if self.service_account_file is None:
                raise ValueError("auth.type 'service_account' requires service_account_file")
            if self.token_file is not None:
                raise ValueError("auth.type 'service_account' must not set token_file")
        else:  # oauth
            if self.token_file is None:
                raise ValueError("auth.type 'oauth' requires token_file")
            if self.service_account_file is not None:
                raise ValueError("auth.type 'oauth' must not set service_account_file")
        return self


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
            raise ValueError("local_subdir must be relative")
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
    """Entry in rclone_users[] — consumed by Ansible, lightly validated.

    `remote_name` and `provider` are optional: a bisync-only org (e.g. `top`)
    has an rclone user with no platform-managed service-account remote — its
    agents bisync to manually-configured personal remotes.
    """

    model_config = ConfigDict(extra="allow")

    user: str
    remote_name: str | None = None
    provider: str | None = None
    key_file: str | None = None
    impersonate: str | None = None


ConflictPolicy = Literal["newer", "suffix"]

# TWO DIFFERENT BOUNDS, TWO DIFFERENT UNITS. Read this before changing either.
#
# `max_delete` on a scope is a COUNT OF FILES — the operator's 50 means fifty
# files. It is NOT an rclone flag: rclone's --max-delete means a PERCENTAGE of
# the files on a side when the command is `bisync` (it is a count for `sync`,
# which is where the confusion came from). Measured live on AI Data by
# estate-manage: --max-delete 50 tripped on a near-empty drive at 2 of 3 files,
# 67%. So the count is emitted as its own env value, MAX_DELETE, and the
# estate-side gate dry-runs and refuses the run when either side's planned
# deletes exceed it.
DEFAULT_MAX_DELETE = 50

# rclone's own percentage backstop, emitted into BISYNC_FLAGS. Deliberately
# high: it exists to stop a near-total wipe, not to express policy — the count
# gate above is the policy. A low percentage is what bit us, because on a small
# side any ordinary deletion is a large fraction of it.
BISYNC_MAX_DELETE_PERCENT = 90


class DriveFolder(BaseModel):
    """An org Drive folder synced two-way (compiled-sync-plan 0.5).

    Today's bisync is agent-shaped: a `scratch` or `memory` surface on an agent
    record, resolved under ADR-0010 §7's mount root. A Drive folder belongs to
    the ORG, not to an agent, so it carries its own local path and names the
    account whose credentials reach it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    remote: str                      # an Account.remote_name in this org
    folder: str                      # the folder as named in the Drive
    local_path: str                  # absolute path on the fileserver
    enabled: bool = True
    team_drive: str | None = None    # shared-drive id; omitted for a personal Drive
    conflict_policy: ConflictPolicy = "newer"
    schedule: str = "*:0/15"
    max_delete: int = DEFAULT_MAX_DELETE

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        if not REMOTE_NAME_RE.match(v):
            raise ValueError(
                f"'{v}' is not a valid folder scope name "
                "(lowercase alphanumeric + underscores, must start with a letter)"
            )
        return v

    @field_validator("local_path")
    @classmethod
    def local_path_absolute(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(f"local_path must be an absolute path: got '{v}'")
        return v

    @field_validator("max_delete")
    @classmethod
    def max_delete_bounded(cls, v: int) -> int:
        """A bound that does not bound is not a bound.

        rclone reads -1 as unlimited and 0 as 'delete nothing'. Unlimited is the
        defect this field exists to close, so it is refused outright rather than
        quietly accepted.
        """
        if v < 1:
            raise ValueError(
                f"max_delete must be at least 1: got {v}. "
                "rclone treats -1 as unlimited, which is the condition this field "
                "exists to prevent; to pause a scope, set enabled: false."
            )
        return v


class RegistryMain(BaseModel):
    """<org>.yml v0.4. Top-level agents live under org `top`; no special case."""

    meta: Meta
    org: str
    rclone_users: list[RcloneUser] = Field(default_factory=list)
    platform: Platform
    accounts: list[Account] = Field(default_factory=list)
    drive_folders: list[DriveFolder] = Field(default_factory=list)

    @field_validator("org")
    @classmethod
    def org_valid(cls, v: str) -> str:
        if not ORG_KEY_RE.match(v):
            raise ValueError(f"'{v}' is not a valid org key")
        return v

    @field_validator("accounts")
    @classmethod
    def accounts_unique(cls, v: list[Account]) -> list[Account]:
        # An empty accounts list is valid — a bisync-only org (e.g. `top`)
        # has no platform-managed cloud-sync drives. remote_name uniqueness
        # is still enforced when accounts are present.
        names = [a.remote_name for a in v]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate remote_name(s): {sorted(dupes)}")
        return v


# ── <org>.cloud.yml — discovery snapshot (unchanged v0.3 → v0.4 shape) ────────

DriveStatus = Literal["new", "present", "renamed", "missing_from_cloud"]


class SnapshotDrive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    cloud_name: str
    status: DriveStatus
    suggested_local_name: str | None = None
    cloud_name_was: str | None = None
    cloud_name_now: str | None = None


class SnapshotAccount(BaseModel):
    remote_name: str
    drives: list[SnapshotDrive] = Field(default_factory=list)


class SnapshotMeta(BaseModel):
    version: str
    stage: str | None = None
    generated_at: str
    generated_by: str
    description: str | None = None
    source_yml_path: str
    source_yml_hash: str


class SnapshotRegistry(BaseModel):
    meta: SnapshotMeta
    org: str
    accounts: list[SnapshotAccount] = Field(default_factory=list)

    @field_validator("org")
    @classmethod
    def org_valid(cls, v: str) -> str:
        if not ORG_KEY_RE.match(v):
            raise ValueError(f"'{v}' is not a valid org key")
        return v


# ── agent_registry.yml — sync-compile reads share_class + cloud_sync ─────────

BisyncSurfaceKey = Literal["scratch", "memory"]


class ShareClass(BaseModel):
    """An agent's home classification. Required if the agent has share-related fields."""

    model_config = ConfigDict(extra="allow")  # rbac-compile may add fields

    org: str
    grade: int
    vertical: str
    scope: str

    @field_validator("org")
    @classmethod
    def org_valid(cls, v: str) -> str:
        if not ORG_KEY_RE.match(v):
            raise ValueError(f"'{v}' is not a valid org key")
        return v


class BisyncSurface(BaseModel):
    """Bisync config for one surface (scratch or memory)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    remote: str | None = None
    conflict_policy: ConflictPolicy = "newer"
    schedule: str = "*:0/1"
    max_delete: int = DEFAULT_MAX_DELETE

    @field_validator("remote")
    @classmethod
    def remote_format(cls, v: str | None) -> str | None:
        if v is not None and ":" not in v:
            raise ValueError(
                f"remote must include a ':' separator (e.g. 'remote:path/'): got '{v}'"
            )
        return v


class AgentCloudSync(BaseModel):
    """Bisync config block on an agent. Extra surface keys are tolerated (warn at validate)."""

    model_config = ConfigDict(extra="allow")  # to let sessions/configs through for warn

    scratch: BisyncSurface | None = None
    memory: BisyncSurface | None = None


class AgentShares(BaseModel):
    """Optional per-surface path overrides for an agent."""

    model_config = ConfigDict(extra="forbid")

    configs: str | None = None
    memory: str | None = None
    sessions: str | None = None
    scratch: str | None = None


class AgentRecord(BaseModel):
    """Lightweight agent view for sync-compile.

    Fields we don't care about (`access`, `description`, `app`, `local_user`, etc.)
    are tolerated via extra=allow — rbac-compile owns them.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    share_class: ShareClass | None = None
    sub_agents: list[str] = Field(default_factory=list)
    shares: AgentShares | None = None
    cloud_sync: AgentCloudSync | None = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        if not LINUX_USERNAME_RE.match(v):
            raise ValueError(f"'{v}' is not a valid Linux username")
        return v

    @field_validator("sub_agents")
    @classmethod
    def sub_agents_valid(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        for name in v:
            if not SUB_AGENT_RE.match(name):
                raise ValueError(
                    f"sub_agent '{name}' invalid (lowercase alphanumeric + underscores)"
                )
            if name == "main":
                raise ValueError("sub_agent 'main' is reserved")
            if name in seen:
                raise ValueError(f"duplicate sub_agent '{name}'")
            seen.add(name)
        return v


class AgentRegistry(BaseModel):
    """The agent_registry.yml file. sync-compile reads it for share_class + cloud_sync."""

    model_config = ConfigDict(extra="allow")

    meta: Meta
    agents: list[AgentRecord] = Field(default_factory=list)


# ── Compiled plan (output dataclasses) ────────────────────────────────────────

SyncMode = Literal["sync", "bisync"]


@dataclass
class RcloneRemote:
    name: str
    type: str
    scope: str
    service_account_file: str | None
    impersonate: str | None
    team_drive: str
    # 0.5: set where the account authenticates by OAuth token reference.
    # Exactly one of service_account_file / token_file is ever populated.
    token_file: str | None = None


@dataclass
class LocalDirectory:
    path: str


@dataclass
class SyncInstance:
    name: str
    enabled: bool
    mode: SyncMode = "sync"
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
    agent_registry_path: str | None
    agent_registry_hash: str | None
    org: str
    platform: PlatformOut
    rclone_remotes: list[RcloneRemote] = field(default_factory=list)
    local_directories: list[LocalDirectory] = field(default_factory=list)
    sync_instances: list[SyncInstance] = field(default_factory=list)
