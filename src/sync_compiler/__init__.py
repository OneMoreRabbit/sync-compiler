"""
sync_compiler — public API for programmatic use (CLI and future web GUI).

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
    AccountCloud,
    AccountMain,
    Auth,
    CompiledPlan,
    Drive,
    LocalDirectory,
    Platform,
    RcloneRemote,
    Registry,
    RegistryCloud,
    RegistryMain,
    SyncDefaults,
    SyncInstance,
)
from .operations import (
    CompileResult,
    DiscoverResult,
    LoadedRegistry,
    ValidateResult,
    compile_for_org,
    discover,
    load_registry,
    validate,
)
from .registry import (
    DiffResult,
    DriveDiff,
    ValidationResult,
    diff_against_cloud,
    merge,
    slugify,
    validate_registry,
)

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # Operations (high-level API)
    "compile_for_org",
    "discover",
    "load_registry",
    "validate",
    "CompileResult",
    "DiscoverResult",
    "LoadedRegistry",
    "ValidateResult",
    # Registry
    "DiffResult",
    "DriveDiff",
    "ValidationResult",
    "diff_against_cloud",
    "merge",
    "slugify",
    "validate_registry",
    # Models
    "Account",
    "AccountCloud",
    "AccountMain",
    "Auth",
    "CompiledPlan",
    "Drive",
    "LocalDirectory",
    "Platform",
    "RcloneRemote",
    "Registry",
    "RegistryCloud",
    "RegistryMain",
    "SyncDefaults",
    "SyncInstance",
    # Errors
    "CloudAPIError",
    "CompilerInternalError",
    "RegistryError",
    "RegistryLoadError",
    "RegistryWarning",
]
