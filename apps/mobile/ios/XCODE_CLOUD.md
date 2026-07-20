# Building Fabric for iOS with Xcode Cloud

This guide connects Apple's **Xcode Cloud** to build the Fabric iOS client and
deliver it to **TestFlight** — the install path the website links to — without
putting any signing credential, team identifier, or private identity in this
repository.

## Values at a glance

| Field | Value | Who sets it |
| --- | --- | --- |
| **Bundle ID** | `io.github.obliviousodin.fabric.mobile` | ✅ Already committed in `project.yml` — nothing to do. |
| **Scheme** | `Fabric` | ✅ Defined in `project.yml`. |
| **App name** | your choice (e.g. `Fabric`) | You — when creating the App Store Connect record (Step 2). |
| **Apple Team ID** | your 10-char team (from developer.apple.com → Membership) | Xcode Cloud pulls this from your Apple account automatically. Only needed by hand for local builds (`Signing.xcconfig`). |
| **Start-condition branch** | `claude/ios-mobile-fabric-merge-urgeht` (or `main` later) | You — in the Xcode Cloud workflow (Step 4). |
| **TestFlight public link** | appears after the first build | You — paste into `website/src/pages/ios.tsx` (Step 6). |

You are using the canonical `io.github.obliviousodin.*` identity, so the bundle
ID is already correct in the repo — you do **not** need the `FABRIC_IOS_BUNDLE_ID`
override described at the end.

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
2. Platform **iOS**. Bundle ID: **`io.github.obliviousodin.fabric.mobile`** —
   this is the exact ID the build produces, so it must match here.
   - If the ID isn't in the dropdown yet, register it first under
     **Certificates, Identifiers & Profiles → Identifiers → ＋**, choose
     **App IDs → App**, and enter `io.github.obliviousodin.fabric.mobile`. Then
     return to **New App** and pick it.
3. Fill in **Name** (your choice — e.g. `Fabric`), primary language, and SKU
   (any unique string, e.g. `fabric-ios`), then create it.

## App ID capabilities & certificates (what to enable)

When you register the identifier `io.github.obliviousodin.fabric.mobile` under
**Certificates, Identifiers & Profiles → Identifiers**, use an **Explicit** App
ID and **leave every capability unchecked**. Fabric needs none of them:

| What the app uses | How it's declared | App ID capability needed? |
| --- | --- | --- |
| Camera (scan the pairing QR) | `NSCameraUsageDescription` in Info.plist | No — Info.plist only |
| Local network (reach the gateway) | `NSLocalNetworkUsageDescription` + ATS local exception | No |
| `fabric://` pairing links | `CFBundleURLTypes` custom URL scheme | No |
| Token storage | Keychain, this app only (no access group) | No — that is *Keychain Sharing*, and it is unused |
| Push notifications | not implemented (a later roadmap item) | **Do not enable** |

So when registering the identifier: **Description** = `Fabric` (any label),
**Bundle ID** = *Explicit* = `io.github.obliviousodin.fabric.mobile`,
**Capabilities** and **App Services** = all left at their defaults, nothing
checked. Then **Register**.

If Push is added to the app later, come back and tick **Push Notifications**
then — not now, since an enabled-but-unused capability only adds provisioning
friction.

### Certificates and provisioning profiles — you do not create these by hand

- **Xcode Cloud** issues and manages the distribution certificate and
  provisioning profile for you. Do **not** manually create a distribution
  certificate.
- **Local builds** (running on your own device from Xcode) use *Automatically
  manage signing*, which creates a development certificate and profile the first
  time.
- The only manual portal step is registering the App ID above. You can skip the
  **Certificates** and **Profiles** sections entirely.

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

## Using your own bundle ID (optional — not needed for this setup)

You are shipping under `io.github.obliviousodin.fabric.mobile`, so you can skip
this section. It is here only if someone later wants to ship under a different
bundle ID **without committing it**:

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
