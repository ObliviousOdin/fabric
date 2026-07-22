# Fabric Mobile shared contract fixtures

This directory is the cross-platform source of truth for the mobile wire
contract. A contract change lands here first; each client that implements that
contract must consume these exact bytes in its parity tests. Coverage is staged
with the delivery loops: the capability-manifest fixtures are exercised by the
TypeScript, Swift, and Kotlin clients today, while the Loop 0 trust, node, and
typed-error corpora currently have canonical TypeScript parsers. Later native
consumer loops must port those parsers against the same fixtures rather than
forking the wire contract.

## Governance rule (how the capability manifest grows)

`gateway.capabilities` grows by exactly one mechanism, the `durable_work`
precedent (see `apps/mobile/ARCHITECTURE.md` §0):

- Each family is one **feature key** whose boolean must equal whether its
  **required method set** is a subset of the advertised `methods[]`.
- New families are **additive-optional**: an omitted key means *unavailable*
  (`false`), never legacy. A present key that contradicts its methods
  invalidates the **entire** contract.
- **Flag-only** families (no dedicated methods, e.g. `scoped_grants`) are a
  boolean advertisement with no subset check; a non-boolean value is invalid.
- No per-method probing. `-32601` on `gateway.capabilities` itself is the only
  legacy path.

[`gateway-feature-registry-v1.json`](gateway-feature-registry-v1.json) is the
canonical feature ⇔ method-set registry. Each platform asserts deep equality
between its compiled-in registry and this file, so the fail-closed subset check
can never fragment across ports. Change the registry only together with all
platform registries and their parity tests.

## Fixture corpus

| Fixture | Proves |
| --- | --- |
| `gateway-capabilities-v1.json` | The canonical version-1 manifest parses verified — and, since new families are additive, every later family stays `false` against it. |
| `gateway-capabilities-families-v1.json` | A manifest advertising the node-program families (`device_node`, `node_invoke`, `trust_center`, `connected_nodes`, `push`, `session_admin`, `artifact_fetch`, `workspace_read`, flag-only `scoped_grants`) parses verified with each family enabled — while the omitted `durable_work` stays `false` (the dark invariant survives alongside new families). |
| `gateway-capabilities-family-contradiction.json` | A family flag that contradicts its advertised methods invalidates the whole contract. |
| `gateway-capabilities-incompatible.json` | A `min_compatible` above the client version is an honest incompatible state. |
| `gateway-capabilities-malformed.json` | Malformed payloads are invalid, never legacy. |
| `legacy-mobile-methods.json` | The exact frozen method set enabled by the `-32601` legacy path. |
| `gateway-error-taxonomy-v1.json` | The shared typed-error classification (`unsupported` / `denied` / `transient` / `needs_reauth` / `reset_required` / `contract_invalid` / `unknown`) every platform maps RPC codes and transport failures through. |
| `fabric-pairing-v2.json` | The pairing v2 payload including the `enrollment` handle clients must fail closed on until `device_node` ships. |
| `fabric-work-v1/` | The complete durable-Work v1 corpus (bootstrap, delta, tombstone, terminal, sensitive, malformed, incompatible, additive-future, replaced-ledger, cursor-expired). |
| `fabric-trust-v1/` | The Trust Center corpus: audit pages (monotonic `entry_id`, `redacted: true` enforced, unknown kinds preserved as non-actionable), grants (unknown scopes non-actionable, `revocable: false` honored), revoke receipts (echo + version-increase), scoped-grant receipts, cursor-expired reset, malformed. |
| `fabric-node-v1/` | The `node.invoke` corpus: announce results (`accepted ⊆ announced`, `routable ⊆ accepted`), invocation envelopes (strict, expiring), receipt echo enforcement, malformed. |
| `fabric-voice-v1/` | `fabric.transcription` v1 plus the client-owned `fabric.phone_audio` v1 envelope: completed/failed/no-speech, additive metadata, incompatible version, malformed invariants, and phone capture modes. Phone audio is never represented as a gateway-host microphone capability. |

## Rules for adding fixtures

1. Wire shapes are defined in `apps/mobile/ARCHITECTURE.md` first; fixtures
   implement them, not the other way around.
2. Never modify an existing fixture to make a new feature fit — add a new file.
   Existing fixtures are compatibility proof for shipped clients.
3. Every fixture must be valid JSON, 2-space indented, lossless in Swift and
   Kotlin (no float where an integer is intended), with a trailing newline.
4. A fixture that represents a live-style manifest must never advertise
   `durable_work` (or any family) beyond what the real gateway provides —
   fixtures used as parser-proof of a *future* family are exactly that, and the
   family stays unadvertised by real servers until its full contract is
   verified end-to-end.
5. New Swift-consumed fixtures must also be wired as `FabricTests` resources in
   `apps/mobile/ios/project.yml` (and the project regenerated on macOS) — see
   `apps/mobile/UPGRADE_PLAN.md` §2 for the build constraint.
