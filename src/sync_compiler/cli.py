"""
Click-based CLI for sync-compile.

Three subcommands:
  compile   - validate and emit compiled_sync_plan_<org>.yml (default)
  discover  - query cloud, rewrite <org>.cloud.yml
  validate  - schema + cross-reference check only

All subcommands are thin wrappers over sync_compiler.operations. The CLI's job
is argument parsing, logging setup, user prompts, and formatting for humans.
Structured results come from operations.py.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from . import __version__
from .cloud import CloudDrive
from .errors import CloudAPIError, RegistryLoadError
from .operations import (
    CompileResult,
    DiscoverResult,
    ValidateResult,
    compile_for_org,
    discover,
    validate,
)
from .registry import DiffResult, DriveDiff, ValidationResult

logger = logging.getLogger("sync_compile")


def _setup_logging(verbose: bool, quiet: bool) -> None:
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING
    logging.basicConfig(format="%(levelname)s: %(message)s", level=level, stream=sys.stderr)


def _default_registry_dir() -> Path:
    return Path.home() / "registry"


# ── Shared option decorators ──────────────────────────────────────────────────

_registry_dir_opt = click.option(
    "--registry-dir", "-r",
    default=None,
    type=click.Path(path_type=Path),
    metavar="PATH",
    help="Registry root directory. Default: ~/registry (sync files expected under <dir>/sync/).",
)

_org_opt = click.option(
    "--org",
    required=True,
    metavar="ORG",
    help="Which org to operate on.",
)

_verbose_opt = click.option("--verbose", "-v", is_flag=True, help="INFO-level logging.")
_quiet_opt = click.option("--quiet", "-q", is_flag=True, help="Errors only.")


# ── Root group ────────────────────────────────────────────────────────────────

@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.version_option(version=__version__, prog_name="sync-compile")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Compile cloud-sync registries into an Ansible-applicable plan.

    Reads ~/registry/sync/<org>.yml and <org>.cloud.yml, validates them, and
    emits compiled_sync_plan_<org>.yml. With no subcommand, behaves like `compile`.
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        sys.exit(0)


# ── compile ───────────────────────────────────────────────────────────────────

@cli.command("compile")
@_registry_dir_opt
@_org_opt
@click.option(
    "--output", "-o",
    default=None,
    type=click.Path(path_type=Path),
    metavar="PATH",
    help="Output file path. Default: <registry-dir>/.compiled/compiled_sync_plan_<org>.yml",
)
@click.option(
    "--format", "fmt",
    default="yaml",
    type=click.Choice(["yaml", "json"], case_sensitive=False),
    show_default=True,
    help="Output format.",
)
@click.option(
    "--check", "-c",
    is_flag=True,
    help="Validate only - do not write output.",
)
@_verbose_opt
@_quiet_opt
def compile_cmd(
    registry_dir: Path | None,
    org: str,
    output: Path | None,
    fmt: str,
    check: bool,
    verbose: bool,
    quiet: bool,
) -> None:
    """Validate and emit the compiled sync plan."""
    _setup_logging(verbose, quiet)
    reg_dir = (registry_dir or _default_registry_dir()).expanduser().resolve()

    try:
        result = compile_for_org(
            registry_dir=reg_dir,
            org=org,
            output=output,
            fmt=fmt.lower(),
            check_only=check,
        )
    except RegistryLoadError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)

    _report_compile(result, check_only=check, quiet=quiet)


def _report_compile(result: CompileResult, check_only: bool, quiet: bool) -> None:
    _print_warnings(result.validation)
    if not result.validation.ok:
        _print_errors(result.validation)
        sys.exit(1)

    if check_only:
        if not quiet:
            click.echo(
                f"Validation passed: {_counts_summary(result)}"
            )
        sys.exit(0)

    if result.plan is None or result.output_path is None:
        click.echo("ERROR: internal state: plan missing after validation passed", err=True)
        sys.exit(4)

    if not quiet:
        click.echo(
            f"Compiled {len(result.plan.rclone_remotes)} remotes, "
            f"{len(result.plan.local_directories)} directories, "
            f"{len(result.plan.sync_instances)} sync instances "
            f"-> {result.output_path}"
        )


def _counts_summary(result: CompileResult) -> str:
    main = result.loaded.main
    cloud_drives = sum(
        len(ca.drives) for ca in (result.loaded.cloud.accounts if result.loaded.cloud else [])
    )
    return f"org='{main.org}', {len(main.accounts)} account(s), {cloud_drives} drive(s)"


# ── validate ──────────────────────────────────────────────────────────────────

@cli.command("validate")
@_registry_dir_opt
@_org_opt
@_verbose_opt
@_quiet_opt
def validate_cmd(
    registry_dir: Path | None, org: str, verbose: bool, quiet: bool
) -> None:
    """Validate the registry without emitting output."""
    _setup_logging(verbose, quiet)
    reg_dir = (registry_dir or _default_registry_dir()).expanduser().resolve()

    try:
        result: ValidateResult = validate(reg_dir, org)
    except RegistryLoadError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)

    _print_warnings(result.validation)
    if not result.validation.ok:
        _print_errors(result.validation)
        sys.exit(1)

    if not quiet:
        main = result.loaded.main if result.loaded else None
        if main:
            click.echo(f"Validation passed: org='{main.org}', {len(main.accounts)} account(s).")
        else:
            click.echo("Validation passed.")


# ── discover ──────────────────────────────────────────────────────────────────

@cli.command("discover")
@_registry_dir_opt
@_org_opt
@click.option("--dry-run", is_flag=True, help="Show diff, don't write <org>.cloud.yml.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@_verbose_opt
@_quiet_opt
def discover_cmd(
    registry_dir: Path | None,
    org: str,
    dry_run: bool,
    yes: bool,
    verbose: bool,
    quiet: bool,
) -> None:
    """Query cloud, rewrite <org>.cloud.yml with the diff."""
    _setup_logging(verbose, quiet)
    reg_dir = (registry_dir or _default_registry_dir()).expanduser().resolve()

    # Phase 1: compute diff without writing
    try:
        result: DiscoverResult = discover(
            registry_dir=reg_dir, org=org, dry_run=True
        )
    except RegistryLoadError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)
    except CloudAPIError as exc:
        click.echo(f"ERROR: Cloud API failure during discover\n  {exc}", err=True)
        sys.exit(3)

    _print_diff(result.diff, result.output_path)

    if not result.diff.has_changes:
        sys.exit(0)
    if dry_run:
        click.echo("(--dry-run) no changes written.")
        sys.exit(0)

    if not yes:
        if not click.confirm(f"Write these changes to {result.output_path}?", default=False):
            click.echo("aborted.")
            sys.exit(1)

    # Phase 2: actually write
    try:
        final: DiscoverResult = discover(
            registry_dir=reg_dir, org=org, dry_run=False
        )
    except RegistryLoadError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)
    except CloudAPIError as exc:
        click.echo(f"ERROR: Cloud API failure during discover\n  {exc}", err=True)
        sys.exit(3)

    if not quiet:
        click.echo(f"Wrote {final.output_path}.")


# ── Reporting helpers ─────────────────────────────────────────────────────────

def _print_warnings(result: ValidationResult) -> None:
    for w in result.warnings:
        click.echo(f"WARN: {w}", err=True)


def _print_errors(result: ValidationResult) -> None:
    for e in result.errors:
        click.echo(f"ERROR: {e}", err=True)
    click.echo(
        f"\nValidation failed: {len(result.errors)} error(s), {len(result.warnings)} warning(s).",
        err=True,
    )


def _print_diff(diff: DiffResult, cloud_path: Path) -> None:
    if not diff.has_changes:
        click.echo("No changes detected.")
        return

    click.echo(f"\nChanges to {cloud_path}:")
    for account_name, d in diff.per_account.items():
        if not (d.new or d.renamed or d.missing or d.reappeared):
            continue
        click.echo(f"\n  account: {account_name}")
        _print_account_diff(d)


def _print_account_diff(d: DriveDiff) -> None:
    if d.new:
        click.echo("    NEW (will be added with enabled: false):")
        for cd in d.new:
            click.echo(f"      - \"{cd.name}\" (id: {cd.id})")
    if d.renamed:
        click.echo("    RENAMED in cloud:")
        for existing, cloud_drive in d.renamed:
            click.echo(f"      - id: {existing.id}")
            click.echo(f"        was: \"{existing.cloud_name}\"")
            click.echo(f"        now: \"{cloud_drive.name}\"")
            click.echo(f"        local_name unchanged: \"{existing.local_name}\"")
    if d.missing:
        click.echo("    MISSING from cloud (will be marked status: missing_from_cloud, disabled):")
        for existing in d.missing:
            click.echo(f"      - \"{existing.cloud_name}\" "
                       f"(id: {existing.id}, local: {existing.local_name})")
    if d.reappeared:
        click.echo("    REAPPEARED in cloud (status flag cleared):")
        for existing in d.reappeared:
            click.echo(f"      - \"{existing.cloud_name}\" (id: {existing.id})")


def main() -> None:
    cli()


# Re-export CloudDrive for tests that import from cli
_ = CloudDrive
