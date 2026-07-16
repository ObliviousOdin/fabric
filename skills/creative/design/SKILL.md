---
name: design
description: Design product surfaces and persistent systems.
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [design, ui, ux, prototype, artifact, design-system, design-md]
    related_skills: [claude-design, design-md, popular-web-designs]
---

# Fabric Design

Use this as the front door for product design work in Fabric. It composes the
existing specialist skills instead of replacing them:

- `claude-design` owns the design process, product taste, artifact building,
  implementation, and visual verification.
- `design-md` owns persistent `DESIGN.md` contracts, tokens, validation, and
  exports.
- `popular-web-designs` supplies named visual references such as Linear,
  Stripe, Vercel, and Claude.

Load every specialist needed for the request with `skill_view`. Read each
selected `SKILL.md` in full before acting.

## Route the request

| Request | Skills to load |
|---|---|
| Prototype, landing page, dashboard, component lab, or product UI | `claude-design` |
| Create, audit, or evolve a reusable design system | `design-md` |
| Named reference such as Linear, Stripe, Vercel, or Claude | `popular-web-designs`, then the matching template, plus `claude-design` |
| Implement UI inside an existing repository | `claude-design`; also load `design-md` when a `DESIGN.md` contract exists or should be created |

If the request spans several rows, compose the skills. Do not paraphrase a
specialist from memory when its current instructions can be loaded.

## Workflow

Use this loop for every substantial design request:

1. **Discover** — read the brief, inspect the actual product context, and find
   existing tokens, components, screenshots, assets, and nearby flows.
2. **Lock direction** — name the surface archetype and agree on or infer one
   coherent visual direction before polishing details.
3. **Build** — produce the real artifact in the requested medium. In an
   existing repo, use its stack and component system rather than forcing a
   standalone HTML file.
4. **Critique** — inspect the result at its real viewport, exercise the main
   interactions, and repair hierarchy, spacing, type, contrast, overflow, and
   state coverage problems.
5. **Deliver** — verify the artifact, preserve useful iterations, and report
   its exact path with a concise implementation handoff.

This loop is inspired by local-first design tools, but all outputs remain
ordinary project files. Never hide the only copy of a design in chat state.

## Design-system contract

Treat `DESIGN.md` as the durable interface between visual intent and
implementation:

- Read a project-level `DESIGN.md` before making visual choices.
- When none exists, do not invent a large token universe. Extract the smallest
  honest contract from the product's real styles and the decisions this task
  introduces.
- Put exact reusable values in tokens and explain rationale in prose.
- Keep brand rules separate from workflow instructions and application code.
- Record component states, interaction rules, accessibility constraints, and
  explicit anti-patterns when they are part of the system.
- Validate the contract using the `design-md` workflow before handoff.

For one-off explorations, keep the contract proportional. A small artifact may
only need a compact design-contract section or colocated notes; a reusable
product system deserves a repository-level `DESIGN.md`.

## Guardrails

- Extend existing product patterns before creating new ones.
- Do not add a core model tool for work the terminal, files, browser, and skills
  already cover.
- Do not build a second chat surface in a host application. Hand the prepared
  design brief into its existing conversation flow.
- Do not claim visual verification from a successful build alone.
- Do not copy a reference product's identity, trademarks, or content. Use its
  design system only as vocabulary unless the user owns the source.
- Do not produce speculative tokens, empty component catalogs, or a design
  system with no concrete consumer.

## Interpreting Design workspace prompts

The desktop and dashboard Design workspaces append structured fields after the
user's brief:

- `Deliverable` selects the artifact or design-system outcome.
- `Fidelity` sets the expected level of finish.
- `Design system` selects project context, a new direction, Fabric, or a named
  reference.

Treat those fields as constraints. The user's prose wins if it conflicts with
generated metadata.
