"""
sync_compiler v0.4 — public API.

Example:
    from pathlib import Path
    from sync_compiler import compile_for_org

    result = compile_for_org(Path("~/registry").expanduser(), "arc")
    if not result.validation.ok:
        for err in result.validation.errors:
            print(f"ERROR: {err}")
"""

from .errors import (
    CloudAPIError,
    CompilerInternalError,
    RegistryError,
    RegistryLoadError,
    RegistryWarning,
)
from .models import (
    Account,
    AgentCloudSync,
    AgentRecord,
    AgentRegistry,
    AgentShares,
    Auth,
    BisyncSurface,
    CompiledPlan,
    Drive,
    LocalDirectory,
    Platform,
    RcloneRemote,
    RegistryMain,
    ShareClass,
    SnapshotAccount,
    SnapshotDrive,
    SnapshotMeta,
    SnapshotRegistry,
    SyncDefaults,
    SyncInstance,
)
from .operations import (
    CompileResult,
    DiscoverResult,
    LoadedRegistry,
    ValidateResult,
    compile_for_org,
    discover_classify,
    discover_write,
    load_registry,
    validate,
)
from .registry import (
    AccountClassification,
    ClassificationResult,
    ValidationResult,
    classify_drives,
    resolve_surface_path,
    slugify,
    uniquify,
    validate_agent_sync,
    validate_registry,
)

__version__ = "0.4.0"

__all__ = [
    "__version__",
    "compile_for_org",
    "discover_classify",
    "discover_write",
    "load_registry",
    "validate",
    "CompileResult",
    "DiscoverResult",
    "LoadedRegistry",
    "ValidateResult",
    "AccountClassification",
    "ClassificationResult",
    "ValidationResult",
    "classify_drives",
    "resolve_surface_path",
    "slugify",
    "uniquify",
    "validate_agent_sync",
    "validate_registry",
    "Account",
    "AgentCloudSync",
    "AgentRecord",
    "AgentRegistry",
    "AgentShares",
    "Auth",
    "BisyncSurface",
    "CompiledPlan",
    "Drive",
    "LocalDirectory",
    "Platform",
    "RcloneRemote",
    "RegistryMain",
    "ShareClass",
    "SnapshotAccount",
    "SnapshotDrive",
    "SnapshotMeta",
    "SnapshotRegistry",
    "SyncDefaults",
    "SyncInstance",
    "CloudAPIError",
    "CompilerInternalError",
    "RegistryError",
    "RegistryLoadError",
    "RegistryWarning",
]
