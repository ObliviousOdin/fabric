# Building Fabric for iOS with Xcode Cloud

This guide connects Apple's **Xcode Cloud** to build the Fabric iOS client and
deliver it to **TestFlight** — the install path the website links to — without
putting any signing credential, team identifier, or release-specific bundle
identity in this repository.

## Values at a glance

| Field | Value | Who sets it |
| --- | --- | --- |
| **Source bundle ID** | `io.github.obliviousodin.fabric.mobile` | ✅ Committed development default in `project.yml`. |
| **TestFlight bundle ID** | Your registered App Store Connect identifier | Set as `FABRIC_IOS_BUNDLE_ID` in Xcode Cloud. |
| **Scheme** | `Fabric` | ✅ Defined in `project.yml`. |
| **App name** | your choice (e.g. `Fabric`) | You — when creating the App Store Connect record (Step 2). |
| **Apple Team ID** | your 10-char team (from developer.apple.com → Membership) | Xcode Cloud pulls this from your Apple account automatically. Only needed by hand for local builds (`Signing.xcconfig`). |
| **Start-condition branch** | `main` | Release only reviewed, merged source. |
| **TestFlight public link** | appears after a public tester group is enabled | You — paste into `website/src/pages/ios.tsx` (Step 6). |

The source bundle ID is a development default. Bundle IDs are globally unique,
so every TestFlight workflow must set `FABRIC_IOS_BUNDLE_ID` to the identifier
registered for its App Store Connect record. The post-clone script renders this
and the unique build number into a temporary XcodeGen specification; it never
edits the tracked `project.yml`.

## Why the setup looks the way it does

- **The app is a thin remote client.** It connects to a `fabric serve` gateway;
  it does not run the agent. Nothing here needs backend secrets.
- **The manifest is authoritative; the generic project is a committed
  bootstrap.** Xcode Cloud validates `FabricMobile.xcodeproj` before it runs
  custom scripts, so the portable project and generated Info.plist from
  `project.yml` must be present in the checkout. `ci_scripts/ci_post_clone.sh`
  then regenerates them on the build machine. Release-only bundle, build, and
  exact source-revision values exist only in its temporary spec and regenerated
  build outputs. Generic builds identify their provenance as `development`.
- **Xcode Cloud owns signing.** Certificates, profiles, and your Apple team are
  held by Xcode Cloud through your Apple account — so no signing material lives
  in git, matching this repo's "no secrets in CI" posture.

## Prerequisites

- Apple Developer Program membership (paid) with App Store Connect access.
- A role of Account Holder, Admin, or App Manager (to create the app record and
  manage Xcode Cloud).
- A Mac with Xcode 16 or newer.
- XcodeGen for the one-time local setup: `brew install xcodegen`.

## Step 1 — Regenerate the bootstrap project

Xcode Cloud needs the project present before it can start a build or run
`ci_post_clone.sh`. Generate the portable bootstrap from the manifest:

```bash
cd apps/mobile/ios
xcodegen generate
open FabricMobile.xcodeproj
```

Commit `FabricMobile.xcodeproj` and `Fabric/Info.plist` whenever `project.yml`
changes. GitHub CI regenerates both and fails if the committed bootstrap drifts
from the manifest. They contain only the public development bundle identity;
protected release values are still applied after clone and never committed.
The **Fabric** scheme is shared so Xcode Cloud can discover it.

## Step 2 — Create the app record in App Store Connect

1. App Store Connect → **Apps → ＋ → New App**.
2. Platform **iOS**. Select the explicit bundle ID you registered for the
   TestFlight release. The Xcode Cloud `FABRIC_IOS_BUNDLE_ID` value in Step 4
   must match it exactly.
3. Fill in **Name** (your choice — e.g. `Fabric`), primary language, and SKU
   (any unique string, e.g. `fabric-ios`), then create it.

## App ID capabilities & certificates (what to enable)

When you register the release identifier under **Certificates, Identifiers &
Profiles → Identifiers**, use an **Explicit** App ID and **leave every
capability unchecked**. Fabric needs none of them:

| What the app uses | How it's declared | App ID capability needed? |
| --- | --- | --- |
| Camera (scan the pairing QR) | `NSCameraUsageDescription` in Info.plist | No — Info.plist only |
| Local network (reach the gateway) | `NSLocalNetworkUsageDescription` + ATS local exception | No |
| `fabric://` pairing links | `CFBundleURLTypes` custom URL scheme | No |
| Token storage | Keychain, this app only (no access group) | No — that is *Keychain Sharing*, and it is unused |
| Push notifications | not implemented (a later roadmap item) | **Do not enable** |

So when registering the identifier: **Description** = `Fabric` (any label),
**Bundle ID** = *Explicit* = your `FABRIC_IOS_BUNDLE_ID` value,
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
4. Xcode Cloud discovers the committed generic project, then detects
   `ci_scripts/ci_post_clone.sh` and runs it after each clone to regenerate the
   release project. There is nothing else to enable for the script.

## Step 4 — Configure the workflow

- **Environment variables** — set `FABRIC_IOS_BUNDLE_ID` to the exact explicit
  App ID used by the App Store Connect record. Xcode Cloud supplies
  `CI_BUILD_NUMBER`; the post-clone script maps it to `CFBundleVersion` so every
  upload is unique. The script requires a clean tracked checkout and derives
  `FabricSourceRevision` from Git `HEAD`; operators do not supply this value.
- **Start Conditions** — use *Branch Changes* on `main`, or a reviewed tag
  pattern such as `ios-v*`. Do not release an unmerged feature branch.
- **Environment** — Xcode 16.x, latest macOS.
- **Actions** — add **Archive → iOS**. This produces the signed archive.
- **Post-Actions** — add **TestFlight (Internal Testing)** so every successful
  build is delivered to your internal testers automatically. Add External
  Testing later; it needs a short Apple beta review.

Xcode Cloud handles signing automatically — there is no certificate or profile
to upload, and no `DEVELOPMENT_TEAM` value in the repo.

## Step 5 — First build and TestFlight

1. Merge the release PR, then let the workflow run from `main` (or create the
   reviewed release tag).
2. After the build finishes, the version appears in **App Store Connect →
   TestFlight** following ~5–15 minutes of processing.
3. Read `FabricSourceRevision` from the archived app's Info.plist and record it
   in `IOS_RELEASES.md`. It must exactly match the merged `main` commit used by
   the workflow.
4. Add **internal testers** (up to 100 people on your team). For an install
   link anyone can use, create a tester group and enable its **Public Link**.

## Step 6 — Wire up the website button

Paste the public TestFlight link into `website/src/pages/ios.tsx`:

```ts
const TESTFLIGHT_URL = "https://testflight.apple.com/join/XXXXXXXX";
```

Commit it; the existing Pages workflow republishes the `/ios` page with a live
**Join the TestFlight beta** button in place of the "coming soon" state.

## Release bundle identity

The committed bundle ID is only the portable development default. Register a
bundle ID under a reverse-domain you control and supply it to release builds
without committing it:

1. **Register the App ID and create the app record** with your own identifier
   (Explicit App ID, no capabilities), exactly as in Step 2 / the App-ID section
   above but using your value, e.g. `com.example.fabric.mobile`.
2. **In Xcode Cloud** — Edit Workflow → **Environment → Environment Variables** →
   add `FABRIC_IOS_BUNDLE_ID` = your value. The post-clone script applies it to
   a temporary spec and generated project; the tracked manifest stays byte-for-
   byte unchanged.
3. **For a local device or archive build** — run the same generator with the
   release identifier and a build number larger than the previous upload:

   ```bash
   FABRIC_XCODEGEN_BIN="$(command -v xcodegen)" \
     FABRIC_IOS_BUNDLE_ID=com.example.fabric.mobile \
     FABRIC_IOS_BUILD_NUMBER=2 \
     ./ci_scripts/ci_post_clone.sh
   ```

   > Note: putting `PRODUCT_BUNDLE_IDENTIFIER` in an `xcconfig` does **not**
   > override it — the generated target sets it explicitly, which wins. Use the
   > generator environment variable instead. An `xcconfig` is still the right
   > place for `DEVELOPMENT_TEAM` on local builds.

   A local release run intentionally rewrites the committed bootstrap outputs
   in that checkout. After archiving, rerun the command without bundle/build
   overrides to restore the generic project before creating a commit. The
   authoritative `project.yml` is never modified.

Your bundle ID and team ID never enter the repository this way.

## Build numbers

Xcode Cloud exposes `$CI_BUILD_NUMBER` and increments it. The post-clone script
uses it as `CURRENT_PROJECT_VERSION`, giving every upload a unique
`(version, build)` pair. `FABRIC_IOS_BUILD_NUMBER` takes precedence for a local
archive. A release bundle ID and build number must be supplied together; a
partial release override fails closed. Build inputs must be positive integers.
The committed `CURRENT_PROJECT_VERSION` is only the development default.

## Source provenance

Generic development builds contain `FabricSourceRevision=development`. A
release generation instead refuses tracked working-tree or index changes,
resolves the exact 40- or 64-character commit at Git `HEAD`, and embeds it in
the generated Info.plist. Before distributing an archive, verify that packaged
value matches the merged `main` SHA and copy both into `IOS_RELEASES.md`.

## Troubleshooting

- **"Scheme not found."** Regenerate locally (`xcodegen generate`) and confirm
  the **Fabric** scheme is shared and committed, then re-select it in the
  workflow.
- **"Project FabricMobile.xcodeproj does not exist."** The generic bootstrap was
  not committed. Regenerate from `project.yml`, commit the full
  `FabricMobile.xcodeproj` directory plus `Fabric/Info.plist`, and rerun the
  workflow.
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
