import Foundation

let fabricTranscriptionContractVersion = 1
let fabricPhoneAudioContractVersion = 1

enum FabricTranscriptionStatus: String, Codable, Equatable {
    case completed
    case noSpeech = "no_speech"
    case cancelled
    case failed
}

enum FabricPhoneAudioMode: String, Codable, Equatable {
    case dictate
    case voiceNote = "voice_note"
    case askFabric = "ask_fabric"
    case chat
}

private extension KeyedDecodingContainer {
    func decodeOptionalNonNull<T: Decodable>(
        _ type: T.Type,
        forKey key: Key
    ) throws -> T? {
        guard contains(key) else { return nil }
        if try decodeNil(forKey: key) {
            throw DecodingError.valueNotFound(
                type,
                DecodingError.Context(
                    codingPath: codingPath,
                    debugDescription: "Optional contract fields may be omitted but not null."
                )
            )
        }
        return try decode(type, forKey: key)
    }
}

struct FabricTranscriptionSegmentV1: Codable, Equatable {
    let startMS: Int
    let endMS: Int
    let text: String

    enum CodingKeys: String, CodingKey {
        case startMS = "start_ms"
        case endMS = "end_ms"
        case text
    }
}

struct FabricTranscriptionErrorV1: Codable, Equatable {
    let code: String
    let message: String
    let retryable: Bool
}

struct FabricTranscriptionResultV1: Codable, Equatable {
    let schema: String
    let version: Int
    let requestID: String
    let status: FabricTranscriptionStatus
    let text: String
    let provider: String?
    let language: String?
    let durationMS: Int?
    let processingMS: Int?
    let model: String?
    let segments: [FabricTranscriptionSegmentV1]
    let warnings: [String]
    let error: FabricTranscriptionErrorV1?
    fileprivate let containsErrorField: Bool

    enum CodingKeys: String, CodingKey {
        case schema
        case version
        case requestID = "request_id"
        case status
        case text
        case provider
        case language
        case durationMS = "duration_ms"
        case processingMS = "processing_ms"
        case model
        case segments
        case warnings
        case error
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        schema = try values.decode(String.self, forKey: .schema)
        version = try values.decode(Int.self, forKey: .version)
        requestID = try values.decode(String.self, forKey: .requestID)
        status = try values.decode(FabricTranscriptionStatus.self, forKey: .status)
        text = try values.decode(String.self, forKey: .text)
        provider = try values.decodeOptionalNonNull(String.self, forKey: .provider)
        language = try values.decodeOptionalNonNull(String.self, forKey: .language)
        durationMS = try values.decodeOptionalNonNull(Int.self, forKey: .durationMS)
        processingMS = try values.decodeOptionalNonNull(Int.self, forKey: .processingMS)
        model = try values.decodeOptionalNonNull(String.self, forKey: .model)
        segments = try values.decodeOptionalNonNull(
            [FabricTranscriptionSegmentV1].self,
            forKey: .segments
        ) ?? []
        warnings = try values.decodeOptionalNonNull([String].self, forKey: .warnings) ?? []
        containsErrorField = values.contains(.error)
        error = try values.decodeOptionalNonNull(FabricTranscriptionErrorV1.self, forKey: .error)
    }
}

struct FabricPhoneAudioEnvelopeV1: Codable, Equatable {
    let contract: String
    let version: Int
    let captureID: String
    let mode: FabricPhoneAudioMode
    let mimeType: String
    let durationMS: Int
    let result: FabricTranscriptionResultV1

    enum CodingKeys: String, CodingKey {
        case contract
        case version
        case captureID = "capture_id"
        case mode
        case mimeType = "mime_type"
        case durationMS = "duration_ms"
        case result
    }
}

enum FabricVoiceContractParseResult<Value: Equatable>: Equatable {
    case verified(Value)
    case incompatible(contract: String, version: Int)
    case invalid(message: String)
}

private struct FabricTranscriptionHeader: Decodable {
    let schema: String
    let version: Int
}

private struct FabricPhoneAudioHeader: Decodable {
    let contract: String
    let version: Int
}

private struct FabricPhoneAudioV1Header: Decodable {
    let result: FabricTranscriptionHeader
}

enum FabricVoiceContractParser {
    private static let maximumAudioMS = 3_600_000
    private static let maximumTextCharacters = 1_000_000

    static func parseTranscription(
        _ data: Data
    ) -> FabricVoiceContractParseResult<FabricTranscriptionResultV1> {
        do {
            let decoder = JSONDecoder()
            let header = try decoder.decode(FabricTranscriptionHeader.self, from: data)
            guard header.schema == "fabric.transcription" else {
                return .invalid(message: "Transcription schema is unsupported.")
            }
            guard header.version == fabricTranscriptionContractVersion else {
                return .incompatible(contract: header.schema, version: header.version)
            }
            let result = try decoder.decode(FabricTranscriptionResultV1.self, from: data)
            return try validate(result)
        } catch {
            return .invalid(message: "Transcription result is malformed.")
        }
    }

    static func parsePhoneAudio(
        _ data: Data
    ) -> FabricVoiceContractParseResult<FabricPhoneAudioEnvelopeV1> {
        do {
            let decoder = JSONDecoder()
            let header = try decoder.decode(FabricPhoneAudioHeader.self, from: data)
            guard header.contract == "fabric.phone_audio" else {
                return .invalid(message: "Phone audio contract is unsupported.")
            }
            guard header.version == fabricPhoneAudioContractVersion else {
                return .incompatible(contract: header.contract, version: header.version)
            }
            let v1Header = try decoder.decode(FabricPhoneAudioV1Header.self, from: data)
            guard v1Header.result.schema == "fabric.transcription" else {
                return .invalid(message: "Transcription schema is unsupported.")
            }
            guard v1Header.result.version == fabricTranscriptionContractVersion else {
                return .incompatible(
                    contract: v1Header.result.schema,
                    version: v1Header.result.version
                )
            }
            let envelope = try decoder.decode(FabricPhoneAudioEnvelopeV1.self, from: data)
            guard !envelope.captureID.isEmpty, textLength(envelope.captureID) <= 128 else {
                return .invalid(message: "Phone audio capture ID is invalid.")
            }
            guard validMIMEType(envelope.mimeType) else {
                return .invalid(message: "Phone audio MIME type is invalid.")
            }
            guard validMilliseconds(envelope.durationMS) else {
                return .invalid(message: "Phone audio duration is invalid.")
            }
            switch try validate(envelope.result) {
            case .verified:
                return .verified(envelope)
            case .incompatible(let contract, let version):
                return .incompatible(contract: contract, version: version)
            case .invalid(let message):
                return .invalid(message: message)
            }
        } catch {
            return .invalid(message: "Phone audio envelope is malformed.")
        }
    }

    private static func validate(
        _ result: FabricTranscriptionResultV1
    ) throws -> FabricVoiceContractParseResult<FabricTranscriptionResultV1> {
        guard result.schema == "fabric.transcription" else {
            return .invalid(message: "Transcription schema is unsupported.")
        }
        guard result.version == fabricTranscriptionContractVersion else {
            return .incompatible(contract: result.schema, version: result.version)
        }
        guard !result.requestID.isEmpty, textLength(result.requestID) <= 128 else {
            return .invalid(message: "Transcription request ID is invalid.")
        }
        guard textLength(result.text) <= maximumTextCharacters,
              result.segments.count <= 10_000,
              result.warnings.count <= 64,
              result.provider.map({ !$0.isEmpty && textLength($0) <= 128 }) ?? true,
              result.language.map({ !$0.isEmpty && textLength($0) <= 64 }) ?? true,
              result.model.map({ !$0.isEmpty && textLength($0) <= 128 }) ?? true,
              result.durationMS.map(validMilliseconds) ?? true,
              result.processingMS.map(validMilliseconds) ?? true else {
            return .invalid(message: "Transcription metadata exceeds its bounds.")
        }
        for segment in result.segments {
            guard validMilliseconds(segment.startMS),
                  validMilliseconds(segment.endMS),
                  segment.endMS >= segment.startMS,
                  result.durationMS.map({ segment.endMS <= $0 }) ?? true,
                  textLength(segment.text) <= maximumTextCharacters else {
                return .invalid(message: "Transcription segment is invalid.")
            }
        }
        guard result.warnings.allSatisfy({ textLength($0) <= 1_000 }) else {
            return .invalid(message: "Transcription warning is invalid.")
        }
        switch result.status {
        case .failed:
            guard result.text.isEmpty,
                  let error = result.error,
                  !error.code.isEmpty,
                  textLength(error.code) <= 128,
                  !error.message.isEmpty,
                  textLength(error.message) <= 4_000 else {
                return .invalid(message: "Failed transcription error is invalid.")
            }
        case .noSpeech, .cancelled:
            guard result.text.isEmpty, !result.containsErrorField else {
                return .invalid(message: "Empty transcription status is inconsistent.")
            }
        case .completed:
            guard !result.containsErrorField else {
                return .invalid(message: "Completed transcription cannot contain an error.")
            }
        }
        return .verified(result)
    }

    private static func textLength(_ value: String) -> Int {
        value.unicodeScalars.count
    }

    private static func validMIMEType(_ value: String) -> Bool {
        let pattern =
            "^(?:audio/[a-z0-9][a-z0-9.+-]*" +
            "(?:;[a-z0-9][a-z0-9_-]*=[a-z0-9][a-z0-9.,_+-]*)*" +
            "|video/webm)(?![\\s\\S])"
        return value.range(of: pattern, options: .regularExpression) != nil
    }

    private static func validMilliseconds(_ value: Int) -> Bool {
        value >= 0 && value <= maximumAudioMS
    }
}
