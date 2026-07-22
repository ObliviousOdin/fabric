# HANDOFF — ship the iOS native-experience branch as a mergeable PR

**You own this branch now** (single writer, `AGENT_GUARDRAILS.md` §7.2 — the
previous agent has stopped pushing). **Zone:** Mobile — iOS,
`apps/mobile/ios/**` only. **Read first:** `AGENTS.md` and
`AGENT_GUARDRAILS.md` (§0, §3.3, §4.2, §6, §7). **Before your first commit:**
`bash scripts/setup-git-guardrails.sh`.

## Mission

Take the four-feature iOS change already on this branch to
**"PR open, CI green, reviewer-ready"** (§3.2): build and test it on this
machine, fix what the toolchain surfaces, smoke it against a real gateway,
then open the pull request with a filled HANDOFF block. You do **not** merge.

## What this branch contains

Commit `6706966` (features), `f570c5f` (test actor-isolation fix), and
`b28fb33` (hardening from a five-lens adversarial review: 10 MB attachment
transport bound, retry-safe upload receipts + send lock, redacted
server-authored presentation strings, ImageIO-bounded HEIC transcode,
rename gated to conversations with a turn plus `/title` failure detection,
strict opt-in password defaults, truthful Settings copy, Quick Look temp
sweep). Authored without a Swift toolchain (Linux container), so it
compiled only in review:

1. **Kept gated sign-in passwords** — opt-in Keychain persistence
   (`GatewayStore.savePassword/password/deletePassword/hasStoredPassword`),
   remember toggles in `AddGatewayView`/`SignInSheet`, silent kept-password
   re-login in `AppModel.gatedReconnectURL` (cookie mint → 401 → provider
   discovery → one login attempt → sign-in sheet; TOTP never auto-submits,
   sheet prefills the kept password when TOTP is required).
2. **Conversation rename** — `GatewayAPI.setSessionTitle` prefers the typed
   `session.title` RPC when advertised, else dispatches the gateway's
   registered `/title` slash command via `slash.exec` (which today's mobile
   contract advertises; `session.title` is *not* in
   `tui_gateway/gateway_capabilities.py` `MOBILE_METHODS`). UI: pencil
   toolbar + alert in `ChatView`, context menu on live rows in
   `SessionListView`.
3. **Rich history restore** — `ChatViewModel.restoredMessages` folds stored
   tool rows into completed activity cards and stored reasoning into the
   turn's disclosure (`SessionTranscriptMessage` gained `toolName`;
   `TranscriptMessage.init?(restoring:)` was deleted). `ChatView` shows an
   "Opening conversation…" state while `session.resume` is in flight.
4. **Prompt attachments** — photos/GIFs/PDFs/files staged in
   `ChatViewModel.pendingAttachments`, uploaded via `image.attach_bytes` /
   `pdf.attach` / `file.attach` before `prompt.submit` (`file.attach`
   `ref_text` is appended to the prompt text; image/PDF placeholders become
   the prompt only when the draft is empty). Inline previews render from
   local bytes only (`BoundedImageView` animates GIFs with a bounded decode;
   Quick Look for full-screen). HEIC transcodes to JPEG before upload.

## Already verified — you don't need to repeat

- Zone containment: `git diff origin/main...HEAD` touches only
  `apps/mobile/ios/**` (+ this file).
- `python3 tests/scripts/test_ios_project_generation.py` — pass.
- `python3 scripts/commit_identity_audit.py --range origin/main..HEAD` — pass.
- Wire shapes hand-checked against `tui_gateway/server.py`:
  `session.title {session_id,title}→{pending,title}`; `/title` is in
  `fabric_cli/commands.py` and not slash-worker-blocked;
  `image.attach_bytes {content_base64,filename}→{attached,text}` (25 MB cap);
  `pdf.attach {content_base64,filename}→{attached,text}` (50 MB / 25 pages);
  `file.attach {data_url,name}→{attached,ref_text}`; resume rows
  `{role,text|context,name,reasoning*}`.

## NOT verified — this is your job

1. **Compile + unit tests** (the critical gate; iOS CI runs only on `main`,
   §4.2 — a green PR proves nothing for this zone):

   ```sh
   cd apps/mobile/ios
   xcodebuild -project FabricMobile.xcodeproj -scheme Fabric \
     -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
     CODE_SIGNING_ALLOWED=NO test
   ```

   Fix failures with the smallest change that preserves the security posture
   (credentials only in Keychain with
   `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`; every
   presentation string through `ChatPresentationSafety`; no network fetch of
   model-authored content; attachment bytes never written to the
   presentation cache).

2. **Project-generation drift** (must be a no-op — the branch adds no files):

   ```sh
   FABRIC_XCODEGEN_BIN=$(command -v xcodegen) ci_scripts/ci_post_clone.sh
   git diff --exit-code -- FabricMobile.xcodeproj Fabric/Info.plist
   ```

   If the generator produces changes, commit them in the same PR; never
   hand-edit generated files.

3. **Simulator smoke against a real gateway** (`fabric mobile` to pair):
   - Gated server, turn ON "Remember password on this iPhone" (defaults
     OFF — persistence is opt-in) → force-quit → relaunch → tap the server
     → connects with no password prompt; Settings shows "password saved in
     Keychain on this iPhone".
   - Toggle OFF and sign in → relaunch → sign-in sheet appears (and any
     previously kept password is gone).
   - Rename from the chat toolbar and from a live Sessions row (both appear
     only once the conversation has a message); the title survives
     closing/reopening and shows in `session.list` on other clients. Try a
     duplicate title — the failure must surface, not silently succeed.
   - Reopen an old conversation that used tools → activity cards + reasoning
     disclosures, not full-width mono rows; "Opening conversation…" shows on
     a slow link.
   - Attach a photo, an animated GIF (must animate inline), and a PDF; send;
     Quick Look opens each; the agent's reply proves it saw the images and
     can read the `@file:` upload. Try an ~11 MB file — the client-side
     10 MB limit copy must appear (the WS frame cap is 16 MiB; bigger
     payloads would kill the socket).

4. **Compile-risk areas flagged upstream** (check these first if the build
   breaks): `ChatGatewayOperations` memberwise init with defaulted `var`
   closures and its labeled constructions in `ChatExperienceTests`;
   `ToolbarContentBuilder` `if let model, model.canRenameSession` in
   `ChatView`; `.alert(_:isPresented:presenting:)` with a `TextField` in
   `SessionListView`; `AppModel.gatedReconnectURL` actor isolation from the
   `connect` closure; `BoundedImageView` (UIViewRepresentable) sizing inside
   transcript rows; `.quickLookPreview` / `.photosPicker` availability under
   the iOS 17 target.

## Definition of done

1. `xcodebuild … test` green; generation check clean; smoke checklist done.
2. `git fetch origin main && git rebase origin/main`, then
   `python3 scripts/commit_identity_audit.py --range origin/main..HEAD`.
3. **Delete this `HANDOFF.md` in your final commit** — it is branch-local
   working state, not repository documentation.
4. Push, then open the PR (base `main`) titled
   `feat(mobile-ios): saved gated sign-in, rename, rich history restore, prompt attachments`,
   with the §7.4 HANDOFF block in the description. Under **Not verified**
   list the cost-gated `main`-only iOS CI job and desktop/packaging matrices
   (§4.2) so the merger expects the post-merge platform check.
5. Do not self-merge; stay responsive to review comments.

## Commit rules (hard gate — hooks and CI both enforce)

- Author/committer must be
  `PrimeOdin <11676741+ObliviousOdin@users.noreply.github.com>` (the
  bootstrap script sets this). No AI-tool identities, no
  `Co-Authored-By`/`Generated with`/session-link footers of any kind (§3.3) —
  strip anything your harness auto-appends.
- Conventional commits (`type(scope): summary`); this branch → one PR.
- Never push to `main`; never force-push except `--force-with-lease` on this
  branch alone.
