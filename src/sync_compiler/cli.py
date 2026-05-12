"""
Click-based CLI for sync-compile (v0.3).

Subcommands:
  compile   - validate <org>.yml and emit compiled_sync_plan_<org>.yml (default)
  discover  - query cloud, write .compiled/<org>.cloud.yml snapshot (interactive)
  validate  - schema + cross-reference check only
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from . import __version__
from .errors import CloudAPIError, RegistryLoadError
from .operations import (
    CompileResult,
    DiscoverResult,
    ValidateResult,
    compile_for_org,
    discover_classify,
    discover_write,
    validate,
)
from .registry import ClassificationResult, ValidationResult

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


_registry_dir_opt = click.option(
    "--registry-dir", "-r",
    default=None,
    type=click.Path(path_type=Path),
    metavar="PATH",
    help="Registry root directory. Default: ~/registry (sync files under <dir>/sync/).",
)
_org_opt = click.option("--org", required=True, metavar="ORG", help="Which org to operate on.")
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

    Reads ~/registry/sync/<org>.yml (sole source of truth) and emits
    ~/registry/.compiled/compiled_sync_plan_<org>.yml.
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
@click.option("--check", "-c", is_flag=True, help="Validate only - do not write output.")
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

    _print_warnings(result.validation)
    if not result.validation.ok:
        _print_errors(result.validation)
        sys.exit(1)

    if check:
        if not quiet:
            click.echo(f"Validation passed: {_counts_summary(result)}")
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
    drive_count = sum(len(a.drives) for a in main.accounts)
    return f"org='{main.org}', {len(main.accounts)} account(s), {drive_count} drive(s)"


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

    if not quiet and result.loaded is not None:
        main = result.loaded.main
        drive_count = sum(len(a.drives) for a in main.accounts)
        click.echo(
            f"Validation passed: org='{main.org}', "
            f"{len(main.accounts)} account(s), {drive_count} drive(s)."
        )


# ── discover ──────────────────────────────────────────────────────────────────

@cli.command("discover")
@_registry_dir_opt
@_org_opt
@click.option(
    "--output", "-o",
    default=None,
    type=click.Path(path_type=Path),
    metavar="PATH",
    help="Snapshot output path. Default: <registry-dir>/.compiled/<org>.cloud.yml",
)
@click.option("--dry-run", is_flag=True, help="Print snapshot to stdout, do not write.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt before writing.")
@_verbose_opt
@_quiet_opt
def discover_cmd(
    registry_dir: Path | None,
    org: str,
    output: Path | None,
    dry_run: bool,
    yes: bool,
    verbose: bool,
    quiet: bool,
) -> None:
    """Query cloud, write .compiled/<org>.cloud.yml discovery snapshot."""
    _setup_logging(verbose, quiet)
    reg_dir = (registry_dir or _default_registry_dir()).expanduser().resolve()

    # Phase 1: classify (no I/O writes)
    try:
        result: DiscoverResult = discover_classify(registry_dir=reg_dir, org=org)
    except RegistryLoadError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)
    except CloudAPIError as exc:
        click.echo(f"ERROR: Cloud API failure during discover\n  {exc}", err=True)
        sys.exit(3)

    target = output or result.output_path
    _print_classification_summary(result.classification, target)

    if dry_run:
        click.echo("\n--- snapshot (dry-run, not written) ---\n")
        click.echo(result.snapshot_yaml)
        sys.exit(0)

    # Decide whether to write
    if not yes:
        if not click.confirm(f"\nWrite snapshot to {target}?", default=False):
            click.echo("aborted.")
            sys.exit(1)

    # Phase 2: atomic write
    try:
        written = discover_write(result, output=target)
    except OSError as exc:
        click.echo(f"ERROR: Cannot write snapshot: {exc}", err=True)
        sys.exit(2)

    if not quiet:
        click.echo(f"Wrote snapshot -> {written.output_path}")


# ── Reporting helpers ─────────────────────────────────────────────────────────

def _print_warnings(result: ValidationResult) -> None:
    for w in result.warnings:
        click.echo(f"WARN: {w}", err=True)


def _print_errors(result: ValidationResult) -> None:
    for e in result.errors:
        click.echo(f"ERROR: {e}", err=True)
    click.echo(
        f"\nValidation failed: {len(result.errors)} error(s), "
        f"{len(result.warnings)} warning(s).",
        err=True,
    )


def _print_classification_summary(c: ClassificationResult, target: Path) -> None:
    click.echo(f"\nDiscovery summary for {target}:")
    for account_name, acc in c.per_account.items():
        click.echo(
            f"  {account_name}: "
            f"{acc.present} present, "
            f"{acc.new} new, "
            f"{acc.renamed} renamed, "
            f"{acc.missing_from_cloud} missing"
        )
        for d in acc.drives:
            if d.status == "new":
                click.echo(
                    f"    NEW                \"{d.cloud_name}\" "
                    f"(id={d.id}, suggested local_name={d.suggested_local_name})"
                )
            elif d.status == "renamed":
                click.echo(
                    f"    RENAMED            id={d.id}"
                )
                click.echo(f"      was: \"{d.cloud_name_was}\"")
                click.echo(f"      now: \"{d.cloud_name_now}\"")
            elif d.status == "missing_from_cloud":
                click.echo(
                    f"    MISSING_FROM_CLOUD \"{d.cloud_name}\" (id={d.id})"
                )

    if not c.has_drift:
        click.echo("  (no drift detected - snapshot matches <org>.yml)")


def main() -> None:
    cli()
