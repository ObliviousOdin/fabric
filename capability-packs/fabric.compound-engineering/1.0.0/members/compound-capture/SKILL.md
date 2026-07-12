---
name: compound-capture
description: Convert independently verified engineering evidence into a durable, retrievable project learning and prove how it should be reused. Use only after review passes and the user authorizes the chosen documentation, test, or project-memory destination.
---

# Fabric Compound Capture

Require an approved `ReviewReceipt`, the verified change evidence, and authority
for the destination. Reject guesses, failed work, and conclusions that were not
independently reviewed.

## Choose the durable form

Inspect the repository's existing tests, architecture/operations docs,
decision records, troubleshooting guides, project-memory conventions, and
agent instructions. Prefer the narrowest existing home that will be found at
the next relevant task. Do not invent a global memory store or update a
reusable skill without a separate explicit request.

Capture both when applicable:

- a regression or acceptance guard that detects recurrence; and
- a retrieval-oriented learning that states the trigger, reusable rule,
  evidence, limits, and links to the change/guard.

Redact credentials, personal data, transient tokens, raw customer content, and
irrelevant logs. Preserve provenance and distinguish the general lesson from
details that apply only to this repository/version.

## Verify retrieval

Validate the artifact with the repository's normal checks and formulate a
specific retrieval cue for a future task. Do not claim compounded value merely
because a file exists. Full reuse evidence requires a later fresh task to find
the artifact and measurably improve its plan or avoid the prior failure.

Return a `CaptureReceipt` with destination/type, content digest, evidence links,
retrieval cue, validation command/result, redactions, limits, and reuse status
`ready_for_future_proof` or `reuse_verified`. This receipt completes the
current workflow; only a separate later task may produce `reuse_verified`.
