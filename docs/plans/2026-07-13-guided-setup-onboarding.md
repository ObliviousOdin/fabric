# SETUP-QR: Guided QR and Click-to-Connect Onboarding

> **Status:** DONE_WITH_CONCERNS — implemented and automated verification complete; physical cross-platform QR scans remain manual follow-up
> **Author:** Codex
> **Date:** 2026-07-13
> **Branch:** main

## Problem

Fabric's setup experience exposes the right capabilities but makes several common paths feel unrelated and fragile. Firecrawl can persist an unusable backend when its credential prompt is cancelled, fresh Web setup defaults to self-hosted Firecrawl, Codex/xAI device-code login prints links without a shared QR treatment, `fabric setup tts` omits Piper because it uses a second provider catalog, and there is no guided Tailscale enrollment path.

## Solution

Provide one trusted-link presentation primitive for QR/click onboarding, make provider activation transactional, add an opt-in Tailscale setup section backed by Tailscale's official QR login, connect Firecrawl through its official browser login with a manual-key fallback, and make standalone TTS setup use the canonical provider catalog with safe Piper CUDA detection.

## Acceptance Criteria

- [x] `git status --branch` shows the latest `origin/main` merge incorporated without dropping the checkout's existing local commits.
- [x] `fabric setup tailscale` detects already-connected machines, otherwise invokes the official Tailscale QR login, and verifies the connected state.
- [x] A first-time guided setup may offer Tailscale, defaults to declining, and never changes routes, Tailscale SSH, Funnel, exit nodes, tags, or ACLs.
- [x] Codex and xAI device-code flows show a scannable QR code, the exact trusted URL, and the user code; a local graphical session may also open the link.
- [x] Firecrawl setup offers official browser login first and manual API-key entry second, disables official CLI telemetry, and only activates Firecrawl after a credential is available.
- [x] Cancelling any keyed provider setup leaves its previous provider/backend selection unchanged.
- [x] Fresh Web setup defaults to an explicit `Automatic (recommended)` row and never activates self-hosted Firecrawl just because Enter was pressed.
- [x] `fabric setup tts` uses the same provider catalog as `fabric tools`, including Piper, MiniMax, NeuTTS, xAI OAuth, and all existing providers.
- [x] Selecting Piper installs an exact reviewed package version and sets `tts.piper.use_cuda: true` only when `CUDAExecutionProvider` is actually available.
- [x] Web and desktop device-code screens render the verification URL as a QR code without changing the polling protocol.
- [x] Existing URL/code fallbacks still work when QR rendering, browser opening, Node/npm, or graphical display support is unavailable.
- [x] Focused Python, web, and desktop tests pass; TypeScript typechecking passes for changed UI packages.

## Constraints

- Do NOT add a core model tool or mutate the model tool schema.
- Do NOT put behavioral Tailscale, Firecrawl URL, or TTS acceleration settings in `.env`; `.env` remains credential-only.
- Do NOT store Tailscale auth keys, node keys, or control-plane state in Fabric config.
- Do NOT run `tailscale up` flags that enable SSH, routes, exit nodes, Funnel, Serve, tags, or ACL changes.
- Do NOT auto-install Tailscale through a remote shell script or bypass OS privilege/system-extension prompts.
- Do NOT treat Codex ChatGPT sign-in or xAI account OAuth as equivalent to an OpenAI/xAI developer API key.
- Do NOT silently select a paid provider because a credential exists; provider choice remains explicit.
- Do NOT run `firecrawl init`, `setup skills`, or `setup defaults`; those commands modify unrelated coding-agent installations.
- Do NOT allow Firecrawl CLI telemetry during Fabric-managed login; set `FIRECRAWL_NO_TELEMETRY=1` in the child process.
- Do NOT install `onnxruntime-gpu` automatically or replace an existing ONNX Runtime package. Only consume an already-reported CUDA provider.
- Must preserve macOS, Linux, Windows, SSH/headless, WSL, and container fallbacks.
- Must preserve per-conversation prompt caching; all changes stay in setup/auth/UI surfaces.

## Runtime Modes

| Mode | Behavior | Notes |
|---|---|---|
| Local interactive CLI | Render QR + exact URL; open a browser when safe | Main setup path |
| SSH/headless CLI | Render QR + exact URL; never attempt a graphical browser | Phone-first path |
| Container/WSL | Print platform-specific install guidance; run a detected host-visible CLI only | No privileged install automation |
| Dashboard web UI | Render device URL QR inside the existing OAuth modal | Existing backend polling remains authoritative |
| Electron desktop | Render QR beside the existing code/link and open external URLs through the existing guarded action | No dependency on dashboard frontend |
| Non-interactive/CI | Existing `--non-interactive` guidance remains; no login subprocess or prompt starts | Setup exits without mutation |

For every device-code screen, closing/unmounting the screen keeps the existing session-cancel and poll-timer cleanup. QR generation is derived UI state and owns no network resource.

## Technical Context

### Current setup flow

1. `fabric setup` parses six section names in `fabric_cli/subcommands/setup.py:19-31`.
2. Section dispatch uses `SETUP_SECTIONS` and persists config after the selected function returns in `fabric_cli/setup.py:2700-2707` and `fabric_cli/setup.py:2860-2883`.
3. The first-time guided path configures model, local terminal, messaging, and tools in `fabric_cli/setup.py:2973-3039`.
4. Standalone TTS uses a duplicate hard-coded provider picker in `fabric_cli/setup.py:1024-1269`; the canonical tool catalog already contains Piper in `fabric_cli/tools_config.py:245-327`.
5. Provider setup writes the provider/backend before collecting credentials in `fabric_cli/tools_config.py:3545-3566`, then accepts an empty prompt in `fabric_cli/tools_config.py:3632-3654`.
6. Fresh provider selection falls back to index zero in `fabric_cli/tools_config.py:3038-3052`; for Web that currently resolves to Firecrawl Self-Hosted.
7. Firecrawl's cloud schema points at general documentation and suggests blank means self-hosted in `plugins/web/firecrawl/provider.py:602-617`, despite self-hosting being a separate picker row.
8. xAI and Codex already implement real device-code polling in `fabric_cli/auth.py:7546-7583` and `fabric_cli/auth.py:7678-7711`; only presentation is inconsistent.
9. Web and desktop already receive `verification_url` and `user_code`, so QR rendering does not require a new RPC or auth protocol.

### Key files

| File | Role |
|---|---|
| `fabric_cli/setup_links.py` | New terminal URL/QR presentation helper with plain-link fallback |
| `fabric_cli/tailscale_setup.py` | New official-CLI discovery, QR login, status parsing, and guidance |
| `fabric_cli/subcommands/setup.py:19-31` | Adds the `tailscale` section to parser help/choices |
| `fabric_cli/setup.py:1024-1269` | Replaces stale standalone TTS picker with canonical tool catalog |
| `fabric_cli/setup.py:2700-2707` | Registers standalone Tailscale setup |
| `fabric_cli/setup.py:2973-3039` | Adds optional first-time Tailscale offer |
| `fabric_cli/tools_config.py:245-327` | Canonical TTS providers and Piper setup metadata |
| `fabric_cli/tools_config.py:3038-3052` | Active/default provider choice |
| `fabric_cli/tools_config.py:3396-3661` | Provider config write and credential transaction boundary |
| `plugins/web/firecrawl/provider.py:602-617` | Cloud Firecrawl setup metadata |
| `plugins/browser/firecrawl/provider.py:158-170` | Browser Firecrawl setup metadata |
| `fabric_cli/auth.py:7546-7583` | xAI device flow presentation/polling |
| `fabric_cli/auth.py:7678-7711` | Codex device flow presentation/polling |
| `web/src/components/OAuthLoginModal.tsx:149-170` | Web device-flow challenge state |
| `web/src/components/OAuthLoginModal.tsx:696-740` | Web device URL/code rendering |
| `apps/desktop/src/store/onboarding.ts:915-997` | Desktop device-flow challenge and browser opening |
| `apps/desktop/src/components/onboarding/flow.tsx:192-213` | Desktop device URL/code rendering |
| `tools/tts_tool.py:154-163` | Piper lazy import |
| `tools/tts_tool.py:1989-2024` | Piper CUDA config consumption |
| `tools/lazy_deps.py:70-115` | Exact lazy dependency allowlist |

### Data model

No database or API schema changes.

`config.yaml` additions/changes:

```yaml
web:
  # backend omitted means automatic provider resolution

tts:
  provider: piper
  piper:
    use_cuda: true  # written only after CUDAExecutionProvider is detected
```

Credential-only state remains:

```dotenv
FIRECRAWL_API_KEY=fc-...
```

## Design Contracts

### 3a. Lifecycle Matrix

| Transition | Owned state | What must happen |
|---|---|---|
| Off → On | Tailscale/Firecrawl child process and auth poll | Spawn one argv-only child with inherited/captured terminal I/O and a bounded timeout |
| On → Off | Child process/poll timer | Finish normally, cancel on interrupt, reap the child, and verify state before persistence |
| On → On (config changed) | Provider selection | Cancel/finish the old ceremony; a later selection starts a new isolated ceremony with no reused secret |
| On → On (config unchanged) | Already-connected Tailscale or already-configured credential | Reuse detected state and do not authenticate again |

Web/desktop QR derived state:

| Transition | Owned state | What must happen |
|---|---|---|
| Unmounted → Mounted | QR data URL | Generate from the current trusted `verification_url` |
| Mounted → Unmounted | QR data URL | Drop component state; existing poll cleanup remains unchanged |
| Mounted → Mounted (URL changed) | QR data URL | Ignore stale async completion and regenerate for the new URL |
| Mounted → Mounted (URL unchanged) | QR data URL | Reuse current image; no duplicate generation |

### 3b. Parameter Contracts

| Method | Scoping parameter | Collection/resource used | Contract |
|---|---|---|---|
| `present_setup_link(url, ...)` | `url` | QR payload and optional browser target | Preserve the exact validated URL, including query and fragment; never substitute a different host |
| `find_tailscale_binary(environ, platform)` | environment/platform | PATH and known app paths | Search only executable candidates for the requested platform |
| `read_firecrawl_cli_credentials(home, platform)` | home/platform | One platform-specific credentials path | Never scan unrelated home files; return only a validated `fc-` key |
| `configure_provider(provider, config)` | provider metadata | The matching config section | Write only the selected provider's declared config keys after its requirements succeed |

### 3c. Return Value Contracts

| Method | Return type | Success means | Failure/null means | Caller must |
|---|---|---|---|---|
| `present_setup_link(...)` | `LinkPresentation` | QR and/or browser presentation succeeded | Plain URL was still printed | Continue the auth flow; presentation failure is non-fatal |
| `tailscale_status(...)` | `TailscaleStatus` | JSON parsed and state known | CLI missing/unreadable/error | Show guidance; do not authenticate or claim success |
| `setup_tailscale(...)` | `bool` | Machine verified `Running` | Declined, missing CLI, timeout, or unverified | Print retry command; never save false success |
| `connect_firecrawl(...)` | `str | None` | Valid `fc-` key imported/supplied | Cancel/failure | Leave provider selection and Fabric secret unchanged |
| `_configure_provider(...)` | `bool` | Requirements completed and selection applied | Cancel/failure | Caller may continue the broader wizard; no partial selection remains |
| `piper_cuda_available()` | `bool` | ONNX Runtime reports `CUDAExecutionProvider` | CPU-only/unavailable/error | Set CUDA only on true; never install/replace ORT |

### 3d. Guard Parity

| Side effect | Template file | Guard condition to copy |
|---|---|---|
| Open a device-login URL | `fabric_cli/auth.py:7566-7574` | `open_browser and not _is_remote_session() and _can_open_graphical_browser()` |
| Save a secret | `fabric_cli/tools_config.py:3649-3651` | `if value:` after provider-specific validation |
| Execute external process | `fabric_cli/tools_config.py:1159-1165` | argv list, `shell=False` default, bounded timeout, resolved executable |
| Web async state update | `web/src/components/OAuthLoginModal.tsx:54-80` | `isMounted.current` plus current flow/session epoch |
| Desktop external link | `apps/desktop/src/store/onboarding.ts:960-997` | existing external-open action and active flow/session guard |

No new unauthenticated dashboard endpoint, WebSocket emission, network listener, or privileged IPC is introduced.

### 3e. Test Harness Requirements

| Assertion | Harness requirement | Negative path |
|---|---|---|
| Tailscale already connected skips login | `status --json` returns `BackendState: Running` and a valid self node | Yes: missing binary and NeedsLogin states |
| Native QR login argv is exact | fake executable runner records `login --qr --qr-format=small --timeout=10m` | Yes: non-zero and timeout do not report success |
| Firecrawl browser login imports key | fake `npx` exits zero and temp credentials file contains `fc-test` | Yes: missing Node, malformed credentials, non-zero, interrupt |
| Failed provider setup is non-mutating | prompt returns empty with pre-existing config snapshot | Yes: assert both config and secret are unchanged |
| Automatic Web row clears pin | config begins with `web.backend: firecrawl` | Yes: choosing self-hosted still requires URL |
| QR helper preserves URL | URL contains query, escaped values, and fragment | Yes: missing qrcode prints exact URL |
| Codex/xAI call QR helper | mocked validated device response supplies URL/code | Yes: remote mode does not open browser |
| Piper CUDA auto-enable | mocked ORT providers include `CUDAExecutionProvider` | Yes: CPU provider only writes/keeps false |
| Web/desktop QR uses challenge URL | challenge fixture includes verification URL and user code | Yes: QR generation rejection leaves link/code usable |

## Implementation Plan

### Step 1: Add the shared trusted-link presenter

- [x] Add `fabric_cli/setup_links.py` with compact terminal QR rendering, exact URL output, and optional guarded browser opening.
- [x] Add `qrcode==7.4.2` to the CLI dependency surface already used by messaging setup.
- [x] Verification: `pytest -q tests/fabric_cli/test_setup_links.py`.

```python
@dataclass(frozen=True)
class LinkPresentation:
    qr_rendered: bool
    browser_opened: bool

def present_setup_link(url: str, *, label: str, open_browser: bool) -> LinkPresentation:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("setup links must use an absolute HTTPS URL")
    print(f"  {label}: {url}")
    qr_rendered = render_terminal_qr(url)
    browser_opened = bool(open_browser and webbrowser.open(url))
    return LinkPresentation(qr_rendered, browser_opened)
```

### Step 2: Make provider activation transactional and Web defaults safe

- [x] Add an `Automatic (recommended)` Web row that clears `web.backend`/`use_gateway` and becomes the fresh default.
- [x] Change `_configure_provider` and `_reconfigure_provider` to collect/validate credentials before calling `_write_provider_config`.
- [x] Return a meaningful success boolean and preserve previous config on cancellation.
- [x] Verification: focused `tests/fabric_cli/test_tools_config.py` tests.

```python
pending_values: dict[str, str] = {}
for var in env_vars:
    existing = get_env_value(var["key"])
    if existing:
        continue
    value = _prompt(var.get("prompt", var["key"]), password=True).strip()
    if not value:
        _print_warning("    Cancelled — provider selection was not changed")
        return False
    pending_values[var["key"]] = value

for key, value in pending_values.items():
    save_env_value(key, value)
_write_provider_config(provider, config, managed_feature=managed_feature)
return True
```

### Step 3: Connect Firecrawl with browser login or a direct key link

- [x] Correct both Firecrawl schemas to use `https://firecrawl.dev/app/api-keys`, free-tier-aware copy, and a `setup_flow: firecrawl` marker.
- [x] Add a plugin-scoped connector that runs `npx -y firecrawl-cli@1.19.24 login --method browser` with telemetry disabled, imports only the official credential file, validates the key prefix, and saves it through Fabric's profile-aware secret writer.
- [x] Fall back to QR/click key-page presentation and a masked manual prompt when Node/npm or browser login is unavailable.
- [x] Verification: plugin connector tests plus provider transaction tests.

```python
env = {**os.environ, "FIRECRAWL_NO_TELEMETRY": "1"}
completed = runner(
    [npx, "-y", "firecrawl-cli@1.19.24", "login", "--method", "browser"],
    env=env,
    timeout=360,
    check=False,
)
if completed.returncode == 0:
    key = read_firecrawl_cli_credentials(Path.home(), sys.platform)
    if key and key.startswith("fc-"):
        save_env_value("FIRECRAWL_API_KEY", key)
        return key
return None
```

### Step 4: Add official Tailscale QR enrollment

- [x] Add CLI discovery/status parsing and idempotent setup in `fabric_cli/tailscale_setup.py`.
- [x] Register `fabric setup tailscale` and offer it once during first-time guided setup, defaulting to No.
- [x] If absent, show a QR/click link to the official platform install page and a rerun command; never install it silently.
- [x] Verification: focused Tailscale and setup-parser tests.

```python
status = tailscale_status(binary)
if status.backend_state == "Running":
    print_success(f"Tailscale connected as {status.dns_name or status.ip}")
    return True
result = runner(
    [binary, "login", "--qr", "--qr-format=small", "--timeout=10m"],
    timeout=620,
    check=False,
)
return result.returncode == 0 and tailscale_status(binary).backend_state == "Running"
```

### Step 5: Apply QR presentation to Codex and xAI device login

- [x] Route both terminal device flows through `present_setup_link` while keeping code display and polling unchanged.
- [x] Preserve xAI's complete verification URL when supplied and Codex's trusted issuer URL.
- [x] Verification: focused auth provider tests.

```python
present_setup_link(
    verification_url,
    label="Scan with your phone or open this link",
    open_browser=(
        open_browser
        and not _is_remote_session()
        and _can_open_graphical_browser()
    ),
)
print(f"  If prompted, enter code: {user_code}")
```

### Step 6: Unify standalone TTS setup and safely accelerate Piper

- [x] Make `fabric setup tts` call the canonical `TOOL_CATEGORIES["tts"]` reconfigure flow.
- [x] Add missing MiniMax and NeuTTS entries to that catalog and retain their install/auth behavior.
- [x] Pin Piper to `piper-tts==1.4.2` in the lazy dependency allowlist and setup installer.
- [x] Detect actual ONNX providers and write `tts.piper.use_cuda` only when CUDA is available.
- [x] Verification: focused setup, tools-config, lazy-deps, and TTS tests.

```python
def piper_cuda_available() -> bool:
    try:
        import onnxruntime
        return "CUDAExecutionProvider" in onnxruntime.get_available_providers()
    except Exception:
        return False

config.setdefault("tts", {}).setdefault("piper", {})["use_cuda"] = (
    piper_cuda_available()
)
```

### Step 7: Add QR to web and desktop device-code screens

- [x] Generate a local QR image from `verification_url` in the existing web OAuth modal.
- [x] Add the same derived QR component to desktop onboarding and declare `qrcode`/types in the desktop package.
- [x] Keep external-link buttons, user code, accessibility labels, timers, and poll lifecycle unchanged.
- [x] Verification: web/desktop component tests and typechecks.

```tsx
useEffect(() => {
  let current = true;
  void QRCode.toDataURL(verificationUrl, { width: 208, margin: 1 })
    .then(dataUrl => current && setQrDataUrl(dataUrl))
    .catch(() => current && setQrDataUrl(null));
  return () => { current = false; };
}, [verificationUrl]);
```

### Step 8: Verify the integrated setup journey

- [x] Run focused Python test files for setup links, Tailscale, Firecrawl, auth, tools config, and TTS.
- [x] Run web/desktop unit tests for changed components.
- [x] Run `npm run typecheck` in `web` and `apps/desktop`.
- [x] Run formatting/lint checks scoped to changed files.
- [x] Inspect `git diff --check` and final worktree status.

## UI/UX Changes

Terminal device flows use the same order everywhere:

1. A provider-specific heading explaining whether this is account sign-in or API-key setup.
2. A compact QR code labeled “Scan with your phone.”
3. The full clickable URL as the guaranteed fallback.
4. A large copyable device code when the provider requires one.
5. A waiting indicator with Ctrl+C/cancel guidance.

Tailscale shows connected machine name/IP on idempotent reruns. Firecrawl shows “Connect in browser (recommended),” “Paste API key,” and “Cancel” rather than treating blank input as self-hosting. Web/desktop preserve the existing visual hierarchy and place the QR beside or immediately above the code/link, with descriptive alt text.

## Migration / Rollout

- No feature flag: setup-only behavior is opt-in and backward compatible.
- Existing explicit providers remain unchanged until a user enters setup and chooses another row.
- Existing `web.backend` pins are preserved; only choosing Automatic removes the pin.
- Existing `tts.piper.use_cuda` remains respected at runtime. Setup recalculates it only when Piper is newly selected/reconfigured.
- Existing Firecrawl keys remain valid and skip login.
- Tailscale state remains owned entirely by Tailscale.

## Test Plan

- [x] Unit: QR rendering, URL validation, browser fallback, missing dependency.
- [x] Unit: Tailscale CLI discovery/status/login timeout/cancel/already-running.
- [x] Unit: Firecrawl official credential-path parsing, browser login, manual fallback, telemetry environment.
- [x] Unit: provider cancellation is config/secret non-mutating; selection is written only after prompts/setup succeed.
- [x] Unit: Automatic Web selection clears only the explicit backend pin.
- [x] Unit: Codex/xAI pass trusted challenge URL and correct browser guard.
- [x] Unit: TTS catalog parity and Piper CUDA detection.
- [x] UI: web/desktop QR success and failure fallback.
- [x] Integration: section parser dispatches `tailscale`; standalone `tts` shows canonical providers.
- [ ] Manual macOS/Linux/Windows: local and SSH device QR scan.
- [ ] Manual Tailscale: absent, NeedsLogin, Running, timeout, and Ctrl+C.
- [ ] Manual Firecrawl: existing key, browser login, missing Node, and manual key.
- [x] Lint/typecheck: changed Python and TypeScript files/packages.

## Out of Scope

- Hosting the Fabric dashboard with `tailscale serve` or exposing it through Funnel.
- Tailscale SSH, subnet routing, exit nodes, ACL/tag management, and auth-key automation.
- Replacing provider OAuth/device protocols or creating Fabric-owned OAuth clients.
- Automatically proving xAI OAuth entitlement by making a billable TTS request during setup.
- Installing NVIDIA drivers, CUDA, `onnxruntime-gpu`, or replacing an ONNX Runtime installation.
- Migrating all legacy behavioral Firecrawl environment variables to config.yaml in this slice.
- Redesigning the entire dashboard/desktop provider settings workflow.

## Open Questions

- Firecrawl's official browser-login CLI is pinned to `1.19.24` for this implementation; future bumps require reviewing its credential path, PKCE flow, and telemetry behavior.
- A later dashboard-focused change should make provider selection + secret submission one server-side transaction; this slice fixes the CLI transaction and does not add a new dashboard API.
- Multi-secret `.env` updates are still one atomic file replacement per key rather than one batch transaction. Prompt cancellation cannot create partial writes, but an I/O failure between two key writes remains a follow-up.
- Web/desktop QR effects guard stale async completion and unmounts; dedicated race tests are a follow-up beyond the success/failure fallback tests in this slice.

## Self-Review

- [x] Every acceptance criterion has a corresponding implementation step.
- [x] Runtime Modes is filled for CLI, remote, web, desktop, and non-interactive execution.
- [x] Lifecycle Matrix includes all four state transitions for child processes and QR UI state.
- [x] Every method with a scoping parameter has a row in Parameter Contracts.
- [x] Every meaningful return value has a caller obligation in Return Value Contracts.
- [x] Every high-consequence side effect matches an existing guard/template.
- [x] Every test assertion names the harness state required to reach it.
- [x] No placeholder implementation steps remain.
- [x] Out of Scope explicitly limits adjacent networking, billing, and GPU work.
- [x] Key files include current line numbers from branch `main` at `6701df5`.

## Status History

- 2026-07-13 — Drafted after syncing `origin/main` and auditing Firecrawl, Tailscale, Codex/xAI auth, TTS, web, and desktop setup surfaces.
- 2026-07-13 — Approved for implementation because the user explicitly requested the setup improvements.
- 2026-07-13 — Implemented and automated-verification complete. Independent integration review found no release blockers; physical device scans on each supported OS remain a manual follow-up.
