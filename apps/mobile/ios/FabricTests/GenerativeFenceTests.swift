import Foundation
import XCTest
@testable import Fabric

final class GenerativeFenceTests: XCTestCase {
    // MARK: - Work fence

    func testWorkSpecParsesTitleStatusAndSteps() {
        let spec = WorkFenceSpec.parse(#"{"title":"Deploy","status":"running","steps":[{"label":"Build","state":"done"}]}"#)
        XCTAssertEqual(spec?.title, "Deploy")
        XCTAssertEqual(spec?.status, .running)
        XCTAssertEqual(spec?.steps, [WorkFenceStep(label: "Build", state: .done)])
    }

    func testWorkSpecDefaultsUnknownStatusAndStepState() {
        let spec = WorkFenceSpec.parse(#"{"title":"X","status":"nope","steps":[{"label":"S","state":"wat"}]}"#)
        XCTAssertEqual(spec?.status, .queued)
        XCTAssertEqual(spec?.steps.first?.state, .pending)
    }

    func testWorkSpecDropsLabellessStepsAndRequiresTitle() {
        XCTAssertNil(WorkFenceSpec.parse(#"{"status":"done"}"#))
        let spec = WorkFenceSpec.parse(#"{"title":"X","steps":[{"state":"done"},{"label":"Keep"}]}"#)
        XCTAssertEqual(spec?.steps, [WorkFenceStep(label: "Keep", state: .pending)])
    }

    func testWorkSpecRejectsInvalidJSONAndBlank() {
        XCTAssertNil(WorkFenceSpec.parse("{not json"))
        XCTAssertNil(WorkFenceSpec.parse("   "))
    }

    // MARK: - Chart fence

    func testChartSpecParsesBarWithFinitePoints() {
        let spec = ChartFenceSpec.parse(#"{"type":"bar","title":"Runs","data":[{"label":"Mon","value":12},{"label":"Tue","value":18}]}"#)
        XCTAssertEqual(spec?.type, .bar)
        XCTAssertEqual(spec?.title, "Runs")
        XCTAssertEqual(spec?.data.count, 2)
        XCTAssertEqual(spec?.data.first, ChartFencePoint(label: "Mon", value: 12))
    }

    func testChartSpecDefaultsTypeAndCoercesNumericStrings() {
        let spec = ChartFenceSpec.parse(#"{"type":"pie","data":[{"label":"A","value":"5"}]}"#)
        XCTAssertEqual(spec?.type, .bar)
        XCTAssertEqual(spec?.data.first?.value, 5)
    }

    func testChartSpecDropsNonFiniteAndRequiresData() {
        let spec = ChartFenceSpec.parse(#"{"data":[{"label":"A","value":3},{"label":"B","value":"nope"}]}"#)
        XCTAssertEqual(spec?.data, [ChartFencePoint(label: "A", value: 3)])
        XCTAssertNil(ChartFenceSpec.parse(#"{"data":[{"value":"x"}]}"#))
        XCTAssertNil(ChartFenceSpec.parse(#"{"type":"bar"}"#))
    }

    func testChartSpecRejectsInvalidJSONAndBlank() {
        XCTAssertNil(ChartFenceSpec.parse("{oops"))
        XCTAssertNil(ChartFenceSpec.parse(""))
    }

    // MARK: - Transcript integration

    func testTranscriptDocumentTagsWorkAndChartFencesAsCodeBlocks() {
        // The generative cards render off the language on an ordinary fenced
        // code block, so the transcript parser must surface that language.
        let document = AssistantTranscriptDocument(
            "```work\n{\"title\":\"X\"}\n```\n\n```chart\n{\"data\":[{\"value\":1}]}\n```"
        )
        let languages = document.blocks.compactMap { block -> String? in
            if case .code(let language, _) = block { return language }
            return nil
        }
        XCTAssertEqual(languages, ["work", "chart"])
    }
}
