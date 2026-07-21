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

        model.setCaptureSupported(true)
        await assertEventually { probe.callCount == 1 && model.frame != nil }
        XCTAssertFalse(model.isUnsupported)

        model.setCaptureSupported(false)
        await assertEventually { !model.isPolling }
        XCTAssertTrue(model.isUnsupported)
        XCTAssertNil(model.frame)

        model.setCaptureSupported(true)
        await assertEventually { probe.callCount == 2 && model.frame != nil }
        XCTAssertEqual(model.frame?.dimensions, "3×3")
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
            "Last frame shown. request timed out: computer.screenshot Live view is paused."
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
        XCTAssertEqual(model.errorText, "Screen capture stopped on the host.")
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
        XCTAssertEqual(model.errorText, "Capture service is unavailable.")

        model.retry()
        await assertEventually {
            probe.callCount == 2 && model.frame != nil && !model.retryRequired
        }
        XCTAssertEqual(model.frame?.dimensions, "2×1")
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
private func makeScreenCapture(width: Int, height: Int, color: UIColor) -> ScreenCapture {
    let renderer = UIGraphicsImageRenderer(size: CGSize(width: width, height: height))
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
