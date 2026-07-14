---
name: fabric-agent-skill-authoring
description: Author governed Fabric skills and evaluation contracts.
version: 1.2.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [skills, authoring, fabric, conventions, skill-md]
    related_skills: [plan, requesting-code-review]
---

# Authoring Fabric Skills (in-repo)

## Overview

There are two places a SKILL.md can live:

1. **User-local:** `~/.fabric/skills/<maybe-category>/<name>/SKILL.md` — personal, not shared. Created via `skill_manage(action='create')`.
2. **In-repo (this skill is about this case):** `<fabric-checkout>/skills/<category>/<name>/SKILL.md` — committed and shipped with the package. Use `write_file` + `git add`. `skill_manage(action='create')` does NOT target this tree.

## When to Use

- User asks you to add a skill "in this branch / repo / commit"
- You're committing a reusable workflow that should ship with Fabric
- You're editing an existing skill under `<fabric-checkout>/skills/` (use `patch` for small edits, `write_file` for rewrites; `skill_manage` still works for patch on in-repo skills, but not for `create`)

## Required Frontmatter

Source of truth: `tools/skill_manager_tool.py::_validate_frontmatter`. Hard requirements:

- Starts with `---` as the first bytes (no leading blank line).
- Closes with `\n---\n` before the body.
- Parses as a YAML mapping.
- `name` field present.
- `description` field present, ≤ **1024 chars** (`MAX_DESCRIPTION_LENGTH`).
- Non-empty body after the closing `---`.

Peer-matched shape used by every skill under `skills/software-development/`:

```yaml
---
name: my-skill-name               # lowercase, hyphens, ≤64 chars (MAX_NAME_LENGTH)
description: Use when <trigger>. <one-line behavior>.
version: 1.2.0
author: Fabric
license: MIT
metadata:
  fabric:
    tags: [short, descriptive, tags]
    related_skills: [other-skill, another-skill]
---
```

`version` / `author` / `license` / `metadata` are NOT enforced by the legacy
frontmatter validator, but governed contract validation requires `name` and
`version` to agree with `skill.contract.yaml`. Every peer has these fields —
omit them and the skill sticks out.

## Size Limits

- Description: ≤ 1024 chars (enforced).
- Full SKILL.md: ≤ 100,000 chars (enforced as `MAX_SKILL_CONTENT_CHARS`, ~36k tokens).
- Peer skills in `software-development/` sit at **8-14k chars**. Aim for that range. If you're pushing past 20k, split into `references/*.md` and reference them from SKILL.md.

## Governance Contract and Evaluations

New first-party skills should add `skill.contract.yaml` and
`evals/cases.yaml`. Existing skills without them remain readable during the
migration, but are reported as `legacy_unverified`, never `verified`.

The contract declares identity, routing triggers and counter-triggers,
compatibility, inputs and outputs, permissions, sources, budgets, outcomes,
and the eval-suite path. It is a declaration, not an authority grant: listing
a tool, file scope, network host, or secret does not make it available at
runtime. Schema v1 is closed, so unknown policy-looking fields fail validation.

The eval manifest is data-only. It must cover all seven behavior classes:

1. `positive_trigger`
2. `negative_trigger`
3. `output_contract`
4. `safety`
5. `tool_use`
6. `regression`
7. `baseline`

Use the governed canary beside this file as the current peer shape. Keep eval
inputs representative but free of secrets; assertions may name required or
forbidden substrings, tools, approvals, and maximum tool calls. Every suite
must compare against a no-skill baseline. Each executable baseline declares a
unique `baseline_for`, repeats the paired case's exact input and effective
trial count, and expects `selected: false`. The manifest validator does not run
models or commands; a pure runner consumes closed observations, enforces case
and suite thresholds, records variance, and computes paired outcome lift.

Quarantined `/learn` and background-review drafts cannot promote on schema
validity alone. Their exact final tree is materialized privately, scanned
independently of `skills.guard_agent_created`, checked for fresh sources and
permission expansion, and bound to the full-batch review token. Supply closed
observations with:

```bash
fabric skills evaluate <pending-id> --observations observations.json
```

Then inspect `/skills diff <pending-id>` and explicitly approve that exact
reviewed batch. Appending any action invalidates both review and evaluation
attestations. `skill_manage` accepts root `skill.contract.yaml` and
`evals/**` for governed drafts; both path classes still reject traversal and
symlink redirects.

Every declared source needs an HTTPS URL, quoted ISO `retrieved_at`, and
nonnegative `ttl_days`. Expired sources leave an installed skill readable but
block governed promotion until refreshed.

## Writing Quality Principles

A skill exists to make the agent's process more predictable. Predictability does **not** mean identical output every run; it means the agent reliably follows the same useful discipline.

Use these quality checks when writing or editing any skill:

1. **Optimize for process predictability.** Ask: what behavior should change when this skill loads? If a line does not change behavior, cut it.
2. **Choose the right context load.** Small catalogs place descriptions in the cached prompt; larger catalogs route them on demand. Either way, keep descriptions focused on trigger classes and distinctive behavior. Put details in the body or linked references.
3. **Use an information hierarchy.** Put always-needed steps in `SKILL.md`; put branch-specific or bulky reference material in `references/`, `templates/`, or `scripts/` and point to it only when needed.
4. **End steps with completion criteria.** Each ordered step should say how the agent knows it is done. Good criteria are checkable and, when it matters, exhaustive: "every modified file accounted for" beats "summarize changes."
5. **Co-locate rules with the concept they govern.** Avoid scattering one idea across the file. Keep definition, caveats, examples, and verification near each other.
6. **Use strong leading words.** Prefer compact concepts the model already knows — e.g. "tight loop," "tracer bullet," "root cause," "regression test" — over long repeated explanations. A good leading word saves tokens and anchors behavior.
7. **Prune duplication and no-ops.** Keep each meaning in one source of truth. Sentence by sentence, ask whether the sentence changes agent behavior versus the default. If not, delete it rather than polishing it.
8. **Watch for premature completion.** If agents tend to rush a step, first sharpen that step's completion criterion. Split the sequence only when later steps distract from doing the current step well.

Common quality failures:

- **Premature completion** — the skill lets the agent move on before the work is genuinely done.
- **Duplication** — the same rule appears in multiple places and drifts.
- **Sediment** — stale lines remain because adding felt safer than deleting.
- **Sprawl** — too much always-visible material; push branch-specific reference behind pointers.
- **No-op prose** — generic advice the agent would already follow without the skill.

## Peer-Matched Structure

Every in-repo skill follows roughly:

```
# <Title>

## Overview
One or two paragraphs: what and why.

## When to Use
- Bulleted triggers
- "Don't use for:" counter-triggers

## <Topic sections specific to the skill>
- Quick-reference tables are common
- Code blocks with exact commands
- Fabric-specific recipes (tests via scripts/run_tests.sh, ui-tui paths, etc.)

## Common Pitfalls
Numbered list of mistakes and their fixes.

## Verification Checklist
- [ ] Checkbox list of post-action verifications

## One-Shot Recipes (optional)
Named scenarios → concrete command sequences.
```

Not every section is mandatory, but `Overview` + `When to Use` + actionable body + pitfalls are the minimum for the skill to feel like a peer.

## Directory Placement

```
skills/<category>/<skill-name>/SKILL.md
```

Categories currently in repo (confirm with `ls skills/`): `autonomous-ai-agents`, `creative`, `data-science`, `devops`, `dogfood`, `email`, `gaming`, `github`, `leisure`, `mcp`, `media`, `mlops/*`, `note-taking`, `productivity`, `red-teaming`, `research`, `smart-home`, `social-media`, `software-development`.

Pick the closest existing category. Don't invent new top-level categories casually.

## Workflow

1. **Survey peers** in the target category:
   ```
   ls skills/<category>/
   ```
   Read 2-3 peer SKILL.md files to match tone and structure.
2. **Check validator constraints** in `agent/skill_contract.py` and
   `agent/skill_evals.py` if unsure.
3. **Draft** `SKILL.md`, `skill.contract.yaml`, and `evals/cases.yaml` with
   `write_file` under `skills/<category>/<name>/`.
4. **Validate locally**:
   ```bash
   fabric skills validate ./skills/<category>/<name> --require-contract
   ```
5. **Run the repository governance audit**:
   ```bash
   python scripts/skills-governance-audit.py
   ```
6. **Git add + commit** on the active branch.
7. **Note:** the CURRENT session's skill loader is cached — `skill_view` /
   `skills_list` will not see the new skill until a new session. This is
   expected, not a bug.

## Cross-Referencing Other Skills

`metadata.fabric.related_skills` unions both trees (`skills/` in-repo and `~/.fabric/skills/`) at load time. Legacy `metadata.hermes` values still load as fallbacks, but new and edited skills should use the canonical `metadata.fabric` namespace. You CAN reference a user-local skill from an in-repo skill, but it won't resolve for other users who clone the repo fresh. Prefer referencing only in-repo skills from in-repo skills. If a frequently-referenced skill lives only in `~/.fabric/skills/`, consider promoting it to the repo.

## Editing Existing In-Repo Skills

- **Small fix (typo, added pitfall, tightened trigger):** `skill_manage(action='patch', name=..., old_string=..., new_string=...)` works fine on in-repo skills.
- **Major rewrite:** `write_file` the whole SKILL.md. `skill_manage(action='edit')` also works but requires supplying the full new content.
- **Adding supporting files:** `write_file` to `skills/<category>/<name>/references/<file>.md`, `templates/<file>`, or `scripts/<file>`. `skill_manage(action='write_file')` also works and enforces the references/templates/scripts/assets subdir allowlist.
- **Always commit** the edit — in-repo skills are source, not runtime state.

## Common Pitfalls

1. **Using `skill_manage(action='create')` for an in-repo skill.** It writes to `~/.fabric/skills/`, not the repo tree. Use `write_file` for in-repo creation.

2. **Leading whitespace before `---`.** The validator checks `content.startswith("---")`; any leading blank line or BOM fails validation.

3. **Description too generic.** Peer descriptions start with "Use when ..." and describe the *trigger class*, not the one task. "Use when debugging X" > "Debug X".

4. **Forgetting the author/license/metadata block.** Not validator-enforced, but every peer has it; omitting makes the skill look half-finished.

5. **Writing a skill that duplicates a peer.** Before creating, `ls skills/<category>/` and open 2-3 peers. Prefer extending an existing skill to creating a narrow sibling.

6. **Expecting the current session to see the new skill.** It won't. The skill loader is initialized at session start. Verify in a fresh session or via `skill_view` using the exact path.

7. **Letting skills accumulate sediment.** A skill should get shorter or sharper over time. When adding a rule, remove the old wording it replaces; don't layer advice forever.

8. **Writing no-op prose.** "Be careful," "be thorough," and "use best practices" rarely change model behavior. Replace with a checkable completion criterion or a stronger leading word.

9. **Linking to skills that don't exist in-repo.** `related_skills: [some-user-local-skill]` works for you but breaks for other clones. Prefer only in-repo links.

10. **Adding a contract without representative evals.** A schema-valid empty
    gesture is not governance. Include both routing directions, safety/tool
    assertions, regression behavior, and the no-skill baseline.

## Verification Checklist

- [ ] File is at `skills/<category>/<name>/SKILL.md` (not in `~/.fabric/skills/`)
- [ ] Frontmatter starts at byte 0 with `---`, closes with `\n---\n`
- [ ] `name`, `description`, `version`, `author`, `license`, `metadata.fabric.{tags, related_skills}` all present
- [ ] Name ≤ 64 chars, lowercase + hyphens
- [ ] Description ≤ 60 chars for routing quality (hard parser ceiling: 1024)
- [ ] Total file ≤ 100,000 chars (aim for 8-15k)
- [ ] `skill.contract.yaml` identity matches SKILL.md and declares closed permissions, sources, budgets, and outcomes
- [ ] `evals/cases.yaml` covers all seven categories and pairs a same-input, same-trial no-skill baseline with `baseline_for`
- [ ] `fabric skills validate ./skills/<category>/<name> --require-contract` passes
- [ ] `python scripts/skills-governance-audit.py` stays within the cached-index budget
- [ ] Structure: `# Title` → `## Overview` → `## When to Use` → body → `## Common Pitfalls` → `## Verification Checklist`
- [ ] Each ordered step has a checkable completion criterion
- [ ] Description is trigger-focused and avoids duplicated body content
- [ ] Bulky or branch-specific reference is progressively disclosed in linked files
- [ ] No-op prose and duplicated rules removed
- [ ] `related_skills` references resolve in-repo (or are explicitly OK to be user-local)
- [ ] `git add skills/<category>/<name>/ && git commit` completed on the intended branch
