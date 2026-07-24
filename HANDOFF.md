# Hand-off — `claude/ios-app-features-waiuh9`

> Working hand-off for continuing this branch on a **Mac** (Xcode available).
> Delete this file before the branch merges to `main` — it is a scratch note,
> not product documentation.

## TL;DR

Two bodies of work are on this branch, **all committed and pushed** (11 commits
ahead of `origin/main`):

- **A. Four new iOS app features** — hide pages, a Work kanban, an artifacts/media
  browser, and Wispr-Flow-style dictation clean-up.
- **B. A "generative UI" chat epic** across **both** the iOS app *and* the
  desktop (Electron + React) app — rich `diff` / `work` / `chart` cards, live
  tool logs, entrance motion, and a reactive ambient backdrop.

All of this was authored on **Linux with no Xcode**, so:

- **Desktop** work is fully verified here (`typecheck` + `eslint` + `vitest` all
  green — it does not need a Mac, only `npm ci` at the repo root).
- **iOS** work is **compile-*reviewed*, not compiled** (a fresh agent read every
  new symbol against the real APIs and found no compile errors), and the pure
  logic is unit-tested. It still needs a real Xcode build.

## ⚠️ The one blocking task (do this first, on the Mac)

The committed `apps/mobile/ios/FabricMobile.xcodeproj` **enumerates individual
source files**, and this branch adds several new `.swift` files. The Xcode
project must be **regenerated** so it references them, and the `main`-only iOS CI
enforces `git diff --exit-code` on the regenerated project. Do **not** hand-edit
the project — regenerate it.

```bash
# from the repo root, once:
bash scripts/setup-git-guardrails.sh        # canonical commit identity + hooks
brew install xcodegen                         # if not already installed

cd apps/mobile/ios
xcodegen generate                             # OR: ci_scripts/ci_post_clone.sh
git add FabricMobile.xcodeproj Fabric/Info.plist   # commit the regenerated project
python3 ../../../tests/scripts/test_ios_project_generation.py   # must pass

# CI-equivalent simulator test:
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  xcodebuild -project FabricMobile.xcodeproj -scheme Fabric \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  CODE_SIGNING_ALLOWED=NO test
```

Fix any real compile errors the simulator build surfaces (the review was careful
but is not a compiler), commit the regenerated project + any fixes, `git rebase
origin/main`, and push. **That single round unblocks the whole iOS side.**

## Guardrails (non-negotiable — read these first)

Read, in order: `AGENT_GUARDRAILS.md`, `AGENTS.md`, `CONTRIBUTING.md`.

- Run `bash scripts/setup-git-guardrails.sh` before your first commit. Commits
  carry the canonical **PrimeOdin** identity and must have **no** AI-tool
  footers (`Co-Authored-By`, `Generated with`, session links). Hooks + CI reject
  violations.
- Never commit to `main`. Stay on `claude/ios-app-features-waiuh9`. `git rebase
  origin/main` before you push.
- Run Python tests with `scripts/run_tests.sh`, never bare `pytest`.

## What's on the branch (commit-by-commit, oldest → newest)

| Commit | Area | Summary |
| --- | --- | --- |
| `97c4bb40` | iOS | Settings **Pages** control to hide optional tabs (e.g. Social) |
| `cfff793c` | iOS | Fail-closed **Work board** (kanban over Durable Work) |
| `8eb92a64` | iOS | Client-side **Artifacts & media** browser |
| `5d9b74b9` | iOS | On-device **dictation clean-up** (Wispr-Flow-style) |
| `96d6d2a7` | iOS | Gen-UI Inc 1 — **live tool-call log** in the activity card |
| `ed3e5d13` | Desktop | Gen-UI Inc 1 — **`diff` fences** → rich diff panels |
| `bb89fd38` | Desktop | Gen-UI Inc 2 — **`work` fences** → job cards |
| `68e65670` | Desktop | Gen-UI Inc 3 — **`chart` fences** → SVG charts |
| `615def52` | Desktop | Gen-UI Inc 4 — **card entrance animation** |
| `929da2b7` | Desktop | Gen-UI Inc 5 — **reactive ambient glow** behind the thread |
| `706455f9` | iOS | Gen-UI Inc 2–5 — **work/chart cards, card motion, reactive ambient** |

## Feature map (where things live + how to see them)

### A. iOS app features

1. **Hide pages** *(works today)* — `Fabric/App/ConnectedAppTabPolicy.swift`
   (pure, tested), tab shell in `Fabric/App/FabricMobileApp.swift`, toggles in
   `Fabric/Features/Settings/SettingsExperienceView.swift`. Verify: hide Social,
   relaunch, confirm it's gone and selection falls back to Home.
2. **Work board** *(fail-closed)* — `Fabric/Features/Work/WorkBoard*.swift`,
   `WorkBoardPresentation.swift`; `AppModel` owns the shared `WorkInboxModel`.
   The tab is **hidden until the gateway advertises the `durable_work`
   capability** (FMB-002). See it now via the DEBUG fixture:
   `-fabric-ui-fixture work-board` (or env `FABRIC_UI_FIXTURE=work-board`).
3. **Artifacts browser** — `Fabric/Core/TranscriptArtifacts.swift` (pure, tested),
   `Fabric/Features/Artifacts/ArtifactsBrowserView.swift`. Verify against a real
   gateway in **both** token and gated auth modes.
4. **Dictation clean-up** — `Fabric/Core/DictationCleanup.swift` (pure, tested),
   composer wand button + Settings toggle in `ChatView.swift` /
   `SettingsExperienceView.swift`. **Needs physical-device QA** per
   `apps/mobile/ios/VOICE.md`'s release gate.

### B. Generative UI — iOS *(compile-reviewed)*

- **Live tool log** — `AssistantTurnPart.Tool.log` folded in the reducer
  (`ChatViewModel.swift`), rendered in `ToolActivityCard` (`ChatView.swift`).
- **Work/chart cards** — `Fabric/Core/GenerativeFence.swift` (pure parsers,
  tested), `Fabric/Features/Chat/GenerativeFenceCards.swift` (SwiftUI `Canvas`),
  dispatched from the `.code` render block by language in `ChatView.swift`
  (`codeBlock(...)`). No parser change; a bad spec falls back to a code block.
- **Reactive ambient** — `Fabric/Features/Chat/ChatAmbientView.swift`
  (`TimelineView` + `Canvas`), mounted as the chat background reacting to
  `model.busy`, frozen under Reduce Motion.
- See it all: `-fabric-ui-fixture chat-activity` (tool log + a `work` card + a
  `chart` card are seeded in the fixture).

### B. Generative UI — Desktop *(verified: `typecheck` + `eslint` + `vitest` green)*

- **Rich fences** — `apps/desktop/src/components/assistant-ui/embeds/`:
  `diff-embed.tsx`, `work-embed.tsx`, `chart-embed.tsx`, registered in
  `registry.tsx` (`RICH_FENCE_LANGUAGES`). Each has a pure parser + a vitest.
- **Reactive ambient** — `thread/thread-ambient.tsx`, mounted in `thread/index.tsx`.
- **Entrance motion** — `animate-in` classes on the fence cards (reduced-motion
  gated).

Verify on the Mac (or any machine):
```bash
npm ci                                        # repo root
npm run --prefix apps/desktop typecheck
npm run --prefix apps/desktop lint
npm run --prefix apps/desktop test:ui         # vitest (jsdom)
```
> Note: some *pre-existing* desktop thread tests (`streaming`, `user-message-edit`,
> `block-direction`) fail when vitest is invoked ad-hoc without the project's
> setup polyfills; they fail identically without any of this branch's changes.
> Use the project script (`test:ui`) which loads the proper config.

To actually *see* the desktop cards, run the app (`npm run --prefix apps/desktop
dev`) and have the agent emit a fenced ` ```work `, ` ```chart `, or ` ```diff `
block (see "Make the agent emit fences" below).

## Deferred work & enhancements (roadmap)

Ordered by leverage:

1. **iOS Xcode regen + simulator/device build** — the blocking task above.
2. **Advertise `durable_work` server-side** → the iOS Work board (tab + future
   inline cards) goes live. Small change: add the family to
   `OPTIONAL_FEATURE_METHODS` in `tui_gateway/gateway_capabilities.py`, then
   rewrite the gate test in `tests/tui_gateway/test_gateway_capabilities.py`
   that asserts `"durable_work" not in payload["features"]`, plus positive
   family tests mirroring the pets tests. Verify with `scripts/run_tests.sh`.
3. **Authenticated `GatewayRESTClient` (iOS)** — unlocks two deferred pieces at
   once: (a) inline preview of *workspace-file* image bytes in the Artifacts
   browser, and (b) **server-Whisper dictation** (record → `POST
   /api/audio/transcribe`, the same endpoint the desktop mic uses). Must handle
   both token (`X-Fabric-Session-Token` header) and gated (cookie session) auth.
4. **Server `artifact.list` / `artifact.fetch` RPCs** — the capability slots
   exist in `apps/mobile/contracts/gateway-feature-registry-v1.json`; implement
   them to replace transcript scraping with a real index.
5. **Make the agent emit fences** — the *renderers* for `work`/`chart` exist on
   both clients, but users only see them if the agent emits ` ```work ` /
   ` ```chart ` fenced JSON. Add guidance to the system/tooling prompt (or a
   tool that emits them). `diff` fences already appear from tool output.
6. **Gen-UI polish** — iOS: per-line log *streaming* animation, message-insertion
   transitions (Inc 4 is a light card-entrance on iOS), consider Swift Charts for
   richer charts, tune the ambient intensity. Desktop: the **web dashboard**
   chat is an xterm/PTY surface (`web/`), so in-transcript generative UI there
   needs a re-architecture — out of scope, noted for the record.

## Visual reference (private links — for the user)

The target UX is captured in two published concept artifacts (private to the
user's Claude account):

- iPhone feature mockups: `https://claude.ai/code/artifact/57f19e15-faf4-443c-8953-678941c5caaf`
- Generative agent-chat concept (WebGL + streaming + cards):
  `https://claude.ai/code/artifact/f11cd8eb-8f43-4323-b2d1-944fa6a360c4`

## Suggested first session on the Mac

1. `git fetch origin && git checkout claude/ios-app-features-waiuh9 && git rebase origin/main`
2. `bash scripts/setup-git-guardrails.sh`
3. Do the **blocking task** (xcodegen regen + `xcodebuild test`); fix any real
   compile errors; commit the regenerated project.
4. Launch the app; walk the DEBUG fixtures (`chat-activity`, `work-board`) and
   the four features; note anything visual to refine.
5. Then pick from the roadmap — item 2 (advertise `durable_work`) is the highest
   value / lowest effort, and lights up the Work board immediately.
6. Open a PR (mirror any `.github` PR template) when ready.
