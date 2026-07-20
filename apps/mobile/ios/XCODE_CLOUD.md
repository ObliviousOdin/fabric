# Building Fabric for iOS with Xcode Cloud

This guide connects Apple's **Xcode Cloud** to build the Fabric iOS client and
deliver it to **TestFlight** — the install path the website links to — without
putting any signing credential, team identifier, or private identity in this
repository.

## Why the setup looks the way it does

- **The app is a thin remote client.** It connects to a `fabric serve` gateway;
  it does not run the agent. Nothing here needs backend secrets.
- **The Xcode project is generated, not committed.** `project.yml` is the source
  of truth; XcodeGen produces `FabricMobile.xcodeproj`, which stays untracked.
  `ci_scripts/ci_post_clone.sh` regenerates it on the build machine after every
  clone.
- **Xcode Cloud owns signing.** Certificates, profiles, and your Apple team are
  held by Xcode Cloud through your Apple account — so no signing material lives
  in git, matching this repo's "no secrets in CI" posture.

## Prerequisites

- Apple Developer Program membership (paid) with App Store Connect access.
- A role of Account Holder, Admin, or App Manager (to create the app record and
  manage Xcode Cloud).
- A Mac with Xcode 16 or newer.
- XcodeGen for the one-time local setup: `brew install xcodegen`.

## Step 1 — Generate the project locally (one time)

Xcode Cloud is configured from inside Xcode, which needs the project present
when you set it up. Generate it:

```bash
cd apps/mobile/ios
xcodegen generate
open FabricMobile.xcodeproj
```

Do **not** commit `FabricMobile.xcodeproj` — it is derived output and is already
gitignored. Build machines regenerate it via `ci_scripts/ci_post_clone.sh`. The
**Fabric** scheme is marked shared by XcodeGen, which is what lets Xcode Cloud
discover it.

## Step 2 — Create the app record in App Store Connect

1. App Store Connect → **Apps → ＋ → New App**.
2. Platform **iOS**. Bundle ID: `io.github.obliviousodin.fabric.mobile` (the
   committed default) — or one you own; see **Using your own bundle ID** below.
   - If the ID isn't in the dropdown, register it first under
     **Certificates, Identifiers & Profiles → Identifiers**.
3. Give the app a name and create it.

## Step 3 — Connect Xcode Cloud

1. In Xcode: **Product → Xcode Cloud → Create Workflow** (or the **Integrate**
   menu → **Create Workflow**).
2. Select the **Fabric** app and the shared **Fabric** scheme.
3. When prompted, grant Xcode Cloud access to this GitHub repository — it
   installs the Xcode Cloud GitHub app. Approve it for `ObliviousOdin/fabric`.
4. Xcode Cloud detects `ci_scripts/ci_post_clone.sh` on its own and runs it
   after each clone to generate the project. There is nothing to enable for that.

## Step 4 — Configure the workflow

- **Start Conditions** — pick how releases are cut, e.g. *Branch Changes* on
  `main`, or a *Tag* pattern like `ios-v*`.
- **Environment** — Xcode 16.x, latest macOS.
- **Actions** — add **Archive → iOS**. This produces the signed archive.
- **Post-Actions** — add **TestFlight (Internal Testing)** so every successful
  build is delivered to your internal testers automatically. Add External
  Testing later; it needs a short Apple beta review.

Xcode Cloud handles signing automatically — there is no certificate or profile
to upload, and no `DEVELOPMENT_TEAM` value in the repo.

## Step 5 — First build and TestFlight

1. Save the workflow (Xcode Cloud runs it immediately) or push to your
   start-condition branch.
2. After the build finishes, the version appears in **App Store Connect →
   TestFlight** following ~5–15 minutes of processing.
3. Add **internal testers** (up to 100 people on your team). For an install
   link anyone can use, create a tester group and enable its **Public Link**.

## Step 6 — Wire up the website button

Paste the public TestFlight link into `website/src/pages/ios.tsx`:

```ts
const TESTFLIGHT_URL = "https://testflight.apple.com/join/XXXXXXXX";
```

Commit it; the existing Pages workflow republishes the `/ios` page with a live
**Join the TestFlight beta** button in place of the "coming soon" state.

## Using your own bundle ID (optional — keeps the repo clean)

The committed default is `io.github.obliviousodin.fabric.mobile`. To ship under
a bundle ID you own **without committing it**:

- **In Xcode Cloud** — Edit Workflow → **Environment → Environment Variables** →
  add `FABRIC_IOS_BUNDLE_ID` set to your value (for example
  `com.example.fabric.mobile`). `ci_scripts/ci_post_clone.sh` applies it to the
  generated project before the build; your value stays in Xcode Cloud, never in
  git.
- **For local builds** — create `apps/mobile/ios/Signing.xcconfig` (gitignored)
  and reference it from the scheme or pass `-xcconfig Signing.xcconfig` to
  `xcodebuild`:

  ```
  DEVELOPMENT_TEAM = <YOUR_TEAM_ID>
  PRODUCT_BUNDLE_IDENTIFIER = com.example.fabric.mobile
  ```

Either way your team ID and bundle ID never enter the repository.

## Build numbers

Xcode Cloud exposes `$CI_BUILD_NUMBER` and can auto-increment it, giving every
upload a unique build so TestFlight never rejects a duplicate `(version, build)`
pair. The committed `CURRENT_PROJECT_VERSION` (`1`) is only the local default.

## Troubleshooting

- **"Scheme not found."** Regenerate locally (`xcodegen generate`) and confirm
  the **Fabric** scheme is shared, then re-select it in the workflow.
- **Signing/registration fails on the default bundle ID.** It may already be
  claimed by another Apple team. Set `FABRIC_IOS_BUNDLE_ID` to one you own (see
  above).
- **`ci_post_clone.sh` didn't run.** Make sure it is executable and located at
  the repository root under `ci_scripts/`.

## Not using Xcode Cloud?

A local **archive → TestFlight** flow works too: Xcode's Organizer (**Product →
Archive → Distribute App**), or `xcodebuild archive` + `-exportArchive` with an
App Store Connect API key. A GitHub Actions pipeline is intentionally **not**
provided here — this repository's release audit forbids `secrets.` references in
workflows, so an Apple signing secret cannot live in Actions. Keep signing on
Xcode Cloud or a local machine.
