---
name: fan-out
description: "Fan independent work out to parallel subagents — decompose a big job into self-contained shards, batch them through delegate_task, then merge results deterministically. Use for many-file audits, migrations, bulk research, or any workload that is N independent copies of the same task shape."
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [fan-out, parallel, batch, sharding, map-reduce]
    related_skills: [orchestration, pipeline, ensemble]
---

# Fan-Out

Use this skill when one job is really N independent copies of the same task
shape: audit 40 modules for a bug class, migrate 12 services off a deprecated
client, research 8 competitors against the same question set, lint every doc
page for stale links. Fan-out is map-reduce on `delegate_task` — shard the
work into self-contained units, dispatch shards as parallel subagents, and
merge their structured returns deterministically in the parent.

Do NOT use this skill for staged work where each stage consumes the previous
stage's output — that is `pipeline`; load it with skill_view. Executing an
existing implementation plan task-by-task is `subagent-driven-development`,
which owns the implement-review loop. To decompose a fuzzy goal into tasks
at all, load `plan`. For one risky unknown, load `spike`. Several MODELS
contributing to one response is Mixture of Agents (`moa` provider presets) —
model-level ensembling, not agent-level fan-out. Durable multi-day pipelines
belong on the kanban board with worker lanes, not in delegate_task chains.

## The independence test

Shard ONLY truly independent work. The test: could the shards run in any
order — or all at once — and produce the same merged result? If shard B needs
shard A's output, or two shards would edit the same file, the job is a
pipeline, not a fan-out. Run the coupled stages sequentially in the parent
and fan out only the independent middle.

| Workload | Shard unit | Independent? |
|---|---|---|
| Audit 40 modules for a known bug class | 1-4 modules per shard, disjoint file lists | Yes |
| Bulk research: 8 competitors, same questions | 1 competitor per shard | Yes |
| Migrate 12 services to a new client library | 1 service per shard | Only if no two services share touched files |
| Rename one symbol used across the codebase | none | No — one mechanical parent-side pass is cheaper and safer |
| Implement a feature, then test it | none | No — step 2 consumes step 1's output; that is a pipeline |

## Workflow

1. **Verify independence.** Apply the test above. Enumerate the complete
   unit list (files, services, topics) with a cheap parent-side scan —
   `ls`, `grep -l`, a directory listing. Never let shards discover their
   own scope.
2. **Cut shards with disjoint, explicit boundaries.** Every unit appears in
   exactly one shard. Name shards by contents ("shard 3: src/billing/,
   src/invoices/"), never by vibes ("the payment-ish stuff").
3. **Write the shard template once.** One goal + context skeleton with
   slots for per-shard scope. It must include absolute paths, exactly what
   to do, what to leave alone, and a mandatory structured return format.
   Subagents start with a completely fresh conversation — they know nothing
   you have not packed into goal + context, and they cannot ask the user or
   you anything (no clarify tool).
4. **Chunk to the concurrency limit, then dispatch.** The default limit is
   3 concurrent children (`delegation.max_concurrent_children`). A batch
   larger than the limit is a tool ERROR, not a truncation — so chunk the
   shard list into batches of at most the limit and dispatch one batch per
   `delegate_task` call. Batches from the top-level agent run in the
   background; results re-enter the conversation as new messages when the
   children finish. Children inherit the parent's toolsets and cannot be
   narrowed per shard — put scope and "do not modify files" constraints in
   each shard's context prose instead.
5. **Validate each return before merging.** A shard result is acceptable
   only if it matches the required format exactly. Free prose, an error, or
   a suspiciously thin answer (zero findings from the largest module) fails
   validation.
6. **Re-dispatch failures with tightened context.** Never accept holes, and
   never fill a hole from memory. Re-run the failed shard as a fresh single
   delegation, adding what the failure taught you: quote the format it
   violated, list the sub-paths it skipped, paste the error it hit.
7. **Merge deterministically.** Concatenate the validated returns, dedupe
   on the natural key (file+line, service name, competitor), sort, and
   write the merged artifact to disk. The parent owns the reduce; no child
   ever sees another child's output.
8. **Spot-check, then report.** Open 2-3 merged entries against the real
   files before presenting. You dispatched the work; you still own its
   correctness.

## Shard template

Instantiate per shard by filling the slots — never paraphrase it fresh each
time, or shard formats will drift and the merge stops being mechanical:

```
GOAL:
Audit {SCOPE} in {REPO_ROOT} for {DEFECT}. Return findings ONLY in the
mandated table format below — no prose before or after it.

CONTEXT:
Repo root: {REPO_ROOT} ({LANGUAGE_AND_STACK}).
Audit ONLY these paths: {EXPLICIT_FILE_LIST}. Do not open, edit, or report
on any other path.
Flag: {PRECISE_DEFECT_DESCRIPTION}. Example of the defect: {ONE_EXAMPLE}.
Ignore: {KNOWN_FALSE_POSITIVES}.
RETURN FORMAT (mandatory): a markdown table with columns
file | line | severity (high/medium/low) | issue | suggested fix
one row per finding, absolute file paths.
If nothing is found, return exactly: NO_FINDINGS {SHARD_ID}
```

## Worked example: audit 9 modules in 3 batches of 3

Nine modules, one shard each. The default limit is 3 concurrent children, so
dispatch three batches of three and merge as each batch's results arrive.

```python
# Batch 1 of 3 (batch 2: orders, payments, shipping; batch 3: search,
# users, webhooks — identical template, different scope slots).
delegate_task(tasks=[
  {
    "role": "leaf",
    "goal": "Audit src/auth/ in /home/user/shop for call sites that dereference db.fetch_one() results without a None check. Return findings ONLY in the mandated table format.",
    "context": "Repo root: /home/user/shop (Python 3.12, SQLAlchemy). Audit ONLY files under src/auth/. db.fetch_one() returns None on a miss; flag every call site that uses the result without a None guard. Example defect: user = db.fetch_one(q); return user.id. Ignore tests/ and sites already guarded by 'if row is None'. RETURN FORMAT (mandatory): markdown table, columns file | line | severity (high/medium/low) | issue | suggested fix, absolute paths, one row per finding. If nothing found return exactly: NO_FINDINGS auth"
  },
  {
    "role": "leaf",
    "goal": "Audit src/billing/ in /home/user/shop for call sites that dereference db.fetch_one() results without a None check. Return findings ONLY in the mandated table format.",
    "context": "Repo root: /home/user/shop (Python 3.12, SQLAlchemy). Audit ONLY files under src/billing/. db.fetch_one() returns None on a miss; flag every call site that uses the result without a None guard. Example defect: user = db.fetch_one(q); return user.id. Ignore tests/ and sites already guarded by 'if row is None'. RETURN FORMAT (mandatory): markdown table, columns file | line | severity (high/medium/low) | issue | suggested fix, absolute paths, one row per finding. If nothing found return exactly: NO_FINDINGS billing"
  },
  {
    "role": "leaf",
    "goal": "Audit src/catalog/ in /home/user/shop for call sites that dereference db.fetch_one() results without a None check. Return findings ONLY in the mandated table format.",
    "context": "Repo root: /home/user/shop (Python 3.12, SQLAlchemy). Audit ONLY files under src/catalog/. db.fetch_one() returns None on a miss; flag every call site that uses the result without a None guard. Example defect: user = db.fetch_one(q); return user.id. Ignore tests/ and sites already guarded by 'if row is None'. RETURN FORMAT (mandatory): markdown table, columns file | line | severity (high/medium/low) | issue | suggested fix, absolute paths, one row per finding. If nothing found return exactly: NO_FINDINGS catalog"
  }
])
```

Reduce, per batch, as results arrive: reject any return that is neither the
table nor a `NO_FINDINGS {SHARD_ID}` line; append accepted rows to
`.fabric/audits/none-deref.md`; dedupe on (file, line); sort by severity then
path. Re-dispatch rejected shards singly with the violation quoted in
context. After batch 3, spot-check three rows against the source and report
the merged table with per-shard coverage (9/9 shards returned).

## Cost and limits

Every shard is a full agent loop. N shards cost roughly N times one unit of
work plus dispatch overhead, and the parent pays again to merge. Below about
five small units, doing the work in a single context is usually cheaper AND
better — one context sees cross-unit patterns that isolated shards miss.
Fan out when the unit list is long, each unit is context-heavy, or pulling
everything into the parent would flood its context.

- Concurrency defaults to 3 (`delegation.max_concurrent_children`, floor 1,
  no hard ceiling). Raise it via the `fabric-agent` skill or
  `fabric config set delegation.max_concurrent_children 6`. Until then,
  chunk to 3 — oversized batches error out.
- Depth defaults to 1 (`delegation.max_spawn_depth`): fan-out is flat, and
  `role="orchestrator"` is a no-op until the depth is raised to 2+.
  `delegation.orchestrator_enabled: false` forces every child to leaf.
  Fan-out rarely needs depth — at depth 3 with 3 children each, a tree can
  reach 27 concurrent leaves. Raise it intentionally or not at all.
- Children never get delegate_task (as leaves), clarify, memory,
  send_message, execute_code, or cronjob. If a shard would need to ask a
  question, its context is under-packed — fix the template, not the child.
- Interrupting the parent interrupts all active children: a mid-batch
  interrupt discards that batch's in-progress work.
- Parents see only each child's final structured summary — never its
  reasoning or tool calls. The return format is your only window; make it
  carry everything you need.

## Common failure modes

- **Sharding coupled work.** Two shards edit the same file and clobber each
  other, or shard B silently needed shard A's output and guessed. Apply the
  any-order test before cutting anything.
- **Vague shard boundaries.** "Audit the auth-ish parts" yields overlap
  (duplicate findings that look like corroboration) and gaps (files nobody
  owned). Enumerate units parent-side; every unit in exactly one shard.
- **Letting shards self-scope.** "Look at whatever seems relevant" produces
  nine different definitions of relevant. Scope is the parent's job.
- **Under-packed context.** The child cannot see your conversation and
  cannot ask. Missing paths, missing defect examples, missing constraints
  become silent guesses that surface as garbage returns.
- **Free-prose returns.** Without a mandated format, merging becomes
  interpretation and dedupe becomes impossible. Put the return format in
  every goal and reject non-conforming results.
- **Accepting thin shards.** `NO_FINDINGS` from the gnarliest module is a
  re-dispatch trigger with sharpened instructions, not a relief.
- **Judging your own work.** The parent wrote the template, so it will
  grade its own shards leniently. Validate against the format and
  spot-check real files, not against your expectations.
- **Assuming oversized batches truncate.** They error. Chunk the shard list
  to the concurrency limit and iterate batches.
- **Hidden shared state.** "Each shard also appends to CHANGELOG.md" makes
  every shard order-dependent. Shards return data; the parent writes all
  shared artifacts in the reduce.
- **Re-reading everything in the parent.** Re-auditing each shard's files
  yourself defeats the point of fanning out. Trust validated structured
  returns; sample, don't repeat.
