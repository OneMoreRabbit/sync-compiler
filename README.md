# sync-compiler

Compiles a per-org sync registry into an Ansible-applicable plan for configuring rclone-based syncs on a multi-tenant Linux fileserver.

Three kinds of sync: a one-way copy of a shared drive; a two-way sync of an agent's folder; a two-way sync of an org Drive folder.

Reads `sync/<org>.yml` (sole source of truth) and emits `compiled_sync_plan_<org>.yml`. Ansible consumes the plan to write rclone config blocks, create local directories, and manage systemd timer instances.

A separate `discover` command queries the cloud and writes a discovery snapshot at `.compiled/<org>.cloud.yml` — purely informational. Humans review the snapshot and copy desired entries into `<org>.yml` to add or update drives.

**Pure YAML → YAML transformer — makes no changes to the host system.** All filesystem, rclone.conf, and systemd changes are Ansible's responsibility.

Companion tool to `rbac-compiler` (same architecture, independent concerns).

## Requirements

- Python 3.10+
- `pipx` (recommended) or `pip`
- `rclone` — only required by the `discover` command

## Installation

### From GitHub (recommended)

```bash
pipx install git+https://github.com/OneMoreRabbit/sync-compiler.git
```

Installs `sync-compile` into `~/.local/bin/`. Upgrade later with `pipx upgrade sync-compiler`.

### For development

```bash
git clone https://github.com/OneMoreRabbit/sync-compiler.git
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

| Command | Purpose | Cloud access |
|---------|---------|--------------|
| `compile` | Validate `<org>.yml` and emit `compiled_sync_plan_<org>.yml` | No |
| `discover` | Query cloud, write `.compiled/<org>.cloud.yml` discovery snapshot | Yes |
| `validate` | Schema + cross-reference check only | No |

### Common options

| Option | Short | Description |
|--------|-------|-------------|
| `--registry-dir PATH` | `-r` | Registry root. Default: `~/registry`. Sync files under `<dir>/sync/`. |
| `--org ORG` | | Which org to operate on (required). |
| `--output PATH` | `-o` | Custom output path. |
| `--check` | `-c` | `compile` only: validate without writing. |
| `--dry-run` | | `discover` only: print snapshot to stdout, don't write. |
| `--yes` | `-y` | `discover` only: skip confirmation prompt. |
| `--format` | | `compile` only: `yaml` (default) or `json`. |
| `--verbose` | `-v` | INFO-level logging. |
| `--quiet` | `-q` | Errors only. |

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Validation failure |
| 2 | File I/O error |
| 3 | Cloud API error (`discover` only) |
| 4 | Internal error |

### Examples

```bash
# Validate
sync-compile validate --org arc

# Compile the plan for Ansible
sync-compile compile --org arc

# Discover cloud state, preview before writing
sync-compile discover --org arc --dry-run

# Discover and write snapshot non-interactively (Ansible / CI)
sync-compile discover --org arc --yes
```

### Adding a new drive

1. `sync-compile discover --org arc` — writes `.compiled/arc.cloud.yml` showing all cloud drives, including any new ones with `status: new` and a `suggested_local_name`.
2. Review the snapshot. Copy desired drive entries into `sync/arc.yml` under the right account's `drives:` list. Set `enabled: true`.
3. `sync-compile compile --org arc` to regenerate the plan.
4. Ansible applies.

The tool **never** mutates `<org>.yml`. Promotion of drives from snapshot to source-of-truth is an explicit human action.

## Registry layout

```
~/registry/
├── sync/
│   ├── arc.yml              # sole source of truth — humans edit
│   └── ...
└── .compiled/               # gitignored, regenerable
    ├── arc.cloud.yml        # discovery snapshot — sync-compile writes
    └── compiled_sync_plan_arc.yml
```

The authoritative documents live in the Atlas vault, not here:
`components/sync-compile/docs/sync-compile-architecture-v0_5.md` (how it works, with diagrams)
and `components/sync-compile/docs/provides/compiled-sync-plan-v0_6.md` (the plan it emits,
field by field). `docs/registry_schema.md` in this repo is a pointer to them.

## Relationship to Ansible

`sync-compile` never touches the host system. The Ansible playbook that consumes `compiled_sync_plan_<org>.yml`:

1. Writes the managed section of `rclone.conf` (between START/END markers, preserving non-managed content)
2. Ensures `local_directories` exist with correct ownership and mode
3. Writes per-instance env files and timer drop-ins
4. Enables/disables systemd timer instances

## Versions

Two different numbers, and they move independently:

- **Input**: `<org>.yml` and the discovery snapshot carry `meta.version: "0.4"`. v0.2 and
  v0.3 layouts trigger a fail-fast with operator-friendly migration instructions.
- **Output**: the compiled plan carries `schema_version: "0.6"` — the
  `compiled-sync-plan` contract version, which is not this package's version.

Installed from tags only. See `release-notes.md` for what each release changed.

## Development

```bash
pytest                          # 135 tests; coverage floor 85%
pytest --cov
ruff check src/ tests/
mypy src/
```

## License

Private.
