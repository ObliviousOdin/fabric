# macOS handoff — Loop 0 Swift verification

**Why this file exists.** The Loop 0 contract slice on this branch was authored
and verified on a Linux host: the TypeScript reference ran its full TDD suite
locally, and the Kotlin mirror is verified by the PR's `android` CI job. Swift
cannot be compiled or the Xcode project regenerated on Linux, and since PR #78
the `ios` CI job runs only on push-to-`main` — so the Swift side of this branch
needs one verification pass on a Mac **before merge**. That pass is this
checklist. Delete this file in the PR once every box is checked.

## What the Swift diff on this branch does

- `Fabric/Core/GatewayAPI.swift` — generalizes the `durable_work`-specific
  optional-feature parsing into a registry loop (`optionalGatewayFeatureMethods`
  with 9 families, `optionalGatewayFeatureFlags` with `scoped_grants`), and adds
  the generic `supportsGatewayFeature` gate. `supportsDurableWork` and all
  existing behavior are unchanged.
- `FabricTests/GatewayCapabilitiesTests.swift` — registry-parity test against
  `gateway-feature-registry-v1.json` plus families/contradiction/additive-compat
  /flag-only cases (mirrors `apps/shared/src/gateway-capabilities.test.ts`).
- `project.yml` — wires the three new contract fixtures as `FabricTests`
  resources. **The committed `.xcodeproj`/`Info.plist` are intentionally NOT
  regenerated on this branch** — that is your step 2.

## The checklist (copy-paste, from the repo root)

```bash
# 0. Get the branch
git fetch origin claude/ios-app-roadmap-architecture-o6gnjm
git checkout claude/ios-app-roadmap-architecture-o6gnjm

# 1. Regenerate the Xcode project from the updated manifest
#    (builds the pinned XcodeGen 2.46.0 exactly as Xcode Cloud does; or set
#    FABRIC_XCODEGEN_BIN to a local xcodegen 2.46.0 binary to skip the build)
cd apps/mobile/ios
ci_scripts/ci_post_clone.sh

# 2. Commit the regenerated project — this is what keeps the push-to-main
#    byte-check green after merge
git add FabricMobile.xcodeproj Fabric/Info.plist
git commit -m "chore(mobile-ios): regenerate Xcode project for Loop 0 contract fixtures"

# 3. Immutable project-generation contract
python3 ../../../tests/scripts/test_ios_project_generation.py

# 4. Unit tests on a simulator (same invocation as CI)
xcodebuild -project FabricMobile.xcodeproj -scheme Fabric \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  -derivedDataPath build/DerivedData \
  CODE_SIGNING_ALLOWED=NO test

# 5. Unsigned Release build (same invocation as CI)
xcodebuild -project FabricMobile.xcodeproj -scheme Fabric \
  -configuration Release -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build/DerivedData \
  CODE_SIGNING_ALLOWED=NO build

# 6. Metadata + privacy audit (byte-for-byte what the ios CI job asserts)
app="build/DerivedData/Build/Products/Release-iphonesimulator/Fabric.app"
plist="$app/Info.plist"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$plist")" = "0.2.0"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$plist")" = "1"
test "$(/usr/libexec/PlistBuddy -c 'Print :FabricSourceRevision' "$plist")" = "development"
plutil -lint "$app/PrivacyInfo.xcprivacy"

# 7. Push (the branch tracks origin)
git push
```

## If something is red

Paste the failing test/compiler output back into the session — the fix loops
from the Linux side (edit → you re-run step 4). Steps 1–2 only need re-running
if `project.yml` changes again.

## Merge gate

Do not merge the PR until steps 1–7 are green and the regeneration commit from
step 2 is on the branch. After merge, confirm the push-to-`main` `ios` job goes
green (it is the tripwire, not the gate).
