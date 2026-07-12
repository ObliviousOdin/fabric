---
name: design-brief
description: Convert a product problem into a testable design contract before exploring solutions. Use for new features, redesigns, unclear UX requests, or work that lacks agreed users, states, constraints, and success evidence.
---

# Fabric Design Brief

Create an evidence-aware contract for design work. Do not propose visual
directions or edit implementation files in this phase.

## Establish the source of truth

Inspect the supplied product context, repository, issue, research, analytics,
and existing interface before asking for facts that are already available.
Label each material statement as one of:

- verified fact, with its source;
- user or business decision;
- working assumption that still needs validation;
- open question that blocks or changes the design.

Do not invent users, metrics, technical limits, brand rules, or research
findings. When a missing answer does not materially alter the contract, record
a bounded assumption and continue. Ask when the answer would change scope,
permissions, the primary journey, or the success definition.

## Build the contract

1. State the user, job, context, current behavior, and observed pain.
2. Describe the smallest end-to-end journey that must improve.
3. Enumerate the required states: empty, loading, partial, success, error,
   permission, offline or disconnected, and destructive confirmation where
   applicable.
4. Capture content and data realities, including long text, missing data,
   latency, stale data, and role differences.
5. Record accessibility, keyboard, responsive, localization, privacy,
   security, technical, brand, and delivery constraints that are evidenced or
   explicitly decided.
6. Separate non-goals from deferred work so later phases do not expand scope
   silently.
7. Define observable acceptance checks and the evidence needed to show each
   check passed.
8. Name the decision owner and unresolved decisions.

## Return `DesignBrief`

Use this structure:

- `problem_statement`
- `primary_user_and_job`
- `evidence_and_assumptions`
- `current_journey`
- `target_journey`
- `required_states`
- `content_and_data_requirements`
- `accessibility_and_responsive_contract`
- `technical_brand_privacy_constraints`
- `success_signals`
- `acceptance_checks`
- `non_goals`
- `open_decisions`
- `decision_owner`
- `approval_status`: `approved`, `approval_required`, or `blocked`

Every acceptance check must be specific enough for `design-review` to verify.
Save an artifact only when the user asked for one, and only at a
workspace-approved path. This phase completes when the contract is internally
consistent and either explicitly approved or clearly marked as awaiting
approval.
