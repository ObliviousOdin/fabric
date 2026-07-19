---
title: "AI Providers"
sidebar_label: "AI Providers"
sidebar_position: 1
---

# AI Providers

Fabric needs one model provider. Start with the setup that matches your constraint, then use the catalog below when you need provider-specific details.

| If you want… | Start with… | Why |
|--------------|-------------|-----|
| A local model with no cloud inference | [Ollama](#ollama-local--first-class-native-provider) | Runs on your machine and requires no provider API key |
| One hosted account with access to many model families | OpenRouter | One API key and a broad model catalog |
| Direct billing and controls from a model vendor | A first-class API-key provider | Fabric connects directly to that vendor's API |
| To use an existing account login | `fabric model` | Shows the OAuth and device-code options available to your installation and account |
| Your own GPU server or compatible gateway | [Custom & self-hosted providers](#custom--self-hosted-llm-providers) | Connects to Ollama, vLLM, SGLang, llama.cpp, LiteLLM, or another compatible endpoint |

Run `fabric model` for the guided path. It stores non-secret settings in `~/.fabric/config.yaml` and credentials in the profile's credential store or `~/.fabric/.env`, depending on the provider.

:::note Account and plan availability
OAuth, device-code, model-catalog, and subscription access are controlled by each provider. Plans, eligible models, usage limits, and terms can change independently of Fabric. Treat `fabric model` as the availability check for your account, and confirm current terms with the provider before relying on a subscription-backed setup.
:::

## Provider Catalog

You need at least one way to connect to an LLM. Use `fabric model` to switch providers and models interactively, or configure directly:

| Provider | Setup |
|----------|-------|
| **OpenAI Codex** | `fabric model` (ChatGPT device-code sign-in; see the [Fabric guide](/guides/chatgpt-codex-subscription)) |
| **GitHub Copilot** | `fabric model` (OAuth device code flow, `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, or `gh auth token`) |
| **GitHub Copilot ACP** | `fabric model` (spawns local `copilot --acp --stdio`) |
| **Anthropic** | `fabric model` or `ANTHROPIC_API_KEY` in `~/.fabric/.env` (API key only — see note below) |
| **Nous Portal** | `fabric auth add nous --client-id <registered-client-id>` (device-code OAuth with a registered Nous OAuth client ID) |
| **OpenRouter** | `OPENROUTER_API_KEY` in `~/.fabric/.env` |
| **NovitaAI** | `NOVITA_API_KEY` in `~/.fabric/.env` (provider: `novita`; Model API, Agent Sandbox, and GPU Cloud) |
| **z.ai / GLM** | `GLM_API_KEY` in `~/.fabric/.env` (provider: `zai`) |
| **Kimi / Moonshot** | `KIMI_API_KEY` in `~/.fabric/.env` (provider: `kimi-coding`) |
| **Kimi / Moonshot (China)** | `KIMI_CN_API_KEY` in `~/.fabric/.env` (provider: `kimi-coding-cn`; aliases: `kimi-cn`, `moonshot-cn`) |
| **Arcee AI** | `ARCEEAI_API_KEY` in `~/.fabric/.env` (provider: `arcee`; aliases: `arcee-ai`, `arceeai`) |
| **GMI Cloud** | `GMI_API_KEY` in `~/.fabric/.env` (provider: `gmi`; aliases: `gmi-cloud`, `gmicloud`) |
| **MiniMax** | `MINIMAX_API_KEY` in `~/.fabric/.env` (provider: `minimax`) |
| **MiniMax China** | `MINIMAX_CN_API_KEY` in `~/.fabric/.env` (provider: `minimax-cn`) |
| **xAI (Grok) — Responses API** | `XAI_API_KEY` in `~/.fabric/.env` (provider: `xai`) |
| **xAI Grok OAuth** | `fabric model` → choose the provider whose label begins "xAI Grok OAuth" — browser login when xAI authorizes the account; no API key. See [guide](../guides/xai-grok-oauth.md) |
| **Qwen Cloud (Alibaba DashScope)** | `DASHSCOPE_API_KEY` in `~/.fabric/.env` (provider: `alibaba`) |
| **Alibaba Cloud (Coding Plan)** | `DASHSCOPE_API_KEY` (provider: `alibaba-coding-plan`, alias: `alibaba_coding`) — separate billing SKU, different endpoint |
| **Kilo Code** | `KILOCODE_API_KEY` in `~/.fabric/.env` (provider: `kilocode`) |
| **Xiaomi MiMo** | `XIAOMI_API_KEY` in `~/.fabric/.env` (provider: `xiaomi`, aliases: `mimo`, `xiaomi-mimo`) |
| **Tencent TokenHub** | `TOKENHUB_API_KEY` in `~/.fabric/.env` (provider: `tencent-tokenhub`, aliases: `tencent`, `tokenhub`, `tencentmaas`) |
| **OpenCode Zen** | `OPENCODE_ZEN_API_KEY` in `~/.fabric/.env` (provider: `opencode-zen`) |
| **OpenCode Go** | `OPENCODE_GO_API_KEY` in `~/.fabric/.env` (provider: `opencode-go`) |
| **DeepSeek** | `DEEPSEEK_API_KEY` in `~/.fabric/.env` (provider: `deepseek`) |
| **Hugging Face** | `HF_TOKEN` in `~/.fabric/.env` (provider: `huggingface`, aliases: `hf`) |
| **Google / Gemini** | `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) in `~/.fabric/.env` (provider: `gemini`) |
| **Google Vertex AI** | `fabric model` → "Google Vertex AI" (provider: `vertex`; OAuth2 via service-account JSON or ADC, GCP billing) |
| **OpenAI API (direct)** | `OPENAI_API_KEY` in `~/.fabric/.env` (provider: `openai-api`, optional `OPENAI_BASE_URL`) |
| **Azure AI Foundry** | `fabric model` → "Azure AI Foundry" (provider: `azure-foundry`; uses Azure OpenAI / Foundry endpoint and key) |
| **AWS Bedrock** | `fabric model` → "AWS Bedrock" (provider: `bedrock`; standard AWS credentials chain via boto3) |
| **NVIDIA Build** | `NVIDIA_API_KEY` in `~/.fabric/.env` (provider: `nvidia`; NIM-hosted models on build.nvidia.com) |
| **Ollama Cloud** | `fabric model` → "Ollama Cloud" (provider: `ollama-cloud`; cloud-hosted Ollama API) |
| **Qwen OAuth** | `fabric model` → "Qwen OAuth" (provider: `qwen-oauth`; browser PKCE login) |
| **MiniMax OAuth** | `fabric model` → "MiniMax (OAuth)" (provider: `minimax-oauth`; browser PKCE login) |
| **StepFun** | `STEPFUN_API_KEY` in `~/.fabric/.env` (provider: `stepfun`) |
| **LM Studio** | `fabric model` → "LM Studio" (provider: `lmstudio`, optional `LM_API_KEY`) |
| **Custom Endpoint** | `fabric model` → choose "Custom endpoint" (saved in `config.yaml`) |

For the official API-key path, see the dedicated [Google Gemini guide](/guides/google-gemini).

:::tip Model key alias
In the `model:` config section, you can use either `default:` or `model:` as the key name for your model ID. Both `model: { default: my-model }` and `model: { model: my-model }` work identically.
:::


:::info Codex Note
The OpenAI Codex provider authenticates via device code (open a URL, enter a code). Fabric stores the resulting credentials in the selected profile's auth store and can import existing Codex CLI credentials from `~/.codex/auth.json` when present. No Codex CLI installation is required. Never email or forward the device code; the [ChatGPT subscription guide](/guides/chatgpt-codex-subscription) explains the separate personal and Fabric-managed paths.

If a token refresh fails with a terminal error (HTTP 4xx, `invalid_grant`, revoked grant, etc.), Fabric marks the refresh token as dead and stops replaying it so you don't see a flood of identical auth failures. The next request surfaces a typed re-auth message instead. Run `fabric auth add openai-codex` (or `fabric model` → OpenAI Codex) to start a fresh device-code login; the quarantine clears on the next successful exchange.
:::

:::warning
Even when using a subscription or custom endpoint, some tools (vision, web
summarization, MoA) use a separate "auxiliary" model. By default
(`auxiliary.*.provider: "auto"`), Fabric routes these tasks to your **main chat
model**. You can override each task individually — see
[Auxiliary Models](/user-guide/configuration#auxiliary-models).
:::

### Two Commands for Model Management

Fabric has **two** model commands that serve different purposes:

| Command | Where to run | What it does |
|---------|-------------|--------------|
| **`fabric model`** | Your terminal (outside any session) | Full setup wizard — add providers, run OAuth, enter API keys, configure endpoints |
| **`/model`** | Inside a Fabric chat session | Quick switch between **already-configured** providers and models |

If you're trying to switch to a provider you haven't set up yet (e.g. you only have OpenRouter configured and want to use Anthropic), you need `fabric model`, not `/model`. Exit your session first (`Ctrl+C` or `/quit`), run `fabric model`, complete the provider setup, then start a new session.


### Anthropic (Native)

Use Claude models directly through the Anthropic API — no OpenRouter proxy needed. Authenticates with a regular API key only; Fabric does not offer an OAuth/subscription login for Anthropic, and does not read or reuse Claude Code's own credentials (see [NOTICE](https://github.com/ObliviousOdin/fabric/blob/main/NOTICE)).

```bash
# With an API key (pay-per-token)
export ANTHROPIC_API_KEY=***
fabric chat --provider anthropic --model claude-sonnet-4-6

# Or authenticate through `fabric model`
fabric model
```

Or set it permanently:
```yaml
model:
  provider: "anthropic"
  default: "claude-sonnet-4-6"
```

:::tip Aliases
`--provider claude` and `--provider claude-code` also work as shorthand for `--provider anthropic` (a plain API key — there is no separate Claude Code credential path).
:::

### GitHub Copilot

Fabric supports GitHub Copilot as a first-class provider with two modes:

**`copilot` — Direct Copilot API**. Authenticates to GitHub Copilot and discovers the model catalog available to your account. Models, usage limits, and availability depend on your current GitHub plan and entitlements.

```bash
fabric chat --provider copilot --model gpt-5.4
```

**Authentication options** (checked in this order):

1. `COPILOT_GITHUB_TOKEN` environment variable
2. `GH_TOKEN` environment variable
3. `GITHUB_TOKEN` environment variable
4. `gh auth token` CLI fallback

If no token is found, `fabric model` offers an **OAuth device code login** — the same flow used by the Copilot CLI and opencode.

:::warning Token types
The Copilot API does **not** support classic Personal Access Tokens (`ghp_*`). Supported token types:

| Type | Prefix | How to get |
|------|--------|------------|
| OAuth token | `gho_` | `fabric model` → GitHub Copilot → Login with GitHub |
| Fine-grained PAT | `github_pat_` | GitHub Settings → Developer settings → Fine-grained tokens (needs **Copilot Requests** permission) |
| GitHub App token | `ghu_` | Via GitHub App installation |

If your `gh auth token` returns a `ghp_*` token, use `fabric model` to authenticate via OAuth instead.
:::

:::info Copilot auth behavior in Fabric
Fabric sends a supported GitHub token (`gho_*`, `github_pat_*`, or `ghu_*`) directly to `api.githubcopilot.com` and includes Copilot-specific headers (`Editor-Version`, `Copilot-Integration-Id`, `Openai-Intent`, `x-initiator`).

On HTTP 401, Fabric now performs a one-shot credential recovery before fallback:

1. Re-resolve token via the normal priority chain (`COPILOT_GITHUB_TOKEN` → `GH_TOKEN` → `GITHUB_TOKEN` → `gh auth token`)
2. Rebuild the shared OpenAI client with refreshed headers
3. Retry the request once

Some older community proxies use `api.github.com/copilot_internal/v2/token` exchange flows. That endpoint can be unavailable for some account types (returns 404). Fabric therefore keeps direct-token auth as the primary path and relies on runtime credential refresh + retry for robustness.
:::

**API routing**: GPT-5+ models (except `gpt-5-mini`) automatically use the Responses API. All other models (GPT-4o, Claude, Gemini, etc.) use Chat Completions. Models are auto-detected from the live Copilot catalog.

**`copilot-acp` — Copilot ACP agent backend**. Spawns the local Copilot CLI as a subprocess:

```bash
fabric chat --provider copilot-acp --model copilot-acp
# Requires the GitHub Copilot CLI in PATH and an existing `copilot login` session
```

**Permanent config:**
```yaml
model:
  provider: "copilot"
  default: "gpt-5.4"
```

| Environment variable | Description |
|---------------------|-------------|
| `COPILOT_GITHUB_TOKEN` | GitHub token for Copilot API (first priority) |
| `COPILOT_CLI_PATH` | Optional path to the GitHub Copilot CLI binary (default: `copilot`) |

### First-Class API-Key Providers

These providers have built-in support with dedicated provider IDs. Set the API key and use `--provider` to select:

```bash
# NovitaAI Model API
fabric chat --provider novita --model moonshotai/kimi-k2.5
# Requires: NOVITA_API_KEY in ~/.fabric/.env

# z.ai / ZhipuAI GLM
fabric chat --provider zai --model glm-5
# Requires: GLM_API_KEY in ~/.fabric/.env

# Kimi / Moonshot AI (international: api.moonshot.ai)
fabric chat --provider kimi-coding --model kimi-for-coding
# Requires: KIMI_API_KEY in ~/.fabric/.env

# Kimi / Moonshot AI (China: api.moonshot.cn)
fabric chat --provider kimi-coding-cn --model kimi-k2.5
# Requires: KIMI_CN_API_KEY in ~/.fabric/.env

# MiniMax (global endpoint)
fabric chat --provider minimax --model MiniMax-M2.7
# Requires: MINIMAX_API_KEY in ~/.fabric/.env

# MiniMax (China endpoint)
fabric chat --provider minimax-cn --model MiniMax-M2.7
# Requires: MINIMAX_CN_API_KEY in ~/.fabric/.env

# Qwen Cloud / DashScope (Qwen models)
fabric chat --provider alibaba --model qwen3.5-plus
# Requires: DASHSCOPE_API_KEY in ~/.fabric/.env

# Xiaomi MiMo
fabric chat --provider xiaomi --model mimo-v2-pro
# Requires: XIAOMI_API_KEY in ~/.fabric/.env

# Tencent TokenHub (Hy3 Preview)
fabric chat --provider tencent-tokenhub --model hy3-preview
# Requires: TOKENHUB_API_KEY in ~/.fabric/.env

# Arcee AI (Trinity models)
fabric chat --provider arcee --model trinity-large-thinking
# Requires: ARCEEAI_API_KEY in ~/.fabric/.env

# GMI Cloud
# Use the exact model ID returned by GMI's /v1/models endpoint.
fabric chat --provider gmi --model zai-org/GLM-5.1-FP8
# Requires: GMI_API_KEY in ~/.fabric/.env
```

Or set the provider permanently in `config.yaml`:
```yaml
model:
  provider: "gmi"
  default: "zai-org/GLM-5.1-FP8"
```

Base URLs can be overridden with `NOVITA_BASE_URL`, `GLM_BASE_URL`, `KIMI_BASE_URL`, `MINIMAX_BASE_URL`, `MINIMAX_CN_BASE_URL`, `DASHSCOPE_BASE_URL`, `XIAOMI_BASE_URL`, `GMI_BASE_URL`, or `TOKENHUB_BASE_URL` environment variables.

:::note Z.AI Endpoint Auto-Detection
When using the Z.AI / GLM provider, Fabric automatically probes multiple endpoints (global, China, coding variants) to find one that accepts your API key. You don't need to set `GLM_BASE_URL` manually — the working endpoint is detected and cached automatically.
:::

### xAI (Grok) — Responses API + Prompt Caching

xAI is wired through the Responses API (`codex_responses` transport) for automatic reasoning support on Grok 4 models — no `reasoning_effort` parameter needed, the server reasons by default. Set `XAI_API_KEY` in `~/.fabric/.env` and pick xAI in `fabric model`, or drop `grok` as a shortcut into `/model grok-4-fast-reasoning`.

Some xAI accounts may be eligible for browser OAuth instead of an API key. In
`fabric model`, choose the provider whose label begins **xAI Grok OAuth**, or run
`fabric auth add xai-oauth`. xAI controls account eligibility; if the login is
not offered or authorization is rejected, use an `XAI_API_KEY`. The same
profile-scoped connection can serve direct xAI tools such as TTS, image
generation, video, transcription, and X Search when enabled. See the
[Fabric xAI Grok OAuth guide](../guides/xai-grok-oauth.md) for the full flow. xAI
uses device-code authorization, so remote hosts do **not** need an `ssh -L`
callback tunnel; open the printed verification URL in a trusted browser instead.

When using xAI as a provider (any base URL containing `x.ai`), Fabric automatically enables prompt caching by sending the `x-grok-conv-id` header with every API request. This routes requests to the same server within a conversation session, allowing xAI's infrastructure to reuse cached system prompts and conversation history.

No configuration is needed — caching activates automatically when an xAI endpoint is detected and a session ID is available. This reduces latency and cost for multi-turn conversations.

xAI also ships a dedicated TTS endpoint (`/v1/tts`). Select **xAI TTS** in `fabric tools` → Voice & TTS, or see the [Voice & TTS](../user-guide/features/tts.md#text-to-speech) page for config.

**Retired xAI model migration:** `fabric doctor` and `fabric chat` startup detect xAI model references covered by Fabric's retirement map and print the recommended replacement. Use `fabric migrate xai` for a one-shot config rewrite. It runs as a dry-run by default; add `--apply` to write changes. Fabric creates a timestamped `config.yaml.bak-pre-migrate-xai-*` backup before applying the migration. Check xAI's current model catalog for retirements added after your installed Fabric release.

```bash
fabric migrate xai          # preview replacements
fabric migrate xai --apply  # rewrite ~/.fabric/config.yaml in place
```

**xAI Web Search backend.** When the [Web Search](../user-guide/features/web-search.md) toolset is enabled, `web.backend: xai` routes search through xAI's hosted search endpoint using the same `XAI_API_KEY` / OAuth credentials. No additional setup required if xAI is already configured as a provider.

### NovitaAI

[NovitaAI](https://novita.ai) provides a Model API, Agent Sandbox, and GPU Cloud. Its model catalog changes over time; use the exact model ID returned by its API.

```bash
# Use any available model
fabric chat --provider novita --model moonshotai/kimi-k2.5
# Requires: NOVITA_API_KEY in ~/.fabric/.env

# Short alias
fabric chat --provider novita-ai --model deepseek/deepseek-v3-0324
```

Or set it permanently in `config.yaml`:
```yaml
model:
  provider: "novita"
  default: "moonshotai/kimi-k2.5"
  base_url: "https://api.novita.ai/openai/v1"
```

Get your API key at [novita.ai/settings/key-management](https://novita.ai/settings/key-management). The base URL can be overridden with `NOVITA_BASE_URL`.

### Ollama Cloud — Managed Ollama Models, OAuth + API Key

[Ollama Cloud](https://ollama.com/cloud) hosts open-weight models without requiring a local GPU. Pick it in `fabric model` as **Ollama Cloud**, paste your API key from [ollama.com/settings/keys](https://ollama.com/settings/keys), and Fabric discovers the available cloud models.

```bash
fabric model
# → pick "Ollama Cloud"
# → paste your OLLAMA_API_KEY
# → select from discovered models (gpt-oss:120b, glm-4.6:cloud, qwen3-coder:480b-cloud, etc.)
```

Or `config.yaml` directly:
```yaml
model:
  provider: "ollama-cloud"
  default: "gpt-oss:120b"
```

The model catalog is fetched dynamically from `ollama.com/v1/models` and cached for one hour. `model:tag` notation (e.g. `qwen3-coder:480b-cloud`) is preserved through normalization — don't use dashes.

:::tip Ollama Cloud vs local Ollama
They are intentionally separate providers. Cloud uses `ollama-cloud` plus
`OLLAMA_API_KEY`. Local uses the keyless `ollama` provider and native
`/api/tags`, `/api/show`, and `/api/chat` at a server root such as
`http://127.0.0.1:11434`. Use cloud for models you cannot run locally; use local
when you want primary inference on hardware you control. That choice alone does
not make the rest of Fabric offline or air-gapped.
:::

### AWS Bedrock

Anthropic Claude, Amazon Nova, DeepSeek v3.2, Meta Llama 4, and other models via AWS Bedrock. Uses the AWS SDK (`boto3`) credential chain — no API key, just standard AWS auth.

```bash
# Simplest — named profile in ~/.aws/credentials
fabric chat --provider bedrock --model us.anthropic.claude-sonnet-4-6

# Or with explicit env vars
AWS_PROFILE=myprofile AWS_REGION=us-east-1 fabric chat --provider bedrock --model us.anthropic.claude-sonnet-4-6
```

Or permanently in `config.yaml`:
```yaml
model:
  provider: "bedrock"
  default: "us.anthropic.claude-sonnet-4-6"
bedrock:
  region: "us-east-1"          # or set AWS_REGION
  # profile: "myprofile"       # or set AWS_PROFILE
  # discovery: true            # auto-discover region from IAM
  # guardrail:                 # optional Bedrock Guardrails
  #   guardrail_identifier: "your-guardrail-id"
  #   guardrail_version: "DRAFT"
```

Authentication uses the standard boto3 chain: explicit `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, `AWS_PROFILE` from `~/.aws/credentials`, IAM role on EC2/ECS/Lambda, IMDS, or SSO. No env var is required if you're already authenticated with the AWS CLI.

Bedrock uses the **Converse API** under the hood — requests are translated to Bedrock's model-agnostic shape, so the same config works for Claude, Nova, DeepSeek, and Llama models. Set `BEDROCK_BASE_URL` only if you're calling a non-default regional endpoint.

See the [AWS Bedrock guide](/guides/aws-bedrock) for a walkthrough of IAM setup, region selection, and cross-region inference.

### Google Vertex AI

Gemini models on Google Cloud Vertex AI via Vertex's OpenAI-compatible endpoint. Authentication is **OAuth2** — a short-lived access token (~1 hour) minted from a service-account JSON or Application Default Credentials (ADC). There is **no static API key**; Fabric mints and auto-refreshes the token for you, including re-minting on a mid-session `401`.

```bash
# Service account JSON (recommended for servers / gateways)
echo "VERTEX_CREDENTIALS_PATH=/path/to/service-account.json" >> ~/.fabric/.env
# or Application Default Credentials
gcloud auth application-default login

fabric model   # → "Google Vertex AI" → project → region → model
```

Or in `config.yaml` (project/region are non-secret and live here; the credential path stays in `.env`):
```yaml
model:
  provider: "vertex"
  default: "google/gemini-3-flash-preview"   # Vertex requires the google/ prefix
vertex:
  project_id: "my-gcp-project"   # blank → use the project embedded in the credentials
  region: "global"               # required for the Gemini 3.x previews
```

`VERTEX_PROJECT_ID` / `VERTEX_REGION` env vars override the `config.yaml` values. Install with `pip install 'fabric-agent[vertex]'` (or let Fabric lazy-install `google-auth` on first use). See the [Google Vertex AI guide](/guides/google-vertex) for the full walkthrough, and the [Google Gemini guide](/guides/google-gemini) for the static-API-key AI Studio path instead.

### Qwen Portal (OAuth)

Alibaba's Qwen Portal with browser-based OAuth login. Pick **Qwen OAuth (Portal)** in `fabric model`, sign in through the browser, and Fabric persists the refresh token.

```bash
fabric model
# → pick "Qwen OAuth (Portal)"
# → browser opens; sign in with your Alibaba account
# → confirm — credentials are saved to ~/.fabric/auth.json

fabric chat   # uses portal.qwen.ai/v1 endpoint
```

Or configure `config.yaml`:
```yaml
model:
  provider: "qwen-oauth"
  default: "qwen3-coder-plus"
```

:::tip Qwen OAuth vs Qwen Cloud (Alibaba DashScope)
`qwen-oauth` uses the consumer-facing Qwen Portal with OAuth login — ideal for individual users. The `alibaba` provider uses Qwen Cloud (Alibaba DashScope) with a `DASHSCOPE_API_KEY` — ideal for programmatic / production workloads. Both route to Qwen-family models but live at different endpoints.
:::

### Alibaba Cloud (Coding Plan)

If you're subscribed to Alibaba's **Coding Plan** (a pricing SKU separate from standard DashScope API access), Fabric exposes it as its own first-class provider: `alibaba-coding-plan`. Endpoint: `https://coding-intl.dashscope.aliyuncs.com/v1`. It's OpenAI-compatible like the regular `alibaba` provider but with a different base URL and billing surface.

```yaml
model:
  provider: alibaba_coding     # alias for alibaba-coding-plan
  model: qwen3-coder-plus
```

Or from the CLI:

```bash
fabric chat --provider alibaba_coding --model qwen3-coder-plus
```

`alibaba_coding` uses the same `DASHSCOPE_API_KEY` your `alibaba` entry already uses — no separate key needed, just a different routing target. Before this provider was registered, users who set `provider: alibaba_coding` in `config.yaml` silently fell through to OpenRouter routing.

### MiniMax (OAuth)

MiniMax-M2.7 via browser OAuth login — no API key needed. Pick **MiniMax (OAuth)** in `fabric model`, sign in through the browser, and Fabric persists the access + refresh tokens. Uses the Anthropic Messages-compatible endpoint (`/anthropic`) under the hood.

```bash
fabric model
# → pick "MiniMax (OAuth)"
# → browser opens; sign in with your MiniMax account (global or CN region)
# → confirm — credentials are saved to ~/.fabric/auth.json

fabric chat   # uses api.minimax.io/anthropic endpoint
```

Or configure `config.yaml`:
```yaml
model:
  provider: "minimax-oauth"
  default: "MiniMax-M2.7"
```

Supported models: `MiniMax-M2.7` (main) and `MiniMax-M2.7-highspeed` (wired as the default auxiliary model). The OAuth path ignores `MINIMAX_API_KEY` / `MINIMAX_BASE_URL`.

:::tip MiniMax OAuth vs API key
`minimax-oauth` uses MiniMax's consumer-facing portal with OAuth login — no billing setup required. The `minimax` and `minimax-cn` providers use `MINIMAX_API_KEY` / `MINIMAX_CN_API_KEY` — for programmatic access. See the [MiniMax OAuth guide](/guides/minimax-oauth) for a full walkthrough.
:::

### NVIDIA NIM

Nemotron and other open-source models via [build.nvidia.com](https://build.nvidia.com) or a local NIM endpoint. Check NVIDIA's current access and billing terms before using the hosted endpoint.

```bash
# Cloud (build.nvidia.com)
fabric chat --provider nvidia --model nvidia/nemotron-3-super-120b-a12b
# Requires: NVIDIA_API_KEY in ~/.fabric/.env

# Local NIM endpoint — override base URL
NVIDIA_BASE_URL=http://localhost:8000/v1 fabric chat --provider nvidia --model nvidia/nemotron-3-super-120b-a12b
```

Or set it permanently in `config.yaml`:
```yaml
model:
  provider: "nvidia"
  default: "nvidia/nemotron-3-super-120b-a12b"
```

:::tip Local NIM
For on-prem deployments (DGX Spark, local GPU), set `NVIDIA_BASE_URL=http://localhost:8000/v1`. NIM exposes the same OpenAI-compatible chat completions API as build.nvidia.com, so switching between cloud and local is a one-line env-var change.
:::

Fabric automatically attaches the NIM billing-origin header on every request to `build.nvidia.com` — no configuration needed. This routes consumption against the correct origin in NVIDIA's billing dashboard.

### GMI Cloud

Open and reasoning models via [GMI Cloud](https://www.gmicloud.ai/) — OpenAI-compatible API, API key authentication.

```bash
# GMI Cloud
fabric chat --provider gmi --model deepseek-ai/DeepSeek-V3.2
# Requires: GMI_API_KEY in ~/.fabric/.env
```

Or set it permanently in `config.yaml`:
```yaml
model:
  provider: "gmi"
  default: "deepseek-ai/DeepSeek-V3.2"
```

The base URL can be overridden with `GMI_BASE_URL` (default: `https://api.gmi-serving.com/v1`).

### StepFun

Step-series models via [StepFun](https://platform.stepfun.com) — OpenAI-compatible API, API key authentication.

```bash
# StepFun
fabric chat --provider stepfun --model step-3.5-flash
# Requires: STEPFUN_API_KEY in ~/.fabric/.env
```

Or set it permanently in `config.yaml`:
```yaml
model:
  provider: "stepfun"
  default: "step-3.5-flash"
```

The base URL can be overridden with `STEPFUN_BASE_URL` (default: `https://api.stepfun.com/v1`).

### Hugging Face Inference Providers

[Hugging Face Inference Providers](https://huggingface.co/docs/inference-providers) routes supported open models through a unified OpenAI-compatible endpoint (`router.huggingface.co/v1`). Backend selection and failover are controlled by Hugging Face.

```bash
# Use any available model
fabric chat --provider huggingface --model Qwen/Qwen3.5-397B-A17B
# Requires: HF_TOKEN in ~/.fabric/.env

# Short alias
fabric chat --provider hf --model deepseek-ai/DeepSeek-V3.2
```

Or set it permanently in `config.yaml`:
```yaml
model:
  provider: "huggingface"
  default: "Qwen/Qwen3.5-397B-A17B"
```

Get your token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) and enable the "Make calls to Inference Providers" permission. Check Hugging Face's current pricing and quota documentation for your account.

You can append routing suffixes to model names: `:fastest` (default), `:cheapest`, or `:provider_name` to force a specific backend.

The base URL can be overridden with `HF_BASE_URL`.

## Custom & Self-Hosted LLM Providers

Fabric works with **any OpenAI-compatible API endpoint**. If a server implements `/v1/chat/completions`, you can point Fabric at it. This means you can use local models, GPU inference servers, multi-provider routers, or any third-party API.

### General Setup

Three ways to configure a custom endpoint:

**Interactive setup (recommended):**
```bash
fabric model
# Select "Custom endpoint (self-hosted / VLLM / etc.)"
# Enter: API base URL, API key, Model name
```

**Manual config (`config.yaml`):**
```yaml
# In ~/.fabric/config.yaml
model:
  default: your-model-name
  provider: custom
  base_url: http://localhost:8000/v1
  api_key: your-key-or-leave-empty-for-local
```

:::warning Legacy env vars
`LLM_MODEL` in `.env` is **removed** — `config.yaml` is the single source of truth for model and endpoint configuration. `OPENAI_BASE_URL` is still honored, but **only** for the `openai-api` provider (it overrides the OpenAI endpoint for direct API-key access). For other providers and custom endpoints, use `fabric model` or set `model.base_url` in `config.yaml` directly. If you have stale entries in your `.env`, they are automatically cleared on the next `fabric setup` or config migration.
:::

Both approaches persist to `config.yaml`, which is the source of truth for model, provider, and base URL.

### Switching Models with `/model`

:::warning fabric model vs /model
**`fabric model`** (run from your terminal, outside any chat session) is the **full provider setup wizard**. Use it to add new providers, run OAuth flows, enter API keys, and configure custom endpoints.

**`/model`** (typed inside an active Fabric chat session) can only **switch between providers and models you've already set up**. It cannot add new providers, run OAuth, or prompt for API keys. If you've only configured one provider (e.g. OpenRouter), `/model` will only show models for that provider.

**To add a new provider:** Exit your session (`Ctrl+C` or `/quit`), run `fabric model`, set up the new provider, then start a new session.
:::

Once you have at least one custom endpoint configured, you can switch models mid-session:

```
/model custom:qwen-2.5          # Switch to a model on your custom endpoint
/model custom                    # Auto-detect the model from the endpoint
/model openrouter:claude-sonnet-4 # Switch back to a cloud provider
```

If you have **named custom providers** configured (see below), use the triple syntax:

```
/model custom:local:qwen-2.5    # Use the "local" custom provider with model qwen-2.5
/model custom:work:llama3       # Use the "work" custom provider with llama3
```

When switching providers, Fabric persists the base URL and provider to config so the change survives restarts. When switching away from a custom endpoint to a built-in provider, the stale base URL is automatically cleared.

:::tip
`/model custom` (bare, no model name) queries your endpoint's `/models` API and auto-selects the model if exactly one is loaded. Useful for local servers running a single model.
:::

Everything below follows this same pattern — just change the URL, key, and model name.

---

### Ollama (Local) — First-Class Native Provider

[Ollama](https://ollama.com/) runs open-weight models locally. Fabric connects
through its keyless `ollama` provider, discovers `/api/tags`, reads readiness
metadata from `/api/show`, and translates the agent loop to native `/api/chat`.
This is distinct from both the `ollama-cloud` provider and the generic Custom
Endpoint flow. Tool calling still depends on the selected model and its Ollama
runtime/template; verify it with a real, reversible tool request after
connecting.

```bash
# Install and run a model
ollama pull qwen2.5-coder:32b
ollama serve   # Starts on port 11434
```

Then configure Fabric:

```bash
fabric -p local model
# Select "Ollama (Local)"
# Server root: http://127.0.0.1:11434
# Select an installed model from the native catalog
```

If no model is installed, the CLI offers a separately confirmed foreground
pull. Desktop first-run onboarding exposes **Ollama (native local)** directly;
later use **Settings → Providers → Local models**. The web **Models** page
has the same native card with an explicit **Refresh** action. Opening any picker
is probe-free; discovery begins only after the user chooses the provider or
presses Refresh.

Or configure `config.yaml` directly:

```yaml
model:
  default: qwen2.5-coder:32b
  provider: ollama
  base_url: http://127.0.0.1:11434
  context_length: 65536
  ollama_num_ctx: 65536

security:
  egress_mode: local_ai
  local_ai_allowed_cidrs: []
```

`local_ai` applies the profile's literal-address policy to primary inference,
model switching, auxiliary work, fallback, delegation, and MoA. It leaves
built-in memory active and blocks external-memory adapters. It is not a
whole-process offline mode: web/browser tools, MCP, plugins, arbitrary terminal
commands, gateways, updates, model downloads, and user-initiated OAuth/device
setup remain outside its boundary. Account setup can contact its remote
authorization service; inference-time auth resolution cannot contact that
remote identity plane.
See [Use a Local Ollama Model with Fabric](/guides/local-ollama-setup) for
private CIDRs, Docker networking, status/Doctor verification, and the honest
`air_gapped` unavailable state.

:::caution Verify the real context allocation
Fabric requires at least **64,000 tokens** of effective context for agent
use with tools. It reads the model's native metadata and explicit Modelfile
`num_ctx`, then refuses a confirmed smaller allocation instead of trusting a
larger catalog label.

**How to increase it** (pick one):

```bash
# Option 1: Set server-wide via environment variable (recommended)
OLLAMA_CONTEXT_LENGTH=64000 ollama serve

# Option 2: For systemd-managed Ollama
sudo systemctl edit ollama.service
# Add: Environment="OLLAMA_CONTEXT_LENGTH=64000"
# Then: sudo systemctl daemon-reload && sudo systemctl restart ollama

# Option 3: Bake it into a custom model (persistent per-model)
echo -e "FROM qwen2.5-coder:32b\nPARAMETER num_ctx 64000" > Modelfile
ollama create qwen2.5-coder-64k -f Modelfile
```

Fabric's native adapter sends the selected `model.ollama_num_ctx` as
`options.num_ctx` on `/api/chat`. The daemon, model, and available memory remain
authoritative: requesting a larger number cannot create capacity the runtime
does not have. A server-wide setting or Modelfile is the durable way to align
every client.
:::

**Verify your context is set correctly:**

```bash
ollama ps
# Look at the CONTEXT column — it should show your configured value
```

:::tip
List available models with `ollama list`. Pull any model from the [Ollama library](https://ollama.com/library) with `ollama pull <model>`. Ollama handles GPU offloading automatically — no configuration needed for most setups.
:::

---

### vLLM — High-Performance GPU Inference

[vLLM](https://docs.vllm.ai/) is the standard for production LLM serving. Best for: maximum throughput on GPU hardware, serving large models, continuous batching.

```bash
pip install vllm
vllm serve meta-llama/Llama-3.1-70B-Instruct \
  --port 8000 \
  --max-model-len 65536 \
  --tensor-parallel-size 2 \
  --enable-auto-tool-choice
```

Then configure Fabric:

```bash
fabric model
# Select "Custom endpoint (self-hosted / VLLM / etc.)"
# Enter URL: http://localhost:8000/v1
# Skip API key (or enter one if you configured vLLM with --api-key)
# Enter model name: meta-llama/Llama-3.1-70B-Instruct
```

**Context length:** vLLM reads the model's `max_position_embeddings` by default. If that exceeds your GPU memory, it errors and asks you to set `--max-model-len` lower. You can also use `--max-model-len auto` to automatically find the maximum that fits. Set `--gpu-memory-utilization 0.95` (default 0.9) to squeeze more context into VRAM.

**Tool calling requires explicit flags:**

| Flag | Purpose |
|------|---------|
| `--enable-auto-tool-choice` | Required for `tool_choice: "auto"` (the default in Fabric) |
| `--tool-call-parser <name>` | Parser for the model's tool call format |

Supported parsers include `llama3_json` (Llama 3.x), `mistral`, `deepseek_v3`, `deepseek_v31`, `xlam`, and `pythonic`. Without the parser required by your model, tool calls may be emitted as text.

**Qwen reasoning parsers:** Fabric preserves structured reasoning metadata such as `reasoning`, `reasoning_content`, and streamed reasoning deltas when OpenAI-compatible servers return them. That metadata is treated as reasoning/thinking trace data, not as a replacement for the assistant's visible answer. For Qwen reasoning models served by vLLM, make sure the final user-visible response still appears in `content`. If `--reasoning-parser qwen3` leaves `content` empty in your deployment, either disable that parser or pass a server-supported request option such as `chat_template_kwargs.enable_thinking: false` through `extra_body`.

:::tip
vLLM supports human-readable sizes: `--max-model-len 64k` (lowercase k = 1000, uppercase K = 1024).
:::

---

### SGLang — Fast Serving with RadixAttention

[SGLang](https://github.com/sgl-project/sglang) is an alternative to vLLM with RadixAttention for KV cache reuse. Best for: multi-turn conversations (prefix caching), constrained decoding, structured output.

```bash
pip install "sglang[all]"
python -m sglang.launch_server \
  --model meta-llama/Llama-3.1-70B-Instruct \
  --port 30000 \
  --context-length 65536 \
  --tp 2 \
  --tool-call-parser qwen
```

Then configure Fabric:

```bash
fabric model
# Select "Custom endpoint (self-hosted / VLLM / etc.)"
# Enter URL: http://localhost:30000/v1
# Enter model name: meta-llama/Llama-3.1-70B-Instruct
```

**Context length:** SGLang reads from the model's config by default. Use `--context-length` to override. If you need to exceed the model's declared maximum, set `SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1`.

**Tool calling:** Use `--tool-call-parser` with the appropriate parser for your model family: `qwen` (Qwen 2.5), `llama3`, `llama4`, `deepseekv3`, `mistral`, `glm`. Without this flag, tool calls come back as plain text.

:::caution SGLang defaults to 128 max output tokens
If responses seem truncated, add `max_tokens` to your requests or set `--default-max-tokens` on the server. SGLang's default is only 128 tokens per response if not specified in the request.
:::

---

### llama.cpp / llama-server — CPU & Metal Inference

[llama.cpp](https://github.com/ggml-org/llama.cpp) runs quantized models on CPU, Apple Silicon (Metal), and consumer GPUs. Best for: running models without a datacenter GPU, Mac users, edge deployment.

```bash
# Build and start llama-server
cmake -B build && cmake --build build --config Release
./build/bin/llama-server \
  --jinja -fa \
  -c 64000 \
  -ngl 99 \
  -m models/qwen2.5-coder-32b-instruct-Q4_K_M.gguf \
  --port 8080 --host 0.0.0.0
```

**Context length (`-c`):** Recent builds default to `0` which reads the model's training context from the GGUF metadata. For models with 128k+ training context, this can OOM trying to allocate the full KV cache. Set `-c` explicitly to at least 64,000 tokens for Fabric. If using parallel slots (`-np`), the total context is divided among slots — with `-c 64000 -np 4`, each slot only gets 16k, which is below Fabric's minimum per active session.

Then configure Fabric to point at it:

```bash
fabric model
# Select "Custom endpoint (self-hosted / VLLM / etc.)"
# Enter URL: http://localhost:8080/v1
# Skip API key (local servers don't need one)
# Enter model name — or leave blank to auto-detect if only one model is loaded
```

This saves the endpoint to `config.yaml` so it persists across sessions.

:::caution `--jinja` is required for tool calling
Without `--jinja`, llama-server ignores the `tools` parameter entirely. The model will try to call tools by writing JSON in its response text, but Fabric won't recognize it as a tool call — you'll see raw JSON like `{"name": "web_search", ...}` printed as a message instead of an actual search.

Native tool calling support (best performance) includes Llama 3.x, Qwen 2.5 (including Coder), Mistral, DeepSeek, and Functionary. Other models use a generic handler that may be less efficient. See the [llama.cpp function calling docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md) for the current list.

You can verify tool support is active by checking `http://localhost:8080/props` — the `chat_template` field should be present.
:::

:::tip
Download GGUF models from [Hugging Face](https://huggingface.co/models?library=gguf). Q4_K_M quantization offers the best balance of quality vs. memory usage.
:::

---

### LM Studio — Desktop App with Local Models

[LM Studio](https://lmstudio.ai/) is a desktop app for running local models with a GUI. Best for: users who prefer a visual interface, quick model testing, developers on macOS/Windows/Linux.

Start the server from the LM Studio app (Developer tab → Start Server), or use the CLI:

```bash
lms server start                        # Starts on port 1234
lms load qwen2.5-coder --context-length 64000
```

Then configure Fabric:

```bash
fabric model
# Select "LM Studio"
# Press Enter to use http://localhost:1234/v1
# Pick one of the discovered models
# If LM Studio server auth is enabled, enter LM_API_KEY when prompted
```

Fabric will automatically load a LM Studio model with 64K context length

To change context length in LM Studio:

1. Click the gear icon next to the model picker
2. Set "Context Length" to at least 64000 for a smooth experience
3. Reload the model for the change to take effect
4. If your machine cannot fit 64000, consider using a smaller model with larger context lengths.

Alternatively, use the CLI: `lms load model-name --context-length 64000`

You can use the CLI to estimate if the model will fit: `lms load model-name --context-length 64000 --estimate-only`

To set persistent per-model defaults: My Models tab → gear icon on the model → set context size.
:::

**Tool calling:** Supported since LM Studio 0.3.6. Models with native tool-calling training (Qwen 2.5, Llama 3.x, Mistral, Fabric) are auto-detected and shown with a tool badge. Other models use a generic fallback that may be less reliable.

---

### WSL2 Networking (Windows Users)

Since Fabric requires a Unix environment, Windows users run it inside WSL2. If your model server (Ollama, LM Studio, etc.) runs on the **Windows host**, you need to bridge the network gap — WSL2 uses a virtual network adapter with its own subnet, so `localhost` inside WSL2 refers to the Linux VM, **not** the Windows host.

:::tip Both in WSL2? No problem.
If your model server also runs inside WSL2 (common for vLLM, SGLang, and llama-server), `localhost` works as expected — they share the same network namespace. Skip this section.
:::

#### Option 1: Mirrored Networking Mode (Recommended)

Available on **Windows 11 22H2+**, mirrored mode makes `localhost` work bidirectionally between Windows and WSL2 — the simplest fix.

1. Create or edit `%USERPROFILE%\.wslconfig` (e.g., `C:\Users\YourName\.wslconfig`):
   ```ini
   [wsl2]
   networkingMode=mirrored
   ```

2. Restart WSL from PowerShell:
   ```powershell
   wsl --shutdown
   ```

3. Reopen your WSL2 terminal. `localhost` now reaches Windows services:
   ```bash
   curl http://localhost:11434/v1/models   # Ollama on Windows — works
   ```

:::note Hyper-V Firewall
On some Windows 11 builds, the Hyper-V firewall blocks mirrored connections by default. If `localhost` still doesn't work after enabling mirrored mode, run this in an **Admin PowerShell**:
```powershell
Set-NetFirewallHyperVVMSetting -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -DefaultInboundAction Allow
```
:::

#### Option 2: Use the Windows Host IP (Windows 10 / older builds)

If you can't use mirrored mode, find the Windows host IP from inside WSL2 and use that instead of `localhost`:

```bash
# Get the Windows host IP (the default gateway of WSL2's virtual network)
ip route show | grep -i default | awk '{ print $3 }'
# Example output: 172.29.192.1
```

Use that IP in your Fabric config:

```yaml
model:
  default: qwen2.5-coder:32b
  provider: custom
  base_url: http://172.29.192.1:11434/v1   # Windows host IP, not localhost
```

:::tip Dynamic helper
The host IP can change on WSL2 restart. You can grab it dynamically in your shell:
```bash
export WSL_HOST=$(ip route show | grep -i default | awk '{ print $3 }')
echo "Windows host at: $WSL_HOST"
curl http://$WSL_HOST:11434/v1/models   # Test Ollama
```

Or use your machine's mDNS name (requires `libnss-mdns` in WSL2):
```bash
sudo apt install libnss-mdns
curl http://$(hostname).local:11434/v1/models
```
:::

#### Server Bind Address (Required for NAT Mode)

If you're using **Option 2** (NAT mode with the host IP), the model server on Windows must accept connections from outside `127.0.0.1`. By default, most servers only listen on localhost — WSL2 connections in NAT mode come from a different virtual subnet and will be refused. In mirrored mode, `localhost` maps directly so the default `127.0.0.1` binding works fine.

| Server | Default bind | How to fix |
|--------|-------------|------------|
| **Ollama** | `127.0.0.1` | Set `OLLAMA_HOST=0.0.0.0` environment variable before starting Ollama (System Settings → Environment Variables on Windows, or edit the Ollama service) |
| **LM Studio** | `127.0.0.1` | Enable **"Serve on Network"** in the Developer tab → Server settings |
| **llama-server** | `127.0.0.1` | Add `--host 0.0.0.0` to the startup command |
| **vLLM** | `0.0.0.0` | Already binds to all interfaces by default |
| **SGLang** | `127.0.0.1` | Add `--host 0.0.0.0` to the startup command |

**Ollama on Windows (detailed):** Ollama runs as a Windows service. To set `OLLAMA_HOST`:
1. Open **System Properties** → **Environment Variables**
2. Add a new **System variable**: `OLLAMA_HOST` = `0.0.0.0`
3. Restart the Ollama service (or reboot)

#### Windows Firewall

Windows Firewall treats WSL2 as a separate network (in both NAT and mirrored mode). If connections still fail after the steps above, add a firewall rule for your model server's port:

```powershell
# Run in Admin PowerShell — replace PORT with your server's port
New-NetFirewallRule -DisplayName "Allow WSL2 to Model Server" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 11434
```

Common ports: Ollama `11434`, vLLM `8000`, SGLang `30000`, llama-server `8080`, LM Studio `1234`.

#### Quick Verification

From inside WSL2, test that you can reach your model server:

```bash
# Replace URL with your server's address and port
curl http://localhost:11434/v1/models          # Mirrored mode
curl http://172.29.192.1:11434/v1/models       # NAT mode (use your actual host IP)
```

If you get a JSON response listing your models, you're good. Use that same URL as the `base_url` in your Fabric config.

---

### Troubleshooting Local Models

These issues affect **all** local inference servers when used with Fabric.

#### "Connection refused" from WSL2 to a Windows-hosted model server

If you're running Fabric inside WSL2 and your model server on the Windows host, `http://localhost:<port>` won't work in WSL2's default NAT networking mode. See [WSL2 Networking](#wsl2-networking-windows-users) above for the fix.

#### Tool calls appear as text instead of executing

The model outputs something like `{"name": "web_search", "arguments": {...}}` as a message instead of actually calling the tool.

**Cause:** Your server doesn't have tool calling enabled, or the model doesn't support it through the server's tool calling implementation.

| Server | Fix |
|--------|-----|
| **llama.cpp** | Add `--jinja` to the startup command |
| **vLLM** | Enable automatic tool choice and configure the parser documented by vLLM for your model |
| **SGLang** | Add `--tool-call-parser qwen` (or appropriate parser) |
| **Ollama** | Tool-call behavior depends on the selected model and its runtime/template; verify it with a real tool request after connecting. |
| **LM Studio** | Update to 0.3.6+ and use a model with native tool support |

#### Model seems to forget context or give incoherent responses

**Cause:** Context window is too small. When the conversation exceeds the context limit, most servers silently drop older messages. Fabric's system prompt + tool schemas alone can use 4k–8k tokens.

**Diagnosis:**

```bash
# Check what Fabric thinks the context is
# Look at startup line: "Context limit: X tokens"

# Check your server's actual context
# Ollama: ollama ps (CONTEXT column)
# llama.cpp: curl http://localhost:8080/props | jq '.default_generation_settings.n_ctx'
# vLLM: check --max-model-len in startup args
```

**Fix:** Set context to at least **64,000 tokens** for agent use. See each server's section above for the specific flag.

#### "Context limit: 2048 tokens" at startup

Fabric auto-detects context length from your server's `/v1/models` endpoint. If the server reports a low value (or doesn't report one at all), Fabric uses the model's declared limit which may be wrong.

**Fix:** Set it explicitly in `config.yaml`:

```yaml
model:
  default: your-model
  provider: custom
  base_url: http://localhost:11434/v1
  context_length: 64000
```

#### Responses get cut off mid-sentence

**Possible causes:**
1. **Low output cap (`max_tokens`) on the server** — SGLang defaults to 128 tokens per response. Set `--default-max-tokens` on the server or configure Fabric with `model.max_tokens` in config.yaml. Note: `max_tokens` controls response length only — it is unrelated to how long your conversation history can be (that is `context_length`).
2. **Context exhaustion** — The model filled its context window. Increase `model.context_length` or enable [context compression](/user-guide/configuration#context-compression) in Fabric.

---

### LiteLLM Proxy — Multi-Provider Gateway

[LiteLLM](https://docs.litellm.ai/) is an OpenAI-compatible proxy that presents multiple LLM providers behind a single API. It is useful for switching providers without Fabric config changes, load balancing, fallback chains, and budget controls.

```bash
# Install and start
pip install "litellm[proxy]"
litellm --model anthropic/claude-sonnet-4 --port 4000

# Or with a config file for multiple models:
litellm --config litellm_config.yaml --port 4000
```

Then configure Fabric with `fabric model` → Custom endpoint → `http://localhost:4000/v1`.

Example `litellm_config.yaml` with fallback:
```yaml
model_list:
  - model_name: "best"
    litellm_params:
      model: anthropic/claude-sonnet-4
      api_key: sk-ant-...
  - model_name: "best"
    litellm_params:
      model: openai/gpt-4o
      api_key: sk-...
router_settings:
  routing_strategy: "latency-based-routing"
```

---

### ClawRouter — Cost-Optimized Routing

[ClawRouter](https://github.com/BlockRunAI/ClawRouter) by BlockRunAI is a third-party routing proxy that selects models based on query complexity. Fabric connects to it as an OpenAI-compatible endpoint; routing behavior, model availability, and payment requirements are controlled by ClawRouter.

```bash
# Install and start
npx @blockrun/clawrouter    # Starts on port 8402
```

Then configure Fabric with `fabric model` → Custom endpoint → `http://localhost:8402/v1` → model name `blockrun/auto`.

Routing profiles:
| Profile | Routing intent |
|---------|----------------|
| `blockrun/auto` | Balance capability and cost |
| `blockrun/eco` | Prioritize lower-cost routes |
| `blockrun/premium` | Prioritize higher-capability routes |
| `blockrun/free` | Prefer eligible no-cost routes when available |
| `blockrun/agentic` | Prioritize models suited to tool use |

:::note
ClawRouter is not a local-inference privacy boundary: requests pass through BlockRun's service. Review its current funding, network, and account requirements, then run `npx @blockrun/clawrouter doctor` to validate your setup.
:::

---

### Other Compatible Providers

Any service with an OpenAI-compatible API works. Some popular options:

| Provider | Base URL | Notes |
|----------|----------|-------|
| [Together AI](https://together.ai) | `https://api.together.xyz/v1` | Cloud-hosted open models |
| [Groq](https://groq.com) | `https://api.groq.com/openai/v1` | Ultra-fast inference |
| [DeepSeek](https://deepseek.com) | `https://api.deepseek.com/v1` | DeepSeek models |
| [Fireworks AI](https://fireworks.ai) | `https://api.fireworks.ai/inference/v1` | Fast open model hosting |
| [GMI Cloud](https://www.gmicloud.ai/) | `https://api.gmi-serving.com/v1` | Managed OpenAI-compatible inference |
| [Cerebras](https://cerebras.ai) | `https://api.cerebras.ai/v1` | Wafer-scale chip inference |
| [Mistral AI](https://mistral.ai) | `https://api.mistral.ai/v1` | Mistral models |
| [OpenAI](https://openai.com) | `https://api.openai.com/v1` | Direct OpenAI access |
| [Azure OpenAI](https://azure.microsoft.com) | `https://YOUR.openai.azure.com/` | Enterprise OpenAI |
| [LocalAI](https://localai.io) | `http://localhost:8080/v1` | Self-hosted, multi-model |
| [Jan](https://jan.ai) | `http://localhost:1337/v1` | Desktop app with local models |

Configure any of these with `fabric model` → Custom endpoint, or in `config.yaml`:

```yaml
model:
  default: meta-llama/Llama-3.1-70B-Instruct-Turbo
  provider: custom
  base_url: https://api.together.xyz/v1
  api_key: your-together-key
```

---

### Context Length Detection

:::note Two settings, easy to confuse
**`context_length`** is the **total context window** — the combined budget for input *and* output tokens (e.g. 200,000 for Claude Opus 4.6). Fabric uses this to decide when to compress history and to validate API requests.

**`model.max_tokens`** is the **output cap** — the maximum number of tokens the model may generate in a *single response*. It has nothing to do with how long your conversation history can be. The industry-standard name `max_tokens` is a common source of confusion; Anthropic's native API has since renamed it `max_output_tokens` for clarity.

Set `context_length` when auto-detection gets the window size wrong.
Set `model.max_tokens` only when you need to limit how long individual responses can be.
:::

Fabric uses a multi-source resolution chain to detect the correct context window for your model and provider:

1. **Config override** — `model.context_length` in config.yaml (highest priority)
2. **Custom provider per-model** — `custom_providers[].models.<id>.context_length`
3. **Persistent cache** — previously discovered values (survives restarts)
4. **Endpoint `/models`** — queries your server's API (local/custom endpoints)
5. **Anthropic `/v1/models`** — queries Anthropic's API for `max_input_tokens` (API-key users only)
6. **OpenRouter API** — live model metadata from OpenRouter
7. **Provider-specific metadata** — used when a built-in provider exposes compatible model metadata
8. **[models.dev](https://models.dev)** — community-maintained registry with provider-specific context lengths
9. **Fallback defaults** — broad model-family patterns

For most setups this works out of the box. The system is provider-aware: the same model ID can have different context limits depending on the service that hosts it.

To set the context length explicitly, add `context_length` to your model config:

```yaml
model:
  default: "qwen3.5:9b"
  base_url: "http://localhost:8080/v1"
  context_length: 131072  # tokens
```

For custom endpoints, you can also set context length per model:

```yaml
custom_providers:
  - name: "My Local LLM"
    base_url: "http://localhost:11434/v1"
    models:
      qwen3.5:27b:
        context_length: 64000
      deepseek-r1:70b:
        context_length: 65536
```

`fabric model` will prompt for context length when configuring a custom endpoint. Leave it blank for auto-detection.

:::tip When to set this manually
- You're using Ollama with a custom `num_ctx` that's lower than the model's maximum
- You want to limit context below the model's maximum (e.g., 8k on a 128k model to save VRAM)
- You're running behind a proxy that doesn't expose `/v1/models`
:::

---

### Named Custom Providers

If you work with multiple custom endpoints (e.g., a local dev server and a remote GPU server), you can define them as named custom providers in `config.yaml`:

```yaml
custom_providers:
  - name: local
    base_url: http://localhost:8080/v1
    # api_key omitted — Fabric uses "no-key-required" for keyless local servers
  - name: work
    base_url: https://gpu-server.internal.corp/v1
    key_env: CORP_API_KEY
    api_mode: chat_completions   # set explicitly by `fabric model` → Custom Endpoint wizard; auto-detection still happens as a fallback
  - name: anthropic-proxy
    base_url: https://proxy.example.com/anthropic
    key_env: ANTHROPIC_PROXY_KEY
    api_mode: anthropic_messages  # for Anthropic-compatible proxies
```

Some OpenAI-compatible endpoints need provider-specific request body fields. Add an `extra_body` map to the matching custom provider and Fabric will merge it into each chat-completions request for that endpoint:

```yaml
custom_providers:
  - name: gemma-local
    base_url: http://localhost:8080/v1
    model: google/gemma-4-31b-it
    extra_body:
      enable_thinking: true
      reasoning_effort: high
```

Use the shape your server documents. For example, vLLM Gemma deployments and some NVIDIA NIM endpoints expect `enable_thinking` under `chat_template_kwargs` instead of as a top-level `extra_body` field:

```yaml
extra_body:
  chat_template_kwargs:
    enable_thinking: true
```

For Qwen reasoning models served by vLLM, this same shape can be used to disable thinking when a reasoning parser separates all generated text into reasoning fields and leaves the assistant `content` empty:

```yaml
extra_body:
  chat_template_kwargs:
    enable_thinking: false
```

The `fabric model` → Custom Endpoint wizard now prompts for `api_mode` explicitly and persists your answer to `config.yaml`. URL-based auto-detection (e.g. `/anthropic` paths → `anthropic_messages`) still happens as a fallback when the field is left blank.

**Native vision for custom-provider models.** If your custom endpoint serves a vision-capable model that isn't in models.dev, set `model.supports_vision: true` so Fabric routes attached images natively (as `image_url` parts) instead of pre-processing them through `vision_analyze`. Single knob — no need to also set `agent.image_input_mode: native`.

```yaml
model:
  provider: custom
  base_url: http://localhost:8080/v1
  default: qwen3.6-35b-a3b
  supports_vision: true   # send images natively; otherwise vision_analyze pre-describes them
```

The same key is honored on per-named-provider models (`custom_providers[*].models[*].supports_vision`) and accepts standard YAML booleans (`true/false/yes/no/on/off/1/0`).

Switch between them mid-session with the triple syntax:

```
/model custom:local:qwen-2.5       # Use the "local" endpoint with qwen-2.5
/model custom:work:llama3-70b      # Use the "work" endpoint with llama3-70b
/model custom:anthropic-proxy:claude-sonnet-4  # Use the proxy
```

You can also select named custom providers from the interactive `fabric model` menu.

---

### Cookbook: Together AI, Groq, Perplexity

The cloud providers listed in [Other Compatible Providers](#other-compatible-providers) all speak OpenAI's REST dialect, so they wire up the same way under `custom_providers:`. Three worked recipes follow. Each drops into `~/.fabric/config.yaml` and the matching API key goes in `~/.fabric/.env`.

#### Together AI

Hosts open-weight models (Llama, MiniMax, Gemma, DeepSeek, Qwen) at prices significantly below first-party APIs. Good default for multi-model fleets.

```yaml
# ~/.fabric/config.yaml
custom_providers:
  - name: together
    base_url: https://api.together.xyz/v1
    key_env: TOGETHER_API_KEY
    # api_mode: chat_completions  # default — no need to set

model:
  default: MiniMaxAI/MiniMax-M2.7   # or any model from together.ai/models
  provider: custom:together
```

```bash
# ~/.fabric/.env
TOGETHER_API_KEY=your-together-key
```

Switch models mid-session:

```
/model custom:together:meta-llama/Llama-3.3-70B-Instruct-Turbo
/model custom:together:google/gemma-4-31b-it
/model custom:together:deepseek-ai/DeepSeek-V3
```

Together's `/v1/models` endpoint works, so `fabric model` can auto-discover available models.

#### Groq

Cloud-hosted inference optimized for low-latency interactive use. Available models and actual throughput vary by region, account tier, and service load.

```yaml
# ~/.fabric/config.yaml
custom_providers:
  - name: groq
    base_url: https://api.groq.com/openai/v1
    key_env: GROQ_API_KEY

model:
  default: llama-3.3-70b-versatile
  provider: custom:groq
```

```bash
# ~/.fabric/.env
GROQ_API_KEY=your-groq-key
```

#### Perplexity

Useful when you want a model that does live web search and citation automatically. Strict about which models are available — check [perplexity.ai/settings/api](https://www.perplexity.ai/settings/api) for the current list.

```yaml
# ~/.fabric/config.yaml
custom_providers:
  - name: perplexity
    base_url: https://api.perplexity.ai
    key_env: PERPLEXITY_API_KEY

model:
  default: sonar
  provider: custom:perplexity
```

```bash
# ~/.fabric/.env
PERPLEXITY_API_KEY=your-perplexity-key
```

#### Multiple providers in one config

The three recipes compose — use all of them together and switch per turn with `/model custom:<name>:<model>`:

```yaml
custom_providers:
  - name: together
    base_url: https://api.together.xyz/v1
    key_env: TOGETHER_API_KEY
  - name: groq
    base_url: https://api.groq.com/openai/v1
    key_env: GROQ_API_KEY
  - name: perplexity
    base_url: https://api.perplexity.ai
    key_env: PERPLEXITY_API_KEY

model:
  default: MiniMaxAI/MiniMax-M2.7
  provider: custom:together      # boot to Together; switch freely after
```

:::tip Troubleshooting
- Run `fabric doctor` after setup. An `Unknown provider` warning usually means the configured provider name does not match the name under `custom_providers:`.
- If a provider's `/v1/models` endpoint is unreachable, `fabric model` can save the model with a warning. Confirm the model ID against the provider's current catalog before starting a session.
- Prefer named `custom_providers:` entries in `config.yaml` for repeatable setups. The legacy bare `provider: custom` plus `CUSTOM_BASE_URL` path remains available for compatibility.
:::

---

### Choosing the Right Setup

| Use Case | Recommended |
|----------|-------------|
| **Guided hosted setup** | `fabric model`, then choose an available API-key or account-login provider |
| **Local models, easy setup** | Ollama |
| **Production GPU serving** | vLLM or SGLang |
| **Mac / no GPU** | Ollama or llama.cpp |
| **Multi-provider routing** | LiteLLM Proxy or OpenRouter |
| **Cost optimization** | ClawRouter or OpenRouter with `sort: "price"` |
| **Maximum privacy** | Ollama, vLLM, or llama.cpp (fully local) |
| **Enterprise / Azure** | Azure OpenAI with custom endpoint |
| **Chinese AI models** | z.ai (GLM), Kimi/Moonshot (`kimi-coding` or `kimi-coding-cn`), MiniMax, Xiaomi MiMo, or Tencent TokenHub (first-class providers) |

:::tip
You can switch between providers at any time with `fabric model` — no restart required. Your conversation history, memory, and skills carry over regardless of which provider you use.
:::

## Optional API Keys

| Feature | Provider | Env Variable |
|---------|----------|--------------|
| Web scraping | [Firecrawl](https://firecrawl.dev/) | `FIRECRAWL_API_KEY`, `FIRECRAWL_API_URL` |
| Browser automation | [Browserbase](https://browserbase.com/) | `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID` |
| Image generation | [FAL](https://fal.ai/) | `FAL_KEY` |
| Premium TTS voices | [ElevenLabs](https://elevenlabs.io/) | `ELEVENLABS_API_KEY` |
| OpenAI TTS + voice transcription | [OpenAI](https://platform.openai.com/api-keys) | `VOICE_TOOLS_OPENAI_KEY` |
| Mistral TTS + voice transcription | [Mistral](https://console.mistral.ai/) | `MISTRAL_API_KEY` |
| Cross-session user modeling | [Honcho](https://honcho.dev/) | `HONCHO_API_KEY` |
| Semantic long-term memory | [Supermemory](https://supermemory.ai) | `SUPERMEMORY_API_KEY` |

### Self-Hosting Firecrawl

By default, Fabric uses the [Firecrawl cloud API](https://firecrawl.dev/) for web search and scraping. If you prefer to run Firecrawl locally, you can point Fabric at a self-hosted instance instead. See Firecrawl's [SELF_HOST.md](https://github.com/firecrawl/firecrawl/blob/main/SELF_HOST.md) for complete setup instructions.

**What you get:** No API key required, no rate limits, no per-page costs, full data sovereignty.

**What you lose:** The cloud version uses Firecrawl's proprietary "Fire-engine" for advanced anti-bot bypassing (Cloudflare, CAPTCHAs, IP rotation). Self-hosted uses basic fetch + Playwright, so some protected sites may fail. Search uses DuckDuckGo instead of Google.

**Setup:**

1. Clone and start the Firecrawl Docker stack (5 containers: API, Playwright, Redis, RabbitMQ, PostgreSQL — requires ~4-8 GB RAM):
   ```bash
   git clone https://github.com/firecrawl/firecrawl
   cd firecrawl
   # In .env, set: USE_DB_AUTHENTICATION=false, HOST=0.0.0.0, PORT=3002
   docker compose up -d
   ```

2. Point Fabric at your instance (no API key needed):
   ```bash
   fabric config set FIRECRAWL_API_URL http://localhost:3002
   ```

You can also set both `FIRECRAWL_API_KEY` and `FIRECRAWL_API_URL` if your self-hosted instance has authentication enabled.

## OpenRouter Provider Routing

When using OpenRouter, you can control how requests are routed across providers. Add a `provider_routing` section to `~/.fabric/config.yaml`:

```yaml
provider_routing:
  sort: "throughput"          # "price" (default), "throughput", or "latency"
  # only: ["anthropic"]      # Only use these providers
  # ignore: ["deepinfra"]    # Skip these providers
  # order: ["anthropic", "google"]  # Try providers in this order
  # require_parameters: true  # Only use providers that support all request params
  # data_collection: "deny"   # Exclude providers that may store/train on data
```

**Shortcuts:** Append `:nitro` to any model name for throughput sorting (e.g., `anthropic/claude-sonnet-4:nitro`), or `:floor` for price sorting.

## OpenRouter Pareto Code Router

OpenRouter exposes an experimental coding-model router at `openrouter/pareto-code`. It uses an external coding score and price data to select a route; its model pool and selection behavior can change as those inputs change. Pick this model and tune the `min_coding_score` knob in `~/.fabric/config.yaml`:

```yaml
model:
  provider: openrouter
  model: openrouter/pareto-code

openrouter:
  min_coding_score: 0.65   # 0.0–1.0; higher = stronger (more expensive) coders. Default 0.65.
```

Notes:

- `min_coding_score` is **only** sent when `model.model` is `openrouter/pareto-code`. On any other model the value is a no-op.
- Set to empty string (or remove the line) to let OpenRouter pick the strongest available coder — its documented behavior when the plugins block is omitted.
- Selection is deterministic per score on a given day, but the actual model chosen can shift as the Pareto frontier moves (new models, benchmark updates).
- See OpenRouter's [Pareto Router docs](https://openrouter.ai/docs/guides/routing/routers/pareto-router) for the full router behavior.
- To use the Pareto Code router for a specific **auxiliary task** (compression, vision, etc.) instead of the main agent, set `extra_body.plugins` under that task — see [Auxiliary Models → OpenRouter routing & Pareto Code for auxiliary tasks](/user-guide/configuration#openrouter-routing--pareto-code-for-auxiliary-tasks).

## Fallback Providers

Configure a chain of backup providers Fabric tries in order when the primary model fails (rate limits, server errors, auth failures). The canonical format is a top-level `fallback_providers:` list:

```yaml
fallback_providers:
  - provider: openrouter
    model: anthropic/claude-sonnet-4
  - provider: anthropic
    model: claude-sonnet-4
    # base_url: http://localhost:8000/v1    # optional, for custom endpoints
    # api_mode: chat_completions           # optional override
```

The legacy single-pair `fallback_model:` dict is still accepted for back-compat:

```yaml
fallback_model:
  provider: openrouter
  model: anthropic/claude-sonnet-4
```

When activated, the fallback swaps the model and provider mid-session without losing your conversation. The chain is tried entry-by-entry; activation is one-shot per session.

Use provider identifiers shown by `fabric model` for your installed version. Built-in catalogs and account-backed model availability can change between releases; named custom providers are also valid fallback targets.

:::tip
Fallback is configured exclusively through `config.yaml` — or interactively via `fabric fallback`. For full details on when it triggers, how the chain advances, and how it interacts with auxiliary tasks and delegation, see [Fallback Providers](/user-guide/features/fallback-providers).
:::

---

## See Also

- [Configuration](/user-guide/configuration) — General configuration (directory structure, config precedence, terminal backends, memory, compression, and more)
- [Environment Variables](/reference/environment-variables) — Complete reference of all environment variables
