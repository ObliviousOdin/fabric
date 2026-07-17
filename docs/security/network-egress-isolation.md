# Network Isolation for Agent Commands

Fabric itself needs outbound access for model providers, messaging platforms,
OAuth, and any network-backed tools you enable. Putting that process on an
internet-capable Docker network while setting `HTTP_PROXY` does **not** create
an egress security boundary: a shell command can unset the proxy variables or
open a raw socket.

The supported isolation boundary is the separate Docker terminal backend. Run
Fabric on the network it needs, then execute `terminal`, `execute_code`, and
file-tool work inside a sandbox container with networking disabled.

## Threat model

This protects against a prompt-injected or mistaken shell command trying to
exfiltrate workspace data with `curl`, `wget`, DNS, or a raw TCP connection.
It does not make every Fabric capability offline. Model requests, messaging
adapters, and explicitly enabled host-side web or browser tools still use the
Fabric process's network access.

## Recommended configuration

Put the following in `~/.fabric/config.yaml`:

```yaml
terminal:
  backend: docker
  docker_image: python:3.11-slim
  docker_network: false
  docker_auto_mount_cwd: true
```

`terminal.docker_network: false` maps to Docker's `--network=none`. Fabric also
checks a reusable sandbox before attaching to it: if an older container has a
network but the current config requests isolation, Fabric removes it and
creates a fresh air-gapped container.

Use this first-class key instead of adding `--network=none` through
`terminal.docker_extra_args`; the explicit setting is validated by the
container-reuse path and is easier to audit.

The boundary looks like this:

```text
Fabric process
  ├─ model, gateway, approved web/browser integrations ── network as configured
  └─ terminal / execute_code / file tools
       └─ Docker sandbox (`--network=none`) ── no network interface
```

Keep mounts narrow. Anything mounted into the sandbox is readable by agent
commands even when the network is disabled. Never mount the Docker socket,
cloud credential directories, or unrelated host paths into an untrusted task
sandbox.

## Verify the boundary

Start one tool-assisted session so Fabric creates the Docker sandbox, then
inspect containers carrying Fabric's execution label:

```bash
docker ps --filter label=fabric-agent=1 \
  --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}'

container_id="$(docker ps -q --filter label=fabric-agent=1 | head -n 1)"
docker inspect --format '{{.HostConfig.NetworkMode}}' "$container_id"
# expected: none
```

Test both HTTP and DNS/raw network behavior inside that sandbox:

```bash
docker exec "$container_id" sh -lc \
  'curl -fsS --max-time 5 https://example.com'
# expected: failure

docker exec "$container_id" sh -lc \
  'python - <<"PY"
import socket
socket.create_connection(("1.1.1.1", 443), timeout=3)
PY'
# expected: failure
```

If the inspection reports `bridge`, `host`, or another network, stop and fix
the configuration before treating the sandbox as isolated. Remove an obsolete
sandbox with `docker rm -f "$container_id"`; Fabric will recreate it on the
next tool call.

## What an HTTP proxy can and cannot do

You may still route the main Fabric process through an allowlisting HTTP proxy
for observability or ordinary policy enforcement:

```bash
HTTP_PROXY=http://proxy.internal:3128 \
HTTPS_PROXY=http://proxy.internal:3128 \
NO_PROXY=127.0.0.1,localhost \
fabric gateway run
```

Treat this as cooperative routing unless the operating system or container
network blocks every direct route and only the proxy is dual-homed. Environment
variables alone do not constrain raw sockets, alternate clients, or DNS. A
secure proxy topology needs its own direct-TCP and DNS-bypass tests; a successful
proxied request is not proof that direct egress is blocked.

## Limitations

- **Network-backed tools are separate capabilities.** `web_search`, remote
  browser providers, model APIs, and messaging adapters run outside the
  air-gapped terminal sandbox unless their own backend says otherwise.
- **Local terminal is not isolated.** With `terminal.backend: local`, agent
  shell commands inherit the Fabric host's network access.
- **Mounted data remains exposed to commands.** Network isolation limits
  exfiltration paths; it does not prevent reads or writes inside mounted paths.
- **No network means no package downloads.** Pre-build the sandbox image with
  required dependencies or temporarily use a separately controlled build
  process. Do not weaken a production sandbox just to run `pip install`.
- **Defense in depth still matters.** Keep dangerous-command approvals,
  URL-safety checks, secret redaction, and least-privilege credentials enabled.

## Related

- [Security policy](../../SECURITY.md)
- [Terminal backend configuration](../../website/docs/user-guide/configuration.md#docker-backend)
- [Docker deployment guide](../../website/docs/user-guide/docker.md)
