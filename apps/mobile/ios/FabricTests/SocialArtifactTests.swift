import Foundation
import XCTest
@testable import Fabric

/// Conformance for the Swift artifact parser. Mirrors the shared fixture at
/// apps/mobile/contracts/social-extraction-v1.json (validated against the
/// TypeScript implementation in apps/shared/src/social-contract.test.ts).
final class SocialArtifactTests: XCTestCase {
    private struct TestMessage: SocialSourceMessage {
        let role: String
        let content: String?
        var timestamp: Int?

        init(_ role: String, _ content: String?, timestamp: Int? = nil) {
            self.role = role
            self.content = content
            self.timestamp = timestamp
        }
    }

    func testCapturesCaptionAndMarkdownImage() {
        let artifacts = SocialExtraction.extract([
            TestMessage("user", "Draft me a launch post."),
            TestMessage(
                "assistant",
                "Here you go:\n\n```linkedin-post\nWe shipped Fabric.\n\nHere is why it matters.\n```\n\n"
                    + "## Artifacts\n\n![Launch graphic](assets/launch.png)",
                timestamp: 1_700_000_000
            ),
        ])

        XCTAssertEqual(artifacts.count, 1)
        XCTAssertEqual(artifacts[0].caption, "We shipped Fabric.\n\nHere is why it matters.")
        XCTAssertEqual(artifacts[0].imagePath, "assets/launch.png")
        XCTAssertEqual(artifacts[0].messageIndex, 1)
        XCTAssertEqual(artifacts[0].timestamp, 1_700_000_000)
        XCTAssertEqual(artifacts[0].id, "1:0")
    }

    func testIgnoresUserMessageNamingTheFence() {
        let messages = [TestMessage("user", "Put the result in a ```linkedin-post``` block please.")]
        XCTAssertTrue(SocialExtraction.extract(messages).isEmpty)
        XCTAssertFalse(SocialExtraction.hasArtifacts(messages))
    }

    func testTextOnlyPostHasNilImageAndTimestamp() {
        let artifact = SocialExtraction.extract([
            TestMessage("assistant", "```linkedin-post\nText only post.\n```"),
        ])[0]
        XCTAssertEqual(artifact.caption, "Text only post.")
        XCTAssertNil(artifact.imagePath)
        XCTAssertNil(artifact.timestamp)
    }

    func testBareImagePathUnderArtifactsIsNotSwallowedByBullet() {
        let artifact = SocialExtraction.extract([
            TestMessage("assistant", "```linkedin-post\nA lesson learned.\n```\n\nArtifacts:\n- ./out/post-image.jpg"),
        ])[0]
        XCTAssertEqual(artifact.imagePath, "./out/post-image.jpg")
    }

    func testIgnoresUnrelatedCodeFence() {
        let artifacts = SocialExtraction.extract([
            TestMessage("assistant", "```python\nprint('not a post')\n```"),
            TestMessage("assistant", "Some prose without any fence."),
        ])
        XCTAssertTrue(artifacts.isEmpty)
    }

    func testCapturesMultipleDraftsInOrder() {
        let artifacts = SocialExtraction.extract([
            TestMessage("assistant", "```linkedin-post\nDraft one.\n```"),
            TestMessage("user", "try another angle"),
            TestMessage("assistant", "```linkedin-post\nDraft two.\n```"),
        ])
        XCTAssertEqual(artifacts.map { $0.caption }, ["Draft one.", "Draft two."])
        XCTAssertEqual(artifacts.map { $0.id }, ["0:0", "2:0"])
    }

    func testDistinguishesRemoteImages() {
        XCTAssertTrue(SocialExtraction.isRemoteImage("https://example.com/a.png"))
        XCTAssertFalse(SocialExtraction.isRemoteImage("assets/launch.png"))
        XCTAssertFalse(SocialExtraction.isRemoteImage("/home/user/out.png"))
    }
}
