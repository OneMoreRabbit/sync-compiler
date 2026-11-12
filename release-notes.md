---
title: Release notes — sync-compiler
status: active
updated: 2026-11-11
owner: agent-eco.component.sync-compile
about: one short entry per release, newest first — what changed and what anyone must do about it
---

# Release notes — sync-compiler

Newest first. One entry per release tag, written in the same commit that cuts the
tag. Plain English: a reader skimming this page should know what changed and
whether they have to act. Detail lives in commits, contracts and troubleshooting
reports — link them, don't repeat them.

## v0.4.3 — 2026-11-12

**TL;DR:** emits compiled-sync-plan **0.6** — the delete bound is now a file COUNT in
its own env var, because rclone's `--max-delete` means a PERCENTAGE for bisync.

- **`MAX_DELETE` carries the count** (default 50 files) in every bisync instance's
  `env_vars`. estate-fileserver's wrapper dry-runs, counts planned deletes per side,
  and refuses the run when either side exceeds it. The name is fixed at the consumer's
  request so the wrapper reads a constant.
- **`BISYNC_FLAGS` now carries `--max-delete 90`**, a fixed percentage backstop against
  a near-total wipe. It is not the scope's count and is not per-scope: a *low*
  percentage is what failed, because on a small side any ordinary deletion is a large
  fraction of it.
- The contract states both units in a table and then says the wrong readings out loud,
  under "what a consumer must not do".

**Two corrections to the v0.4.2 entry above.** It is left as written — a tagged entry is
not rewritten — so the record is here:

1. **v0.4.2 passed the scope's count to rclone, which was wrong for bisync.**
   `rclone sync`'s `--max-delete` is a count (default `-1`); `rclone bisync`'s is a
   *percentage* (default 50). Both estate measurements were true of different commands.
   Measured live by estate-manage: `--max-delete 50` tripped on a near-empty AI Data
   drive at 2 of 3 files, 67%. If you installed 0.4.2, upgrade — its bound is a
   percentage wearing a count's clothes.
2. **"Unbounded" overstated the original defect.** Pre-0.5 bisync jobs emitted no
   `--max-delete` and so took rclone's bisync default, which is 50% — a loose bound,
   not no bound. The v0.4.2 entry calls it unlimited; that was the `sync` default
   quoted against a `bisync` job.
3. v0.4.2's "inert until arc declares `agent_mount_base`" is also overtaken: the ruled
   path is PR 20 setting `agent_arc_exec`'s surfaces `enabled: false`, after which arc
   compiles without that field. The bound applies to every *enabled* bisync, and arc
   has none until ADR-0010 stage 3; every new `drive_folders` scope carries it from
   day one.

**Action:** estate-fileserver reads `MAX_DELETE` as a file count and must not pass it to
rclone. Plan `schema_version` moves 0.5 → 0.6.

## v0.4.2 — 2026-11-11

**TL;DR:** emits compiled-sync-plan **0.5** — org Drive folder scopes, OAuth by token
reference, and a `--max-delete` bound on every two-way sync.

> **The version numbers look mismatched and are both correct.** The compiled plan's
> schema is 0.5; the compiler itself is 0.4.2. They are separate lines: the
> version-numbering rule (0.3, operator ruling 2026-10-09) says the middle number moves
> only on the operator's call, so a contract change is still the next last number.

- **Every bisync now carries `--max-delete`, default 50** (operator ruling 2026-11-11,
  matching estate-manage's vault drive-sync). This includes the **existing agent
  `scratch` and `memory` jobs**, which until now compiled with no delete bound at all —
  rclone 1.73.5 defaults to `-1`, unlimited. Set per scope to override; values below 1
  are refused, because a bound that does not bound is not a bound.
- **Folder scopes:** a `drive_folders:` list in `sync/<org>.yml` declares an org Drive
  folder synced two-way. It belongs to the org, not an agent, so it runs as the org's
  rclone user and takes ownership from platform defaults.
- **`auth.type: oauth`:** an account may authenticate by a token **file path** on the
  fileserver, for a personal org whose account cannot use a service account. The token
  value is never read, never compiled, and never appears in a plan — there is a test
  that asserts exactly that.
- A registry still declaring `meta.version: "0.4"` keeps compiling unchanged, and gains
  the delete bound without being edited.

**The delete bound does nothing until `arc` declares `agent_mount_base`.** Measured
against the live registry on release day: the whole registry holds exactly one enabled
bisync surface, `agent_arc_exec` `scratch`, and it is in `arc` — which does not compile,
because `sync/arc.yml` has no `platform.agent_mount_base` and ADR-0010 §7 requires one.
That is a pre-existing mismatch (dev HEAD fails identically, before this release), and
arch holds the decision. `top` compiles, but both its surfaces are `enabled: false` and
emit as skeletons with no flags. So this release makes the estate *ready* to be safe; it
does not by itself make any running job safe.

**Action:** estate-fileserver must handle plan `schema_version: 0.5` — rclone remote
config now reads `token_file` where an oauth account is used, folder scope instances take
ownership from `platform` defaults rather than an agent user, and every remote now carries
a `token_file` key, empty on service-account remotes (arch ruling: keep, consistent with
the emitter's existing null keys). See `compiled-sync-plan-v0_5.md` in the vault.
