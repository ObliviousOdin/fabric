# Built-in memory governance

Fabric keeps the existing narrow-waist `memory` model tool unchanged. Durable
text still lives in the profile-local `memories/MEMORY.md` and
`memories/USER.md` files. A local sidecar at
`memories/.governance/memory-governance.json` adds lifecycle metadata without
putting governance into the model tool schema or the conversation prompt.

The sidecar is a closed, bounded JSON schema. It stores opaque record/content
IDs, SHA-256 content digests, source origin/context/platform, confidence and
profile scope, validation/review/expiry timestamps, supersession/removal, and
explicit relevance counters. It has no fields for memory text, prompts,
responses, tool arguments, secrets, or raw session/task/tool-call IDs. Source
correlations are HMAC-pseudonymized with a random profile-local 0600 key.

Writes from both agent memory execution paths are recorded after the memory
file commits. Recording is deliberately best-effort: a corrupt, unsafe, or
unwritable sidecar never reverses or blocks the user's memory write. The next
audit reports that content as untracked. Sidecar updates use a process and file
lock, a same-directory temporary file, `fsync`, and atomic replacement. State,
keys, and lock files are restricted to 0600; symlinked governance paths are
rejected.

At session load, an expired governed record is replaced in the system-prompt
snapshot by a neutral unavailable placeholder. The original entry remains in
the live store and on disk for inspection and correction. Expiry decisions are
captured once per `MemoryStore`, so revalidation or a wall-clock boundary does
not mutate that session's frozen prompt classification. Legacy entries with no
governance record remain usable and are reported as untracked.

Operator commands:

```bash
fabric memory audit
fabric memory audit --json
fabric memory revalidate mem_<opaque-id>
fabric memory reset --target memory
```

The audit reconciles sidecar records against current files and reports exact
duplicate digest groups, conservative structured-key conflict candidates,
untracked entries, orphaned records, review-due records, and expired records.
It never echoes memory text. Retrieval precision remains `null` until an
explicit relevance label has been recorded; absence of feedback is not treated
as a negative label.

Current limitations are intentional: contradiction detection only flags
simple `key: value` or `key = value` mismatches and is not a semantic truth
engine; old untracked entries do not acquire historical provenance
retroactively; and the memory-file commit and sidecar commit cannot be one
filesystem transaction. The audit/revalidation workflow makes that final gap
visible and recoverable without risking memory loss. Exact SHA-256 content
digests are locally dictionary-testable if the 0600 sidecar is copied away from
the profile; they are retained because deterministic reconciliation and exact
duplicate accounting require a stable content identity. In the normal local
threat model, any principal able to read that sidecar can already read the
adjacent `MEMORY.md`/`USER.md`; deployments that separately export governance
metadata must treat it as private profile data rather than anonymous telemetry.
