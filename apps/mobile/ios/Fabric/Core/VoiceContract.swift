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
        provider = try values.decodeIfPresent(String.self, forKey: .provider)
        language = try values.decodeIfPresent(String.self, forKey: .language)
        durationMS = try values.decodeIfPresent(Int.self, forKey: .durationMS)
        processingMS = try values.decodeIfPresent(Int.self, forKey: .processingMS)
        model = try values.decodeIfPresent(String.self, forKey: .model)
        segments = try values.decodeIfPresent(
            [FabricTranscriptionSegmentV1].self,
            forKey: .segments
        ) ?? []
        warnings = try values.decodeIfPresent([String].self, forKey: .warnings) ?? []
        error = try values.decodeIfPresent(FabricTranscriptionErrorV1.self, forKey: .error)
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

enum FabricVoiceContractParser {
    private static let maximumAudioMS = 3_600_000
    private static let maximumTextCharacters = 1_000_000

    static func parseTranscription(
        _ data: Data
    ) -> FabricVoiceContractParseResult<FabricTranscriptionResultV1> {
        do {
            let result = try JSONDecoder().decode(FabricTranscriptionResultV1.self, from: data)
            return try validate(result)
        } catch {
            return .invalid(message: "Transcription result is malformed.")
        }
    }

    static func parsePhoneAudio(
        _ data: Data
    ) -> FabricVoiceContractParseResult<FabricPhoneAudioEnvelopeV1> {
        do {
            let envelope = try JSONDecoder().decode(FabricPhoneAudioEnvelopeV1.self, from: data)
            guard envelope.contract == "fabric.phone_audio" else {
                return .invalid(message: "Phone audio contract is unsupported.")
            }
            guard envelope.version == fabricPhoneAudioContractVersion else {
                return .incompatible(contract: envelope.contract, version: envelope.version)
            }
            guard !envelope.captureID.isEmpty, envelope.captureID.count <= 128 else {
                return .invalid(message: "Phone audio capture ID is invalid.")
            }
            let mimeType = envelope.mimeType.lowercased()
            guard mimeType.hasPrefix("audio/") || mimeType == "video/webm" else {
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
        guard !result.requestID.isEmpty, result.requestID.count <= 128 else {
            return .invalid(message: "Transcription request ID is invalid.")
        }
        guard result.text.count <= maximumTextCharacters,
              result.segments.count <= 10_000,
              result.warnings.count <= 64,
              result.provider.map({ !$0.isEmpty && $0.count <= 128 }) ?? true,
              result.language.map({ !$0.isEmpty && $0.count <= 64 }) ?? true,
              result.model.map({ !$0.isEmpty && $0.count <= 128 }) ?? true,
              result.durationMS.map(validMilliseconds) ?? true,
              result.processingMS.map(validMilliseconds) ?? true else {
            return .invalid(message: "Transcription metadata exceeds its bounds.")
        }
        for segment in result.segments {
            guard validMilliseconds(segment.startMS),
                  validMilliseconds(segment.endMS),
                  segment.endMS >= segment.startMS,
                  result.durationMS.map({ segment.endMS <= $0 }) ?? true,
                  segment.text.count <= maximumTextCharacters else {
                return .invalid(message: "Transcription segment is invalid.")
            }
        }
        guard result.warnings.allSatisfy({ $0.count <= 1_000 }) else {
            return .invalid(message: "Transcription warning is invalid.")
        }
        switch result.status {
        case .failed:
            guard result.text.isEmpty,
                  let error = result.error,
                  !error.code.isEmpty,
                  error.code.count <= 128,
                  !error.message.isEmpty,
                  error.message.count <= 4_000 else {
                return .invalid(message: "Failed transcription error is invalid.")
            }
        case .noSpeech, .cancelled:
            guard result.text.isEmpty, result.error == nil else {
                return .invalid(message: "Empty transcription status is inconsistent.")
            }
        case .completed:
            guard result.error == nil else {
                return .invalid(message: "Completed transcription cannot contain an error.")
            }
        }
        return .verified(result)
    }

    private static func validMilliseconds(_ value: Int) -> Bool {
        value >= 0 && value <= maximumAudioMS
    }
}
