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
