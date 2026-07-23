# Security and trust model

Profile distributions can change Fabric's standing identity instructions and
may include skills or config. Treat them as code, even when a particular
release contains only Markdown and YAML.

## Before installing

1. Review the checkout, especially `SOUL.md`, `config.yaml`, `skills/`, and
   `distribution.yaml` in the selected generated profile.
2. Prefer a reviewed, immutable tag or commit over a mutable branch.
3. Run `python3 tools/validate_collection.py` and
   `python3 tools/build_collection.py --check`.
4. Inspect the payload digest printed by `manage.py`; it identifies the bytes
   you reviewed but does not authenticate their publisher.
5. Keep the checkout in a stable path because Fabric records local sources by
   absolute path for later updates.

## What distributions never contain

- `.env`, API keys, OAuth tokens, passwords, or `auth.json`
- memories, sessions, conversation history, state databases, logs, or caches
- cron jobs or automatically scheduled work
- MCP servers or network endpoints
- a selected model or provider
- symlinks, executables, or binary media

The validator fails closed if generated payloads contain protected state names,
unexpected files, symlinks, or binary data.

## Installation behavior

`manage.py` invokes `fabric profile install` and `fabric profile update`; it
does not write directly to Fabric's home directory. Installs are isolated
profiles and therefore need their own model/provider setup before first use.
Normal updates preserve user memory, sessions, credentials, and local
`config.yaml`. The manager verifies that an installed profile's recorded
source is this checkout's exact generated profile directory before updating;
same-slug profiles from another source are refused. Fabric's current
distribution updater is not fully atomic and does not enforce
`distribution_owned` as a strict copy allow-list. For that reason generated
payloads are intentionally minimal.

`install --force` replaces an existing profile's `SOUL.md`, `config.yaml`, and
skins. `update --force-config` replaces `config.yaml` with the distribution's
empty model plus skin selection. The manager surfaces those effects even with
`--yes`; use either option only after reviewing the named profiles.

Bulk installation can partially succeed if a later profile fails. The manager
reports every failed slug and exits non-zero; it does not delete successful
installs automatically.

## Persona safety

Persona flavor never expands authorization. A fictional identity, rank,
reputation, intelligence, power, or villain role cannot grant real-world
credentials or permission. Every generated SOUL requires explicit scope for
destructive, security-sensitive, privacy-sensitive, financial, or externally
visible actions.

Report a security issue privately to the repository owner when the collection
is published. Do not include live credentials, private conversation data, or
third-party personal data in the report.
