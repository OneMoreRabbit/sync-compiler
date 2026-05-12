"""
sync_compiler v0.3 — public API.

Example:
    from pathlib import Path
    from sync_compiler import compile_for_org

    result = compile_for_org(Path("~/registry").expanduser(), "arc")
    if not result.validation.ok:
        for err in result.validation.errors:
            print(f"ERROR: {err}")
    else:
        print(f"Wrote plan to {result.output_path}")
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
    Auth,
    CompiledPlan,
    Drive,
    LocalDirectory,
    Platform,
    RcloneRemote,
    RegistryMain,
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
    slugify,
    uniquify,
    validate_registry,
)

__version__ = "0.3.0"

__all__ = [
    "__version__",
    # Operations
    "compile_for_org",
    "discover_classify",
    "discover_write",
    "load_registry",
    "validate",
    "CompileResult",
    "DiscoverResult",
    "LoadedRegistry",
    "ValidateResult",
    # Registry
    "AccountClassification",
    "ClassificationResult",
    "ValidationResult",
    "classify_drives",
    "slugify",
    "uniquify",
    "validate_registry",
    # Models
    "Account",
    "Auth",
    "CompiledPlan",
    "Drive",
    "LocalDirectory",
    "Platform",
    "RcloneRemote",
    "RegistryMain",
    "SnapshotAccount",
    "SnapshotDrive",
    "SnapshotMeta",
    "SnapshotRegistry",
    "SyncDefaults",
    "SyncInstance",
    # Errors
    "CloudAPIError",
    "CompilerInternalError",
    "RegistryError",
    "RegistryLoadError",
    "RegistryWarning",
]
