# Shared compute broker — artifacts

Serve a **frontier open-source model** on a rented GPU and (eventually) share it
across many Fabric users, metered and billed. Full design + roadmap:
[`/deploy/compute-broker`](https://obliviousodin.github.io/fabric/deploy/compute-broker).

## What's here (works today)

| File | Purpose |
| --- | --- |
| `vast-vllm-onstart.sh` | Vast.ai *on-start* script: launch vLLM serving a frontier model, OpenAI-compatible on `:8000`, tool-calling on, `--max-model-len 65536` |
| `docker-compose.vllm.yml` | The same, self-hosted on any NVIDIA CUDA box |

Both give you **one GPU box, one OpenAI-compatible endpoint**. A Fabric agent
uses it immediately as a custom provider — no Fabric code change:

```yaml
# ~/.fabric/config.yaml on each agent
model:
  provider: custom
  base_url: http://<gpu-host>:8000/v1
  default: <the model id you served>
  api_key: ${VLLM_API_KEY}      # kept in ~/.fabric/.env
security:
  egress_mode: local_ai         # optional: pin the agent to the broker's address space
```

Verify the endpoint:

```bash
curl -s http://<gpu-host>:8000/v1/models -H "Authorization: Bearer $VLLM_API_KEY"
```

## From "one box" to "shared, metered broker"

Pointing every user straight at the vLLM box works but has no per-user auth,
metering, or routing. The **broker** is a thin service that sits in front and is
built almost entirely from primitives Fabric already ships:

```
Tenant Fabric agents ──Bearer tenant-key──▶ Broker ──▶ vLLM pool (this dir)
                                             │
                        ┌────────────────────┼────────────────────┐
                        ▼                     ▼                    ▼
                  identify tenant       meter tokens→$       pick a backend
                  (proxy discards       (usage_pricing.py)   (CredentialPool:
                   inbound bearer        already rates        rotation/cooldown/
                   today — add auth)     usage)               lease over boxes)
```

Reuse map (see the design page for detail):

- **Forwarder** = the [subscription proxy](https://obliviousodin.github.io/fabric/user-guide/features/subscription-proxy)
  `UpstreamAdapter` ABC (`fabric_cli/proxy/adapters/`). Add a vLLM adapter that
  returns `UpstreamCredential(base_url="http://gpu-host:8000/v1")`.
- **Backend pool** = `agent/credential_pool.py` (`select` / `acquire_lease` /
  `mark_exhausted_and_rotate`) over the vLLM boxes.
- **Rating** = `agent/usage_pricing.py` (`normalize_usage` + `estimate_usage_cost`)
  — set your own per-model rates + markup over the GPU-hour cost.

What the broker must **add**: authenticate the inbound bearer → `tenant_id`, a
per-request usage ledger (today usage is per-*session*), and a
credits/quota/billing layer. Build order is in the design page.

## Notes

- Fabric needs **≥ 64k** effective context for agentic/tool use — keep
  `--max-model-len 65536` (or higher).
- The `--tool-call-parser` must match the model family or Fabric's tool calls
  won't parse (`llama3_json` for Llama 3.x, `mistral` for Mistral, `deepseek_v3`
  for DeepSeek-V3 — see the vLLM tool-calling docs for your model's parser).
- Big models need multiple GPUs — set `VLLM_TP` to the GPU count.
