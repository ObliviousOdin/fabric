# Local Ollama Pull and Verification

Use this workflow when the user asks Fabric to install, connect, diagnose, or
verify an Ollama model. Keep the profile explicit from pull through chat.

## Pull safely

1. Identify the intended profile and exact model ID/tag.
2. Treat a pull as a network- and disk-consuming mutation. Obtain explicit user
   intent before starting it.
3. Prefer the foreground Fabric command:

   ```bash
   fabric -p PROFILE ollama pull MODEL
   ```

4. In a non-interactive agent terminal, add `--yes` only when the user already
   approved this exact model pull. Do not infer approval from a general request
   to inspect or configure Ollama.
5. Do not pass a credential on the command line. There is no API-key flag. A
   pull to the same configured endpoint can reuse that profile's stored access
   policy without rendering or persisting it.

For an explicit remote/private daemon, pass only `localhost` or a literal
loopback/private IP:

```bash
fabric -p PROFILE ollama pull MODEL --host http://192.168.1.20:11434
```

The pull mutation rejects DNS hostnames until Fabric has a transport that can
pin the authorized address without breaking HTTPS hostname verification. If a
container can reach Ollama only through a name such as
`host.docker.internal`, run native `ollama pull MODEL` in the Ollama
host/network namespace, then configure that hostname for inference separately.

## Interpret the result

- Exit `0`: a fresh `/api/tags` read reported the installed model with an exact
  canonical `sha256:<64 lowercase hex>` digest.
- Exit `1`: validation, access, transport, protocol, disk, pull, or final
  verification failed.
- Exit `130`: Fabric's client request was cancelled. The daemon may still
  finish work; read the reconciliation result before deciding what happened.

Never say that Ctrl+C acknowledged daemon cancellation. Never claim partial
layers were deleted. The command deliberately does not call `/api/delete` or
clean content-addressed blobs because they may be shared with an older model.

The command writes only a sanitized, profile-scoped operation ledger. It does
not select the model, change `config.yaml`, modify fallbacks, or create a chat
session.

## Connect and prove the runtime

After a successful pull, configure the same profile if needed:

```bash
fabric -p PROFILE model
fabric -p PROFILE config check
fabric -p PROFILE status --deep
fabric -p PROFILE doctor
fabric -p PROFILE memory status
fabric -p PROFILE chat
```

In `fabric -p PROFILE model`, choose **Ollama (Local)** and use
`http://127.0.0.1:11434` for the default native server root. Do not add `/v1`
and do not request an API key. An authenticated reverse proxy belongs in the
advanced custom-provider flow. Configure at least the real context the
model/runtime can serve; agentic use requires 64,000 tokens and 65,536 is the
practical target.

Set the same profile's application policy explicitly:

```yaml
security:
  egress_mode: local_ai
  local_ai_allowed_cidrs: []
```

Loopback needs no CIDR. For a LAN/container daemon, use a literal private IP in
`model.base_url`, keep `model.provider: ollama`, and add the narrow exact
RFC1918, ULA, or CGNAT network to
`local_ai_allowed_cidrs`. Do not use a DNS name under `local_ai`; exact
`localhost` is canonicalized to `127.0.0.1`, and every other hostname is
rejected without resolution. Do not approve public, link-local, metadata,
documentation, multicast, or unspecified ranges.

Confirm that status reports mode `local_ai`, enforcement `available`, scope
`ai_inference_routes`, and the expected private-CIDR count. Treat the Ollama
portion of `status --deep` as passive metadata readiness only. Prove the path
with a plain chat and a small reversible tool request. Report tool/vision
metadata as reported capability, not a successful execution.

Doctor uses a restricted view under `local_ai`: it skips live provider, OAuth,
secret-vault, MCP, plugin, package-audit, container, SSH, and update probes.
Built-in `MEMORY.md` and `USER.md` remain usable. A selected external-memory
adapter is unavailable in this milestone and must not be imported, probed,
recalled from, or written to.

## Preserve the locality boundary

`local_ai` enforces the address boundary for primary inference, live model
switches, auxiliary work including title/compression, fallback, delegation, and
each MoA slot. Participating clients use the canonical authorized address
without environment proxies or redirects. Remote fallback is skipped; it never
overrides the policy.

A local primary model is not a whole-system air gap. Review web/browser tools,
MCP, plugins, skills, arbitrary terminal commands, gateways, installs, updates,
model downloads, explicit CLI/dashboard OAuth or device-code setup, and the
behavior of the trusted local server itself. User-initiated account setup can
contact its remote authorization service under `local_ai`; inference-time auth
resolution cannot contact that remote identity plane. `air_gapped`
is configured but unavailable and blocks runtime startup with reason
`whole_process_network_boundary_missing`; it does not activate an air gap.
Require an external verified firewall/container/network boundary for a
whole-process no-egress claim.

Use the full Fabric guide for setup and troubleshooting:
https://obliviousodin.github.io/fabric/guides/local-ollama-setup
