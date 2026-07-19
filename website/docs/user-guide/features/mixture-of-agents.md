---
sidebar_position: 7
title: "Mixture of Agents"
description: "Create named MoA presets that appear as selectable models under the Mixture of Agents provider"
---

# Mixture of Agents

Mixture of Agents is a virtual model provider. Each named MoA preset appears as a selectable model under the `moa` provider.

When you select a MoA preset, the preset's aggregator is the acting model. It is the model that writes the assistant response and emits tool calls. Reference models run first and provide analysis for the aggregator to use.

Use MoA when a hard task benefits from multiple model perspectives but still needs Fabric's normal agent loop: tool calls, follow-up iterations, interrupts, transcript persistence, and the same session context as any other message.

## Select a MoA preset as your model

You can select a preset through the normal model picker surfaces:

```bash
/model default --provider moa
/model review --provider moa
```

MoA presets are selectable on **every Fabric surface**, because MoA is a normal provider in the model system:

- **CLI / gateway / TUI `/model`** — `/model <preset> --provider moa`, or `/model --provider moa` for the default preset. A bare `/model <preset>` also works when the name exactly matches a configured preset.
- **`fabric model`** and the **Dashboard model picker** — a `Mixture of Agents` provider row appears with your preset names as its models.
- **Desktop GUI app** — the model dropdown shows an `MoA presets` section; selecting one (`MoA: <preset>`) switches the active model to that preset. The Desktop settings panel also creates and edits presets.

Configured presets therefore show up wherever you would pick any other model.

## Slash command shortcut

`/moa` is one-shot convenience sugar. It runs a single prompt through the **default** MoA preset, then restores whatever model you were on:

```bash
/moa design and implement a migration plan for this flaky test cluster
```

Fabric temporarily switches to the default MoA preset for that one turn, sends the prompt, then restores your previous model afterward. The whole argument is the prompt — `/moa` no longer interprets it as a preset name.

```bash
/moa
```

Bare `/moa` (no prompt) just prints usage.

To **switch** to a MoA preset for the rest of the session, select it from the model picker — MoA presets appear under a `Mixture of Agents` provider in every model-selection surface (see above). `/moa` is deliberately not a model switch, so a normal prompt can never accidentally change your model.

## How it works in the agent loop

For each main model call when provider `moa` is selected, Fabric:

1. resolves the selected preset by name;
2. runs the configured reference models without tool schemas (they receive a trimmed advisory view: the Fabric system prompt is removed, and any prior tool calls/results are folded into bounded user/assistant text so references can reason about evidence without acting);
3. appends the reference outputs as private context for the aggregator;
4. calls the configured aggregator with the normal Fabric tool schema;
5. treats the aggregator response as the real model response;
6. if the aggregator calls tools, Fabric executes those tools normally;
7. on the next model iteration, references either run again (`fanout: per_iteration`, the default) or their first-turn advice is reused (`fanout: user_turn`).

Because MoA is selected through the normal model system, it composes automatically with `/goal`, gateway sessions, TUI sessions, and Desktop chat.

## Configure presets

You can configure named MoA presets from:

- Dashboard → Models → Model Settings → Mixture of Agents
- Desktop app → Settings → Model → Mixture of Agents
- `fabric moa configure [name]`
- `fabric moa bootstrap subscriptions` for validated OpenAI Codex + xAI OAuth presets
- `config.yaml`

The config stores explicit provider/model pairs, so you can mix providers and use multiple models from the same provider:

```yaml
moa:
  default_preset: default
  presets:
    default:
      reference_models:
        - provider: openai-codex
          model: gpt-5.5
          # Optional specialization. Role/instructions are private advisor
          # framing; references remain non-acting and receive no tools.
          role: implementation feasibility reviewer
          instructions: Check repository fit, compatibility, and testability.
          # Optional per-slot override. Invalid/unset values are omitted and
          # the provider default applies.
          reasoning_effort: low
        - provider: openrouter
          model: deepseek/deepseek-v4-pro
      aggregator:
        provider: openrouter
        model: anthropic/claude-opus-4.8
        role: decision owner
        instructions: Resolve disagreement against user constraints and evidence.
        reasoning_effort: high
      # Optional: pin sampling temperatures. When omitted (the default),
      # temperature is NOT sent and each model uses its provider default —
      # the same behavior as a single-model Fabric agent.
      # reference_temperature: 0.6
      # aggregator_temperature: 0.4
      max_tokens: 4096
      # user_turn runs references once for the user's turn, then lets the
      # aggregator act alone through the tool loop.
      fanout: user_turn
      enabled: true
```

Default preset:

- reference: `openai-codex:gpt-5.5`
- reference: `openrouter:deepseek/deepseek-v4-pro`
- aggregator / acting model: `openrouter:anthropic/claude-opus-4.8`

### Role-specialized slots

Every reference and aggregator slot accepts three optional additive fields:

- `role` — a short label shown in MoA output and attached to the private prompt;
- `instructions` — bounded role-specific focus (up to 2,000 characters);
- `reasoning_effort` — `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, or `max`.

Reference role instructions are wrapped inside Fabric's hard advisor envelope.
They can specialize the analysis, but cannot make a reference an acting agent,
give it tools, or override aggregator ownership. Slot reasoning overrides the
acting request's reasoning setting only for that slot. If a provider/model does
not support the selected effort, that call can fail normally; reference failure
is isolated and surfaced to the aggregator.

### Tuning advisor speed with `reference_max_tokens`

Each turn, MoA runs the reference models (advisors) in parallel and then the
aggregator acts. Advisor generation is the dominant per-turn latency — turn
wall time correlates strongly with how many tokens the advisors emit, because
the turn waits for the slowest advisor to finish writing. By default advisors
are **uncapped** (`reference_max_tokens` unset), so they may write long,
essay-length advice.

Set `reference_max_tokens` on a preset to cap advisor output when every
selected reference transport supports provider-side output caps. The aggregator
only needs the gist of each advisor's judgement, so a cap (e.g. `600`) can cut
per-turn wall time with little quality impact. It caps **advisors only** — the
acting aggregator's output (the user-visible answer) is never capped.

```yaml
moa:
  presets:
    fast:
      reference_models:
        - provider: openrouter
          model: anthropic/claude-opus-4.8
        - provider: openrouter
          model: openai/gpt-5.5
      aggregator:
        provider: openrouter
        model: anthropic/claude-opus-4.8
      reference_max_tokens: 600   # concise advice → faster turns
```

Leave it unset (or `0`/blank) to keep the prior uncapped behavior. The ChatGPT
Codex subscription Responses endpoint rejects `max_output_tokens`, so Fabric's
generated GPT/Grok subscription presets deliberately leave this field unset
rather than promise a cap that one reference lane cannot enforce.

### Choose the fan-out cadence

`fanout: per_iteration` (default) reruns references after the aggregator calls a
tool and receives new output. This is useful when advisors must monitor live
execution state, but it multiplies model calls across a long tool loop.

`fanout: user_turn` runs the reference panel once for the current user turn and
reuses that advice while the aggregator acts. Use it for stage-boundary MoA —
architecture planning, plan review, and final patch selection — where the
references receive a complete evidence packet up front. This avoids repeatedly
running the whole panel after every test, file read, or tool result.

## Subscription-backed planning and review

If both ChatGPT/Codex OAuth and xAI OAuth are authenticated, Fabric can install
two software-development presets using only models returned by those live
subscription catalogs:

```bash
fabric auth add openai-codex
fabric auth add xai-oauth

fabric moa bootstrap subscriptions --dry-run
fabric moa bootstrap subscriptions
fabric moa list
```
The command refreshes both authenticated subscription catalogs directly and
fails closed if either live entitlement check is unavailable. For OAuth-only
Grok Composer/Build models that are omitted from the collection response,
Fabric validates the exact model through xAI's authenticated metadata endpoint
without generating content. The bootstrap never falls back to static or
API-billed provider lists, and never replaces an existing `subscription-plan`
or `subscription-review` preset unless you rerun with `--force`. Use
`--keep-default` to install without changing the current default preset.

It prefers the strongest available subscription lanes for these roles:

| Lane | Provider | Preferred model family |
|---|---|---|
| Architecture / final decision owner | `openai-codex` | GPT-5.6 Sol, then Terra/available GPT fallback |
| Feasibility / correctness reference | `openai-codex` | GPT-5.6 Terra, then available GPT fallback |
| Adversarial planning / review reference | `xai-oauth` | Grok 4.5, then available reasoning fallback |
| Independent coding worker (reported for the workflow) | `xai-oauth` | Grok Composer 2.5 Fast, then Grok Build |

Both generated presets use `fanout: user_turn` and deliberately leave
`reference_max_tokens` unset because the ChatGPT Codex subscription endpoint
does not accept provider-side output caps. `subscription-plan` reconciles an
adversarial Grok review with GPT implementation feasibility.
`subscription-review` compares only deterministically viable patches and uses
GPT as the merge-decision owner.

For full independent implementation, load the bundled
`moa-software-development` skill. It writes a task brief, runs one-shot MoA at
planning/review boundaries, launches GPT and Grok acting workers in separate
git worktrees, runs deterministic gates, blinds candidate identity in the
judge packet, and leaves integration to one parent merge owner. The reference
models cannot read task files or diffs by path, so that workflow inlines the
relevant brief and evidence at each MoA boundary.

## Terminal preset management

```bash
fabric moa list
fabric moa configure              # update the default preset
fabric moa configure review       # create or update a named preset
fabric moa bootstrap subscriptions --dry-run
fabric moa bootstrap subscriptions
fabric moa delete review
```

## Prompt caching

MoA is built so the **main conversation's prompt cache is never broken**. Selecting a MoA preset is a normal model selection: it does not mutate past context, swap toolsets, or rebuild the system prompt mid-conversation. Your conversation history, system prompt, and tool schema stay byte-stable, so the cached prefix every other model relies on is preserved exactly as it would be for a plain model. Switching to or away from a MoA preset costs the same cache invalidation as any other `/model` switch — no more.

Both internal call types cache normally:

- **Reference models** receive a trimmed, deterministic view of the conversation (system prompt and tool transcript stripped — see the loop above). Because that view is a stable function of the stable history, a reference model's prompt prefix repeats across iterations and caches normally. References are short advisory calls with no tools.
- **The aggregator** is the acting model. The reference outputs are appended to the *end* of the latest user turn as private guidance. Because that text sits at the tail — below the entire stable prefix (system prompt + prior history) — it does not invalidate any cached prefix: the aggregator gets a cache hit on everything above the injection, and only the freshly appended tail is new. That is exactly how every normal turn behaves, where each new user message is also uncached tail tokens.

So MoA does not sacrifice prompt caching on either call type. Its only real cost is the extra reference calls per iteration — you pay for multiple model perspectives, not for broken caches. The long-lived conversation prefix shared with the rest of Fabric is fully intact.

## Notes

- MoA is no longer listed under `fabric tools`; there is no `moa` toolset to enable.
- Setting `enabled: false` on a preset disables the reference fan-out for that preset: the aggregator acts alone, exactly as if you selected it as a plain model. This is the per-preset off switch surfaced in the dashboard and desktop settings.
- A preset's aggregator cannot be another MoA preset. Recursive MoA trees are intentionally blocked.
- Credential failures on one reference model do not abort the turn. Fabric includes the failure in the reference context and continues with whatever models returned.
- MoA increases model-call count. A single model iteration can involve multiple reference calls plus the aggregator call.
