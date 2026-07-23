import Foundation
import XCTest
@testable import Fabric

final class TranscriptArtifactsTests: XCTestCase {
    private func session(id: String = "s1", title: String = "My session") -> SessionSummary {
        SessionSummary(
            id: id,
            title: title,
            preview: "",
            startedAt: 0,
            messageCount: 4,
            source: "mobile"
        )
    }

    private func collect(_ messages: [SessionTranscriptMessage]) -> [TranscriptArtifact] {
        TranscriptArtifactExtraction.collect(session: session(), messages: messages)
    }

    // MARK: - Kinds

    func testExtractsMarkdownImageAsImage() {
        let items = collect([
            SessionTranscriptMessage(role: .assistant, text: "Here ![chart](https://ex.com/a.png) done")
        ])
        XCTAssertEqual(items.count, 1)
        XCTAssertEqual(items.first?.kind, .image)
        XCTAssertEqual(items.first?.value, "https://ex.com/a.png")
        XCTAssertEqual(items.first?.label, "a.png")
    }

    func testBareImageURLIsImage() {
        let items = collect([
            SessionTranscriptMessage(role: .assistant, text: "See https://ex.com/pic.jpeg for the plot")
        ])
        XCTAssertEqual(items.map(\.kind), [.image])
        XCTAssertEqual(items.first?.value, "https://ex.com/pic.jpeg")
    }

    func testPlainURLIsLink() {
        let items = collect([
            SessionTranscriptMessage(role: .assistant, text: "Docs live at https://example.com/guide")
        ])
        XCTAssertEqual(items.map(\.kind), [.link])
        XCTAssertEqual(items.first?.label, "guide")
    }

    func testAbsolutePathInInlineCodeIsFile() {
        let items = collect([
            SessionTranscriptMessage(role: .assistant, text: "Wrote report to `/home/user/out.pdf` now")
        ])
        XCTAssertEqual(items.map(\.value), ["/home/user/out.pdf"])
        XCTAssertEqual(items.first?.kind, .file)
        XCTAssertEqual(items.first?.label, "out.pdf")
    }

    func testLocalImagePathClassifiesAsImageByExtension() {
        let items = collect([
            SessionTranscriptMessage(role: .tool, text: "/home/user/render.png", toolName: "shell")
        ])
        XCTAssertEqual(items.map(\.kind), [.image])
        XCTAssertEqual(items.first?.value, "/home/user/render.png")
    }

    // MARK: - Filtering & resolution

    func testRelativePathIsDroppedWithoutWorkingDirectory() {
        // Even though it looks like a file, a relative path cannot be resolved
        // without a cwd, so nothing is surfaced.
        let items = collect([
            SessionTranscriptMessage(role: .assistant, text: "Saved to `out/result.txt`")
        ])
        XCTAssertTrue(items.isEmpty)
    }

    func testOnlyAssistantAndToolMessagesAreScanned() {
        let items = collect([
            SessionTranscriptMessage(role: .user, text: "look at https://ex.com/mine.png"),
            SessionTranscriptMessage(role: .system, text: "system /etc/data.json"),
            SessionTranscriptMessage(role: .assistant, text: "ok https://ex.com/yours.png")
        ])
        XCTAssertEqual(items.map(\.value), ["https://ex.com/yours.png"])
    }

    func testDuplicatesWithinSessionAreDeduped() {
        let items = collect([
            SessionTranscriptMessage(role: .assistant, text: "first https://ex.com/a.png"),
            SessionTranscriptMessage(role: .assistant, text: "again https://ex.com/a.png")
        ])
        XCTAssertEqual(items.count, 1)
    }

    func testTrailingPunctuationIsTrimmed() {
        let items = collect([
            SessionTranscriptMessage(role: .assistant, text: "Open (https://ex.com/page.html).")
        ])
        XCTAssertEqual(items.first?.value, "https://ex.com/page.html")
    }

    func testSessionTitleFallsBackToDisplayTitle() {
        let untitled = SessionSummary(
            id: "s2", title: "", preview: "a preview", startedAt: 0, messageCount: 1, source: "mobile"
        )
        let items = TranscriptArtifactExtraction.collect(
            session: untitled,
            messages: [SessionTranscriptMessage(role: .assistant, text: "https://ex.com/x.png")]
        )
        XCTAssertEqual(items.first?.sessionTitle, "a preview")
    }

    // MARK: - Filter helper

    func testFilterMatchesByKind() {
        XCTAssertTrue(ArtifactFilter.all.matches(sample(kind: .link)))
        XCTAssertTrue(ArtifactFilter.images.matches(sample(kind: .image)))
        XCTAssertFalse(ArtifactFilter.files.matches(sample(kind: .image)))
    }

    private func sample(kind: TranscriptArtifactKind) -> TranscriptArtifact {
        TranscriptArtifact(
            id: "s1:v",
            kind: kind,
            value: "v",
            label: "v",
            sessionID: "s1",
            sessionTitle: "t"
        )
    }
}
