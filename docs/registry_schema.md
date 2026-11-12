# Registry schema — see the vault

This file used to restate the registry schema. It described schema 0.2 and had
drifted badly from the code, which is the hazard of a second home for one fact.

The authoritative documents are in the Atlas vault:

| For | Read |
|---|---|
| how sync-compile works, with diagrams | `components/sync-compile/docs/sync-compile-architecture-v0_5.md` |
| the plan it emits, field by field | `components/sync-compile/docs/provides/compiled-sync-plan-v0_6.md` |
| the `cloud_sync` and `shares` fields on an agent record | `components/sync-compile/docs/provides/agent-shares-schema-v0_5.md` |
| who owns which registry file | `components/rbac-compile/docs/provides/registry-handoff-v0_6.md` |

The models in `src/sync_compiler/models.py` are the executable statement of the
input schema; when this repo and the vault disagree, the vault contract is the
agreement and the models are what actually runs.
