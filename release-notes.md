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

## v0.4.8 — 2026-11-17

**TL;DR:** emits compiled-sync-plan **0.10** — a one-way sync now carries the same
`MAX_DELETE` file count a two-way one does, and one warning stops firing where it said
nothing true.

- **`MAX_DELETE` on every enabled instance of both kinds**, default 50 files, from
  `sync_defaults.max_delete`, overridable per drive, refused below 1. Operator ruling
  2026-11-17. Until now a one-way run deleted whatever the remote no longer had,
  unbounded — the estate counted one copy wanting to delete 356 files, 175 of which had
  moved or been renamed rather than been deleted.
- **It is never passed to rclone as `--max-delete`.** For a one-way sync that flag *is* a
  count, so the temptation is real — but rclone stops part-way through the run and leaves
  the destination half-changed. The estate's wrapper dry-runs and refuses the run before
  anything is deleted.
- **The unprovisioned-remote warning now fires only when some `rclone_users` entry
  declares a `remote_name`.** An org whose entries all omit it is the deliberately
  userless shape — a personal org reaching its Drive by `oauth` — and the warning was
  written when "no `remote_name`" also meant "no accounts".

**Action for consumers:** read and enforce `MAX_DELETE` on one-way instances. This is the
first change since 0.4.5 that needs anything done, rather than just being passed through.

**Measured** on the estate's registry copy: `MAX_DELETE` emitted on 6 instances for
`arc`, 1 for `job`, all at 50; `top` has none because both its instances are disabled.
The warning is gone for `job` and still fires for `arc`. **Not measured:** anything on
beaver.

## v0.4.7 — 2026-11-17

**TL;DR:** emits compiled-sync-plan **0.9** — closes two ways a value in the plan could
reach rclone as a stray **positional** argument.

Both have one shape: a value that word-splits at the consumer into loose words. On an
`rclone sync` command positional arguments are the source and destination, so neither is
a missed option — each changes what the command operates on.

- **Whitespace in an exclude pattern is now refused at compile time**, in all three
  layers that feed `EXCLUDE_PATTERNS`. `--exclude=/a/Weekly sync Recording` arrived as
  `--exclude=/a/Weekly` plus `sync` and `Recording`. Layer 2 (`drives[].overrides`)
  needed its own check — it is a free-form map, so the model's validator did not reach
  it, and it is the layer a per-drive exclusion is actually written in.
- **A repeated flag keeps its value.** The merge removed repeated tokens, so
  `--max-age 7d --max-age 30d` became `--max-age 7d 30d`, orphaning `30d`. Repeats
  within the registry's own flags are now kept (rclone takes the last value); only an
  item exactly equalling a compiler-added baseline flag is dropped. Exclude patterns keep
  the deduping merge, where a repeat is a no-op.

- **An override given as a string instead of a list is refused.**
  `overrides.exclude_patterns: "*.log"` was walked letter by letter and emitted
  `--exclude=*` — excluding everything, so the sync transferred nothing and reported
  success. `overrides.sync_flags` had the same hole. Found by arch reviewing this
  release.

**A path with spaces** is written with `?` for each space, with the literal path in a
registry comment. Two cautions: `?` matches any character, so it can over-match and the
failure is silent; and a pattern needing a literal `?` has no escape. `--exclude-from`
is proposed in the contract and **not built**.

**Nothing changes for any registry in use.** Compiling the estate's `arc` and `top` with
0.4.6 and with this release gives plans identical apart from `meta`, and no pattern in
use is refused. What changes is which registries are accepted.

## v0.4.6 — 2026-11-17

**TL;DR:** emits compiled-sync-plan **0.8** — `--no-update-dir-modtime` now on every
**one-way** sync too, not only the two-way ones.

- **A one-way sync had no baseline flags at all.** `SYNC_FLAGS` came *entirely* from the
  registry, so this could not be fixed once for every org — it would have had to be
  written into every account by hand and kept there. 0.8 adds a fixed baseline, merged
  with the registry's own flags and **deduped**, so an account already listing the flag
  is unaffected and no registry needs editing.
- Two ARC one-way Drive copies have **failed on every run since at least 2026-09-15**.
  **The folder date is one of three causes, not the cause** — this fixes the one that is
  sync-compile's and does not on its own fix those copies.

**Measured:** a real compile of `arc` emits
`SYNC_FLAGS: --no-update-dir-modtime --use-server-modtime --fast-list` on both one-way
instances. **Not measured:** anything on beaver — no one-way run has been made with the
flag, and rclone is not installed on this seat.

**Nothing for consumers to change.** One flag inside a string consumers already pass to
rclone verbatim. Plan `schema_version` moves 0.7 → 0.8.

## v0.4.5 — 2026-11-15

**TL;DR:** emits compiled-sync-plan **0.7** — every two-way sync now carries
`--no-update-dir-modtime`, so a folder the sync user does not own cannot stop the sync.

- **The outage this fixes.** Mico Data (org `job`) completed no pass between
  2026-11-13 13:15 UTC and 2026-11-15 — **212 refused passes**. As `rclone_job` it
  could not set the time on a folder the Mico Manager seat owns; rclone treats that as
  critical, and every later pass ended "path1 and path2 are out of sync, run
  `--resync`". Measured by estate-manage (hub #14069).
- **The delete bounds were not involved.** Worth saying because "a two-way sync stopped
  dead" reads like the `MAX_DELETE` count tripping, and it was not.
- The flag removes the operation that cannot succeed. **It grants no access** — the sync
  user's membership of the share group is the other half of the fix, and it lives in the
  RBAC registry's `seats:` list, not in anything this compiler emits.
- Also in this release: the **import guard** asked of all four compilers (constitution
  principle 2) — one test reading every module with `ast`, failing if `sync_compiler`
  imports `rbac_compiler`, `agent_compile` or `image_compile`, and failing if it finds
  no files to read.

**Nothing for consumers to change.** `BISYNC_FLAGS` gains one flag inside a string
consumers already pass to rclone verbatim; no key is added, removed or renamed. Plan
`schema_version` moves 0.6 → 0.7.

**Mico Data syncs again — with three fixes in place, not this one alone.** Measured on
beaver by estate-manage (hub #14099); sync-compile ran none of it, and rclone is not
installed on this seat.

- **Mico Data, first good pass with the flag:** the 20:00 UTC timed pass on 2026-11-15
  exited 0 at 20:00:42, 0 planned deletes on each side. The 19:45 pass met the resync's
  lock (exit 1, nothing synced).
- Both sync users joined their share's group at 19:31 UTC (ansible `5d92732`); below Mico
  Data the sync user then had 0 entries it could not read. Mico Data was resynced on the
  operator's word, 19:38–19:46 UTC, exit 0, 0 deletes.
- **AI Data** passed at 19:15, 19:30, 19:45 and 20:00 with the flag — a healthy sync is
  unaffected, so the flag causes no regression.

**What this does not show: the flag on its own.** The good pass came after the group fix
and the resync as well, so the evidence is that the three together work, not which one
did it. Anyone reading back for the cause of the recovery should know all three landed
inside half an hour.

**Nothing for consumers to change.** `BISYNC_FLAGS` gains one flag inside a string
consumers already pass to rclone verbatim; no key is added, removed or renamed. Plan
`schema_version` moves 0.6 → 0.7.

**The flag runs; it is not yet shown to fix the failure.** Two claims, and only the
first is measured.

- **Measured** (estate-manage, hub #14081): ansible `c350c61` put the flag in both
  two-way env files on beaver from 19:10 UTC 2026-11-15, and the AI Data pass at
  19:15 UTC exited 0 with 0 planned deletes. So rclone on beaver accepts the flag and a
  healthy two-way sync still passes with it — which rules out a regression.
- **Not measured**: that the flag lets the *failing* sync pass. Mico Data still refuses
  until a `--resync`, which waits on the sync user joining the share group and then on
  the operator.

What settles it: did a pass of Mico Data complete after the flag was added? sync-compile
has run none of this — rclone is not installed on this seat.

## v0.4.4 — 2026-11-12

**TL;DR:** refuses a per-agent `shares:` override of `memory`, `sessions` or `scratch`
(ADR-0010 §8), and clears three stale documents in this repo.

- **The override is now a hard validation error**, not a silently honoured path.
  rbac-compile has refused it since September; sync-compile still honoured it, so the
  two compilers could disagree about where an agent's hot surface lived. A registry
  carrying one now cannot compile at all, which is what the ADR asks for — failing at
  load also stops the migration being run out of order. `shares.configs` stays
  overridable, because `configs/` did not move.
- No plan contract change: `compiled-sync-plan` stays **0.6**. This narrows which
  registries are accepted; it does not change the shape of what is emitted.
- **Docs in this repo corrected**: the README pointed at `jobcpf/sync-compiler` and
  claimed schema 0.3 and 91 tests; `docs/registry_schema.md` restated schema 0.2 and had
  drifted; `TODO.md` said auth was service-account-only and that two-way sync was "never
  wanted for bulk data". All three were written before ADR-0010 and the 0.5/0.6 work.
  `docs/registry_schema.md` is now a pointer to the vault rather than a second home for
  the same fact, which is how it drifted.

**Action:** none for consumers. If a registry anywhere still carries
`shares.memory/sessions/scratch`, it must be removed before this version will compile it
— the error names the surface and the ADR.

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
