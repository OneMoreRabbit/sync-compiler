# sync-compiler

Compiles per-org sync registry YAML files into an Ansible-applicable plan for configuring rclone-based cloud→local syncs on a multi-tenant Linux fileserver.

Reads `sync/<org>.yml` (human-owned intent) and `sync/<org>.cloud.yml` (tool-updated drive inventory) from a registry directory, validates them, and emits `compiled_sync_plan_<org>.yml`. Ansible consumes the plan to write rclone config blocks, create local directories, and manage systemd timer instances.

**Pure YAML → YAML transformer — makes no changes to the host system.** All filesystem, rclone.conf, and systemd changes are Ansible's responsibility.

Companion tool to `rbac-compiler` (same architecture, independent concerns).

## Requirements

- Python 3.10+
- `pipx` (recommended) or `pip`
- `rclone` — only required by the `discover` command

## Installation

### From GitHub (recommended for production)

```bash
pipx install git+https://github.com/ojblakeman/sync-compiler.git
```

This installs `sync-compile` into `~/.local/bin/`. No virtualenv management needed on Ubuntu 24.04.

### For development

```bash
git clone https://github.com/ojblakeman/sync-compiler.git
cd sync-compiler
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```
sync-compile <command> [OPTIONS]
```

### Commands

| Command | Purpose | Needs cloud access |
|---------|---------|--------------------|
| `compile` *(default)* | Emit `compiled_sync_plan_<org>.yml` for Ansible | No |
| `discover` | Query cloud, rewrite `<org>.cloud.yml` with diffs | Yes |
| `validate` | Schema + cross-reference check only | No |

### Common options

| Option | Short | Description |
|--------|-------|-------------|
| `--registry-dir PATH` | `-r` | Registry root. Default: `~/registry`. Sync files expected under `<dir>/sync/`. |
| `--org ORG` | | Which org to operate on (required). |
| `--output PATH` | `-o` | For `compile`: output path. Default: `<registry-dir>/.compiled/compiled_sync_plan_<org>.yml`. |
| `--check` | `-c` | For `compile`: validate only, don't write output. |
| `--dry-run` | | For `discover`: show diff without rewriting `<org>.cloud.yml`. |
| `--yes` | `-y` | Skip confirmation prompts. |
| `--format` | | Output format: `yaml` (default) or `json`. |
| `--verbose` | `-v` | INFO-level logging. |
| `--quiet` | `-q` | Errors only. |

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Validation failure |
| 2 | File I/O error |
| 3 | Cloud API error (discover only) |
| 4 | Internal error |

### Examples

```bash
# First-time setup: create arc.yml by hand, then discover drives
sync-compile discover --org arc
# Review arc.cloud.yml, flip `enabled: true` on the drives you want, save.

# Compile the plan for Ansible
sync-compile compile --org arc

# Validate without emitting output (pre-commit)
sync-compile validate --org arc

# Show what discover would change without writing
sync-compile discover --org arc --dry-run
```

## Registry layout

```
~/registry/
├── sync/
│   ├── arc.yml              # human-owned: platform, accounts, auth, sync defaults
│   ├── arc.cloud.yml        # tool-owned: drive inventory (created by `discover`)
│   └── ...
└── .compiled/
    ├── compiled_sync_plan_arc.yml    # consumed by Ansible
    └── ...
```

See [docs/registry_schema.md](docs/registry_schema.md) for the full schema.

## Relationship to Ansible

sync-compile never touches the host system. The Ansible playbook that consumes `compiled_sync_plan_<org>.yml`:

1. Writes the managed section of `rclone.conf` (between START/END markers, preserving non-managed content)
2. Ensures `local_directories` exist with correct ownership and mode
3. Writes per-instance env files and timer drop-ins
4. Enables/disables systemd timer instances

See the architecture brief for the full contract.

## Development

```bash
pytest                # run all tests
pytest --cov          # with coverage
ruff check src/ tests/
mypy src/
```

## Schema version

Both `<org>.yml` and `<org>.cloud.yml` must carry `meta.version: "0.2"`. Files with mismatched versions are rejected.

## License

Private.
