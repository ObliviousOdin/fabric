# Langfuse Observability Plugin

This plugin ships bundled with Fabric but is **opt-in** — it only loads when
you explicitly enable it.

## Enable

Pick one:

```bash
# Interactive: walks you through credentials + SDK install + enable
fabric tools  # → Langfuse Observability

# Manual
pip install langfuse
fabric plugins enable observability/langfuse
```

## Required credentials

Set these in `~/.fabric/.env` (or via `fabric tools`):

```bash
FABRIC_LANGFUSE_PUBLIC_KEY=pk-lf-...
FABRIC_LANGFUSE_SECRET_KEY=sk-lf-...
FABRIC_LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

Without the SDK or credentials the hooks no-op silently — the plugin fails
open.

## Verify

```bash
fabric plugins list                 # observability/langfuse should show "enabled"
fabric chat -q "hello"              # then check Langfuse for a "Fabric turn" trace
```

## Optional tuning

```bash
FABRIC_LANGFUSE_ENV=production       # environment tag
FABRIC_LANGFUSE_RELEASE=v1.0.0       # release tag
FABRIC_LANGFUSE_SAMPLE_RATE=0.5      # sample 50% of traces
FABRIC_LANGFUSE_MAX_CHARS=12000      # max chars per field (default: 12000)
FABRIC_LANGFUSE_DEBUG=true           # verbose plugin logging
```

## Disable

```bash
fabric plugins disable observability/langfuse
```
