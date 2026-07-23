import Foundation
import XCTest
@testable import Fabric

final class SocialPromptTests: XCTestCase {
    private let base = SocialRequest(
        brief: "Shipping our new agent dashboard after six weeks of work",
        includeImage: true
    )

    func testIncludesBriefChannelAndFenceTag() {
        let prompt = SocialPrompt.build(base)
        XCTAssertTrue(prompt.contains(base.brief))
        XCTAssertTrue(prompt.contains("LinkedIn"))
        XCTAssertTrue(prompt.contains("`\(SocialPrompt.postFence)`"))
    }

    func testAsksForImageOnlyWhenRequested() {
        var withImage = base
        withImage.includeImage = true
        XCTAssertTrue(SocialPrompt.build(withImage).contains("Artifacts"))

        var noImage = base
        noImage.includeImage = false
        let text = SocialPrompt.build(noImage)
        XCTAssertTrue(text.lowercased().contains("text only"))
        XCTAssertFalse(text.contains("Artifacts"))
    }

    func testVariesWithToneGoalAndFormat() {
        var candid = base
        candid.tone = .candid
        var analytical = base
        analytical.tone = .analytical
        XCTAssertNotEqual(SocialPrompt.build(candid), SocialPrompt.build(analytical))

        var authority = base
        authority.goal = .authority
        var engagement = base
        engagement.goal = .engagement
        XCTAssertNotEqual(SocialPrompt.build(authority), SocialPrompt.build(engagement))

        var story = base
        story.format = .hookStory
        var tips = base
        tips.format = .tips
        XCTAssertNotEqual(SocialPrompt.build(story), SocialPrompt.build(tips))
    }

    func testNormalizesWhitespaceAndControlCharacters() {
        var request = base
        request.brief = "line one\n\tline two   spaced"
        let prompt = SocialPrompt.build(request)
        XCTAssertTrue(prompt.contains("line one line two spaced"))
        XCTAssertFalse(prompt.contains("\t"))
    }

    func testIsDeterministic() {
        XCTAssertEqual(SocialPrompt.build(base), SocialPrompt.build(base))
    }
}
