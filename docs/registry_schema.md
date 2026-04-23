# Registry schema

The authoritative schema is documented in the architecture brief at
`Sync Compiler Architecture 0.2.md` in the parent repository.

## Quick reference

Each org has two files under `~/registry/sync/`:

- **`<org>.yml`** — human-owned intent. Contains `meta`, `org`, `rclone_users[]`
  (for Ansible, ignored by sync-compile), `platform`, and `accounts[]` with
  auth config and sync defaults. **Never rewritten by sync-compile.**
- **`<org>.cloud.yml`** — tool-owned drive inventory. Contains `meta`, `org`,
  and `accounts[]` with just `remote_name` + `drives[]`. **Rewritten atomically
  by `sync-compile discover`**; humans edit it between discoveries to flip
  `enabled: true` and refine `local_name` / `overrides`.

Join key: `accounts[].remote_name` in `<org>.cloud.yml` must reference an
account in `<org>.yml`.

Schema version: both files carry `meta.version: "0.2"`.
