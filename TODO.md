# sync-compiler — TODO / Future Work

Consolidated list of deferred work, parked in scope discussions, or extracted from prior architecture briefs. Not commitments — just where ideas live so they don't get lost.

---

## High-value next-pass UX

### `sync-compile add-drive` — promote a snapshot entry into `<org>.yml`
Today, after `discover` writes the snapshot, humans manually copy YAML from `.compiled/<org>.cloud.yml` into `sync/<org>.yml`. A helper that does this would be a real ergonomic win:

```bash
sync-compile add-drive --org arc --account drive --id 0NEW... [--enabled]
```

Reads the snapshot, finds the entry, appends it under the matching account in `<org>.yml` with `enabled: false` (or `true` if `--enabled` is passed), uses ruamel round-trip to preserve comments. Future GUI obviates this need, but a CLI helper is a cheap interim win.

### `sync-compile migrate` — auto-migrate v0.2 → v0.3 on disk
v0.3 currently detects v0.2 layout and fails with manual instructions. A `migrate` command could:

1. Read `sync/<org>.yml` (v0.2) + `sync/<org>.cloud.yml`
2. Merge drives into the main file under the matching account
3. Bump `meta.version` → `"0.3"`
4. Delete `sync/<org>.cloud.yml`
5. Optionally run `discover` to produce the v0.3 snapshot in `.compiled/`

Out of scope for v0.3 because there's exactly one operator with two orgs — manual is faster than building the migrator. Useful if/when more orgs come online.

### Snapshot retention / history
Right now `discover` overwrites `.compiled/<org>.cloud.yml` atomically each run. A small history (timestamped previous snapshots) would let operators diff "what changed in the cloud since last week." Probably stored under `.compiled/snapshots/<org>/<timestamp>.yml`, with a configurable retention count.

### `sync-compile diff` — preview compile output changes
Compare the current `compiled_sync_plan_<org>.yml` against what a fresh compile would produce. Useful pre-apply review:

```bash
sync-compile diff --org arc
# shows: 1 sync_instance added, 1 enabled→disabled, schedule changed on 2 drives
```

### `sync-compile status` — runtime view
Read `/var/lib/rclone-sync/status/*.json` (written by the sync wrapper) and present per-drive last-run / errors / bytes-transferred. Read-only, fits the pure-transformation model. Originally in the v0.1 brief, deferred for v0.2 and v0.3.

---

## Provider support

### Dropbox / OneDrive
v0.2 / v0.3 hard-code `provider: drive`. `cloud.py` is structured around a `CloudProvider` protocol so adding new adapters is non-disruptive. Each new provider needs:
- Its own auth shape (Dropbox is OAuth refresh token, not service account)
- A `list_drives` analogue (Dropbox: list shared folders; OneDrive: list drives)
- Provider-specific rclone backend or API client

### OAuth flows
Required for Dropbox and non-Workspace Google accounts. Auth module needs a refresh-token code path. Currently service-account-only.

---

## Agent / fileserver integration

### Per-agent inbox/outbox syncs
Bulk org syncs (current scope) handle `arc/dropbox` → `/mnt/raid/arc/dropbox`. Agent-specific cloud→local→cloud flows (`Agents/agent_X/inbox`, `Agents/agent_X/outbox`) follow a similar pattern at finer granularity. Likely a separate tool or a subcommand — design before implementing.

### Bidirectional sync
Never wanted for bulk data. May eventually be wanted for agent outboxes. Different semantics from one-way sync; separate code path. Don't conflate.

---

## Schema / platform

### `meta.schema_version` on compiled plan
Already present in v0.2/v0.3 plan output. Lets future GUI / consumers negotiate format. If you ever ship a v0.4 plan shape, bump this and let consumers branch on it.

### Future schema migrations
Whenever schema bumps, follow the v0.2 → v0.3 pattern: detect old layout, fail-fast with operator-friendly migration instructions in the error message.

### Plan diff / drift detection
A future mode could compare the compiled plan against actual live system state (rclone.conf managed section, enabled systemd timers, present env files). Separate tool, but could share the compiler's model code.

---

## GUI / web UI

### Importable Python API
`sync_compiler.operations.compile_for_org` / `discover` / `validate` already return structured result objects rather than printing. A future web UI calls these directly.

### Structured error fields
Errors carry `file`, `line`, `field`, `message` (see `errors.RegistryError`). A GUI can render them as inline annotations rather than reformatting from string.

### Cross-tool unified registry view
Eventually the GUI presents `rbac-compile` + `sync-compile` as one config surface. Both tools share `~/registry/` already; the UI is the next layer. Until then, two parallel CLIs.

---

## Maintenance / operational

### Pre-commit hook example
`sync-compile validate --org <org>` is offline and fast. Worth documenting as a pre-commit hook example in the README.

### CI for the registry repo
Lint check (`ruff`), `sync-compile validate` for every org file on push. Catches schema regressions before they reach beaver.

### Status JSON schema
If `sync-compile status` is implemented, the JSON schema for `/var/lib/rclone-sync/status/<org>-<local_name>.json` (currently written by the wrapper script) should be formalised — there's an example in the v0.1 brief.

---

## Cleanups

### `cloud.py` vs `registry.py` module split
Provider adapter stays in `cloud.py`. Pure classify/diff stays in `registry.py`. Don't conflate. (Was noted as a v0.3 brief item to push back on.)

### Drop `--yes` deprecation path
Originally proposed as "deprecate for one release" in the v0.3 brief draft. Decision: keep `--yes` as a first-class flag (matches v0.2 ergonomics, supports both interactive and scripted invocations).
