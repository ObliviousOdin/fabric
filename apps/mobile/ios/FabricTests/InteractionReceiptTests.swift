import XCTest
@testable import Fabric

final class InteractionReceiptTests: XCTestCase {
    func testApprovalReceiptRequiresExactRequestAndOneResolution() throws {
        XCTAssertNoThrow(
            try GatewayAPI.requireMatchingInteractionReceipt(
                ["request_id": "approval-2", "resolved": 1],
                requestId: "approval-2",
                approval: true
            )
        )

        XCTAssertThrowsError(
            try GatewayAPI.requireMatchingInteractionReceipt(
                ["request_id": "approval-1", "resolved": 1],
                requestId: "approval-2",
                approval: true
            )
        )
        XCTAssertThrowsError(
            try GatewayAPI.requireMatchingInteractionReceipt(
                ["request_id": "approval-2", "resolved": 0],
                requestId: "approval-2",
                approval: true
            )
        )
    }

    func testGenericPromptReceiptRequiresExactRequest() throws {
        XCTAssertNoThrow(
            try GatewayAPI.requireMatchingInteractionReceipt(
                ["request_id": "secret-2"],
                requestId: "secret-2"
            )
        )
        XCTAssertThrowsError(
            try GatewayAPI.requireMatchingInteractionReceipt(
                ["request_id": "secret-1"],
                requestId: "secret-2"
            )
        )
    }
}
