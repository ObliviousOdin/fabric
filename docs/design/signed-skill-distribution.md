# Signed skill distribution

Status: implemented verification and install boundary
Last updated: 2026-07-14

## Scope

Fabric's signed distribution layer authenticates an exact skill release before
the existing quarantined Hub transaction can install it. It is a deliberately
small TUF-style subset, not a claim of full TUF conformance and not a network
registry client.

The authenticated chain is:

```text
out-of-band root SHA-256 pin
  -> threshold-signed root
  -> threshold-signed timestamp
  -> threshold-signed snapshot
  -> threshold-signed targets + revocations
  -> exact skill tree + contract + eval-manifest digests
  -> authoritative local scan
  -> atomic Hub commit + authenticated installed proof
```

This adds no model tool, prompt content, environment variable, analytics call,
or third-party runtime dependency. Verification occurs outside the agent loop.

## Metadata contract

`agent.skill_distribution` accepts only bounded, canonical UTF-8 JSON. Object
keys are sorted and NFC-normalized; insignificant whitespace, duplicate keys,
floats, unbounded integers, unknown fields, excessive nesting, and oversized
collections are rejected. Signatures cover each canonical `signed` object,
while parent roles bind the complete canonical child envelope by version,
length, and SHA-256 digest.

The root assigns independent Ed25519 keys and thresholds to `root`,
`timestamp`, `snapshot`, `targets`, and `revocations`. Root rotation must be
consecutive and satisfy both the old and new root thresholds. A changed
timestamp or snapshot key invalidates all downstream rollback state; target or
revocation key changes invalidate their respective role state.

Every target identifies an exact SemVer release and binds:

- canonical distribution name and version;
- full descriptor-safe tree digest;
- canonical `skill.contract.yaml` digest;
- canonical eval-manifest digest;
- release channel and publisher.

Revocation metadata can revoke one name/version, one tree digest, or every
release below a minimum safe SemVer. Revocation is checked on every verification
path, including explicit offline grace.

## Durable trust state

`agent.skill_distribution_state.SkillDistributionStateStore` owns the
profile-local trust directory at `skills/.hub/trust`. Bootstrap requires an
out-of-band root SHA-256 pin. Root envelope bytes and all per-role
version/digest rollback state are persisted together in one canonical `0600`
file using a process lock, file lock, same-directory atomic replacement,
`fsync`, and redirect/type checks.

Successful release verification durably advances rollback and equivocation
state before returning a `VerifiedRelease`. A caller therefore cannot use a
release whose trust-state commit failed. `TrustedRoot` and `VerifiedRelease`
objects are verifier-issued and sealed against ordinary construction or
subclass lookalikes.

Installed-proof issuance reloads the profile store under its lock and requires
the release's complete role-version and canonical-digest tuple to equal the
persisted trust state exactly. An unadvanced, stale, cross-root, or cross-profile
store is rejected before a receipt key is created. Offline proof verification
authenticates and compares that same exact trust tuple; a valid HMAC from an
unrelated or older local state cannot lower rollback floors.

A separate random `0600` HMAC key authenticates installed-release proofs. The
proof binds the release identity, exact installed tree measurement, verification
time, and complete trusted role state. It is inert without a fresh measurement
of the installed tree and is never a substitute for signed revocation metadata.
Offline grace is explicit, positive, and capped at 30 days.

## Install boundary and rollout

`tools.skills_hub.install_from_quarantine` remains the single filesystem
transaction boundary. When supplied a verifier-issued release and the concrete
state store, it requires a valid contract and eval manifest, rejects stale
declared sources, reruns the authoritative scanner, binds the exact scanned
tree/contract/eval digests to the signed target, issues the installed proof,
and commits release/proof metadata with the Hub lock entry atomically. The HMAC
key is never written to that lock.

Distribution enforcement is staged in `config.yaml`:

```yaml
skills:
  distribution:
    mode: observe # observe | enforce_learned | enforce_all
```

- `observe` preserves existing unsigned installs while making verification
  available to callers;
- `enforce_learned` reserves a migration lane for locally learned skills;
- `enforce_all` refuses an unsigned Hub quarantine commit.

Malformed or missing configuration defaults to `observe`. There is no
environment-variable override.

## Reversibility

Trust-state writes are atomic, so a failed verification never partially
advances a role. Same-version different-byte metadata is equivocation and
fails closed; lower versions are rollback. Signed older targets can be
reinstalled only while they remain authorized and non-revoked.

Agent-created skill promotion has a separate exact-byte rollback surface:
`fabric skills rollback <transaction-id> [--now]` and
`/skills rollback <transaction-id> [--now]` restore the latest eligible retained
snapshot only when no newer promotion or manual byte/sidecar change touches the
same skill. Cache activation is deferred to the next system-prompt build unless
the user explicitly supplies `--now`.

## Intentional limitations

- Fabric does not yet ship a publisher, mirror protocol, or network transport
  for this metadata. Callers must fetch bytes and pin the first root out of
  band.
- There are no delegated targets or consistent-snapshot filenames.
- Existing public Hub sources remain unsigned in the default observation lane;
  `enforce_all` is useful only with a caller that supplies the signed chain.
- A dedicated signed-version history/rollback command is not implemented;
  reinstalling an older target still requires current signed authorization.
- Local users who can arbitrarily replace both application code and profile
  state remain outside the threat model. Filesystem hardening prevents
  accidental redirects and common same-profile races; it is not an OS sandbox.

These boundaries are explicit so the verifier is not mistaken for a registry
service or a complete endpoint-security system.
