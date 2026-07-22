import Foundation
import UIKit
import XCTest
@testable import Fabric

final class GatewayCapabilitiesTests: XCTestCase {
    func testAcceptsCanonicalContractAndExecutionTruth() throws {
        let negotiation = GatewayCapabilitiesParser.parse(
            try fixtureObject("gateway-capabilities-v1.json")
        )

        guard case .verified(let capabilities) = negotiation else {
            return XCTFail("Expected verified capabilities, got \(negotiation)")
        }
        XCTAssertEqual(capabilities.contract.name, "fabric.gateway")
        XCTAssertEqual(capabilities.contract.version, 1)
        XCTAssertEqual(capabilities.contract.minimumCompatibleVersion, 1)
        XCTAssertEqual(capabilities.execution.location, "gateway")
        XCTAssertEqual(capabilities.execution.toolExecution, "gateway")
        XCTAssertTrue(capabilities.execution.survivesClientDisconnect)
        XCTAssertFalse(capabilities.execution.survivesGatewayRestart)
        XCTAssertTrue(capabilities.execution.requiresGatewayHostOnline)
        XCTAssertTrue(negotiation.supportsGatewayMethod("prompt.submit"))
        XCTAssertFalse(negotiation.supportsGatewayMethod("voice.record"))
        XCTAssertNil(capabilities.features["voice"])
        XCTAssertNil(capabilities.features["code"])
        XCTAssertEqual(capabilities.features["code_session_baseline"], true)
        XCTAssertFalse(negotiation.supportsGatewayMethod("future.missing"))
    }

    func testAcceptsAdditiveFutureContractWhenMinimumRemainsCompatible() throws {
        var payload = try fixtureObject("gateway-capabilities-v1.json")
        var contract = try XCTUnwrap(payload["contract"] as? [String: Any])
        contract["version"] = gatewayClientContractVersion + 3
        contract["future_rule"] = ["safe": true]
        payload["contract"] = contract
        payload["future_top_level"] = ["safe": true]
        var methods = try XCTUnwrap(payload["methods"] as? [Any])
        methods.append("future.safe_method")
        payload["methods"] = methods

        let negotiation = GatewayCapabilitiesParser.parse(payload)

        guard case .verified(let capabilities) = negotiation else {
            return XCTFail("Expected compatible future contract, got \(negotiation)")
        }
        XCTAssertEqual(capabilities.contract.version, gatewayClientContractVersion + 3)
        XCTAssertTrue(capabilities.methods.contains("future.safe_method"))
    }

    func testClassifiesValidHigherMinimumAsIncompatible() throws {
        let negotiation = GatewayCapabilitiesParser.parse(
            try fixtureObject("gateway-capabilities-incompatible.json")
        )

        XCTAssertEqual(negotiation, .incompatible(minimumCompatibleVersion: 2))
        XCTAssertFalse(negotiation.allowsBaselineSessionCalls)
        XCTAssertFalse(negotiation.supportsGatewayMethod("prompt.submit"))
    }

    func testRejectsMalformedAndContradictoryContracts() throws {
        let malformed = GatewayCapabilitiesParser.parse(
            try fixtureObject("gateway-capabilities-malformed.json")
        )
        guard case .invalid(let malformedReason) = malformed else {
            return XCTFail("Expected malformed fixture to be invalid")
        }
        XCTAssertTrue(malformedReason.contains("execution contract"))

        var contradictory = try fixtureObject("gateway-capabilities-v1.json")
        var features = try XCTUnwrap(contradictory["features"] as? [String: Any])
        features["files"] = false
        contradictory["features"] = features

        guard case .invalid(let featureReason) = GatewayCapabilitiesParser.parse(contradictory) else {
            return XCTFail("Expected contradictory feature to be invalid")
        }
        XCTAssertTrue(featureReason.contains("files"))
    }

    func testRejectsDuplicateEmptyAndNonStringMethods() throws {
        let canonical = try fixtureObject("gateway-capabilities-v1.json")
        let methods = try XCTUnwrap(canonical["methods"] as? [Any])
        let invalidMethods: [[Any]] = [
            methods + [try XCTUnwrap(methods.first)],
            methods + [""],
            methods + [42],
        ]

        for values in invalidMethods {
            var payload = canonical
            payload["methods"] = values
            guard case .invalid = GatewayCapabilitiesParser.parse(payload) else {
                return XCTFail("Expected methods \(values) to be invalid")
            }
        }
    }

    func testVerifiedContractWithoutBaselineMethodsCannotIssueSessionCalls() throws {
        var payload = try fixtureObject("gateway-capabilities-v1.json")
        let methods = try XCTUnwrap(payload["methods"] as? [Any])
            .filter { ($0 as? String) != "session.create" }
        payload["methods"] = methods
        var features = try XCTUnwrap(payload["features"] as? [String: Any])
        features["baseline_chat"] = false
        payload["features"] = features

        let negotiation = GatewayCapabilitiesParser.parse(payload)

        guard case .verified = negotiation else {
            return XCTFail("A coherent reduced contract should remain verified")
        }
        XCTAssertFalse(negotiation.allowsBaselineSessionCalls)
        XCTAssertFalse(negotiation.supportsGatewayMethod("session.create"))
    }

    func testLegacyModeMatchesCanonicalShippedMethodSet() throws {
        let fixture = Set(try fixtureArray("legacy-mobile-methods.json").compactMap { $0 as? String })

        XCTAssertEqual(legacyMobileMethods, fixture)
        XCTAssertTrue(GatewayCapabilityNegotiation.legacy.allowsBaselineSessionCalls)
        XCTAssertTrue(GatewayCapabilityNegotiation.legacy.supportsGatewayMethod("session.active_list"))
        XCTAssertTrue(GatewayCapabilityNegotiation.legacy.supportsGatewayMethod("prompt.background"))
        XCTAssertTrue(GatewayCapabilityNegotiation.legacy.supportsGatewayMethod("computer.screenshot"))
        XCTAssertFalse(GatewayCapabilityNegotiation.legacy.supportsGatewayMethod("voice.record"))
        XCTAssertFalse(GatewayCapabilityNegotiation.legacy.supportsGatewayMethod("session.branch"))
    }

    func testNegotiatorUsesLegacyOnlyForMethodNotFound() async throws {
        let legacy = try await GatewayCapabilityNegotiator.negotiate {
            throw GatewayClientError.rpc(message: "method not found", code: -32_601)
        }
        XCTAssertEqual(legacy, .legacy)

        do {
            _ = try await GatewayCapabilityNegotiator.negotiate {
                throw GatewayClientError.rpc(message: "server error", code: 5_000)
            }
            XCTFail("Expected non-method-not-found RPC error to propagate")
        } catch GatewayClientError.rpc(_, let code, _) {
            XCTAssertEqual(code, 5_000)
        }

        do {
            _ = try await GatewayCapabilityNegotiator.negotiate {
                throw GatewayClientError.requestTimedOut(method: "gateway.capabilities")
            }
            XCTFail("Expected timeout to propagate")
        } catch GatewayClientError.requestTimedOut(let method) {
            XCTAssertEqual(method, "gateway.capabilities")
        }
    }

    func testMalformedSuccessNeverFallsBackToLegacy() async throws {
        let negotiation = try await GatewayCapabilityNegotiator.negotiate {
            ["contract": "not-an-object"]
        }

        guard case .invalid = negotiation else {
            return XCTFail("Malformed success must fail closed")
        }
    }

    /// The optional method-backed families introduced alongside durable_work.
    private let newOptionalFamilies = [
        "artifact_fetch",
        "connected_nodes",
        "device_node",
        "node_invoke",
        "push",
        "session_admin",
        "trust_center",
        "workspace_read",
    ]

    func testRegistryFixtureMatchesCompiledFeatureGovernance() throws {
        let registry = try fixtureObject("gateway-feature-registry-v1.json")

        let contract = try XCTUnwrap(registry["contract"] as? [String: Any])
        XCTAssertEqual(contract["name"] as? String, "fabric.gateway")
        XCTAssertEqual((contract["version"] as? NSNumber)?.intValue, gatewayClientContractVersion)

        let baseline = try XCTUnwrap(registry["baseline_features"] as? [String: [String]])
        XCTAssertEqual(baseline.mapValues { Set($0) }, gatewayFeatureMethods)

        let optional = try XCTUnwrap(registry["optional_features"] as? [String: [String]])
        XCTAssertEqual(optional.mapValues { Set($0) }, optionalGatewayFeatureMethods)

        let flags = try XCTUnwrap(registry["flag_only_optional_features"] as? [String])
        XCTAssertEqual(Set(flags), optionalGatewayFeatureFlags)

        let legacy = try XCTUnwrap(registry["legacy_mobile_methods"] as? [String])
        XCTAssertEqual(Set(legacy), legacyMobileMethods)
    }

    func testFamiliesFixtureVerifiesEveryNewFamilyWithDurableWorkDark() throws {
        let negotiation = GatewayCapabilitiesParser.parse(
            try fixtureObject("gateway-capabilities-families-v1.json")
        )

        guard case .verified(let capabilities) = negotiation else {
            return XCTFail("Expected verified capabilities, got \(negotiation)")
        }
        for family in newOptionalFamilies {
            XCTAssertEqual(capabilities.features[family], true, family)
        }
        XCTAssertEqual(capabilities.features["scoped_grants"], true)
        XCTAssertEqual(capabilities.features["durable_work"], false)
        XCTAssertFalse(negotiation.supportsDurableWork)
    }

    func testRejectsFamilyWhoseRequiredMethodSetIsMissing() throws {
        let negotiation = GatewayCapabilitiesParser.parse(
            try fixtureObject("gateway-capabilities-family-contradiction.json")
        )

        guard case .invalid(let reason) = negotiation else {
            return XCTFail("Expected contradictory family fixture to be invalid")
        }
        XCTAssertTrue(reason.contains("trust_center"))
    }

    func testOriginalFixtureStillVerifiesWithEveryOptionalFamilyFalse() throws {
        let negotiation = GatewayCapabilitiesParser.parse(
            try fixtureObject("gateway-capabilities-v1.json")
        )

        guard case .verified(let capabilities) = negotiation else {
            return XCTFail("Expected verified capabilities, got \(negotiation)")
        }
        for family in newOptionalFamilies {
            XCTAssertEqual(capabilities.features[family], false, family)
        }
        XCTAssertEqual(capabilities.features["scoped_grants"], false)
        XCTAssertEqual(capabilities.features["durable_work"], false)
    }

    func testRejectsAdvertisedFalseFamilyWhoseMethodsAreAllPresent() throws {
        var payload = try fixtureObject("gateway-capabilities-families-v1.json")
        var features = try XCTUnwrap(payload["features"] as? [String: Any])
        features["push"] = false
        payload["features"] = features

        guard case .invalid(let reason) = GatewayCapabilitiesParser.parse(payload) else {
            return XCTFail("Expected advertised-false push family to be invalid")
        }
        XCTAssertTrue(reason.contains("push"))
    }

    private let petsFamilyMethods = [
        "pet.info",
        "pet.info.meta",
        "pet.gallery",
        "pet.select",
        "pet.disable",
        "pet.thumb",
    ]

    func testPetsFamilyVerifiesWhenAdvertisedWithItsFullMethodSet() throws {
        var payload = try fixtureObject("gateway-capabilities-v1.json")
        var methods = try XCTUnwrap(payload["methods"] as? [Any])
        methods.append(contentsOf: petsFamilyMethods as [Any])
        payload["methods"] = methods
        var features = try XCTUnwrap(payload["features"] as? [String: Any])
        features["pets"] = true
        payload["features"] = features

        let negotiation = GatewayCapabilitiesParser.parse(payload)

        guard case .verified(let capabilities) = negotiation else {
            return XCTFail("Expected verified capabilities, got \(negotiation)")
        }
        XCTAssertEqual(capabilities.features["pets"], true)
        XCTAssertTrue(negotiation.supportsGatewayFeature("pets"))
        for method in petsFamilyMethods {
            XCTAssertTrue(negotiation.supportsGatewayMethod(method), method)
        }
    }

    func testPetsAdvertisedWithoutItsMethodsIsInvalid() throws {
        var payload = try fixtureObject("gateway-capabilities-v1.json")
        var features = try XCTUnwrap(payload["features"] as? [String: Any])
        features["pets"] = true
        payload["features"] = features

        guard case .invalid(let reason) = GatewayCapabilitiesParser.parse(payload) else {
            return XCTFail("Expected pets without its method family to be invalid")
        }
        XCTAssertTrue(reason.contains("pets"))
    }

    func testBaseFixtureLeavesPetsUnavailable() throws {
        let negotiation = GatewayCapabilitiesParser.parse(
            try fixtureObject("gateway-capabilities-v1.json")
        )

        guard case .verified(let capabilities) = negotiation else {
            return XCTFail("Expected verified capabilities, got \(negotiation)")
        }
        XCTAssertEqual(capabilities.features["pets"], false)
        XCTAssertFalse(negotiation.supportsGatewayFeature("pets"))
    }

    func testPetSpriteSheetDecodesOnlyEnabledPayloadsWithSaneGeometry() {
        let payload: [String: Any] = [
            "enabled": true,
            "slug": "buddy",
            "displayName": "Buddy",
            "mime": "image/webp",
            "spritesheetBase64": "AAAA",
            "spritesheetRevision": "12345:678",
            "frameW": 192,
            "frameH": 208,
            "framesPerState": 8,
            "framesByState": ["idle": 4],
            "framesByRow": ["idle": 4, "waving": 6],
            "loopMs": 900,
            "scale": 1.0,
            "stateRows": ["idle", "waving"],
        ]

        let sheet = PetSpriteSheet.from(payload: payload)
        XCTAssertEqual(sheet?.slug, "buddy")
        XCTAssertEqual(sheet?.displayName, "Buddy")
        XCTAssertEqual(sheet?.spritesheetRevision, "12345:678")
        XCTAssertEqual(sheet?.frameW, 192)
        XCTAssertEqual(sheet?.frameH, 208)
        XCTAssertEqual(sheet?.framesByRow["waving"], 6)
        XCTAssertEqual(sheet?.stateRows, ["idle", "waving"])

        XCTAssertNil(PetSpriteSheet.from(payload: ["enabled": false]))

        var degenerate = payload
        degenerate["frameW"] = 0
        XCTAssertNil(PetSpriteSheet.from(payload: degenerate))
    }

    func testScopedGrantsIsAPureFlagWithNoMethodSetCheck() throws {
        let canonical = try fixtureObject("gateway-capabilities-v1.json")

        var nonBoolean = canonical
        var features = try XCTUnwrap(nonBoolean["features"] as? [String: Any])
        features["scoped_grants"] = "yes"
        nonBoolean["features"] = features
        guard case .invalid(let reason) = GatewayCapabilitiesParser.parse(nonBoolean) else {
            return XCTFail("Expected non-boolean scoped_grants to be invalid")
        }
        XCTAssertTrue(reason.contains("scoped_grants"))

        var explicitFalse = canonical
        var falseFeatures = try XCTUnwrap(explicitFalse["features"] as? [String: Any])
        falseFeatures["scoped_grants"] = false
        explicitFalse["features"] = falseFeatures
        let negotiation = GatewayCapabilitiesParser.parse(explicitFalse)
        guard case .verified(let capabilities) = negotiation else {
            return XCTFail("Expected explicit-false scoped_grants to remain verified")
        }
        XCTAssertEqual(capabilities.features["scoped_grants"], false)
        XCTAssertFalse(negotiation.supportsGatewayFeature("scoped_grants"))
    }

    func testSupportsGatewayFeatureOnlyOnVerifiedContractsAdvertisingTrue() throws {
        let families = GatewayCapabilitiesParser.parse(
            try fixtureObject("gateway-capabilities-families-v1.json")
        )
        XCTAssertTrue(families.supportsGatewayFeature("trust_center"))
        XCTAssertTrue(families.supportsGatewayFeature("scoped_grants"))
        XCTAssertFalse(families.supportsGatewayFeature("durable_work"))

        let verified = GatewayCapabilitiesParser.parse(
            try fixtureObject("gateway-capabilities-v1.json")
        )
        XCTAssertTrue(verified.supportsGatewayFeature("baseline_chat"))
        XCTAssertFalse(verified.supportsGatewayFeature("trust_center"))

        // Legacy gateways advertise every baseline_chat method, but a feature
        // is only real on a verified contract.
        XCTAssertFalse(GatewayCapabilityNegotiation.legacy.supportsGatewayFeature("baseline_chat"))
        XCTAssertFalse(GatewayCapabilityNegotiation.legacy.supportsGatewayFeature("trust_center"))
        XCTAssertFalse(GatewayCapabilityNegotiation.negotiating.supportsGatewayFeature("baseline_chat"))
        XCTAssertFalse(
            GatewayCapabilityNegotiation.incompatible(minimumCompatibleVersion: 2)
                .supportsGatewayFeature("baseline_chat")
        )
        XCTAssertFalse(
            GatewayCapabilityNegotiation.invalid(reason: "bad")
                .supportsGatewayFeature("baseline_chat")
        )
    }

    @MainActor
    func testScreenCaptureDecoderAcceptsOnlyMatchingBoundedPNGMetadata() throws {
        let expected = makeScreenCapture(width: 12, height: 8, color: .systemBlue)

        let decoded = try GatewayAPI.decodeScreenCapture([
            "png_b64": expected.image.base64EncodedString(),
            "width": 12,
            "height": 8,
        ])

        XCTAssertEqual(decoded.image, expected.image)
        XCTAssertEqual(decoded.width, 12)
        XCTAssertEqual(decoded.height, 8)
    }

    @MainActor
    func testScreenCaptureDecoderAcceptsJPEGAndRequiresAdvertisedMIMEToMatch() throws {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let renderer = UIGraphicsImageRenderer(
            size: CGSize(width: 14, height: 9),
            format: format
        )
        let image = renderer.image { context in
            UIColor.systemOrange.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 14, height: 9))
        }
        let jpeg = try XCTUnwrap(image.jpegData(compressionQuality: 0.85))

        let decoded = try GatewayAPI.decodeScreenCapture([
            "png_b64": jpeg.base64EncodedString(),
            "width": 14,
            "height": 9,
            "mime": "image/jpeg",
        ])

        XCTAssertEqual(decoded.image, jpeg)
        XCTAssertEqual(decoded.width, 14)
        XCTAssertEqual(decoded.height, 9)

        assertInvalidScreenCapture([
            "png_b64": jpeg.base64EncodedString(),
            "width": 14,
            "height": 9,
            "mime": "image/png",
        ])
    }

    @MainActor
    func testScreenCaptureDecoderRejectsEncodedPayloadBeforeBase64DecodeLimit() {
        let expected = makeScreenCapture(width: 4, height: 3, color: .systemPurple)
        let encoded = expected.image.base64EncodedString()
        let limits = ScreenCaptureValidationLimits(
            maxEncodedBytes: encoded.utf8.count - 1,
            maxDecodedBytes: expected.image.count,
            maxDimension: 6_144,
            maxPixelCount: 22_000_000
        )

        assertInvalidScreenCapture([
            "png_b64": encoded,
            "width": 4,
            "height": 3,
        ], limits: limits)
    }

    @MainActor
    func testScreenCaptureDecoderRejectsInvalidReportedOrActualDimensions() {
        let expected = makeScreenCapture(width: 10, height: 6, color: .systemGreen)
        let encoded = expected.image.base64EncodedString()

        assertInvalidScreenCapture([
            "png_b64": encoded,
            "width": 11,
            "height": 6,
        ])
        assertInvalidScreenCapture([
            "png_b64": encoded,
            "width": 0,
            "height": 6,
        ])
        assertInvalidScreenCapture([
            "png_b64": encoded,
            "width": true,
            "height": 6,
        ])

        let dimensionLimit = ScreenCaptureValidationLimits(
            maxEncodedBytes: encoded.utf8.count,
            maxDecodedBytes: expected.image.count,
            maxDimension: 9,
            maxPixelCount: 22_000_000
        )
        assertInvalidScreenCapture([
            "png_b64": encoded,
            "width": 10,
            "height": 6,
        ], limits: dimensionLimit)

        let pixelLimit = ScreenCaptureValidationLimits(
            maxEncodedBytes: encoded.utf8.count,
            maxDecodedBytes: expected.image.count,
            maxDimension: 6_144,
            maxPixelCount: 59
        )
        assertInvalidScreenCapture([
            "png_b64": encoded,
            "width": 10,
            "height": 6,
        ], limits: pixelLimit)
    }

    @MainActor
    func testScreenCaptureDecoderRejectsUnsupportedFormatAndOversizedDecodedData() {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let renderer = UIGraphicsImageRenderer(
            size: CGSize(width: 8, height: 5),
            format: format
        )
        let image = renderer.image { context in
            UIColor.systemOrange.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 8, height: 5))
        }

        assertInvalidScreenCapture([
            "png_b64": Data("GIF89a unsupported".utf8).base64EncodedString(),
            "width": 8,
            "height": 5,
        ])

        let png = image.pngData() ?? Data()
        let decodedLimit = ScreenCaptureValidationLimits(
            maxEncodedBytes: png.base64EncodedString().utf8.count,
            maxDecodedBytes: max(0, png.count - 1),
            maxDimension: 6_144,
            maxPixelCount: 22_000_000
        )
        assertInvalidScreenCapture([
            "png_b64": png.base64EncodedString(),
            "width": 8,
            "height": 5,
        ], limits: decodedLimit)
    }

    @MainActor
    func testLiveViewCapabilityChangesStopAndResumeCaptureDynamically() async {
        let probe = ImmediateLiveViewCaptureProbe(outcomes: [
            .capture(makeScreenCapture(width: 2, height: 2, color: .systemPurple)),
            .capture(makeScreenCapture(width: 3, height: 3, color: .systemBlue)),
        ])
        let model = LiveViewModel(
            supportsCapture: false,
            interval: .seconds(60),
            capture: probe.capture
        )

        model.appear(sceneIsActive: true)
        model.retry()
        await Task.yield()

        XCTAssertTrue(model.isUnsupported)
        XCTAssertFalse(model.isPolling)
        XCTAssertEqual(probe.callCount, 0)
        XCTAssertNil(model.frame)

        model.setCaptureCapability(.supported)
        await assertEventually { probe.callCount == 1 && model.frame != nil }
        XCTAssertFalse(model.isUnsupported)

        model.setCaptureCapability(.unsupported)
        await assertEventually { !model.isPolling }
        XCTAssertTrue(model.isUnsupported)
        XCTAssertNil(model.frame)

        model.setCaptureCapability(.supported)
        await assertEventually { probe.callCount == 2 && model.frame != nil }
        XCTAssertEqual(model.frame?.dimensions, "3×3")
        model.setPaused(true)
    }

    @MainActor
    func testLiveViewPreservesVerifiedFrameAcrossNegotiatingReconnect() async throws {
        let verifiedNegotiation = GatewayCapabilitiesParser.parse(
            try fixtureObject("gateway-capabilities-v1.json")
        )
        let verifiedCapability = LiveViewCaptureCapability(
            negotiation: verifiedNegotiation
        )
        XCTAssertEqual(verifiedCapability, .supported)
        XCTAssertEqual(
            LiveViewCaptureCapability(negotiation: .negotiating),
            .negotiating
        )

        let firstFrame = makeScreenCapture(width: 5, height: 3, color: .systemPurple)
        let probe = ImmediateLiveViewCaptureProbe(outcomes: [
            .capture(firstFrame),
            .capture(makeScreenCapture(width: 8, height: 6, color: .systemBlue)),
        ])
        let model = LiveViewModel(
            captureCapability: verifiedCapability,
            connectionReady: true,
            interval: .seconds(60),
            capture: probe.capture
        )

        model.appear(sceneIsActive: true)
        await assertEventually { probe.callCount == 1 && model.frame != nil }
        let verifiedImage = model.frame?.image
        XCTAssertEqual(model.lastVerifiedSupportsCapture, true)

        model.setCaptureCapability(
            LiveViewCaptureCapability(negotiation: .negotiating)
        )
        model.setConnectionReady(false)
        await assertEventually { !model.isPolling }

        XCTAssertEqual(model.captureCapability, .negotiating)
        XCTAssertEqual(model.lastVerifiedSupportsCapture, true)
        XCTAssertFalse(model.isUnsupported)
        XCTAssertTrue(model.frame?.image === verifiedImage)
        XCTAssertTrue(model.isFrameStale)
        XCTAssertEqual(model.statusTone, .warning)
        XCTAssertEqual(probe.callCount, 1)

        model.setCaptureCapability(
            LiveViewCaptureCapability(negotiation: verifiedNegotiation)
        )
        model.setConnectionReady(true)
        await assertEventually {
            probe.callCount == 2 && model.frame?.dimensions == "8×6"
        }
        XCTAssertEqual(model.lastVerifiedSupportsCapture, true)
        XCTAssertFalse(model.isFrameStale)
        model.setPaused(true)
    }

    @MainActor
    func testLiveViewKeepsOneCaptureInFlightAcrossCancellationAndPresentationRaces() async {
        let probe = SuspendedLiveViewCaptureProbe(
            capture: makeScreenCapture(width: 3, height: 2, color: .systemBlue)
        )
        let model = LiveViewModel(
            supportsCapture: true,
            interval: .seconds(60),
            capture: probe.capture
        )

        model.appear(sceneIsActive: true)
        await assertEventually { probe.callCount == 1 }

        // Exercise every restart edge while the transport deliberately
        // ignores cancellation. None may open a second screenshot request.
        model.setPaused(true)
        model.setPaused(false)
        model.setSceneActive(false)
        model.setSceneActive(true)
        model.disappear()
        XCTAssertTrue(model.shouldObscureContent)
        model.appear(sceneIsActive: true)
        XCTAssertFalse(model.shouldObscureContent)
        model.retry()
        await Task.yield()

        XCTAssertEqual(probe.callCount, 1)
        XCTAssertEqual(probe.maximumInFlight, 1)

        probe.succeedPending()
        await assertEventually { probe.callCount == 2 }
        XCTAssertEqual(probe.maximumInFlight, 1)
        // The cancelled first result must not become visible while the new
        // lifecycle generation is waiting for its own frame.
        XCTAssertNil(model.frame)

        model.setPaused(true)
        probe.succeedPending()
        await assertEventually { !model.isPolling }
        XCTAssertEqual(probe.maximumInFlight, 1)
    }

    @MainActor
    func testLiveViewStopsOffscreenAndRefreshesImmediatelyOnResume() async {
        let capture = makeScreenCapture(width: 4, height: 3, color: .systemGreen)
        let probe = ImmediateLiveViewCaptureProbe(outcomes: Array(
            repeating: .capture(capture),
            count: 4
        ))
        let model = LiveViewModel(
            supportsCapture: true,
            interval: .seconds(60),
            capture: probe.capture
        )

        model.appear(sceneIsActive: true)
        await assertEventually { probe.callCount == 1 && model.frame != nil }
        XCTAssertFalse(model.shouldObscureContent)

        model.setPaused(true)
        await assertEventually { !model.isPolling }
        XCTAssertTrue(model.isFrameStale)
        await briefYield()
        XCTAssertEqual(probe.callCount, 1)

        model.setPaused(false)
        await assertEventually { probe.callCount == 2 }

        model.setSceneActive(false)
        await assertEventually { !model.isPolling }
        XCTAssertTrue(model.shouldObscureContent)
        await briefYield()
        XCTAssertEqual(probe.callCount, 2)

        model.setSceneActive(true)
        await assertEventually { probe.callCount == 3 }
        XCTAssertFalse(model.shouldObscureContent)

        model.disappear()
        await assertEventually { !model.isPolling }
        XCTAssertTrue(model.shouldObscureContent)
        model.setSceneActive(false)
        model.setSceneActive(true)
        await briefYield()
        XCTAssertEqual(probe.callCount, 3)
    }

    @MainActor
    func testForegroundReconnectWaitsForReadinessAndRecoversWithoutRetry() async {
        let probe = ImmediateLiveViewCaptureProbe(outcomes: [
            .failure(GatewayClientError.socketClosed),
            .capture(makeScreenCapture(width: 8, height: 5, color: .systemCyan)),
            .capture(makeScreenCapture(width: 8, height: 5, color: .systemCyan)),
        ])
        let model = LiveViewModel(
            supportsCapture: true,
            connectionReady: false,
            interval: .milliseconds(10),
            capture: probe.capture
        )

        model.appear(sceneIsActive: false)
        XCTAssertTrue(model.shouldObscureContent)
        XCTAssertNil(model.frame)
        XCTAssertFalse(model.isConnectionReady)
        XCTAssertEqual(model.statusTone, .info)
        model.setSceneActive(true)
        await briefYield()
        XCTAssertEqual(probe.callCount, 0)
        XCTAssertFalse(model.retryRequired)

        // The session reconnect completing opens the gate. A socket-close
        // race from that window remains recoverable and the sequential loop
        // obtains a frame without requiring a user Retry.
        model.setConnectionReady(true)
        await assertEventually {
            probe.callCount >= 2
                && model.frame?.dimensions == "8×5"
                && !model.retryRequired
        }
        XCTAssertEqual(probe.maximumInFlight, 1)
        model.setPaused(true)
    }

    @MainActor
    func testRawTransportFailureDoesNotLatchRetryAcrossReconnect() async {
        let probe = ImmediateLiveViewCaptureProbe(outcomes: [
            .failure(URLError(.networkConnectionLost)),
            .capture(makeScreenCapture(width: 6, height: 4, color: .systemMint)),
        ])
        let model = LiveViewModel(
            supportsCapture: true,
            interval: .seconds(60),
            capture: probe.capture
        )

        model.appear(sceneIsActive: true)
        await assertEventually { probe.callCount == 1 }
        await assertEventually { !model.isCaptureInFlight }
        XCTAssertFalse(model.retryRequired)
        XCTAssertNil(model.frame)

        model.setConnectionReady(false)
        XCTAssertFalse(model.retryRequired)
        model.setConnectionReady(true)
        await assertEventually {
            probe.callCount == 2 && model.frame?.dimensions == "6×4"
        }
        XCTAssertFalse(model.retryRequired)
        model.setPaused(true)
    }

    @MainActor
    func testUnclassifiedTransportRetryLatchClearsOnAuthoritativeReconnect() async {
        let rawTransportError = NSError(
            domain: NSPOSIXErrorDomain,
            code: 5,
            userInfo: [NSLocalizedDescriptionKey: "raw transport failure"]
        )
        let probe = ImmediateLiveViewCaptureProbe(outcomes: [
            .failure(rawTransportError),
            .capture(makeScreenCapture(width: 7, height: 5, color: .systemCyan)),
        ])
        let model = LiveViewModel(
            supportsCapture: true,
            interval: .seconds(60),
            capture: probe.capture
        )

        model.appear(sceneIsActive: true)
        await assertEventually {
            probe.callCount == 1
                && model.retryRequired
                && !model.isCaptureInFlight
        }

        model.setConnectionReady(false)
        XCTAssertFalse(model.retryRequired)
        model.setConnectionReady(true)
        await assertEventually {
            probe.callCount == 2 && model.frame?.dimensions == "7×5"
        }
        XCTAssertFalse(model.retryRequired)
        model.setPaused(true)
    }

    @MainActor
    func testHungRefreshLabelsRetainedFrameAsLastFrame() async {
        let probe = RefreshSuspensionLiveViewCaptureProbe(
            firstCapture: makeScreenCapture(
                width: 9,
                height: 6,
                color: .systemPurple
            )
        )
        let model = LiveViewModel(
            supportsCapture: true,
            interval: .milliseconds(1),
            capture: probe.capture
        )

        model.appear(sceneIsActive: true)
        await assertEventually {
            probe.callCount == 2
                && model.frame?.dimensions == "9×6"
                && model.isCaptureInFlight
        }

        XCTAssertEqual(model.statusText, "Refreshing · last frame")
        XCTAssertEqual(model.frameAccessibilityLabel, "Last available screen frame")
        XCTAssertEqual(model.statusTone, .info)
        XCTAssertFalse(model.isFrameStale)
        XCTAssertEqual(probe.maximumInFlight, 1)

        model.setPaused(true)
        probe.succeedPending()
        await assertEventually { !model.isPolling && !model.isCaptureInFlight }
        XCTAssertEqual(probe.maximumInFlight, 1)
    }

    @MainActor
    func testLiveViewMarksTransientFrameStaleAndStopsOnHardFailure() async {
        let firstCapture = makeScreenCapture(width: 5, height: 4, color: .systemOrange)
        let recoveredCapture = makeScreenCapture(width: 7, height: 6, color: .systemIndigo)
        let probe = ImmediateLiveViewCaptureProbe(outcomes: [
            .capture(firstCapture),
            .failure(GatewayClientError.requestTimedOut(method: "computer.screenshot")),
            .capture(recoveredCapture),
            .failure(GatewayClientError.rpc(message: "Screen capture stopped on the host.")),
        ])
        let model = LiveViewModel(
            supportsCapture: true,
            interval: .seconds(60),
            capture: probe.capture
        )

        model.appear(sceneIsActive: true)
        await assertEventually { probe.callCount == 1 && model.frame != nil }
        let firstImage = model.frame?.image
        XCTAssertEqual(model.frame?.dimensions, "5×4")
        XCTAssertFalse(model.isFrameStale)

        model.retry()
        await assertEventually {
            probe.callCount == 2 && model.isFrameStale && model.errorText != nil
        }
        XCTAssertFalse(model.retryRequired)
        XCTAssertTrue(model.frame?.image === firstImage)
        model.setPaused(true)
        XCTAssertEqual(
            model.staleNoticeText,
            "Last frame shown. Live view refresh timed out. Live view is paused."
        )
        XCTAssertFalse(model.staleNoticeText?.contains("Retrying") == true)

        model.retry()
        await assertEventually {
            probe.callCount == 3 && !model.isFrameStale && model.frame?.dimensions == "7×6"
        }
        let recoveredImage = model.frame?.image
        XCTAssertFalse(recoveredImage === firstImage)

        model.retry()
        await assertEventually {
            probe.callCount == 4 && model.retryRequired && !model.isPolling
        }
        XCTAssertTrue(model.isFrameStale)
        XCTAssertTrue(model.frame?.image === recoveredImage)
        XCTAssertEqual(model.errorText, "Live view stopped on the Fabric computer.")
    }

    @MainActor
    func testInitialLiveViewFailureWaitsForExplicitRetry() async {
        let probe = ImmediateLiveViewCaptureProbe(outcomes: [
            .failure(GatewayClientError.rpc(message: "Capture service is unavailable.")),
            .capture(makeScreenCapture(width: 2, height: 1, color: .systemTeal)),
        ])
        let model = LiveViewModel(
            supportsCapture: true,
            interval: .seconds(60),
            capture: probe.capture
        )

        model.appear(sceneIsActive: true)
        await assertEventually {
            probe.callCount == 1 && model.retryRequired && !model.isPolling
        }
        await briefYield()
        XCTAssertEqual(probe.callCount, 1)
        XCTAssertNil(model.frame)
        XCTAssertEqual(model.errorText, "Live view stopped on the Fabric computer.")

        model.retry()
        await assertEventually {
            probe.callCount == 2 && model.frame != nil && !model.retryRequired
        }
        XCTAssertEqual(model.frame?.dimensions, "2×1")
    }

    @MainActor
    func testLiveViewNeverPublishesRawRPCFailureText() async {
        let probe = ImmediateLiveViewCaptureProbe(outcomes: [
            .failure(GatewayClientError.rpc(
                message: "Authorization: Bearer raw-secret /Users/private/.fabric"
            )),
        ])
        let model = LiveViewModel(
            supportsCapture: true,
            interval: .seconds(60),
            capture: probe.capture
        )

        model.appear(sceneIsActive: true)
        await assertEventually {
            probe.callCount == 1 && model.retryRequired && !model.isPolling
        }

        XCTAssertEqual(model.errorText, "Live view stopped on the Fabric computer.")
        XCTAssertFalse(model.errorText?.contains("raw-secret") == true)
        XCTAssertFalse(model.errorText?.contains("/Users/private") == true)
    }

    private func fixtureObject(_ name: String) throws -> [String: Any] {
        let value = try fixtureValue(name)
        return try XCTUnwrap(value as? [String: Any])
    }

    private func fixtureArray(_ name: String) throws -> [Any] {
        let value = try fixtureValue(name)
        return try XCTUnwrap(value as? [Any])
    }

    private func fixtureValue(_ name: String) throws -> Any {
        let fileURL = URL(fileURLWithPath: name)
        let fixtureURL = try XCTUnwrap(Bundle(for: Self.self).url(
            forResource: fileURL.deletingPathExtension().lastPathComponent,
            withExtension: fileURL.pathExtension
        ))
        let data = try Data(contentsOf: fixtureURL)
        return try JSONSerialization.jsonObject(with: data)
    }

    private func assertInvalidScreenCapture(
        _ payload: [String: Any],
        limits: ScreenCaptureValidationLimits = .production,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertThrowsError(
            try GatewayAPI.decodeScreenCapture(payload, limits: limits),
            file: file,
            line: line
        ) { error in
            XCTAssertEqual(
                error.localizedDescription,
                "Live view unavailable on this server.",
                file: file,
                line: line
            )
        }
    }
}

@MainActor
private enum LiveViewCaptureOutcome {
    case capture(ScreenCapture)
    case failure(Error)
}

@MainActor
private final class ImmediateLiveViewCaptureProbe {
    private var outcomes: [LiveViewCaptureOutcome]
    private(set) var callCount = 0
    private(set) var maximumInFlight = 0
    private var inFlight = 0

    init(outcomes: [LiveViewCaptureOutcome]) {
        self.outcomes = outcomes
    }

    func capture() async throws -> ScreenCapture {
        callCount += 1
        inFlight += 1
        maximumInFlight = max(maximumInFlight, inFlight)
        defer { inFlight -= 1 }

        guard !outcomes.isEmpty else {
            throw GatewayClientError.rpc(message: "Unexpected capture request.")
        }
        switch outcomes.removeFirst() {
        case .capture(let capture):
            return capture
        case .failure(let error):
            throw error
        }
    }
}

@MainActor
private final class SuspendedLiveViewCaptureProbe {
    private let captureValue: ScreenCapture
    private var continuation: CheckedContinuation<ScreenCapture, Error>?
    private(set) var callCount = 0
    private(set) var maximumInFlight = 0
    private var inFlight = 0

    init(capture: ScreenCapture) {
        captureValue = capture
    }

    func capture() async throws -> ScreenCapture {
        callCount += 1
        inFlight += 1
        maximumInFlight = max(maximumInFlight, inFlight)
        defer { inFlight -= 1 }
        return try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
        }
    }

    func succeedPending() {
        let pending = continuation
        continuation = nil
        pending?.resume(returning: captureValue)
    }
}

@MainActor
private final class RefreshSuspensionLiveViewCaptureProbe {
    private let firstCapture: ScreenCapture
    private var continuation: CheckedContinuation<ScreenCapture, Error>?
    private(set) var callCount = 0
    private(set) var maximumInFlight = 0
    private var inFlight = 0

    init(firstCapture: ScreenCapture) {
        self.firstCapture = firstCapture
    }

    func capture() async throws -> ScreenCapture {
        callCount += 1
        inFlight += 1
        maximumInFlight = max(maximumInFlight, inFlight)
        defer { inFlight -= 1 }

        if callCount == 1 { return firstCapture }
        return try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
        }
    }

    func succeedPending() {
        let pending = continuation
        continuation = nil
        pending?.resume(returning: firstCapture)
    }
}

@MainActor
private func makeScreenCapture(width: Int, height: Int, color: UIColor) -> ScreenCapture {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    let renderer = UIGraphicsImageRenderer(
        size: CGSize(width: width, height: height),
        format: format
    )
    let image = renderer.image { context in
        color.setFill()
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    }
    return ScreenCapture(
        image: image.pngData() ?? Data(),
        width: width,
        height: height
    )
}

@MainActor
private func eventually(_ predicate: () -> Bool) async -> Bool {
    for _ in 0..<500 {
        if predicate() { return true }
        try? await Task.sleep(for: .milliseconds(2))
    }
    return predicate()
}

@MainActor
private func assertEventually(
    _ predicate: () -> Bool,
    file: StaticString = #filePath,
    line: UInt = #line
) async {
    let matched = await eventually(predicate)
    XCTAssertTrue(matched, "Timed out waiting for condition", file: file, line: line)
}

@MainActor
private func briefYield() async {
    try? await Task.sleep(for: .milliseconds(20))
}
