# NeMo Relay Observability

Optional Fabric observability plugin that maps Fabric observer hooks to
NeMo Relay scopes, LLM spans, tool spans, marks, ATOF, and ATIF.

NeMo Relay is NVIDIA's runtime layer for agent execution boundaries. It does
not replace Fabric's planner, tools, memory, model provider routing, or
CLI UX. Instead, this plugin lets Fabric emit NeMo Relay lifecycle events for
the work Fabric already owns: sessions, turns, provider/API calls, tool calls,
approval prompts, and delegated subagents.

With this plugin enabled, Fabric can:

- Preserve Fabric execution as NeMo Relay scopes, LLM spans, tool spans, and
  mark events.
- Export raw lifecycle events as Agent Trajectory Observability Format (ATOF)
  JSONL for debugging and offline inspection.
- Export Agent Trajectory Interchange Format (ATIF) trajectories for replay,
  evaluation, and harness analysis workflows.
- Correlate parent sessions, delegated subagents, tool calls, and provider
  calls through shared session, turn, and trajectory metadata.

See the NeMo Relay overview for the broader runtime model:
https://docs.nvidia.com/nemo/relay/about-nemo-relay/overview

ATOF is NVIDIA's canonical JSONL event stream representation for NeMo Relay
lifecycle events. The format is documented in the NeMo Agent Toolkit:
https://github.com/NVIDIA/NeMo-Agent-Toolkit/blob/develop/packages/nvidia_nat_atif/atof-event-format.md

ATIF is the trajectory representation produced from those events. NVIDIA and
Harbor upstreamed ATIF v1.7 support for complex harness workflows, including
subagent trajectory embedding, trajectory IDs, multi-LLM-call step metadata, and
deterministic no-LLM orchestration steps:
https://github.com/harbor-framework/harbor/blob/main/rfcs/0001-trajectory-format.md

## Enablement

Enable the plugin before setting export options:

```bash
fabric plugins enable observability/nemo_relay
```

Exporter behavior is configured under `observability.nemo_relay` in
`config.yaml`; enabling the plugin and configuring it are separate steps.

For isolated test homes, enable the plugin in the same `FABRIC_HOME` that the
agent run will use:

```bash
env FABRIC_HOME=/tmp/fabric-nemo-relay-test \
  fabric plugins enable observability/nemo_relay
```

Runs started with `--ignore_user_config` skip the enabled-plugin state from
`FABRIC_HOME`, so local E2E tests should omit that flag unless the test harness
loads `observability/nemo_relay` explicitly another way.

`FABRIC_HOME` is the Fabric profile/config home used by both
`fabric plugins enable ...` and the later `fabric chat ...` run. If unset,
Fabric uses the user's default home, usually `~/.fabric`. For isolated smoke
tests, choose any writable temporary directory and use the same value for every
command in that test:

```bash
export FABRIC_HOME=/tmp/fabric-nemo-relay-test
fabric plugins enable observability/nemo_relay
fabric chat --query 'Reply exactly ok' --provider custom --model qwen3.6:35b
```

For source checkouts, make sure the `fabric` command you run is built from the
checkout that contains this plugin. A globally installed older CLI will not see
new bundled plugins from your working tree.

```bash
uv sync --extra nemo-relay
uv run fabric plugins enable observability/nemo_relay
uv run fabric chat --query 'Reply exactly ok' --provider custom --model qwen3.6:35b
```

To ship the updated CLI into another environment, build and install a fresh
wheel from this checkout, then install the official NeMo Relay runtime extra:

```bash
uv build --wheel
python -m pip install --force-reinstall dist/fabric_agent-*.whl
python -m pip install "nemo-relay==0.3"
fabric plugins enable observability/nemo_relay
```

The plugin fails open when `nemo-relay` is not installed. Install and test it against the official NeMo Relay 0.3 PyPI distribution:

```bash
pip install "nemo-relay==0.3"
```

## Export Configuration

Direct ATOF and ATIF exporters use the canonical Fabric configuration:

```yaml
observability:
  nemo_relay:
    atof:
      enabled: true
      output_directory: .nemo-relay/atof
      filename: events.jsonl
      mode: overwrite
    atif:
      enabled: true
      output_directory: .nemo-relay/atif
      filename_template: trajectory-{session_id}.json
      subagent_export_mode: embedded
      agent_name: Fabric
      agent_version: local
```

### NeMo Relay Component Config

To let NeMo Relay own exporter or adaptive-middleware setup, create a
`plugins.toml` file and reference it from the same Fabric config block:

```yaml
observability:
  nemo_relay:
    plugins_toml: .nemo-relay/plugins.toml
```

Minimal ATOF and ATIF config:

```toml
version = 1

[[components]]
kind = "observability"
enabled = true

[components.config]
version = 1

[components.config.atof]
enabled = true
output_directory = ".nemo-relay/atof"
filename = "events.jsonl"
mode = "overwrite"

[components.config.atif]
enabled = true
output_directory = ".nemo-relay/atif"
filename_template = "trajectory-{session_id}.json"
agent_name = "Fabric"
agent_version = "local"
```

When `plugins_toml` initializes successfully, NeMo Relay owns the exporters
declared there. Fabric does not create a second exporter for the same format.

To enable NeMo Relay managed execution intercepts for provider and tool calls,
include an adaptive component in the same `plugins.toml`:

```toml
[[components]]
kind = "adaptive"
enabled = true

[components.config.tool_parallelism]
mode = "observe_only"
```

When the adaptive component is enabled and the installed NeMo Relay runtime
exposes `llm.execute(...)` / `tools.execute(...)`, Fabric routes LLM and tool
execution through those middleware boundaries. The observer hooks still emit
session, turn, approval, and subagent marks; the plugin skips its manual
`llm.call` and `tools.call` spans for executions that are already managed by
NeMo Relay. `tool_parallelism.mode = "observe_only"` keeps tool scheduling
observational while still wrapping the real execution boundary.

For the full generic Fabric middleware contract, see
[`docs/middleware/README.md`](../../../docs/middleware/README.md).

## Canonical Local Examples

The observe-only examples in this section use the official `nemo-relay==0.3`
distribution and a local Ollama model served through the OpenAI-compatible API.

```bash
pip install "nemo-relay==0.3"

export FABRIC_HOME=/tmp/fabric-nemo-relay-docs/fabric-home
mkdir -p "$FABRIC_HOME"

cat > "$FABRIC_HOME/config.yaml" <<'YAML'
model:
  provider: custom
  default: qwen3.6:35b
  base_url: http://127.0.0.1:11434/v1
  api_key: ollama
plugins:
  enabled:
    - observability/nemo_relay
delegation:
  max_spawn_depth: 2
  max_concurrent_children: 2
  child_timeout_seconds: 180
  model: qwen3.6:35b
  provider: custom
  base_url: http://127.0.0.1:11434/v1
  api_key: ollama
YAML
```

### Delegated Subagent Tool Call

This run starts a parent Fabric session, delegates to a child subagent, has the
child call `terminal`, and writes both ATOF and ATIF.

```yaml
observability:
  nemo_relay:
    atof:
      enabled: true
      output_directory: /tmp/fabric-nemo-relay-docs/subagent/atof
      filename: nested-subagent-atof.jsonl
      mode: overwrite
    atif:
      enabled: true
      output_directory: /tmp/fabric-nemo-relay-docs/subagent/atif
      filename_template: nested-subagent-atif-{session_id}.json
      agent_name: Fabric E2E
      agent_version: docs-example
      subagent_export_mode: all
```

```bash
fabric chat \
  --query 'Use delegate_task exactly once. Ask the child subagent to use the terminal tool exactly once to run printf docs_nested_leaf_function. After the child returns, reply with exactly: parent received nested subagent result.' \
  --provider custom \
  --model qwen3.6:35b \
  --toolsets delegation,terminal \
  --max-turns 10 \
  --quiet \
  --accept-hooks
```

CLI output:

```text
session_id: docs-parent-session
parent received nested subagent result.
```

Sanitized ATOF excerpt:

```jsonl
{"kind":"scope","category":"tool","name":"delegate_task","scope_category":"start","metadata":{"session_id":"docs-parent-session","tool_call_id":"call_delegate"},"data":{"goal":"Run the command `printf docs_nested_leaf_function` using the terminal tool.","toolsets":["terminal"]}}
{"kind":"mark","name":"fabric.subagent.start","metadata":{"parent_session_id":"docs-parent-session","session_id":"docs-child-session","subagent_id":"sa-0-docs","child_role":"leaf"}}
{"kind":"scope","category":"tool","name":"terminal","scope_category":"end","metadata":{"session_id":"docs-child-session","tool_call_id":"call_terminal","status":"ok"},"data":"{\"output\":\"docs_nested_leaf_function\",\"exit_code\":0,\"error\":null}"}
{"kind":"scope","category":"tool","name":"delegate_task","scope_category":"end","metadata":{"session_id":"docs-parent-session","tool_call_id":"call_delegate","status":"ok"}}
```

Sanitized ATIF excerpt:

```json
{
  "schema_version": "ATIF-v1.7",
  "session_id": "docs-parent-session",
  "agent": {"name": "Fabric E2E", "version": "docs-example", "model_name": "qwen3.6:35b"},
  "steps": [
    {
      "source": "agent",
      "tool_calls": [{"function_name": "delegate_task"}],
      "observation": {
        "results": [
          {
            "subagent_trajectory_ref": [{"session_id": "docs-child-session"}],
            "content": "{\"results\":[{\"status\":\"completed\",\"tool_trace\":[{\"tool\":\"terminal\",\"status\":\"ok\"}]}]}"
          }
        ]
      }
    },
    {"source": "agent", "message": "parent received nested subagent result."}
  ],
  "subagent_trajectories": [
    {
      "session_id": "docs-child-session",
      "steps": [
        {
          "source": "agent",
          "tool_calls": [{"function_name": "terminal", "arguments": {"command": "printf docs_nested_leaf_function"}}],
          "observation": {"results": [{"content": "{\"output\":\"docs_nested_leaf_function\",\"exit_code\":0,\"error\":null}"}]}
        }
      ]
    }
  ]
}
```

### Parallel Tool Calls

This run asks the model to emit two `read_file` tool calls in the same assistant
message. Fabric dispatches the read-only tools as one batch, and NeMo Relay
records both tool invocations.

```bash
mkdir -p /tmp/fabric-nemo-relay-docs/workdir
printf 'docs_parallel_alpha_function\n' > /tmp/fabric-nemo-relay-docs/workdir/alpha.txt
printf 'docs_parallel_beta_function\n' > /tmp/fabric-nemo-relay-docs/workdir/beta.txt
cd /tmp/fabric-nemo-relay-docs/workdir

fabric chat \
  --query 'Use exactly two read_file tool calls in the same assistant message. Read alpha.txt and beta.txt. Do not call terminal. After both tool results are available, reply with exactly: parallel tools complete.' \
  --provider custom \
  --model qwen3.6:35b \
  --toolsets file \
  --max-turns 8 \
  --quiet \
  --accept-hooks
```

CLI output:

```text
session_id: docs-parallel-session
parallel tools complete.
```

Sanitized ATOF excerpt:

```jsonl
{"kind":"scope","category":"llm","name":"custom","scope_category":"end","data":{"assistant_message":{"tool_calls":[{"id":"call_alpha","name":"read_file","arguments":"{\"path\":\"alpha.txt\"}"},{"id":"call_beta","name":"read_file","arguments":"{\"path\":\"beta.txt\"}"}]},"finish_reason":"tool_calls"}}
{"kind":"scope","category":"tool","name":"read_file","scope_category":"start","timestamp":"2026-05-31T00:15:08.956732+00:00","metadata":{"session_id":"docs-parallel-session","tool_call_id":"call_alpha"},"data":{"path":"alpha.txt"}}
{"kind":"scope","category":"tool","name":"read_file","scope_category":"start","timestamp":"2026-05-31T00:15:08.956804+00:00","metadata":{"session_id":"docs-parallel-session","tool_call_id":"call_beta"},"data":{"path":"beta.txt"}}
{"kind":"scope","category":"tool","name":"read_file","scope_category":"end","metadata":{"session_id":"docs-parallel-session","tool_call_id":"call_beta","status":"ok"},"data":"{\"content\":\"     1|docs_parallel_beta_function\\n\"}"}
{"kind":"scope","category":"tool","name":"read_file","scope_category":"end","metadata":{"session_id":"docs-parallel-session","tool_call_id":"call_alpha","status":"ok"},"data":"{\"content\":\"     1|docs_parallel_alpha_function\\n\"}"}
```

Sanitized ATIF excerpt:

```json
{
  "schema_version": "ATIF-v1.7",
  "session_id": "docs-parallel-session",
  "agent": {"name": "Fabric E2E", "version": "docs-example", "model_name": "qwen3.6:35b"},
  "steps": [
    {
      "source": "agent",
      "tool_calls": [
        {"tool_call_id": "call_alpha", "function_name": "read_file", "arguments": {"path": "alpha.txt"}},
        {"tool_call_id": "call_beta", "function_name": "read_file", "arguments": {"path": "beta.txt"}}
      ],
      "observation": {
        "results": [
          {"source_call_id": "call_beta", "content": "{\"content\":\"     1|docs_parallel_beta_function\\n\"}"},
          {"source_call_id": "call_alpha", "content": "{\"content\":\"     1|docs_parallel_alpha_function\\n\"}"}
        ]
      }
    },
    {"source": "agent", "message": "parallel tools complete."}
  ]
}
```

## ATOF Mapping

The plugin keeps NeMo Relay's native event model:

- Fabric sessions map to `agent` scopes.
- Fabric API request hooks map to `llm` scope start/end events.
- Fabric tool hooks map to `tool` scope start/end events.
- Turn, approval, subagent, and diagnostic fallback events map to `mark`
  events.

For subagent correlation, mark metadata includes parent and child session IDs,
subagent IDs, role/status fields when present, and derived
`parent_trajectory_id` / `child_trajectory_id` values. This keeps the ATOF
stream lossless for later ATIF conversion that can compact subagents into
separate trajectories.

## Adaptive Middleware Example

The `observability/nemo_relay` plugin uses Fabric execution middleware to hand
LLM and tool calls to NeMo Relay managed execution when an adaptive component is
enabled.

Minimal `plugins.toml`:

```toml
version = 1

[[components]]
kind = "adaptive"
enabled = true

[components.config.tool_parallelism]
mode = "observe_only"
```

Enable it for Fabric:

```yaml
observability:
  nemo_relay:
    plugins_toml: /tmp/fabric-middleware-test/plugins.toml
```

When the adaptive component is enabled and the installed NeMo Relay runtime
exposes `llm.execute(...)` and `tools.execute(...)`, Fabric routes execution
through these boundaries:

```text
Fabric provider call
  -> llm_execution middleware
    -> nemo_relay.llm.execute(...)
      -> Fabric provider adapter next_call(...)

Fabric tool call
  -> tool_execution middleware
    -> nemo_relay.tools.execute(...)
      -> Fabric tool dispatcher next_call(...)
```

The plugin still emits observer marks for sessions, turns, approvals, and
subagents. When adaptive managed execution is active, it skips manual
`llm.call` and `tools.call` observer spans to avoid duplicate LLM/tool events
for the same execution.

### Local Adaptive E2E

This example enables both NeMo Relay observability export and adaptive execution
middleware for a local Fabric run. This path requires a NeMo Relay runtime that
supports `[components.config.tool_parallelism]`; the `nemo-relay==0.3`
install used by the earlier observability-only examples does not support this
adaptive config.

```bash
export FABRIC_HOME=/tmp/fabric-middleware-test/fabric-home
mkdir -p "$FABRIC_HOME" /tmp/fabric-middleware-test/nemo-relay

cat > "$FABRIC_HOME/config.yaml" <<'YAML'
model:
  provider: custom
  default: qwen3.6:35b
  base_url: http://127.0.0.1:11434/v1
  api_key: ollama
plugins:
  enabled:
    - observability/nemo_relay
observability:
  nemo_relay:
    plugins_toml: /tmp/fabric-middleware-test/nemo-relay/plugins.toml
YAML

cat > /tmp/fabric-middleware-test/nemo-relay/plugins.toml <<'TOML'
version = 1

[[components]]
kind = "observability"
enabled = true

[components.config]
version = 1

[components.config.atof]
enabled = true
output_directory = "/tmp/fabric-middleware-test/atof"
filename = "middleware-events.jsonl"
mode = "overwrite"

[components.config.atif]
enabled = true
output_directory = "/tmp/fabric-middleware-test/atif"
filename_template = "middleware-trajectory-{session_id}.json"
agent_name = "Fabric Middleware E2E"
agent_version = "local"

[[components]]
kind = "adaptive"
enabled = true

[components.config.tool_parallelism]
mode = "observe_only"
TOML

fabric chat \
  --query 'Use the terminal tool exactly once to run printf middleware_execution_ok. Then reply with exactly the command output.' \
  --provider custom \
  --model qwen3.6:35b \
  --toolsets terminal \
  --max-turns 4 \
  --quiet \
  --accept-hooks
```

Expected CLI output:

```text
session_id: middleware-demo-session
middleware_execution_ok
```

Expected ATOF shape:

```jsonl
{"kind":"scope","category":"llm","name":"custom","scope_category":"start","metadata":{"session_id":"middleware-demo-session"},"data":{"mode":"observe_only"}}
{"kind":"scope","category":"tool","name":"terminal","scope_category":"start","metadata":{"session_id":"middleware-demo-session","tool_call_id":"call_terminal"},"data":{"mode":"observe_only"}}
{"kind":"scope","category":"tool","name":"terminal","scope_category":"end","metadata":{"session_id":"middleware-demo-session","tool_call_id":"call_terminal","status":"ok"},"data":"{\"output\":\"middleware_execution_ok\",\"exit_code\":0,\"error\":null}"}
```

Expected ATIF shape:

```json
{
  "schema_version": "ATIF-v1.7",
  "session_id": "middleware-demo-session",
  "agent": {
    "name": "Fabric Middleware E2E",
    "version": "local",
    "model_name": "qwen3.6:35b"
  },
  "steps": [
    {
      "source": "agent",
      "tool_calls": [
        {
          "function_name": "terminal",
          "arguments": {"command": "printf middleware_execution_ok"}
        }
      ],
      "observation": {
        "results": [
          {
            "source_call_id": "call_terminal",
            "content": "{\"output\":\"middleware_execution_ok\",\"exit_code\":0,\"error\":null}"
          }
        ]
      }
    },
    {
      "source": "agent",
      "message": "middleware_execution_ok"
    }
  ]
}
```
