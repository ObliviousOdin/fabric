import Foundation
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
