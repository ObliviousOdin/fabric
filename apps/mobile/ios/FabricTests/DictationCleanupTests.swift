import Foundation
import XCTest
@testable import Fabric

final class DictationCleanupTests: XCTestCase {
    func testRemovesStandaloneFillers() {
        XCTAssertEqual(DictationCleanup.apply("um hello uh there"), "Hello there.")
    }

    func testKeepsWordsThatContainFillerSubstrings() {
        // "umbrella" and "usher" must not lose their leading letters.
        XCTAssertEqual(DictationCleanup.apply("the umbrella is red"), "The umbrella is red.")
    }

    func testCollapsesImmediateRepeats() {
        XCTAssertEqual(DictationCleanup.apply("I I think the the plan"), "I think the plan.")
    }

    func testCollapsesTripleRepeats() {
        XCTAssertEqual(DictationCleanup.apply("no no no"), "No.")
    }

    func testNormalizesWhitespace() {
        XCTAssertEqual(DictationCleanup.apply("hello    world"), "Hello world.")
        XCTAssertEqual(DictationCleanup.apply("line one\n\n\n\nline two"), "Line one\n\nLine two.")
    }

    func testSentenceCasing() {
        XCTAssertEqual(
            DictationCleanup.apply("this is one. this is two"),
            "This is one. This is two."
        )
    }

    func testAddsTerminalPunctuationOnlyWhenMissing() {
        XCTAssertEqual(DictationCleanup.apply("done"), "Done.")
        XCTAssertEqual(DictationCleanup.apply("done already."), "Done already.")
        XCTAssertEqual(DictationCleanup.apply("really?"), "Really?")
    }

    func testPreservesURLVerbatimAndAddsNoTrailingPeriod() {
        XCTAssertEqual(
            DictationCleanup.apply("see https://example.com/Path_Keeps-Case"),
            "See https://example.com/Path_Keeps-Case"
        )
    }

    func testPreservesURLInTheMiddle() {
        XCTAssertEqual(
            DictationCleanup.apply("open https://example.com/a now"),
            "Open https://example.com/a now."
        )
    }

    func testPreservesBacktickCodeSpan() {
        XCTAssertEqual(
            DictationCleanup.apply("run `git Status --Short` now"),
            "Run `git Status --Short` now."
        )
    }

    func testEmptyStringIsUnchanged() {
        XCTAssertEqual(DictationCleanup.apply(""), "")
    }

    func testIsIdempotent() {
        let inputs = [
            "um so I I think we should, uh, ship it",
            "check https://example.com/x and run `make build`",
            "hello    world\n\n\nthere",
            "done already.",
            "no no no",
        ]
        for input in inputs {
            let once = DictationCleanup.apply(input)
            let twice = DictationCleanup.apply(once)
            XCTAssertEqual(once, twice, "Not idempotent for: \(input)")
        }
    }
}
