# Deterministic Skill Evaluation Runner

Fabric's first-class skill evaluation runner is a pure scoring boundary. It
does not call a provider, execute a tool, load a hook, read configuration, or
change a prompt. A separate harness records observations; the runner validates
and scores them against a validated `evals/cases.yaml` manifest.

## Observation contract

Observations are keyed by manifest case ID. Every case must be present exactly
once and contain exactly its declared number of ordered trials. Each trial is a
closed mapping with these five required fields:

| Field | Contract |
| --- | --- |
| `selected` | Boolean indicating whether the governed skill was selected. |
| `output` | UTF-8 string, at most 128 KiB. |
| `tools` | Ordered tool-name list, at most 256 entries; arguments are forbidden. |
| `approvals` | Ordered approval-name list, at most 256 entries; payloads are forbidden. |
| `outcome_score` | Finite numeric score in `[0, 1]`. |

Unknown fields, missing or extra cases, missing or extra trials, non-finite
scores, and over-limit data fail the whole run before a report is returned.
Suite-wide work is additionally capped at 16 MiB of output and 100,000 tool
plus approval events, even when every individual observation is under its cap.
Outputs and event names are evaluated in memory but are not retained in the
report.

## Assertion and threshold semantics

Substring matching is literal and case-sensitive. Required tool and approval
names need at least one occurrence; forbidden names need none. `max_calls`
counts every tool-name event, including repeats. A trial passes only if all its
selected, output, tool, and approval assertions pass.

Case pass rate is `passing trials / declared trials`. A case uses its own
`pass_threshold`, when present, or the suite threshold. The suite pass rate is
computed across every declared trial, including baseline trials. A suite passes
only when every case meets its threshold and the aggregate rate meets the suite
threshold. Population variance is reported for binary trial passes and outcome
scores.

## Paired no-skill lift

A baseline case may declare `baseline_for: <case-id>`. The validator requires
the target to be a unique non-baseline case with an exactly equal JSON input and
the same effective trial count. The field is additive in schema v1: an older
unpaired manifest still validates with a warning, but the runner refuses to
score its lift until pairing is explicit.

Baseline observations must report `selected: false`. Trial `n` is compared only
with trial `n` of its declared target. The runner computes each delta as:

```text
paired lift = governed outcome_score - no-skill outcome_score
```

The suite's observed lift is the mean of those already-paired deltas, so scores
from unrelated inputs never inflate the comparison. The suite passes the lift
gate when observed lift is at least `suite.min_lift`. The observation producer
is responsible for actually running baseline trials with the skill disabled;
the runner intentionally has no execution authority with which to do that.
