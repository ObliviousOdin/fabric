# Fabric Achievements — Leaderboard Relay

A tiny, self-hostable service that lets several Fabric users share a team
achievement leaderboard. It is **not** a Fabric cloud: you run it, you own the
data, and it only ever stores *aggregate* achievement profiles — never raw
session content.

It is deliberately dependency-free (Python 3.11+ standard library only), so it
runs anywhere: a spare laptop, a $5 VPS, a Raspberry Pi, or a Tailscale node.

## What it stores

For each team: a name, a hashed invite secret, and a set of members. For each
member: a chosen display name, a hashed per-member token, and the aggregate
profile their Fabric published — a score, unlock/tier counts, per-category
tallies, and up to eight unlocked-badge names from the static achievement
catalogue. Secrets are salted-SHA256 hashed at rest and compared with
`hmac.compare_digest`. Session titles, ids, transcripts, file paths, and raw
metrics are rejected at ingest by `store.sanitize_profile()` — they cannot be
stored even if a client tried to send them.

## Run it

The easiest way is from the dashboard: open **Achievements → Team Leaderboard**,
expand **Advanced: host a private leaderboard (Tailscale)**, and click **Host on
this machine**. The dashboard spawns this relay for you (`POST
/team/host/start`), tracks it in `~/.fabric/plugins/fabric-achievements/relay.json`
so **Stop** and status survive a dashboard restart, logs to
`~/.fabric/logs/fabric-achievements-relay.log`, and auto-fills a shareable Relay
URL. You never have to run the command below by hand.

To run it yourself instead (e.g. as a system service on an always-on box), from
the plugin directory:

```bash
cd plugins/fabric-achievements

# In-memory (state lost on restart) — fine for a quick trial:
python -m relay --host 127.0.0.1 --port 9137

# Persist rosters to disk so restarts keep the board:
python -m relay --host 0.0.0.0 --port 9137 --state ./roster.json
```

- `--host 127.0.0.1` (default) — reachable only from the same machine. Good for
  trying the feature locally with two `FABRIC_HOME`s.
- `--host 0.0.0.0` — reachable from your LAN / anywhere the port is exposed
  (this is what **Host on this machine** uses).

Whichever way it runs, everyone else just **Joins** with the invite code. If a
relay is already answering on the port, **Host on this machine** adopts it
rather than starting a second one; a relay it didn't start is reported but not
managed (no Stop button).

### How auto-fill picks the URL

The dashboard's `GET /team/host/status` endpoint combines three local checks:

- a probe of `http://127.0.0.1:<port>/health` to see whether a relay is
  already answering on this machine,
- this node's own Tailscale identity (`tailscale status --json` → `Self`), and
- when both exist, a probe of the resulting Tailscale URL so a relay bound only
  to `127.0.0.1` is never claimed to be teammate-reachable.

It prefers your Tailscale MagicDNS name (`something.ts.net`) because it is
stable and reachable by teammates on the tailnet with no port-forwarding, but
marks it shareable only after that address answers as a Fabric relay. If
Tailscale isn't connected it falls back to `http://127.0.0.1:<port>`, which
only works for a same-machine trial and is flagged as such in the UI.

## Exposing it beyond your LAN (TLS)

`http.server` speaks plain HTTP and is not a hardened, internet-facing server.
Do **not** put it directly on the public internet. Instead bind it to
`127.0.0.1` and front it with something that terminates TLS and forwards to it:

- **Tailscale** (simplest for a friend group): run the relay on any node and
  share `http://<magicdns-name>:9137`, or use `tailscale funnel 9137` for a
  public HTTPS URL. To connect this machine to your tailnet, run
  `fabric setup tailscale` (Fabric's built-in QR login — the dashboard's
  hosting panel links to this same command). The dashboard reads the resulting
  MagicDNS name to auto-fill the Relay URL.
- **Cloudflare Tunnel**: `cloudflared tunnel --url http://127.0.0.1:9137`.
- **Caddy** (auto-HTTPS reverse proxy):

  ```
  leaderboard.example.com {
      reverse_proxy 127.0.0.1:9137
  }
  ```

Members then use the `https://…` URL as the relay URL / inside their invite.

## HTTP API

All bodies are JSON. Secrets are returned exactly once at create/join time;
only their hashes are retained.

| Method & path | Body | Purpose |
|---|---|---|
| `GET /health` | — | `{teams, members, schema_version}` |
| `POST /api/teams` | `{name, display_name}` | Create a team; returns `team_id`, `join_secret`, owner `member_id` + `member_token` |
| `POST /api/teams/{id}/join` | `{join_secret, display_name}` | Join; returns `member_id` + `member_token` |
| `POST /api/teams/{id}/publish` | `{member_id, member_token, profile, display_name?}` | Store this member's aggregate profile |
| `POST /api/teams/{id}/unpublish` | `{member_id, member_token}` | Retract your profile (stay a member, show as not-shared) |
| `POST /api/teams/{id}/leave` | `{member_id, member_token}` | Remove yourself |
| `POST /api/teams/{id}/rotate` | `{member_id, member_token}` | Owner-only: mint a fresh invite secret |
| `POST /api/teams/{id}/kick` | `{member_id, member_token, target_member_id}` | Owner-only: remove a member |
| `GET /api/teams/{id}/leaderboard` | headers `X-Join-Secret` **or** `X-Member-Id`+`X-Member-Token` | Ranked roster |

Only Fabric *backends* call this API (server-to-server via `urllib`). Browsers
never contact the relay directly — each member's dashboard proxies — so there
is no CORS surface here.

## Trust model & limitations (read before relying on rankings)

- The **invite secret** is a bearer capability: anyone who has the invite code
  can view the roster and join. Share it only with people you want on the team.
  The owner can **Reset invite** (rotate) to invalidate old links and **Remove**
  members.
- **Scores are self-reported.** Each member's Fabric computes its own profile;
  the relay does not (and cannot) verify it against real session history. This
  board is for friends/teams who trust each other, not an adversarial ranking.
  Cryptographic attestation is noted as future work.
- No accounts, no global discovery: a team is reachable only with its secret.
- `create_team` is unauthenticated (that's how invites work), so the relay caps
  total teams (`MAX_TEAMS`, default 1000) to bound a create-spam DoS. This is a
  backstop, not a substitute for running the relay on a trusted network or
  behind an authenticating proxy.

## Testing

```bash
python -m unittest plugins.fabric-achievements.tests.test_leaderboard_store -v
```
