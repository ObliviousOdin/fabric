import XCTest
@testable import Fabric

final class VoiceContractTests: XCTestCase {
    func testCanonicalVoiceFixtureCorpus() throws {
        let manifest = try fixtureObject("voice-manifest")
        XCTAssertEqual(manifest["name"] as? String, "fabric.voice.fixture-manifest")
        XCTAssertEqual(manifest["version"] as? Int, 1)
        let cases = try XCTUnwrap(manifest["cases"] as? [[String: Any]])

        for fixtureCase in cases {
            let name = try XCTUnwrap(fixtureCase["file"] as? String)
            let kind = try XCTUnwrap(fixtureCase["kind"] as? String)
            let expected = try XCTUnwrap(fixtureCase["expected"] as? String)
            let data = try fixtureData(String(name.dropLast(5)))
            let actual: String
            if kind == "phone_audio" {
                actual = parseKind(FabricVoiceContractParser.parsePhoneAudio(data))
            } else {
                actual = parseKind(FabricVoiceContractParser.parseTranscription(data))
            }
            XCTAssertEqual(actual, expected, name)
        }
    }

    func testVoiceNoteKeepsCaptureModeAndClientOwnershipExplicit() throws {
        let data = try fixtureData("phone-audio-voice-note")
        guard case .verified(let envelope) = FabricVoiceContractParser.parsePhoneAudio(data) else {
            return XCTFail("Voice note fixture did not verify")
        }
        XCTAssertEqual(envelope.contract, "fabric.phone_audio")
        XCTAssertEqual(envelope.mode, .voiceNote)
        XCTAssertEqual(envelope.result.status, .completed)
    }

    private func parseKind<Value: Equatable>(_ result: FabricVoiceContractParseResult<Value>) -> String {
        switch result {
        case .verified: return "verified"
        case .incompatible: return "incompatible"
        case .invalid: return "invalid"
        }
    }

    private func fixtureData(_ name: String) throws -> Data {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: "json"))
        return try Data(contentsOf: url)
    }

    private func fixtureObject(_ name: String) throws -> [String: Any] {
        let value = try JSONSerialization.jsonObject(with: fixtureData(name))
        return try XCTUnwrap(value as? [String: Any])
    }
}
