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
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

Without the SDK or credentials the hooks no-op silently — the plugin fails
open.

## Verify

```bash
fabric plugins list                 # observability/langfuse should show "enabled"
fabric chat -q "hello"              # then check Langfuse for a "Fabric turn" trace
```

## Optional tuning

```yaml
observability:
  langfuse:
    base_url: https://cloud.langfuse.com
    environment: production
    release: v1.0.0
    sample_rate: 0.5
    max_chars: 12000
    debug: false
```

## Disable

```bash
fabric plugins disable observability/langfuse
```
