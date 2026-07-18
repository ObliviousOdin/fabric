---
name: ios-app-development
description: "Build and ship iOS apps — Swift and SwiftUI architecture, Xcode project setup, Human Interface Guidelines, on-device testing, signing, TestFlight beta distribution, and App Store submission. Use when the user wants an iPhone or iPad app designed, built, or shipped."
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [ios, swift, swiftui, xcode, testflight, app-store]
    related_skills: [webapp-development, design]
---

# iOS App Development

Use this skill when the user wants a native iPhone or iPad app taken from idea to App Store: architecture, Swift/SwiftUI code, Xcode project setup, device testing, TestFlight betas, and submission. It covers the whole pipeline, including the parts that happen outside code — signing, review, and post-launch iteration.

Do NOT use this for a mobile-friendly website or PWA — load `webapp-development` with skill_view instead. For visual identity work beyond platform conventions (brand, custom design systems), load `design` with skill_view and bring its output back here as the app's visual contract. If the user only wants to validate a risky idea before committing to a build, run a spike first.

## Prerequisites — state them honestly, first

Building, signing, and submitting an iOS app requires macOS with Xcode and an Apple Developer Program membership ($99/year). Do not pretend otherwise. Before writing code, establish which environment you are actually in:

| You have | You can | You cannot |
|---|---|---|
| macOS + Xcode + paid developer account | Everything: build, run simulators, sign, TestFlight, submit | — |
| macOS + Xcode, free account | Build, simulators, run on your own device (7-day provisioning) | TestFlight, App Store |
| Linux or Windows (this agent, often) | Write all Swift/SwiftUI source, design architecture, compile and test pure-Swift packages with the open-source toolchain, prepare metadata, review-proof the submission | Compile SwiftUI/UIKit, run simulators, sign, upload |
| CI (Xcode Cloud, GitHub Actions macOS runners) | Automated build, test, TestFlight upload | Interactive debugging |

On Linux, be explicit with the user: "I will write the complete project; you (or CI) run and archive it on a Mac." Structure code so the platform-independent core (models, business logic, parsing, networking) lives in a Swift package you CAN compile and unit-test locally with `swift test`, and only the SwiftUI layer waits for a Mac. This is good architecture anyway.

## Workflow

1. **Scope the app.** Ask the user: target devices (iPhone only? iPad? both?), minimum iOS version (default: current major minus one), offline requirements, accounts/backend or local-only, and whether App Store distribution is actually the goal (an internal tool may only need TestFlight or ad-hoc installs).
2. **Check the environment** against the table above and say plainly which steps you can execute versus hand off.
3. **Design the architecture** (next section) and write it down before generating files. One paragraph plus a module list is enough; get a nod from the user on anything opinionated.
4. **Scaffold the project.** On a Mac, create the Xcode project (or use `xcodegen`/`tuist` if the user prefers generated projects for clean diffs). Elsewhere, lay out the full source tree and a Swift package for the core so tests run now.
5. **Build vertical slices.** Ship one complete feature — view, state, persistence, tests — before starting the next. Run unit tests after every slice (`swift test` for the core package; `xcodebuild test -scheme App -destination 'platform=iOS Simulator,name=iPhone 16'` on a Mac).
6. **Verify on device or simulator.** Screenshots of real screens beat claims. Exercise rotation, Dynamic Type at large sizes, dark mode, and airplane mode.
7. **Distribute a beta** through TestFlight; collect crashes and feedback for at least one build cycle.
8. **Submit** using the checklist below, with the rejection pitfalls reviewed against the actual app.
9. **Iterate post-launch**: crash triage, phased rollout, review responses.

## SwiftUI-first architecture

Default to SwiftUI with the `@Observable` macro (Observation framework); reach for UIKit only for gaps (advanced text editing, complex collection layouts) and wrap those in `UIViewRepresentable`.

- **Views are cheap value types.** Keep them dumb: render state, forward intent. If a view body exceeds ~50 lines, extract subviews.
- **State lives in `@Observable` model objects.** Use `@State` for view-local ephemera, `@Environment` to inject shared models, and pass bindings down explicitly. Avoid singletons reached from view bodies.
- **Dependency boundaries as protocols.** Networking, persistence, and clocks sit behind protocols with a live and a test/preview implementation. This keeps previews instant and unit tests hermetic.
- **Three-layer split**: `AppCore` (Swift package: models, logic, services — compiles anywhere), `AppUI` (SwiftUI views + view models), app target (entry point, composition root, Info.plist).
- **Navigation** via `NavigationStack` with a typed path enum owned by a router model, not ad-hoc `NavigationLink` sprawl — this makes deep links and state restoration tractable.

Suggested tree (app target plus a local package):

```
MyApp/
  MyAppApp.swift          entry point, composition root
  Features/
    Timeline/             one folder per feature: views + view model
    Settings/
  Support/                extensions, small shared views
  Resources/              Assets.xcassets, Localizable.xcstrings
Packages/AppCore/
  Sources/AppCore/        models, services, protocols
  Tests/AppCoreTests/     runs with `swift test` on any platform
```

## HIG essentials reviewers and users actually notice

- Use SF Symbols and system fonts; support Dynamic Type (no fixed font sizes) and dark mode from day one — retrofitting is painful.
- Tap targets at least 44x44 points; respect safe areas; never hide primary actions behind gestures with no visible affordance.
- Standard navigation patterns: tab bar for top-level sections, `NavigationStack` for hierarchies, sheets for scoped tasks. Novel navigation is a usability tax, not a feature.
- Ask for permissions in context, right before the feature needs them, with a purpose string that names the user benefit. Blanket launch-time permission walls get rejected and deleted.
- Support both orientations on iPad or justify a lock; test at iPad split-view widths.
- Empty states, loading states, and error states are part of every screen, not a polish pass.

## Data persistence options

| Option | Best for | Avoid when |
|---|---|---|
| SwiftData | New SwiftUI apps, model graphs, iCloud sync via CloudKit | Needing complex queries/migrations under heavy load, or supporting very old iOS versions |
| Core Data | Mature apps, fine-grained migration control, existing stores | Greenfield SwiftUI-only apps (SwiftData is less ceremony) |
| SQLite (via GRDB) | Complex queries, full-text search, large datasets, portability of the core package | You want automatic iCloud sync with zero SQL |
| Files + Codable | Documents, small config, export/import formats | Concurrent structured mutation or partial reads of large data |
| UserDefaults | Tiny preferences and flags | Anything sensitive or larger than a few KB |
| Keychain | Tokens, credentials, secrets | Anything that is not a secret |

Pick one primary store; mixing SwiftData and raw SQLite in one app is usually a smell. Whatever you choose, hide it behind a protocol in `AppCore`.

## Signing and provisioning, demystified

Four artifacts, one sentence each — most signing pain is not knowing which one is broken:

- **Certificate**: proves who you (the developer account) are; lives in the Mac's keychain.
- **App ID**: the bundle identifier registered with Apple, plus its entitlements (push, iCloud, etc.).
- **Provisioning profile**: a signed document tying certificate + App ID + (for dev/ad-hoc) device list together.
- **Entitlements file**: what capabilities the binary claims; must be a subset of what the profile allows.

Default advice: enable "Automatically manage signing" in Xcode and let it mint everything. Move to manual (fastlane `match` or Xcode Cloud) only when a team or CI needs shared credentials. When signing fails, diagnose in order: is the certificate valid and present, does the bundle ID match the App ID exactly, does the profile include this device, do entitlements match capabilities enabled in the developer portal.

## TestFlight beta flow

1. Bump build number, archive in Xcode (Product > Archive) or CI, upload via the Xcode Organizer, the Transporter app, or fastlane `pilot` (App Store Connect API). Do not use `xcrun altool` — it is deprecated and App Store Connect no longer accepts uploads from it.
2. Wait for processing, answer the export-compliance question (most apps using only HTTPS qualify for the exemption).
3. Internal testers (your App Store Connect team, up to 100) get builds immediately, no review.
4. External testers (up to 10,000, invited by link or email) require a lightweight beta review for the first build of each version.
5. Watch TestFlight crash reports and screenshots-with-feedback; fix, bump build, re-upload. Builds expire after 90 days — keep a cadence.

## App Store submission checklist

Draft this file with the user and check every line against the real app before submitting:

```markdown
# Ship checklist — [App Name] v[version]

## App Store Connect
- [ ] App record created; bundle ID, SKU, primary language set
- [ ] Pricing and availability configured
- [ ] Age rating questionnaire answered honestly

## Metadata
- [ ] Name (30 chars), subtitle (30), description, keywords (100)
- [ ] Screenshots for every size App Store Connect currently marks required (one 6.9" iPhone set; 13" iPad set if iPad app) — verify the live list in App Store Connect before upload
- [ ] Privacy nutrition labels match ACTUAL data collection (including SDKs)
- [ ] Privacy policy URL live and accurate; support URL live

## Binary
- [ ] Version + build bumped; release build tested on a physical device
- [ ] Purpose strings for every permission the app can request
- [ ] No placeholder content, broken links, or debug UI
- [ ] Sign in with Apple offered if any third-party login is offered
- [ ] Account deletion available in-app if accounts can be created

## Review readiness
- [ ] Demo account credentials in App Review notes (if login required)
- [ ] Review notes explain anything non-obvious (hardware needs, region features)
- [ ] Export compliance answered
```

Rejection pitfalls that account for most first-submission failures: privacy labels that omit third-party SDK collection (guideline 5.1); missing account deletion (5.1.1); digital goods sold outside in-app purchase (3.1.1); apps that are thin wrappers around a website (4.2 — should be a website; see `webapp-development`); crashes on launch on the reviewer's device because only the simulator was tested (2.1); permission requests with vague purpose strings; and login-gated apps with no demo account for the reviewer.

## Post-launch iteration

- Use **phased release** for automatic updates (7-day gradual rollout, pausable) so a bad build hits 1% of users, not 100%.
- Triage crashes in Xcode Organizer or App Store Connect within days of each release; fix the top crasher before adding features.
- Respond to App Store reviews — replies are public and factor into perception; ask for ratings with `SKStoreReviewController`/`requestReview` only after a success moment, never at launch.
- Keep TestFlight running as a permanent beta channel one version ahead of production.

## Cross-platform alternatives — offer them honestly

If the user has not firmly chosen native, present this before scaffolding:

| Choose | When | Cost |
|---|---|---|
| Native Swift/SwiftUI | iOS-first product, platform features (widgets, live activities), best feel per effort on one platform | Separate Android codebase later |
| React Native (+ Expo) | Web/JS team, iOS + Android from one codebase, OTA updates matter | Native modules for anything unusual; still needs a Mac to ship iOS |
| Flutter | Design-heavy custom UI identical on both platforms, Dart acceptable | Non-native look unless you fight for it; larger binaries |
| Capacitor | An existing web app that needs store presence and a few native APIs | Web-level feel; the 4.2 "thin wrapper" rejection risk is real |

Every option in this table still requires macOS, signing, and App Store review to ship on iOS — cross-platform frameworks remove none of this skill's distribution sections.

## Common failure modes

- **Pretending Linux can archive an IPA.** It cannot. Say so in step 2, structure the handoff, and give the user exact Mac-side commands instead of vague "then build it" instructions.
- **Simulator-only confidence.** Camera, push, keychain edge cases, performance, and some crashes only manifest on hardware. Require one physical-device pass before TestFlight.
- **Privacy labels written from memory.** Audit what the code and every third-party SDK actually collect; mismatches are a rejection and a trust problem.
- **Skipping TestFlight to "save time."** The first external crash report always finds something; one beta cycle is cheaper than a 1-star launch week.
- **God views.** A 400-line `ContentView` with a dozen `@State` variables is unmaintainable and untestable. Enforce the extraction rule early.
- **Designing against the HIG for novelty.** Custom navigation and hidden gestures read as broken to users and sometimes to reviewers.
- **Submitting v1.0 with build 1 untested in Release configuration.** Optimized builds behave differently (timing, assertions stripped); always test the archived configuration.
- **Ignoring the review notes field.** A two-sentence explanation and a demo login prevent the most common metadata rejections outright.
