# Fabric deploy templates

Ready-to-use artifacts for hosting an always-on Fabric agent, and for standing up
a shared frontier-model compute backend. Full write-ups:

- **Self-hosting guide:** [`/deploy/self-hosting`](https://obliviousodin.github.io/fabric/deploy/self-hosting)
  (source: `website/docs/deploy/self-hosting.md`)
- **Managed hosting design:** [`/deploy/managed-hosting`](https://obliviousodin.github.io/fabric/deploy/managed-hosting)
- **Shared compute broker design:** [`/deploy/compute-broker`](https://obliviousodin.github.io/fabric/deploy/compute-broker)

## What's here

| File | Purpose |
| --- | --- |
| `.env.hosted.example` | Environment template — copy to `.env`, edit the Required block |
| `provision.sh` | Unattended, idempotent config seeding: generates a dashboard login + API key, writes `config.yaml`, emits `fabric-credentials.txt` |
| `docker-compose.hosted.yml` | Always-on gateway + dashboard + Caddy TLS (only Caddy is public) |
| `Caddyfile` | Automatic HTTPS; routes `/v1` → API server, everything else → dashboard |
| `cloud-init.yaml` | Paste into a fresh VPS's user-data for a one-shot bring-up |
| `compute-broker/` | Vast.ai + vLLM bootstrap to serve a frontier open model behind an OpenAI-compatible endpoint |

## Quick start (Docker Compose)

```bash
cp .env.hosted.example .env         # edit FABRIC_PUBLIC_DOMAIN, ACME_EMAIL, a provider key
./provision.sh                      # generate login + secrets, write config
docker compose -f docker-compose.hosted.yml up -d
cat ./fabric-credentials.txt        # dashboard login + API key
```

Point a DNS A/AAAA record for your domain at the box first, so Caddy can issue a
certificate.

## Quick start (fresh VPS)

Edit the three values at the top of [`cloud-init.yaml`](./cloud-init.yaml) and
paste it into your provider's *user data / cloud-init* field when creating the
server. After boot: `ssh root@<box> && cat /root/fabric-credentials.txt`.

## Provider notes

A small box ($4–10/mo, 1–2 GB RAM) runs the agent comfortably; keep heavy local
models on their own GPU box (see `compute-broker/`).

| Provider | Starter tier | Notes |
| --- | --- | --- |
| Hetzner Cloud | CX22 / CPX21 | Cheapest solid option; accepts cloud-init user-data |
| DigitalOcean | 2 vCPU / 8 GB Droplet | One-click Docker; accepts user-data |
| Vultr | 2–4 vCPU / 8 GB | Cheap GPU add-ons for co-locating a model |
| Contabo | 4–6 vCPU / 8–16 GB | Most RAM/storage per dollar |

## Safety notes

- The dashboard auth gate is **fail-closed** on any non-loopback bind — a
  misconfigured public dashboard refuses to start. `provision.sh` always
  configures a login, so it starts.
- The API server never starts without a strong `API_SERVER_KEY` (`provision.sh`
  generates one).
- **One gateway writer per data volume.** Don't add a second `gateway run`
  container on the same `./data`. For several agents, use
  [profiles](https://obliviousodin.github.io/fabric/user-guide/profiles).
- Nothing here sends email; `fabric-credentials.txt` is written locally. Email
  delivery is the managed control plane's job (see the design docs).
