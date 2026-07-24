import Foundation
import Observation
import CryptoKit

/// A typed, presentation-only record inside one assistant turn. Activity is
/// folded into the turn (rather than a transient global status string), so a
/// tool that finishes remains beside the reasoning/text that surrounded it.
struct AssistantTurnPart: Identifiable, Equatable {
    struct Reasoning: Equatable {
        var text: String
        var wasTruncated: Bool
    }

    struct Tool: Equatable {
        enum State: String, Hashable {
            case generating
            case running
            case complete
            case failed
        }

        var callID: String?
        var name: String
        var detail: String?
        var state: State
        var durationSeconds: Double?
    }

    /// A generated image's renderable source. Images are either opaque gateway
    /// artifacts or bounded in-memory bytes; arbitrary tool URLs never reach
    /// the renderer.
    enum GeneratedImageSource: Equatable {
        case gatewayArtifact
        case unavailable
        case data(Data, mimeType: String)
    }

    /// An image produced by Fabric's dedicated image-generation tool.
    struct GeneratedImage: Equatable {
        let source: GeneratedImageSource
        let callID: String?
    }

    enum Content: Equatable {
        case text(String)
        case reasoning(Reasoning)
        case tool(Tool)
        case generatedImage(GeneratedImage)
    }

    let id: String
    var content: Content
}

/// The narrow event vocabulary consumed by the assistant-turn reducer. It is
/// intentionally detached from `[String: Any]` so ordering and bounds can be
/// verified without a socket or an Observable view model.
enum AssistantTurnEvent: Equatable {
    case textDelta(String)
    case reasoningDelta(String)
    case reasoningAvailable(String)
    case toolGenerating(name: String)
    case toolStarted(callID: String?, name: String, detail: String?)
    case toolProgress(callID: String?, name: String, detail: String?)
    case toolCompleted(
        callID: String?,
        name: String,
        detail: String?,
        failed: Bool,
        durationSeconds: Double?,
        generatedImage: AssistantTurnPart.GeneratedImage? = nil
    )
    case messageComplete(authoritativeText: String?)
}

/// Redaction and text caps shared by live cards and the offline presentation
/// cache. Tool result/argument objects never enter the reducer except for
/// a bounded generated-image artifact id; these patterns are a second line
/// of defence for the small
/// server-authored summary fields that are otherwise allowed through.
enum ChatPresentationSafety {
    static let maximumReasoningCharacters = 6_000
    static let maximumActivityDetailCharacters = 800
    static let maximumToolNameCharacters = 80
    static let maximumCachedMessageCharacters = 12_000
    static let maximumGeneratedImageURLCharacters = 2_048

    private static let sensitivePatterns: [(NSRegularExpression, String)] = {
        let definitions: [(String, String)] = [
            (
                #"(?i)\b(authorization|proxy-authorization)\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"#,
                "$1: [REDACTED]"
            ),
            (
                #"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|cookie|client[_-]?secret)\b(\s*[:=]\s*|\s+)[^\s,;]+"#,
                "$1$2[REDACTED]"
            ),
            (
                #"(?i)(--(?:api[-_]?key|access[-_]?token|token|password|secret))(?:=|\s+)[^\s]+"#,
                "$1 [REDACTED]"
            ),
            (
                #"(?i)([?&](?:api[_-]?key|token|password|secret)=)[^&#\s]+"#,
                "$1[REDACTED]"
            ),
            (
                #"\b(?:sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}|xox[baprs]-[A-Za-z0-9-]{8,})\b"#,
                "[REDACTED]"
            ),
        ]
        return definitions.compactMap { pattern, replacement in
            guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
            return (regex, replacement)
        }
    }()

    static func sanitized(_ source: String, maximumCharacters: Int) -> String {
        var result = source
        for (regex, replacement) in sensitivePatterns {
            let range = NSRange(result.startIndex..<result.endIndex, in: result)
            result = regex.stringByReplacingMatches(
                in: result,
                range: range,
                withTemplate: replacement
            )
        }
        guard result.count > maximumCharacters else { return result }
        let marker = "\n… [truncated]"
        guard maximumCharacters > marker.count else {
            return String(result.prefix(max(0, maximumCharacters)))
        }
        let prefixCount = maximumCharacters - marker.count
        let end = result.index(result.startIndex, offsetBy: prefixCount)
        return String(result[..<end]) + marker
    }

    static func toolName(_ source: String?) -> String {
        let trimmed = (source ?? "tool").trimmingCharacters(in: .whitespacesAndNewlines)
        let value = trimmed.isEmpty ? "tool" : trimmed
        return sanitized(value, maximumCharacters: maximumToolNameCharacters)
    }

    static func activityDetail(_ source: String?) -> String? {
        guard let source else { return nil }
        let trimmed = source.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return sanitized(trimmed, maximumCharacters: maximumActivityDetailCharacters)
    }

    /// Create an in-memory placeholder for an image that stayed on the
    /// authenticated gateway host. The client exchanges only the opaque tool
    /// call ID for bytes; a gateway file path never becomes presentation data.
    static func gatewayArtifactImage(
        from payload: [String: Any],
        toolName: String,
        callID: String?
    ) -> AssistantTurnPart.GeneratedImage? {
        guard toolName == "image_generate", let callID, !callID.isEmpty else { return nil }

        if let result = object(fromToolResult: payload["result"]) {
            guard result["success"] as? Bool != false else { return nil }
            for key in ["host_image", "image", "agent_visible_image"] {
                if let path = result[key] as? String, isLocalImageArtifactPath(path) {
                    return AssistantTurnPart.GeneratedImage(source: .gatewayArtifact, callID: callID)
                }
            }
        }

        if let files = payload["files_written"] as? [Any], files.contains(where: { value in
            guard let path = value as? String else { return false }
            return isLocalImageArtifactPath(path)
        }) {
            return AssistantTurnPart.GeneratedImage(source: .gatewayArtifact, callID: callID)
        }
        return nil
    }

    private static func isLocalImageArtifactPath(_ rawPath: String) -> Bool {
        let path = rawPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !path.isEmpty, path.count <= 2_048,
              path.hasPrefix("/") || path.hasPrefix("~/") || path.hasPrefix("./") || path.hasPrefix("file://")
        else { return false }
        let lowercase = path.lowercased()
        return [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"].contains { lowercase.hasSuffix($0) }
    }

    private static func object(fromToolResult value: Any?) -> [String: Any]? {
        if let object = value as? [String: Any] { return object }
        guard let string = value as? String,
              string.utf8.count <= maximumGeneratedImageURLCharacters * 2,
              let data = string.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        return object
    }

    /// Transport errors can embed arbitrary JSON-RPC messages, HTTP bodies,
    /// credentials, or socket diagnostics in `localizedDescription`. Chat is
    /// persisted as a presentation cache, so only caller-owned recovery copy
    /// is eligible to cross this boundary; the raw error stays diagnostic-only.
    static func userVisibleFailure(for _: Error, fallback: String) -> String {
        sanitized(fallback, maximumCharacters: maximumActivityDetailCharacters)
    }
}

/// Pure event folding for rich assistant turns. At most 64 reasoning/tool
/// cards survive in a turn. Text parts remain authoritative transcript text;
/// the bound applies only to high-frequency presentation activity.
enum AssistantTurnReducer {
    static let maximumActivityParts = 64

    static func event(from gatewayEvent: GatewayEvent) -> AssistantTurnEvent? {
        let payload = gatewayEvent.payload
        switch gatewayEvent.type {
        case "message.delta":
            guard let text = gatewayEvent.payloadText else { return nil }
            return .textDelta(text)
        case "reasoning.delta":
            guard let text = gatewayEvent.payloadText else { return nil }
            return .reasoningDelta(text)
        case "reasoning.available":
            guard let text = gatewayEvent.payloadText else { return nil }
            return .reasoningAvailable(text)
        case "tool.generating":
            return .toolGenerating(name: ChatPresentationSafety.toolName(payload["name"] as? String))
        case "tool.start":
            return .toolStarted(
                callID: toolCallID(payload),
                name: ChatPresentationSafety.toolName(
                    (payload["name"] as? String) ?? (payload["tool"] as? String)
                ),
                detail: ChatPresentationSafety.activityDetail(
                    (payload["context"] as? String) ?? (payload["preview"] as? String)
                )
            )
        case "tool.progress":
            return .toolProgress(
                callID: toolCallID(payload),
                name: ChatPresentationSafety.toolName(
                    (payload["name"] as? String) ?? (payload["tool"] as? String)
                ),
                detail: ChatPresentationSafety.activityDetail(
                    (payload["text"] as? String)
                        ?? (payload["preview"] as? String)
                        ?? (payload["context"] as? String)
                )
            )
        case "tool.complete":
            let failed: Bool
            if let value = payload["error"] as? Bool {
                failed = value
            } else {
                // A non-boolean error body is deliberately not rendered.
                failed = payload["error"] != nil
            }
            let callID = toolCallID(payload)
            let name = ChatPresentationSafety.toolName(
                (payload["name"] as? String) ?? (payload["tool"] as? String)
            )
            return .toolCompleted(
                callID: callID,
                name: name,
                // Only the server-authored compact summary is presentation
                // eligible. The sole exception is image_generate's bounded
                // public HTTPS output, converted to a typed image value here.
                detail: ChatPresentationSafety.activityDetail(payload["summary"] as? String),
                failed: failed,
                durationSeconds: (payload["duration_s"] as? NSNumber)?.doubleValue,
                generatedImage: failed ? nil : ChatPresentationSafety.gatewayArtifactImage(
                    from: payload,
                    toolName: name,
                    callID: callID
                )
            )
        case "message.complete":
            return .messageComplete(authoritativeText: gatewayEvent.payloadText)
        default:
            return nil
        }
    }

    static func reducing(
        _ message: TranscriptMessage,
        event: AssistantTurnEvent
    ) -> TranscriptMessage {
        guard message.role == .assistant else { return message }
        var next = message

        switch event {
        case .textDelta(let delta):
            guard !delta.isEmpty else { return next }
            next.text += delta
            appendText(delta, to: &next.assistantParts)

        case .reasoningDelta(let delta):
            appendReasoning(delta, replace: false, to: &next.assistantParts)

        case .reasoningAvailable(let text):
            appendReasoning(text, replace: true, to: &next.assistantParts)

        case .toolGenerating(let name):
            let safeName = ChatPresentationSafety.toolName(name)
            if let index = latestToolIndex(in: next.assistantParts, callID: nil, name: safeName),
               case .tool(let existing) = next.assistantParts[index].content,
               existing.state == .generating {
                break
            }
            appendTool(
                AssistantTurnPart.Tool(
                    callID: nil,
                    name: safeName,
                    detail: nil,
                    state: .generating,
                    durationSeconds: nil
                ),
                to: &next.assistantParts
            )

        case .toolStarted(let callID, let name, let detail):
            let safeName = ChatPresentationSafety.toolName(name)
            let safeDetail = ChatPresentationSafety.activityDetail(detail)
            upsertTool(
                callID: callID,
                name: safeName,
                fallbackStates: [.generating, .running],
                in: &next.assistantParts
            ) { tool in
                tool.callID = callID ?? tool.callID
                tool.name = safeName
                tool.detail = safeDetail ?? tool.detail
                tool.state = .running
            }

        case .toolProgress(let callID, let name, let detail):
            let safeName = ChatPresentationSafety.toolName(name)
            let safeDetail = ChatPresentationSafety.activityDetail(detail)
            upsertTool(
                callID: callID,
                name: safeName,
                fallbackStates: [.running, .generating],
                in: &next.assistantParts
            ) { tool in
                tool.callID = callID ?? tool.callID
                tool.name = safeName
                tool.detail = safeDetail ?? tool.detail
                tool.state = .running
            }

        case .toolCompleted(let callID, let name, let detail, let failed, let duration, let generatedImage):
            let safeName = ChatPresentationSafety.toolName(name)
            let safeDetail = ChatPresentationSafety.activityDetail(detail)
            upsertTool(
                callID: callID,
                name: safeName,
                fallbackStates: [.running, .generating],
                in: &next.assistantParts
            ) { tool in
                tool.callID = callID ?? tool.callID
                tool.name = safeName
                tool.detail = safeDetail ?? tool.detail
                tool.state = failed ? .failed : .complete
                tool.durationSeconds = duration
            }
            if !failed, let generatedImage {
                appendGeneratedImage(generatedImage, to: &next.assistantParts)
            }

        case .messageComplete(let authoritativeText):
            if let authoritativeText, !authoritativeText.isEmpty,
               authoritativeText != next.text {
                next.text = authoritativeText
                next.assistantParts.removeAll { part in
                    if case .text = part.content { return true }
                    return false
                }
                appendText(authoritativeText, to: &next.assistantParts)
            }
            next.streaming = false
        }

        trimActivityParts(in: &next.assistantParts)
        return next
    }

    private static func appendText(_ delta: String, to parts: inout [AssistantTurnPart]) {
        if let index = latestPartIndex(in: parts, matching: { content in
            if case .text = content { return true }
            if case .tool = content { return false }
            if case .generatedImage = content { return false }
            return nil
        }), case .text(let text) = parts[index].content {
            let crossesReasoning = parts[(index + 1)...].contains { part in
                if case .reasoning = part.content { return true }
                return false
            }
            // The child-session mirror terminates its one-line goal header
            // with a newline before reasoning begins. Keep that complete line
            // in source order, while still coalescing ordinary mid-sentence
            // text/reasoning fragments like the desktop transcript does.
            if !crossesReasoning || !text.hasSuffix("\n") {
                parts[index].content = .text(text + delta)
                return
            }
        }
        parts.append(AssistantTurnPart(id: nextID(prefix: "text", parts: parts), content: .text(delta)))
    }

    private static func appendReasoning(
        _ source: String,
        replace: Bool,
        to parts: inout [AssistantTurnPart]
    ) {
        guard !source.isEmpty || replace else { return }
        let index = latestPartIndex(in: parts, matching: { content in
            if case .reasoning = content { return true }
            if case .tool = content { return false }
            if case .generatedImage = content { return false }
            return nil
        })
        let current: String
        if !replace, let index, case .reasoning(let reasoning) = parts[index].content {
            current = reasoning.text + source
        } else {
            current = source
        }
        let bounded = ChatPresentationSafety.sanitized(
            current,
            maximumCharacters: ChatPresentationSafety.maximumReasoningCharacters
        )
        let reasoning = AssistantTurnPart.Reasoning(
            text: bounded,
            wasTruncated: current.count > ChatPresentationSafety.maximumReasoningCharacters
        )
        if let index {
            parts[index].content = .reasoning(reasoning)
        } else if !bounded.isEmpty {
            parts.append(AssistantTurnPart(
                id: nextID(prefix: "reasoning", parts: parts),
                content: .reasoning(reasoning)
            ))
        }
    }

    /// Return true/false for a match/stop boundary, nil to continue scanning.
    private static func latestPartIndex(
        in parts: [AssistantTurnPart],
        matching: (AssistantTurnPart.Content) -> Bool?
    ) -> Int? {
        for index in parts.indices.reversed() {
            if let result = matching(parts[index].content) {
                return result ? index : nil
            }
        }
        return nil
    }

    private static func toolCallID(_ payload: [String: Any]) -> String? {
        for key in ["tool_id", "tool_call_id", "id"] {
            guard let raw = payload[key] as? String else { continue }
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty { return String(trimmed.prefix(256)) }
        }
        return nil
    }

    private static func latestToolIndex(
        in parts: [AssistantTurnPart],
        callID: String?,
        name: String,
        states: Set<AssistantTurnPart.Tool.State>? = nil
    ) -> Int? {
        if let callID, let exact = parts.lastIndex(where: { part in
            guard case .tool(let tool) = part.content else { return false }
            return tool.callID == callID
        }) {
            return exact
        }
        return parts.lastIndex { part in
            guard case .tool(let tool) = part.content, tool.name == name else { return false }
            return states?.contains(tool.state) ?? true
        }
    }

    private static func upsertTool(
        callID: String?,
        name: String,
        fallbackStates: Set<AssistantTurnPart.Tool.State>,
        in parts: inout [AssistantTurnPart],
        update: (inout AssistantTurnPart.Tool) -> Void
    ) {
        if let index = latestToolIndex(
            in: parts,
            callID: callID,
            name: name,
            states: fallbackStates
        ), case .tool(var tool) = parts[index].content {
            update(&tool)
            parts[index].content = .tool(tool)
            return
        }
        var tool = AssistantTurnPart.Tool(
            callID: callID,
            name: name,
            detail: nil,
            state: .running,
            durationSeconds: nil
        )
        update(&tool)
        appendTool(tool, to: &parts)
    }

    private static func appendTool(
        _ tool: AssistantTurnPart.Tool,
        to parts: inout [AssistantTurnPart]
    ) {
        parts.append(AssistantTurnPart(
            id: nextID(prefix: "tool", parts: parts),
            content: .tool(tool)
        ))
    }

    private static func appendGeneratedImage(
        _ image: AssistantTurnPart.GeneratedImage,
        to parts: inout [AssistantTurnPart]
    ) {
        let alreadyPresent = parts.contains { part in
            guard case .generatedImage(let existing) = part.content else { return false }
            if let callID = image.callID { return existing.callID == callID }
            return existing.source == image.source
        }
        guard !alreadyPresent else { return }
        let id = image.callID.map { "image:\($0)" } ?? nextID(prefix: "image", parts: parts)
        parts.append(AssistantTurnPart(id: id, content: .generatedImage(image)))
    }

    private static func nextID(prefix: String, parts: [AssistantTurnPart]) -> String {
        let nextSequence = parts.compactMap { part -> Int? in
            guard part.id.hasPrefix(prefix + ":") else { return nil }
            return Int(part.id.dropFirst(prefix.count + 1))
        }.max().map { $0 + 1 } ?? 0
        return "\(prefix):\(nextSequence)"
    }

    static func trimActivityParts(in parts: inout [AssistantTurnPart]) {
        var overflow = parts.reduce(into: 0) { count, part in
            if case .text = part.content { return }
            count += 1
        } - maximumActivityParts
        guard overflow > 0 else { return }
        parts.removeAll { part in
            guard overflow > 0 else { return false }
            if case .text = part.content { return false }
            overflow -= 1
            return true
        }
    }
}

/// A user-picked attachment staged for the next prompt. The raw bytes stay
/// in memory only until the gateway confirms the upload, and are rendered
/// locally — never fetched over the network.
struct ChatComposerAttachment: Identifiable, Equatable {
    enum Kind: String, Equatable {
        /// PNG/JPEG/GIF/WebP/BMP → `image.attach_bytes` (vision tiles).
        case image
        /// `pdf.attach` — the gateway renders each page for vision.
        case pdf
        /// Everything else → `file.attach` (readable workspace artifact).
        case file
    }

    let id: UUID
    let kind: Kind
    let filename: String
    let data: Data
    let mimeType: String

    init(
        id: UUID = UUID(),
        kind: Kind,
        filename: String,
        data: Data,
        mimeType: String
    ) {
        self.id = id
        self.kind = kind
        self.filename = filename
        self.data = data
        self.mimeType = mimeType
    }
}

/// Pure classification and bounds for composer attachments, mirroring the
/// gateway's magic-byte sniffing and caps so an over-limit or unsupported
/// upload fails on-device with clear copy instead of a server error.
enum ChatAttachmentPolicy {
    /// The gateway itself accepts larger decoded payloads (25 MB images and
    /// 50 MB PDFs — `_ATTACH_BYTES_MAX_BYTES` / `_PDF_ATTACH_MAX_BYTES` in
    /// `tui_gateway/server.py`), but every upload travels as ONE base64
    /// JSON-RPC WebSocket text frame and the serving uvicorn keeps its
    /// default 16 MiB `ws_max_size`. 10 MB raw (~13.3 MiB encoded plus the
    /// JSON envelope) is the largest payload that reliably clears that
    /// transport bound instead of closing the socket mid-send.
    static let maximumAttachmentBytes = 10 * 1_024 * 1_024
    static let maximumStagedAttachments = 8

    /// The image formats the server's `_sniff_image_ext` accepts, detected
    /// by the same magic bytes. BMP additionally requires the header's
    /// zeroed reserved fields so ordinary text starting with "BM" is not
    /// misrouted to the image upload the server would then reject.
    static func sniffedImageMIME(_ data: Data) -> String? {
        if data.starts(with: [0x89, 0x50, 0x4E, 0x47]) { return "image/png" }
        if data.starts(with: [0xFF, 0xD8, 0xFF]) { return "image/jpeg" }
        if data.starts(with: Data("GIF8".utf8)) { return "image/gif" }
        if data.count >= 12,
           data.starts(with: Data("RIFF".utf8)),
           data.dropFirst(8).prefix(4).elementsEqual(Data("WEBP".utf8)) {
            return "image/webp"
        }
        if data.count >= 14,
           data.starts(with: Data("BM".utf8)),
           data.dropFirst(6).prefix(4).allSatisfy({ $0 == 0 }) {
            return "image/bmp"
        }
        return nil
    }

    static func isPDF(_ data: Data) -> Bool {
        data.starts(with: Data("%PDF-".utf8))
    }

    static func isAnimatableGIF(_ data: Data) -> Bool {
        data.starts(with: Data("GIF8".utf8))
    }

    private static func fileExtension(forImageMIME mime: String) -> String {
        switch mime {
        case "image/png": return "png"
        case "image/jpeg": return "jpg"
        case "image/gif": return "gif"
        case "image/webp": return "webp"
        default: return "bmp"
        }
    }

    /// Build the staged attachment for picked bytes. A name is synthesized
    /// when the picker did not provide one (photo-library items).
    static func attachment(
        data: Data,
        suggestedName: String?,
        sequence: Int
    ) -> ChatComposerAttachment {
        let providedName: String? = {
            let trimmed = suggestedName?.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed?.isEmpty == false ? trimmed : nil
        }()
        if let mime = sniffedImageMIME(data) {
            return ChatComposerAttachment(
                kind: .image,
                filename: providedName ?? "photo-\(sequence).\(fileExtension(forImageMIME: mime))",
                data: data,
                mimeType: mime
            )
        }
        if isPDF(data) {
            return ChatComposerAttachment(
                kind: .pdf,
                filename: providedName ?? "document-\(sequence).pdf",
                data: data,
                mimeType: "application/pdf"
            )
        }
        return ChatComposerAttachment(
            kind: .file,
            filename: providedName ?? "attachment-\(sequence)",
            data: data,
            mimeType: "application/octet-stream"
        )
    }

    /// Caller-owned recovery copy when the attachment cannot be staged;
    /// nil means it is acceptable.
    static func stagingProblem(
        _ attachment: ChatComposerAttachment,
        alreadyStaged: Int
    ) -> String? {
        guard alreadyStaged < maximumStagedAttachments else {
            return "Up to \(maximumStagedAttachments) attachments can be sent per message."
        }
        guard !attachment.data.isEmpty else {
            return "\"\(attachment.filename)\" is empty and can't be attached."
        }
        guard attachment.data.count <= maximumAttachmentBytes else {
            let megabytes = maximumAttachmentBytes / (1_024 * 1_024)
            return "\"\(attachment.filename)\" is larger than the \(megabytes) MB attachment limit."
        }
        return nil
    }
}

/// Presentation-only record of media the user attached to a sent message.
/// Previews render from these local bytes; nothing is fetched remotely, and
/// the bytes never enter the on-disk presentation cache.
struct TranscriptAttachmentPreview: Identifiable, Equatable {
    let id: UUID
    let kind: ChatComposerAttachment.Kind
    let filename: String
    let data: Data

    /// Bytes are immutable per preview id, so equality is identity. SwiftUI
    /// re-compares the whole transcript on every streamed delta; this keeps
    /// that diff from byte-comparing multi-megabyte media each time.
    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.id == rhs.id && lhs.kind == rhs.kind && lhs.filename == rhs.filename
    }
}

/// One transcript row. Assistant messages accumulate `message.delta` text
/// while `streaming` is true; `message.complete` finalizes them.
struct TranscriptMessage: Identifiable, Equatable {
    enum Role: Equatable {
        case user
        case assistant
        /// Errors and failures — rendered prominently.
        case system
        /// Neutral local notices (slash output, steer/background confirmations).
        case info
    }

    let id: UUID
    let role: Role
    var text: String
    var streaming: Bool
    var assistantParts: [AssistantTurnPart]
    /// Local previews of media the user sent with this message.
    var attachments: [TranscriptAttachmentPreview]

    init(
        id: UUID = UUID(),
        role: Role,
        text: String,
        streaming: Bool = false,
        assistantParts: [AssistantTurnPart]? = nil,
        attachments: [TranscriptAttachmentPreview] = []
    ) {
        self.id = id
        self.role = role
        self.text = text
        self.streaming = streaming
        self.assistantParts = assistantParts ?? (
            role == .assistant && !text.isEmpty
                ? [AssistantTurnPart(id: "text:\(id.uuidString)", content: .text(text))]
                : []
        )
        self.attachments = attachments
    }
}

/// A pending `approval.request` awaiting an allow/deny. The command string
/// arrives pre-redacted from the server.
struct PendingApproval: Equatable {
    let command: String?
    let requestId: String
    let summary: String?
    let cwd: String?
    let allowPermanent: Bool

    init(
        command: String?,
        requestId: String,
        summary: String?,
        cwd: String? = nil,
        allowPermanent: Bool = true
    ) {
        self.command = command.flatMap {
            ChatPresentationSafety.activityDetail($0)
        }
        self.requestId = requestId
        self.summary = summary.flatMap {
            ChatPresentationSafety.activityDetail($0)
        }
        self.cwd = cwd.flatMap {
            ChatPresentationSafety.activityDetail($0)
        }
        self.allowPermanent = allowPermanent
    }
}

enum ApprovalChoice: String, CaseIterable, Equatable {
    case once
    case session
    case always
    case deny

    var label: String {
        switch self {
        case .once: return "Once"
        case .session: return "For this session"
        case .always: return "Always"
        case .deny: return "Deny"
        }
    }

    var accessibilityHint: String {
        switch self {
        case .once: return "Allows only this request"
        case .session: return "Allows matching requests until this session ends"
        case .always: return "Saves a permanent matching approval rule"
        case .deny: return "Rejects this request"
        }
    }

    var accessibilityLabel: String {
        switch self {
        case .once: return "Allow once"
        case .session: return "Allow for this session"
        case .always: return "Always allow"
        case .deny: return "Deny"
        }
    }
}

enum ApprovalResponseState: Equatable {
    case idle
    case submitting(ApprovalChoice)
    case failed(String)

    var isSubmitting: Bool {
        if case .submitting = self { return true }
        return false
    }
}

enum ChatMutationAction: String, Equatable {
    case prompt
    case steering
    case slashCommand
    case legacyBackground
}

enum ChatMutationFailureDisposition: Equatable {
    case rejected
    case outcomeUnknown
}

struct ChatMutationFailurePresentation: Equatable {
    let disposition: ChatMutationFailureDisposition
    let message: String
    let outcomeDescription: String?

    static func classify(
        _ error: Error,
        action: ChatMutationAction
    ) -> ChatMutationFailurePresentation {
        let rejected: Bool
        if let gatewayError = error as? GatewayClientError,
           case .rpc = gatewayError {
            rejected = true
        } else {
            // Socket closure, timeout, connection loss, and unknown adapters
            // can all happen after the server accepted the mutation.
            rejected = false
        }

        if rejected {
            let copy: String
            switch action {
            case .prompt:
                copy = "Fabric rejected this message. Review it and try again."
            case .steering:
                copy = "Fabric rejected the steering note. The active turn was not changed."
            case .slashCommand:
                copy = "Fabric rejected this command. Review it and try again."
            case .legacyBackground:
                copy = "Fabric rejected this background request. Review it and try again."
            }
            return ChatMutationFailurePresentation(
                disposition: .rejected,
                message: copy,
                outcomeDescription: nil
            )
        }

        let noun: String
        switch action {
        case .prompt: noun = "message delivery"
        case .steering: noun = "steering"
        case .slashCommand: noun = "command"
        case .legacyBackground: noun = "background start"
        }
        return ChatMutationFailurePresentation(
            disposition: .outcomeUnknown,
            message: "The \(noun) outcome is unknown. Fabric may have received it. No automatic retry will occur. Check this conversation before sending again.",
            outcomeDescription: "Fabric may have received this request. It will not be retried automatically."
        )
    }
}

struct UnknownSendOutcome: Equatable {
    let action: ChatMutationAction
    let description: String
}

/// A blocking prompt from the agent: `clarify.request` (question + optional
/// choices), `sudo.request` (password), or `secret.request` (secret value).
/// Answered via the matching `*.respond` RPC keyed by `requestId`.
struct PendingPrompt: Equatable {
    struct PresentationChoice: Identifiable, Equatable {
        let id: Int
        let label: String
        /// Exact server value. The sanitized label is presentation-only and
        /// must never be echoed back as the clarify response.
        let response: String
    }

    enum Kind: Equatable {
        case clarify
        case sudo
        case secret
    }

    let kind: Kind
    let requestId: String
    let question: String
    let choices: [String]

    var isSecureEntry: Bool { kind != .clarify }

    var presentationQuestion: String {
        ChatPresentationSafety.activityDetail(question)
            ?? (kind == .clarify ? "The agent has a question." : "A credential was requested.")
    }

    var presentationChoices: [PresentationChoice] {
        choices.enumerated().map { index, raw in
            PresentationChoice(
                id: index,
                label: ChatPresentationSafety.activityDetail(raw) ?? "Option \(index + 1)",
                response: raw
            )
        }
    }

    var responseMethod: String {
        switch kind {
        case .clarify: return "clarify.respond"
        case .sudo: return "sudo.respond"
        case .secret: return "secret.respond"
        }
    }
}

enum PendingInteraction: Equatable {
    case approval(PendingApproval)
    case prompt(PendingPrompt)

    var identity: String {
        switch self {
        case .approval(let approval):
            return "approval:\(approval.requestId)"
        case .prompt(let prompt):
            return "\(prompt.kind):\(prompt.requestId)"
        }
    }
}

/// One coalesced accessibility signal for a blocking interaction. The copy is
/// deliberately generic: approval commands and credential prompts can contain
/// sensitive values, so VoiceOver announces the required action without
/// reading server-authored detail across the room.
struct PendingInteractionAccessibilityCue: Equatable {
    let identity: String
    let announcement: String

    init(interaction: PendingInteraction) {
        identity = interaction.identity
        switch interaction {
        case .approval:
            announcement = "Approval needed. Review the request and choose a response."
        case .prompt(let prompt):
            announcement = prompt.kind == .clarify
                ? "The agent has a question. Review it and choose or enter a response."
                : "A private credential is requested. Review the prompt and enter a response."
        }
    }
}

/// Prevents duplicate gateway events and view refreshes from repeatedly
/// interrupting VoiceOver. Clearing the queue resets the identity so a later,
/// genuinely new appearance of the same server request can be announced.
struct PendingInteractionAccessibilityCoordinator {
    private(set) var lastIdentity: String?

    mutating func cue(for interaction: PendingInteraction?) -> PendingInteractionAccessibilityCue? {
        guard let interaction else {
            lastIdentity = nil
            return nil
        }
        guard interaction.identity != lastIdentity else { return nil }
        lastIdentity = interaction.identity
        return PendingInteractionAccessibilityCue(interaction: interaction)
    }
}

/// Presentation vocabulary for the pet companion. Raw values are the UI
/// states the sprite alias mapping in `PetSpriteView` consumes.
enum PetState: String {
    case idle
    case wave
    case run
    case failed
    case review
    case jump
    case waiting
}

/// Pure activity→pet-state projection mirroring `agent/pet/state.py`:
/// error > celebrate > justCompleted > awaitingInput > toolRunning >
/// reasoning > busy > idle. Steady flags (toolRunning/reasoning) only count
/// while the turn is busy, so an interrupted turn cannot pin the running or
/// review animation.
struct PetActivitySnapshot: Equatable {
    var busy = false
    var awaitingInput = false
    var toolRunning = false
    var reasoning = false
    var errorBeat = false
    var celebrateBeat = false
    // Pre-wired to keep the priority order identical to `agent/pet/state.py`.
    // The mobile event stream carries no plan-finished/todo signal yet, so
    // `message.complete` fires `celebrate` (jump) to match the desktop app; the
    // calmer `wave` becomes reachable once such a signal exists.
    var justCompletedBeat = false

    static func derive(_ s: PetActivitySnapshot) -> PetState {
        if s.errorBeat { return .failed }
        if s.celebrateBeat { return .jump }
        if s.justCompletedBeat { return .wave }
        if s.awaitingInput { return .waiting }
        if s.busy, s.toolRunning { return .run }
        if s.busy, s.reasoning { return .review }
        if s.busy { return .run }
        return .idle
    }
}

/// Capability-derived composition contract for the compact action strip.
/// Unsupported actions are absent rather than permanently disabled; temporary
/// state (offline, empty draft, missing Work identity) is handled separately.
struct ChatAdvertisedActions: Equatable {
    let commands: Bool
    let background: Bool
    let processes: Bool
    let liveView: Bool

    init(
        supportsMethod: (String) -> Bool,
        supportsDurableWork: Bool,
        liveViewSupported: Bool
    ) {
        commands = supportsMethod("commands.catalog") && supportsMethod("slash.exec")
        background = supportsDurableWork || supportsMethod("prompt.background")
        processes = supportsMethod("process.list")
        liveView = liveViewSupported
    }

    var isEmpty: Bool {
        !commands && !background && !processes && !liveView
    }
}

/// One user intent awaiting a durable create receipt. Its stable key is held
/// only in memory so a timeout/reconnect retry cannot create a second Job.
private struct PendingDurableBackgroundMutation: Equatable {
    let text: String
    let title: String
    let idempotencyKey: String
}

struct PendingInteractionQueue {
    private(set) var items: [PendingInteraction] = []

    var first: PendingInteraction? { items.first }

    mutating func enqueue(_ interaction: PendingInteraction) {
        items.removeAll { $0.identity == interaction.identity }
        items.append(interaction)
    }

    mutating func remove(_ interaction: PendingInteraction) {
        items.removeAll { $0.identity == interaction.identity }
    }

    mutating func clear() {
        items.removeAll()
    }
}

/// A file-protected, bounded snapshot used only to paint a conversation while
/// `session.resume` fetches authoritative history. It is never passed to a
/// gateway method and is replaced (or removed) as soon as resume succeeds.
struct ChatPresentationCache {
    static let maximumMessages = 120
    static let maximumTotalCharacters = 160_000
    static let maximumEncodedBytes = 1_048_576
    static let maximumDirectoryBytes = 8 * 1_048_576
    static let maximumSessions = 24
    static let maximumAge: TimeInterval = 14 * 24 * 60 * 60
    static let requiredFileProtection = FileProtectionType.complete

    struct Policy {
        let maximumEncodedBytes: Int
        let maximumDirectoryBytes: Int
        let maximumSessions: Int
        let maximumAge: TimeInterval

        static let production = Policy(
            maximumEncodedBytes: ChatPresentationCache.maximumEncodedBytes,
            maximumDirectoryBytes: ChatPresentationCache.maximumDirectoryBytes,
            maximumSessions: ChatPresentationCache.maximumSessions,
            maximumAge: ChatPresentationCache.maximumAge
        )
    }

    private struct Record: Codable, Equatable {
        struct Part: Codable, Equatable {
            let id: String
            let kind: String
            let text: String?
            let toolName: String?
            let toolDetail: String?
            let toolState: String?
            let durationSeconds: Double?
        }

        let id: String
        let role: String
        let text: String
        let parts: [Part]
    }

    private let directoryURL: URL
    private let policy: Policy

    init(directoryURL: URL? = nil, policy: Policy = .production) {
        self.policy = policy
        if let directoryURL {
            self.directoryURL = directoryURL
        } else {
            let applicationSupport = FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first ?? FileManager.default.temporaryDirectory
            self.directoryURL = applicationSupport
                .appendingPathComponent("Fabric", isDirectory: true)
                .appendingPathComponent("ChatPresentationCache", isDirectory: true)
        }
    }

    func load(key: String) -> [TranscriptMessage] {
        let url = fileURL(for: key)
        do {
            try secureDirectory()
            prune()
            guard try isSecureItem(url),
                  try fileSize(at: url) <= policy.maximumEncodedBytes else {
                try? FileManager.default.removeItem(at: url)
                return []
            }
            let data = try Data(contentsOf: url, options: .mappedIfSafe)
            guard data.count <= policy.maximumEncodedBytes else {
                try? FileManager.default.removeItem(at: url)
                return []
            }
            let records = try JSONDecoder().decode([Record].self, from: data)
            // A successful read makes this snapshot most-recently used for
            // the global session-count/byte eviction pass.
            try FileManager.default.setAttributes(
                [.modificationDate: Date()],
                ofItemAtPath: url.path
            )
            prune()
            return records.compactMap(Self.message(from:))
        } catch {
            // A missing, corrupt, oversized, or incorrectly protected cache
            // is never rendered. Authoritative resume remains the only source
            // of live conversation state.
            try? FileManager.default.removeItem(at: url)
            return []
        }
    }

    func replace(key: String, messages: [TranscriptMessage]) {
        let url = fileURL(for: key)
        var records = Self.records(from: messages)
        guard !records.isEmpty else {
            try? FileManager.default.removeItem(at: url)
            return
        }
        do {
            try secureDirectory()
            var data = try JSONEncoder().encode(records)
            while data.count > policy.maximumEncodedBytes, records.count > 1 {
                records.removeFirst()
                data = try JSONEncoder().encode(records)
            }
            guard data.count <= policy.maximumEncodedBytes else {
                try? FileManager.default.removeItem(at: url)
                return
            }
            try data.write(to: url, options: .atomic)
            try FileManager.default.setAttributes(
                [.protectionKey: Self.requiredFileProtection],
                ofItemAtPath: url.path
            )
            try excludeFromBackup(url)
            guard try isSecureItem(url) else {
                try? FileManager.default.removeItem(at: url)
                return
            }
            prune()
        } catch {
            // Cache failure never affects the authoritative live transcript.
            try? FileManager.default.removeItem(at: url)
        }
    }

    func clear(key: String) {
        try? FileManager.default.removeItem(at: fileURL(for: key))
    }

    /// Internal inspection seam for behavioural file-protection and eviction
    /// tests. The path contains only the existing opaque key hash.
    func snapshotURL(for key: String) -> URL {
        fileURL(for: key)
    }

    /// Internal for behavioural tests: proves both bounds and redaction before
    /// any bytes can reach disk.
    static func presentationStrings(from messages: [TranscriptMessage]) -> [String] {
        records(from: messages).flatMap { record in
            [record.text] + record.parts.flatMap { part in
                [part.text, part.toolName, part.toolDetail].compactMap { $0 }
            }
        }
    }

    private static func records(from messages: [TranscriptMessage]) -> [Record] {
        var remaining = maximumTotalCharacters
        var reversed: [Record] = []
        for message in messages.suffix(maximumMessages).reversed() {
            guard remaining > 0 else { break }
            let maximum = min(
                remaining,
                ChatPresentationSafety.maximumCachedMessageCharacters
            )
            let text = ChatPresentationSafety.sanitized(
                message.text,
                maximumCharacters: maximum
            )
            remaining -= min(text.count, remaining)
            let parts = message.assistantParts.compactMap { part -> Record.Part? in
                guard remaining > 0 else { return nil }
                switch part.content {
                case .text(let value):
                    let text = ChatPresentationSafety.sanitized(
                        value,
                        maximumCharacters: min(
                            remaining,
                            ChatPresentationSafety.maximumCachedMessageCharacters
                        )
                    )
                    remaining -= min(text.count, remaining)
                    return Record.Part(
                        id: part.id,
                        kind: "text",
                        text: text,
                        toolName: nil,
                        toolDetail: nil,
                        toolState: nil,
                        durationSeconds: nil
                    )
                case .reasoning(let reasoning):
                    let text = ChatPresentationSafety.sanitized(
                        reasoning.text,
                        maximumCharacters: min(
                            remaining,
                            ChatPresentationSafety.maximumReasoningCharacters
                        )
                    )
                    remaining -= min(text.count, remaining)
                    return Record.Part(
                        id: part.id,
                        kind: "reasoning",
                        text: text,
                        toolName: nil,
                        toolDetail: nil,
                        toolState: nil,
                        durationSeconds: nil
                    )
                case .tool(let tool):
                    let name = ChatPresentationSafety.sanitized(
                        tool.name,
                        maximumCharacters: min(
                            remaining,
                            ChatPresentationSafety.maximumToolNameCharacters
                        )
                    )
                    remaining -= min(name.count, remaining)
                    let detail = remaining > 0 ? tool.detail.flatMap {
                        ChatPresentationSafety.activityDetail($0).map { value in
                            let bounded = String(value.prefix(remaining))
                            remaining -= min(bounded.count, remaining)
                            return bounded
                        }
                    } : nil
                    return Record.Part(
                        id: part.id,
                        kind: "tool",
                        text: nil,
                        toolName: name,
                        toolDetail: detail,
                        toolState: tool.state.rawValue,
                        durationSeconds: tool.durationSeconds
                    )
                case .generatedImage:
                    // Image URLs may be signed/ephemeral. Keep them only in
                    // memory; gateway transcript remains the restore authority.
                    return nil
                }
            }
            reversed.append(Record(
                id: message.id.uuidString,
                role: roleName(message.role),
                text: text,
                parts: parts
            ))
        }
        return reversed.reversed()
    }

    private static func message(from record: Record) -> TranscriptMessage? {
        guard let role = role(named: record.role) else { return nil }
        let parts = record.parts.compactMap { part -> AssistantTurnPart? in
            switch part.kind {
            case "text":
                guard let text = part.text else { return nil }
                return AssistantTurnPart(id: part.id, content: .text(text))
            case "reasoning":
                guard let text = part.text else { return nil }
                return AssistantTurnPart(
                    id: part.id,
                    content: .reasoning(.init(text: text, wasTruncated: text.hasSuffix("… [truncated]")))
                )
            case "tool":
                guard let name = part.toolName,
                      let rawState = part.toolState,
                      let state = AssistantTurnPart.Tool.State(rawValue: rawState) else { return nil }
                return AssistantTurnPart(
                    id: part.id,
                    content: .tool(.init(
                        callID: nil,
                        name: name,
                        detail: part.toolDetail,
                        state: state,
                        durationSeconds: part.durationSeconds
                    ))
                )
            default:
                return nil
            }
        }
        return TranscriptMessage(
            id: UUID(uuidString: record.id) ?? UUID(),
            role: role,
            text: record.text,
            streaming: false,
            assistantParts: role == .assistant ? parts : []
        )
    }

    private static func roleName(_ role: TranscriptMessage.Role) -> String {
        switch role {
        case .user: return "user"
        case .assistant: return "assistant"
        case .system: return "system"
        case .info: return "info"
        }
    }

    private static func role(named name: String) -> TranscriptMessage.Role? {
        switch name {
        case "user": return .user
        case "assistant": return .assistant
        case "system": return .system
        case "info": return .info
        default: return nil
        }
    }

    private func fileURL(for key: String) -> URL {
        // A cryptographic digest keeps unrelated gateway/session keys from
        // ever sharing one local snapshot path while still avoiding disclosure
        // of the authoritative key in the file name.
        let digest = SHA256.hash(data: Data(key.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        return directoryURL.appendingPathComponent("\(digest).json")
    }

    private func secureDirectory() throws {
        let fileManager = FileManager.default
        try fileManager.createDirectory(
            at: directoryURL,
            withIntermediateDirectories: true,
            attributes: [.protectionKey: Self.requiredFileProtection]
        )
        try fileManager.setAttributes(
            [.protectionKey: Self.requiredFileProtection],
            ofItemAtPath: directoryURL.path
        )
        try excludeFromBackup(directoryURL)
        guard try isSecureItem(directoryURL) else {
            throw CocoaError(.fileWriteNoPermission)
        }
    }

    private func excludeFromBackup(_ url: URL) throws {
        var mutableURL = url
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try mutableURL.setResourceValues(values)
    }

    private func isSecureItem(_ url: URL) throws -> Bool {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        let rawProtection = attributes[.protectionKey]
        #if targetEnvironment(simulator)
        // CoreSimulator does not consistently persist NSFileProtectionKey on
        // its host-backed APFS files. Accept only that platform-specific
        // absence; any explicit non-complete value still fails closed. Device
        // builds require and verify `.complete` below.
        let hasCompleteProtection = rawProtection == nil
            || Self.hasRequiredFileProtection(rawProtection)
        #else
        let hasCompleteProtection = Self.hasRequiredFileProtection(rawProtection)
        #endif
        let values = try url.resourceValues(forKeys: [.isExcludedFromBackupKey])
        return hasCompleteProtection && values.isExcludedFromBackup == true
    }

    static func hasRequiredFileProtection(_ raw: Any?) -> Bool {
        (raw as? FileProtectionType) == requiredFileProtection
            || (raw as? String) == requiredFileProtection.rawValue
    }

    private func fileSize(at url: URL) throws -> Int {
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        return values.fileSize ?? 0
    }

    /// Directory-wide LRU pruning. Modification time is the access clock:
    /// successful loads touch it, writes naturally refresh it, and every pass
    /// removes stale/oversized/insecure snapshots before enforcing the global
    /// session-count and byte ceilings.
    private func prune(now: Date = Date()) {
        let keys: Set<URLResourceKey> = [
            .contentModificationDateKey,
            .fileSizeKey,
            .isRegularFileKey,
        ]
        guard let urls = try? FileManager.default.contentsOfDirectory(
            at: directoryURL,
            includingPropertiesForKeys: Array(keys),
            options: [.skipsHiddenFiles]
        ) else { return }

        let cutoff = now.addingTimeInterval(-policy.maximumAge)
        var candidates: [(url: URL, modified: Date, size: Int)] = []
        for url in urls where url.pathExtension == "json" {
            guard let values = try? url.resourceValues(forKeys: keys),
                  values.isRegularFile == true,
                  let modified = values.contentModificationDate,
                  let size = values.fileSize,
                  size <= policy.maximumEncodedBytes,
                  modified >= cutoff,
                  (try? isSecureItem(url)) == true else {
                try? FileManager.default.removeItem(at: url)
                continue
            }
            candidates.append((url, modified, size))
        }

        candidates.sort {
            if $0.modified != $1.modified { return $0.modified > $1.modified }
            return $0.url.lastPathComponent < $1.url.lastPathComponent
        }
        var retainedBytes = 0
        for (index, candidate) in candidates.enumerated() {
            let exceedsCount = index >= policy.maximumSessions
            let exceedsBytes = retainedBytes + candidate.size > policy.maximumDirectoryBytes
            if exceedsCount || exceedsBytes {
                try? FileManager.default.removeItem(at: candidate.url)
            } else {
                retainedBytes += candidate.size
            }
        }
    }
}

/// Small injectable seam around the non-idempotent chat RPCs. Production uses
/// the typed `GatewayAPI`; tests can deterministically prove rejection versus
/// ambiguous transport outcomes without opening a WebSocket or adding a new
/// tool/protocol to the app's core surface.
struct ChatGatewayOperations {
    let createSession: () async throws -> LiveSession
    let resumeSession: (String) async throws -> LiveSession
    let submitPrompt: (String, String) async throws -> Void
    let steer: (String, String) async throws -> Bool
    let execSlash: (String, String) async throws -> String?
    let submitLegacyBackground: (String, String) async throws -> String?
    /// (sessionId, title, preferTypedMethod) → server-confirmed title. Like
    /// the attach defaults below, this fails closed so a fixture that never
    /// wired rename cannot fake a successful server rename.
    var renameSession: (String, String, Bool) async throws -> String = { _, _, _ in
        throw GatewayClientError.rpc(message: "Renaming is unavailable.")
    }
    /// (sessionId, data, filename) → server placeholder line. Defaults fail
    /// closed so a fixture without attachment support cannot fake an upload.
    var attachImage: (String, Data, String) async throws -> String = { _, _, _ in
        throw GatewayClientError.rpc(message: "Attachments are unavailable.")
    }
    var attachPDF: (String, Data, String) async throws -> String = { _, _, _ in
        throw GatewayClientError.rpc(message: "Attachments are unavailable.")
    }
    /// (sessionId, data, filename, mimeType) → `@file:` prompt reference.
    var attachFile: (String, Data, String, String) async throws -> String = { _, _, _, _ in
        throw GatewayClientError.rpc(message: "Attachments are unavailable.")
    }

    static func live(api: GatewayAPI) -> ChatGatewayOperations {
        ChatGatewayOperations(
            createSession: { try await api.createSession() },
            resumeSession: { try await api.resumeSession(storedSessionId: $0) },
            submitPrompt: { try await api.submitPrompt(sessionId: $0, text: $1) },
            steer: { try await api.steer(sessionId: $0, text: $1) },
            execSlash: { try await api.execSlashCommand(sessionId: $0, command: $1) },
            submitLegacyBackground: {
                try await api.submitBackgroundPrompt(sessionId: $0, text: $1)
            },
            renameSession: {
                try await api.setSessionTitle(sessionId: $0, title: $1, preferTypedMethod: $2)
            },
            attachImage: {
                try await api.attachImageBytes(sessionId: $0, data: $1, filename: $2)
            },
            attachPDF: {
                try await api.attachPDF(sessionId: $0, data: $1, filename: $2)
            },
            attachFile: {
                try await api.attachFile(sessionId: $0, data: $1, filename: $2, mimeType: $3)
            }
        )
    }
}

/// Wires one chat session to the gateway event stream: creates or resumes
/// the runtime session, submits prompts, and folds streaming events into a
/// renderable transcript. Event names/payloads match the shared contract in
/// `apps/shared/src/json-rpc-gateway.ts` and `tui_gateway/server.py`.
@Observable
@MainActor
final class ChatViewModel {
    private(set) var messages: [TranscriptMessage] = []
    private(set) var statusLine: String?
    private(set) var persistenceWarning: String?
    private(set) var showingCachedTranscript = false
    private(set) var unknownSendOutcome: UnknownSendOutcome?
    private(set) var busy = false
    private(set) var pendingApproval: PendingApproval?
    private(set) var approvalResponseState: ApprovalResponseState = .idle
    private(set) var pendingPrompt: PendingPrompt?
    private(set) var interactionAccessibilityCue: PendingInteractionAccessibilityCue?
    private(set) var sessionReady = false
    private(set) var sessionError: String?
    /// Server-confirmed conversation title after a successful rename.
    private(set) var sessionTitle: String?
    /// Attachments staged for the next plain prompt.
    private(set) var pendingAttachments: [ChatComposerAttachment] = []
    /// True while a send is uploading its staged attachments; the composer
    /// locks its send action so a second tap cannot start an overlapping
    /// upload batch.
    private(set) var isUploadingAttachments = false
    /// Receipts for uploads that already succeeded within the current staged
    /// batch, keyed by attachment id. A failed batch keeps its items staged;
    /// the retry replays these receipts instead of double-queuing the bytes
    /// on the gateway.
    private var stagedUploadOutcomes: [UUID: StagedUploadOutcome] = [:]
    /// Server-issued Work namespace that fences durable background mutations
    /// and the in-memory Job recovery path. It does not render a Work UI.
    private(set) var workIdentity: FabricWorkSessionIdentity?
    /// Sanitized public Job after-states keyed by their server-issued IDs.
    /// This is intentionally in-memory until the Work projection UI lands.
    private(set) var durableBackgroundJobs: [String: FabricWorkJobSummary] = [:]
    /// Reference-only current Work state. It is populated exclusively by
    /// validated bootstrap/delta pages, never by an event hint.
    private(set) var durableWorkProjection: FabricWorkProjection?
    /// Cumulative token/context usage. Seeded from the create/resume response
    /// and merged from `session.info` / `message.complete` events with
    /// desktop-parity overlay semantics (newer keys win only when present).
    private(set) var usage: SessionUsage?
    /// Live activity flags feeding the pet companion. `busy` is mirrored from
    /// this view model's own in-flight-turn state when the state is derived.
    private(set) var petActivity = PetActivitySnapshot()

    var petState: PetState {
        var snapshot = petActivity
        snapshot.busy = busy
        return PetActivitySnapshot.derive(snapshot)
    }

    /// Product-facing Work state shared by every future home/mission-control
    /// direction. It remains a pure projection; rendering stays out of this
    /// view model until the visual direction is selected.
    var goalPortfolio: FabricGoalPortfolio? {
        durableWorkProjection.map(FabricGoalPortfolio.init(projection:))
    }

    let api: GatewayAPI
    private(set) var storedSessionId: String?
    private(set) var sessionId: String?
    private var unsubscribe: (() -> Void)?
    private var pendingEvents: [GatewayEvent] = []
    private var interactionQueue = PendingInteractionQueue()
    private var interactionAccessibilityCoordinator = PendingInteractionAccessibilityCoordinator()
    private var bootstrapGeneration = 0
    private var starting = false
    private let supportsMethod: (String) -> Bool
    private let operations: ChatGatewayOperations
    private let durableWorkNegotiation: () -> GatewayCapabilityNegotiation?
    private let workGatewayID: () -> String?
    private let presentationCache: ChatPresentationCache
    private var pendingImageArtifactFetches: Set<String> = []
    private var pendingDurableBackgroundMutations: [PendingDurableBackgroundMutation] = []
    private var workSyncInFlight = false
    private var workSyncNeedsAnotherPass = false
    private var petTransientBeatTask: Task<Void, Never>?

    static func approval(from event: GatewayEvent) -> PendingApproval? {
        guard
            let requestId = event.payload["request_id"] as? String,
            !requestId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return nil }
        return PendingApproval(
            command: event.payload["command"] as? String,
            requestId: requestId,
            summary: (event.payload["summary"] as? String)
                ?? (event.payload["description"] as? String),
            cwd: event.payload["cwd"] as? String,
            allowPermanent: event.payload["allow_permanent"] as? Bool ?? true
        )
    }

    /// Gateway `error` payloads may contain raw exception messages, paths,
    /// request headers, or credentials. They never become presentation text;
    /// this caller-owned bounded copy is the entire UI/cache contract.
    static func safeGatewayErrorMessage(from _: GatewayEvent) -> String {
        ChatPresentationSafety.sanitized(
            "Fabric reported an error for this conversation. Check the gateway connection, then try again.",
            maximumCharacters: ChatPresentationSafety.maximumActivityDetailCharacters
        )
    }

    init(
        api: GatewayAPI,
        resumeStoredSessionId: String?,
        supportsMethod: @escaping (String) -> Bool,
        durableWorkNegotiation: @escaping () -> GatewayCapabilityNegotiation? = { nil },
        workGatewayID: @escaping () -> String? = { nil },
        presentationCache: ChatPresentationCache = ChatPresentationCache(),
        operations: ChatGatewayOperations? = nil
    ) {
        self.api = api
        self.storedSessionId = resumeStoredSessionId
        self.supportsMethod = supportsMethod
        self.durableWorkNegotiation = durableWorkNegotiation
        self.workGatewayID = workGatewayID
        self.presentationCache = presentationCache
        self.operations = operations ?? .live(api: api)
    }

    func supportsGatewayMethod(_ method: String) -> Bool {
        supportsMethod(method)
    }

    /// A durable-capable gateway never falls through to `prompt.background`.
    /// The server-issued Work profile identity is also required before this
    /// client can bind a Job to the current session scope.
    var canSendInBackground: Bool {
        if durableWorkNegotiation()?.supportsDurableWork == true {
            return workIdentity != nil
        }
        return supportsMethod("prompt.background")
    }

    var advertisesDurableWork: Bool {
        durableWorkNegotiation()?.supportsDurableWork == true
    }

    var canSubmitInitialPrompt: Bool {
        sessionReady && sessionId != nil && supportsMethod("prompt.submit")
    }

    var hasReadOnlyCachedTranscriptAfterResumeFailure: Bool {
        showingCachedTranscript
            && !messages.isEmpty
            && sessionError != nil
            && !sessionReady
    }

    private func canCall(_ method: String, action: String) -> Bool {
        guard supportsMethod(method) else {
            messages.append(TranscriptMessage(
                role: .system,
                text: "\(action) is unavailable on this gateway."
            ))
            return false
        }
        return true
    }

    private func installWorkIdentity(_ identity: FabricWorkSessionIdentity?) {
        // A gateway profile change is a new Work namespace. Do not show or
        // refresh Job IDs that were learned under the previous one.
        if workIdentity?.profileID != identity?.profileID {
            durableBackgroundJobs.removeAll()
            durableWorkProjection = nil
            // A raw prompt retry must never cross the server-issued profile
            // boundary. The user can submit a new intent after a profile
            // change, with a new idempotency key.
            pendingDurableBackgroundMutations.removeAll()
        }
        workIdentity = identity
    }

    private func mergeUsage(from payload: [String: Any]) {
        guard let raw = payload["usage"] as? [String: Any],
              let parsed = SessionUsage.from(payload: raw) else { return }
        usage = usage?.merging(parsed) ?? parsed
    }

    private func updatePetSteadyFlags(for eventType: String) {
        switch eventType {
        case "reasoning.delta", "reasoning.available", "thinking.delta":
            petActivity.reasoning = true
        case "tool.start", "tool.progress", "tool.generating":
            petActivity.toolRunning = true
            petActivity.reasoning = false
        case "tool.complete":
            petActivity.toolRunning = false
        default:
            break
        }
    }

    private enum PetTransientBeat {
        case celebrate
        case error

        var decay: Duration {
            switch self {
            case .celebrate: return .milliseconds(2_200)
            case .error: return .milliseconds(1_600)
            }
        }
    }

    /// Setting a transient beat clears its siblings first, so a completion
    /// can never render `failed` off a stale error flag (and vice versa).
    private func triggerPetBeat(_ beat: PetTransientBeat) {
        petTransientBeatTask?.cancel()
        petActivity.errorBeat = beat == .error
        petActivity.celebrateBeat = beat == .celebrate
        petActivity.justCompletedBeat = false
        petTransientBeatTask = Task { [weak self] in
            try? await Task.sleep(for: beat.decay)
            guard !Task.isCancelled, let self else { return }
            switch beat {
            case .celebrate: self.petActivity.celebrateBeat = false
            case .error: self.petActivity.errorBeat = false
            }
        }
    }

    private func enqueueInteraction(_ interaction: PendingInteraction) {
        interactionQueue.enqueue(interaction)
        publishActiveInteraction()
    }

    private func removeInteraction(_ interaction: PendingInteraction) {
        interactionQueue.remove(interaction)
        publishActiveInteraction()
    }

    private func clearInteractions() {
        interactionQueue.clear()
        publishActiveInteraction()
    }

    private func publishActiveInteraction() {
        petActivity.awaitingInput = interactionQueue.first != nil
        let previousApprovalID = pendingApproval?.requestId
        pendingApproval = nil
        pendingPrompt = nil
        guard let interaction = interactionQueue.first else {
            approvalResponseState = .idle
            _ = interactionAccessibilityCoordinator.cue(for: nil)
            interactionAccessibilityCue = nil
            return
        }
        if let cue = interactionAccessibilityCoordinator.cue(for: interaction) {
            interactionAccessibilityCue = cue
        }
        switch interaction {
        case .approval(let approval):
            pendingApproval = approval
            if previousApprovalID != approval.requestId {
                approvalResponseState = .idle
            }
        case .prompt(let prompt):
            pendingPrompt = prompt
            approvalResponseState = .idle
        }
    }

    func start() async {
        guard sessionId == nil, !starting else { return }
        let method = storedSessionId == nil ? "session.create" : "session.resume"
        guard supportsMethod(method) else {
            sessionError = "This gateway does not support the required \(method) control."
            return
        }
        starting = true
        sessionError = nil
        restoreCachedPresentationIfAvailable()
        bootstrapGeneration += 1
        let generation = bootstrapGeneration
        defer {
            if generation == bootstrapGeneration { starting = false }
        }
        subscribeToEvents()
        do {
            let restoring = storedSessionId != nil
            let live: LiveSession
            if let storedSessionId {
                live = try await operations.resumeSession(storedSessionId)
            } else {
                live = try await operations.createSession()
            }
            guard generation == bootstrapGeneration, !Task.isCancelled else { return }
            guard !live.sessionId.isEmpty else {
                pendingEvents.removeAll()
                sessionError = "Gateway returned no session id."
                return
            }
            guard let durableId = live.storedSessionId, !durableId.isEmpty else {
                pendingEvents.removeAll()
                sessionError = "Gateway returned no durable session key. Check Active sessions before starting another chat."
                return
            }
            storedSessionId = durableId
            installWorkIdentity(live.workIdentity)
            if let seeded = live.usage {
                usage = usage?.merging(seeded) ?? seeded
            }
            if restoring {
                messages = Self.restoredMessages(from: live)
                busy = live.running
                showingCachedTranscript = false
            }
            sessionId = live.sessionId
            let events = Self.eventsForReplay(
                pendingEvents,
                live: live,
                restoredMessages: messages
            ) + live.pendingInteractions
            pendingEvents.removeAll()
            for event in events {
                handle(event)
            }
            fetchGatewayImageArtifactsIfNeeded()
            sessionReady = true
            sessionError = nil
            unknownSendOutcome = nil
            replacePresentationCache()
            Task { [weak self] in
                await self?.retryPendingDurableBackgroundMutations()
                await self?.syncDurableWork()
                await self?.refreshDurableBackgroundJobs()
            }
        } catch {
            guard generation == bootstrapGeneration, !Task.isCancelled else { return }
            pendingEvents.removeAll()
            sessionError = storedSessionId == nil
                ? "Session creation outcome is unknown. Check Active sessions before starting another chat."
                : ChatPresentationSafety.userVisibleFailure(
                    for: error,
                    fallback: "Couldn't resume this conversation. Check the gateway connection, then try again."
                )
        }
    }

    func connectionDidClose() {
        replacePresentationCache()
        // Keep the already-rendered conversation visible while reconnecting.
        // If the authoritative resume then fails, Chat presents this retained
        // snapshot as read-only instead of replacing it with an empty error.
        showingCachedTranscript = !messages.isEmpty
        bootstrapGeneration += 1
        starting = false
        sessionId = nil
        sessionReady = false
        pendingEvents.removeAll()
        pendingImageArtifactFetches.removeAll()
        clearInteractions()
        petActivity.toolRunning = false
        petActivity.reasoning = false
        statusLine = nil
    }

    func resumeAfterReconnect() async {
        guard let storedSessionId, !storedSessionId.isEmpty, !starting else {
            if self.storedSessionId == nil {
                sessionError = "Session creation outcome is unknown. Check Active sessions before starting another chat."
            }
            return
        }
        guard supportsMethod("session.resume") else {
            sessionError = "This gateway does not support session.resume."
            return
        }

        if sessionId != nil {
            connectionDidClose()
        }
        starting = true
        sessionError = nil
        bootstrapGeneration += 1
        let generation = bootstrapGeneration
        defer {
            if generation == bootstrapGeneration { starting = false }
        }
        subscribeToEvents()

        do {
            let live = try await operations.resumeSession(storedSessionId)
            guard generation == bootstrapGeneration, !Task.isCancelled else { return }
            guard !live.sessionId.isEmpty,
                  let durableId = live.storedSessionId,
                  !durableId.isEmpty else {
                pendingEvents.removeAll()
                sessionError = "Gateway returned an invalid resume snapshot."
                return
            }

            let restored = Self.restoredMessages(from: live)
            messages = restored
            showingCachedTranscript = false
            busy = live.running
            clearInteractions()
            statusLine = nil
            self.storedSessionId = durableId
            installWorkIdentity(live.workIdentity)
            if let seeded = live.usage {
                usage = usage?.merging(seeded) ?? seeded
            }
            sessionId = live.sessionId
            let events = Self.eventsForReplay(
                pendingEvents,
                live: live,
                restoredMessages: restored
            ) + live.pendingInteractions
            pendingEvents.removeAll()
            for event in events { handle(event) }
            fetchGatewayImageArtifactsIfNeeded()
            sessionReady = true
            sessionError = nil
            unknownSendOutcome = nil
            replacePresentationCache()
            Task { [weak self] in
                await self?.retryPendingDurableBackgroundMutations()
                await self?.syncDurableWork()
                await self?.refreshDurableBackgroundJobs()
            }
        } catch {
            guard generation == bootstrapGeneration, !Task.isCancelled else { return }
            pendingEvents.removeAll()
            sessionError = ChatPresentationSafety.userVisibleFailure(
                for: error,
                fallback: "Couldn't resume this conversation. Check the gateway connection, then try again."
            )
        }
    }

    func stop() {
        replacePresentationCache()
        bootstrapGeneration += 1
        starting = false
        unsubscribe?()
        unsubscribe = nil
        petTransientBeatTask?.cancel()
        petTransientBeatTask = nil
        pendingEvents.removeAll()
        pendingImageArtifactFetches.removeAll()
        // Never retain raw background prompt text after this chat surface is
        // discarded. Durable public Job summaries remain server-authoritative.
        pendingDurableBackgroundMutations.removeAll()
        // Staged attachment bytes are draft-local; release them with the
        // surface instead of holding picked media in memory.
        pendingAttachments.removeAll()
        stagedUploadOutcomes.removeAll()
    }

    /// Route a composer submit the way the TUI does: a busy turn gets a
    /// steering note, "/..." dispatches a slash command, everything else is
    /// a normal prompt. Staged attachments ride only the plain-prompt path;
    /// steering notes and slash commands leave them staged.
    func send(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard unknownSendOutcome == nil, let sessionId else { return }

        if busy {
            guard !trimmed.isEmpty else { return }
            await steer(trimmed)
            return
        }

        if trimmed.hasPrefix("/") {
            await execSlash(trimmed)
            return
        }

        guard !trimmed.isEmpty || !pendingAttachments.isEmpty else { return }
        _ = await submitPrompt(trimmed, sessionId: sessionId)
    }

    /// Submit a conversation-first Home objective as a normal prompt even
    /// when its first character is `/`. Home promises the baseline
    /// `prompt.submit` contract; it must not silently reinterpret user prose
    /// as a slash command or steering note. The return value means an attempt
    /// began, not that the gateway confirmed receipt; the transcript retains
    /// the objective when the network outcome is unknown.
    @discardableResult
    func sendInitialPrompt(_ text: String) async -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard unknownSendOutcome == nil,
              sessionReady,
              let sessionId,
              !trimmed.isEmpty else { return false }
        return await submitPrompt(trimmed, sessionId: sessionId)
    }

    @discardableResult
    private func submitPrompt(_ trimmed: String, sessionId: String) async -> Bool {
        guard canCall("prompt.submit", action: "Sending messages") else { return false }
        guard !isUploadingAttachments else { return false }

        // Upload staged attachments first: the gateway folds queued images
        // and PDF pages into this prompt's turn, and file refs must appear in
        // the prompt text. A failed upload keeps EVERY item staged (already-
        // confirmed receipts are memoized above) and does not submit a
        // half-described prompt.
        let staged = pendingAttachments
        if !staged.isEmpty {
            isUploadingAttachments = true
        }
        defer { isUploadingAttachments = false }
        for attachment in staged where stagedUploadOutcomes[attachment.id] == nil {
            do {
                stagedUploadOutcomes[attachment.id] =
                    try await uploadAttachment(attachment, sessionId: sessionId)
            } catch {
                messages.append(TranscriptMessage(
                    role: .system,
                    text: ChatPresentationSafety.userVisibleFailure(
                        for: error,
                        fallback: "\"\(attachment.filename)\" couldn't be attached. It stays ready — send again or remove it."
                    )
                ))
                return false
            }
        }
        let outcomes = staged.compactMap { stagedUploadOutcomes[$0.id] }
        let placeholders = outcomes.map(\.placeholder)
        let promptLines = outcomes.filter(\.mustAppearInPrompt).map(\.placeholder)
        let stagedIDs = Set(staged.map(\.id))
        pendingAttachments.removeAll { stagedIDs.contains($0.id) }
        for id in stagedIDs { stagedUploadOutcomes.removeValue(forKey: id) }

        var promptText = trimmed
        if !promptLines.isEmpty {
            promptText = (trimmed.isEmpty ? promptLines : [trimmed] + promptLines)
                .joined(separator: "\n")
        }
        if promptText.isEmpty {
            promptText = placeholders.joined(separator: "\n")
        }
        guard !promptText.isEmpty else { return false }

        // The placeholder copy is server-authored; it enters presentation
        // only redacted and bounded, while the wire prompt keeps the exact
        // refs the gateway issued.
        let presentationText = trimmed.isEmpty
            ? ChatPresentationSafety.sanitized(
                placeholders.joined(separator: "\n"),
                maximumCharacters: ChatPresentationSafety.maximumActivityDetailCharacters
            )
            : trimmed
        messages.append(TranscriptMessage(
            role: .user,
            text: presentationText,
            attachments: staged.map {
                TranscriptAttachmentPreview(
                    id: $0.id,
                    kind: $0.kind,
                    filename: $0.filename,
                    data: $0.data
                )
            }
        ))
        unknownSendOutcome = nil
        busy = true
        do {
            try await operations.submitPrompt(sessionId, promptText)
        } catch {
            busy = false
            recordMutationFailure(error, action: .prompt)
        }
        return true
    }

    private struct StagedUploadOutcome {
        let placeholder: String
        let mustAppearInPrompt: Bool
    }

    /// Send one staged attachment over its advertised RPC. Images and PDFs
    /// fall back to the readable `file.attach` path when their dedicated
    /// vision upload is not advertised, so the agent can still open them.
    private func uploadAttachment(
        _ attachment: ChatComposerAttachment,
        sessionId: String
    ) async throws -> StagedUploadOutcome {
        switch attachment.kind {
        case .image where supportsMethod("image.attach_bytes"):
            return StagedUploadOutcome(
                placeholder: try await operations.attachImage(
                    sessionId, attachment.data, attachment.filename
                ),
                mustAppearInPrompt: false
            )
        case .pdf where supportsMethod("pdf.attach"):
            return StagedUploadOutcome(
                placeholder: try await operations.attachPDF(
                    sessionId, attachment.data, attachment.filename
                ),
                mustAppearInPrompt: false
            )
        case .image, .pdf, .file:
            guard supportsMethod("file.attach") else {
                throw GatewayClientError.rpc(
                    message: "Attachments are unavailable on this gateway."
                )
            }
            return StagedUploadOutcome(
                placeholder: try await operations.attachFile(
                    sessionId, attachment.data, attachment.filename, attachment.mimeType
                ),
                mustAppearInPrompt: true
            )
        }
    }

    /// Explicitly re-hydrate authoritative history after an ambiguous
    /// `prompt.submit` receipt. This never resends the original prompt.
    func checkConversationAfterUnknownSend() async {
        guard unknownSendOutcome != nil, storedSessionId?.isEmpty == false else { return }
        await resumeAfterReconnect()
    }

    /// Inject a note into the running turn without interrupting it.
    func steer(_ text: String) async {
        guard unknownSendOutcome == nil else { return }
        guard canCall("session.steer", action: "Steering") else { return }
        guard let sessionId else { return }
        do {
            let queued = try await operations.steer(sessionId, text)
            messages.append(TranscriptMessage(
                role: .info,
                text: queued
                    ? "Steering note queued — the agent sees it on its next step."
                    : "Steering rejected: no turn is accepting notes right now."
            ))
        } catch {
            recordMutationFailure(error, action: .steering)
        }
    }

    /// Dispatch a slash command (`/status`, `/model`, skills, quick commands…).
    func execSlash(_ command: String) async {
        guard unknownSendOutcome == nil else { return }
        guard canCall("slash.exec", action: "Slash commands") else { return }
        guard let sessionId else { return }
        messages.append(TranscriptMessage(role: .user, text: command))
        do {
            let output = try await operations.execSlash(sessionId, command)
            if let output, !output.isEmpty {
                messages.append(TranscriptMessage(role: .info, text: output))
            }
        } catch {
            recordMutationFailure(error, action: .slashCommand)
        }
    }

    /// Run the text as a detached background task. On a truthfully advertised
    /// Work gateway this is an idempotent `job.create`; legacy
    /// `prompt.background` remains only for gateways that do not advertise
    /// Durable Work at all.
    func sendInBackground(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard unknownSendOutcome == nil,
              let sessionId,
              !trimmed.isEmpty else { return }
        if let negotiation = durableWorkNegotiation(), negotiation.supportsDurableWork {
            guard workIdentity != nil else {
                messages.append(TranscriptMessage(
                    role: .system,
                    text: "Durable background work is unavailable until this session provides a valid Work profile identity."
                ))
                return
            }
            await submitDurableBackgroundWork(
                sessionID: sessionId,
                text: trimmed,
                negotiation: negotiation
            )
            return
        }

        guard canCall("prompt.background", action: "Background work") else { return }
        messages.append(TranscriptMessage(role: .user, text: trimmed))
        do {
            let taskId = try await operations.submitLegacyBackground(sessionId, trimmed)
            messages.append(TranscriptMessage(
                role: .info,
                text: "Background task started\(taskId.map { " (\($0))" } ?? "")."
            ))
        } catch {
            recordMutationFailure(error, action: .legacyBackground)
        }
    }

    private func recordMutationFailure(_ error: Error, action: ChatMutationAction) {
        let presentation = ChatMutationFailurePresentation.classify(error, action: action)
        if let description = presentation.outcomeDescription {
            unknownSendOutcome = UnknownSendOutcome(
                action: action,
                description: description
            )
        }
        messages.append(TranscriptMessage(role: .system, text: presentation.message))
        replacePresentationCache()
    }

    private func submitDurableBackgroundWork(
        sessionID: String,
        text: String,
        negotiation: GatewayCapabilityNegotiation
    ) async {
        let title = "Background work"
        let existing = pendingDurableBackgroundMutations.first {
            $0.text == text && $0.title == title
        }
        let mutation = existing ?? PendingDurableBackgroundMutation(
            text: text,
            title: title,
            idempotencyKey: UUID().uuidString
        )
        if existing == nil {
            pendingDurableBackgroundMutations.append(mutation)
            messages.append(TranscriptMessage(role: .user, text: text))
        }

        do {
            let receipt = try await api.createBackgroundWork(
                sessionID: sessionID,
                text: mutation.text,
                title: mutation.title,
                idempotencyKey: mutation.idempotencyKey,
                negotiation: negotiation
            )
            pendingDurableBackgroundMutations.removeAll {
                $0.idempotencyKey == mutation.idempotencyKey
            }
            durableBackgroundJobs[receipt.job.jobID] = receipt.job
            Task { [weak self] in
                await self?.syncDurableWork()
            }
            let taskID = receipt.taskID ?? receipt.job.runtimeSessionID
            messages.append(TranscriptMessage(
                role: .info,
                text: "Background Job started \(receipt.job.jobID)\(taskID.map { " (\($0))" } ?? "")."
            ))
        } catch {
            // Preserve the exact idempotency key only when the outcome may be
            // unknown. A later explicit retry replays the original receipt
            // instead of creating a duplicate Job. Never fall back to the
            // legacy RPC after this durable attempt.
            if !Self.mayNeedDurableBackgroundRetry(error) {
                pendingDurableBackgroundMutations.removeAll {
                    $0.idempotencyKey == mutation.idempotencyKey
                }
            }
            messages.append(TranscriptMessage(
                role: .system,
                text: ChatPresentationSafety.userVisibleFailure(
                    for: error,
                    fallback: "The background Job couldn't be started. Check the gateway connection, then try again."
                )
            ))
        }
    }

    private func refreshDurableBackgroundJobs() async {
        guard let sessionId,
              workIdentity != nil,
              let negotiation = durableWorkNegotiation(),
              negotiation.supportsDurableWork
        else { return }
        let generation = bootstrapGeneration
        let jobIDs = Array(durableBackgroundJobs.keys)
        for jobID in jobIDs {
            do {
                let job = try await api.getWorkJob(
                    sessionID: sessionId,
                    jobID: jobID,
                    negotiation: negotiation
                )
                guard generation == bootstrapGeneration, self.sessionId == sessionId else { return }
                durableBackgroundJobs[jobID] = job
            } catch {
                // The ledger remains authoritative; leave the last sanitized
                // after-state visible until a later Work event/reconnect can
                // refresh it. Do not turn a refresh failure into legacy work.
            }
        }
    }

    private func retryPendingDurableBackgroundMutations() async {
        guard let sessionId,
              workIdentity != nil,
              let negotiation = durableWorkNegotiation(),
              negotiation.supportsDurableWork
        else { return }
        // Snapshot before awaiting: a receipt removes the matching mutation.
        let mutations = pendingDurableBackgroundMutations
        for mutation in mutations {
            await submitDurableBackgroundWork(
                sessionID: sessionId,
                text: mutation.text,
                negotiation: negotiation
            )
        }
    }

    /// Bootstrap or advance the one fenced Work projection for this chat. A
    /// `work.changed` event only calls this method; it never supplies state.
    private func syncDurableWork() async {
        guard let sessionId,
              let identity = workIdentity,
              let gatewayID = workGatewayID(),
              let scope = identity.syncScope(gatewayID: gatewayID),
              let negotiation = durableWorkNegotiation(),
              negotiation.supportsDurableWork
        else { return }

        if workSyncInFlight {
            workSyncNeedsAnotherPass = true
            return
        }
        workSyncInFlight = true
        defer {
            workSyncInFlight = false
            if workSyncNeedsAnotherPass {
                workSyncNeedsAnotherPass = false
                Task { [weak self] in
                    await self?.syncDurableWork()
                }
            }
        }

        do {
            var state: FabricWorkProjection
            if let existing = durableWorkProjection,
               existing.gatewayID == scope.gatewayID,
               existing.profileID == scope.profileID {
                state = existing
            } else {
                state = try FabricWorkProjectionReducer.create(scope: scope)
            }
            var mode: FabricWorkProjectionPhase =
                state.phase == .empty || state.phase == .bootstrapping ? .bootstrapping : .syncing
            var pages = 0

            while pages < 1_000 {
                pages += 1
                let response: FabricWorkGatewayResponse
                let context: FabricWorkSyncRequestContext
                switch mode {
                case .bootstrapping:
                    let token = state.nextPageToken
                    context = FabricWorkSyncRequestContext(scope: scope, pageToken: token)
                    response = try await api.syncWork(
                        sessionID: sessionId,
                        request: .bootstrap(pageToken: token, limit: FabricWorkLimits.syncPageItems),
                        negotiation: negotiation
                    )
                case .syncing:
                    guard let ledgerID = state.ledgerID, let cursor = state.cursor else {
                        mode = .bootstrapping
                        continue
                    }
                    context = FabricWorkSyncRequestContext(scope: scope, after: cursor)
                    response = try await api.syncWork(
                        sessionID: sessionId,
                        request: .delta(
                            ledgerID: ledgerID,
                            after: cursor,
                            limit: FabricWorkLimits.syncPageItems
                        ),
                        negotiation: negotiation
                    )
                case .empty, .current:
                    // This local state machine uses only bootstrap/syncing.
                    return
                }

                switch response {
                case .page(let page):
                    state = try FabricWorkProjectionReducer.apply(state, page: page, context: context)
                    durableWorkProjection = state
                    refreshKnownJobStates(from: state)
                    if state.phase == .current { return }
                    mode = page.mode == "bootstrap" ? .bootstrapping : .syncing
                case .reset(let reset):
                    state = try FabricWorkProjectionReducer.applyCursorReset(
                        state,
                        reset: reset,
                        scope: scope
                    )
                    durableWorkProjection = state
                    durableBackgroundJobs.removeAll()
                    mode = .bootstrapping
                }
            }
        } catch {
            // A malformed page/RPC failure never updates `state` outside the
            // reducer. Later event hints or reconnect recovery retry safely.
        }
    }

    private func refreshKnownJobStates(from projection: FabricWorkProjection) {
        for jobID in Array(durableBackgroundJobs.keys) {
            if let job = projection.jobs[jobID] {
                durableBackgroundJobs[jobID] = job
            }
        }
    }

    private static func mayNeedDurableBackgroundRetry(_ error: Error) -> Bool {
        guard let gatewayError = error as? GatewayClientError else { return false }
        switch gatewayError {
        case .notConnected, .connectFailed, .socketClosed, .requestTimedOut:
            return true
        case .rpc(_, _, let data):
            return (data as? [String: Any])?["retryable"] as? Bool == true
        }
    }

    func interrupt() async {
        guard canCall("session.interrupt", action: "Interrupting a turn") else { return }
        guard let sessionId else { return }
        try? await api.interrupt(sessionId: sessionId)
    }

    /// Whether the composer should offer media attachments at all. Any of
    /// the three `files`-family uploads is enough — the upload router picks
    /// the best advertised RPC per item.
    var supportsAttachments: Bool {
        supportsMethod("image.attach_bytes")
            || supportsMethod("pdf.attach")
            || supportsMethod("file.attach")
    }

    /// Stage one picked attachment for the next prompt. Rejections surface
    /// as transcript notices with caller-owned copy; raw picker errors never
    /// enter presentation.
    func stageAttachment(_ attachment: ChatComposerAttachment) {
        if let problem = ChatAttachmentPolicy.stagingProblem(
            attachment,
            alreadyStaged: pendingAttachments.count
        ) {
            messages.append(TranscriptMessage(
                role: .system,
                text: ChatPresentationSafety.sanitized(
                    problem,
                    maximumCharacters: ChatPresentationSafety.maximumActivityDetailCharacters
                )
            ))
            return
        }
        pendingAttachments.append(attachment)
    }

    func removeAttachment(id: UUID) {
        pendingAttachments.removeAll { $0.id == id }
        // If this item already uploaded in a failed batch, its bytes stay
        // queued on the gateway and fold into the next prompt; the client
        // has no un-queue RPC, so only the local receipt is dropped.
        stagedUploadOutcomes.removeValue(forKey: id)
    }

    /// Surface a local ingest problem (unreadable photo, denied file) using
    /// the same caller-owned-copy contract as other failures.
    func reportAttachmentProblem(_ copy: String) {
        messages.append(TranscriptMessage(
            role: .system,
            text: ChatPresentationSafety.sanitized(
                copy,
                maximumCharacters: ChatPresentationSafety.maximumActivityDetailCharacters
            )
        ))
    }

    /// Whether this conversation can be renamed right now. The typed
    /// `session.title` RPC and the always-shipped `/title` slash dispatch are
    /// both accepted; either one is enough. A conversation with no turns yet
    /// is excluded: its gateway DB row does not exist until the first prompt,
    /// so a slash-dispatched title would only be queued in the worker and
    /// silently lost.
    var canRenameSession: Bool {
        sessionReady && sessionId != nil
            && !messages.isEmpty
            && (supportsMethod("session.title") || supportsMethod("slash.exec"))
    }

    /// Rename this conversation on the gateway. The confirmed title is
    /// published through `sessionTitle` so navigation chrome and the session
    /// list agree with the server. Returns false when the gateway rejected or
    /// couldn't receive the rename.
    @discardableResult
    func renameSession(to rawTitle: String) async -> Bool {
        let title = rawTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let sessionId, !title.isEmpty else { return false }
        let preferTyped = supportsMethod("session.title")
        guard preferTyped || canCall("slash.exec", action: "Renaming this conversation") else {
            return false
        }
        do {
            // The confirmed title is server-authored on the typed path;
            // bound and redact it like every other server string that
            // reaches presentation.
            sessionTitle = ChatPresentationSafety.sanitized(
                try await operations.renameSession(sessionId, title, preferTyped),
                maximumCharacters: 200
            )
            return true
        } catch {
            messages.append(TranscriptMessage(
                role: .system,
                text: ChatPresentationSafety.userVisibleFailure(
                    for: error,
                    fallback: "The conversation couldn't be renamed. Check the gateway connection, then try again."
                )
            ))
            return false
        }
    }

    func respondToApproval(choice: ApprovalChoice) async {
        guard canCall("approval.respond", action: "Approval responses") else { return }
        guard let sessionId, let approval = pendingApproval else { return }
        guard !approvalResponseState.isSubmitting else { return }
        guard choice != .always || approval.allowPermanent else {
            approvalResponseState = .failed(
                "Permanent approval is unavailable for this request. Choose Once or For this session."
            )
            return
        }
        let interaction = PendingInteraction.approval(approval)
        let generation = bootstrapGeneration
        approvalResponseState = .submitting(choice)
        do {
            try await api.respondToApproval(
                sessionId: sessionId,
                requestId: approval.requestId,
                choice: choice.rawValue
            )
            guard generation == bootstrapGeneration else { return }
            removeInteraction(interaction)
            approvalResponseState = .idle
        } catch {
            guard generation == bootstrapGeneration else { return }
            approvalResponseState = .failed(
                ChatPresentationSafety.userVisibleFailure(
                    for: error,
                    fallback: "The approval response couldn't be sent. Check the gateway connection, then try again."
                )
            )
        }
    }

    /// Compatibility seam for callers that only distinguish allow/deny.
    func respondToApproval(allow: Bool) async {
        await respondToApproval(choice: allow ? .once : .deny)
    }

    /// Answer the pending clarify/sudo/secret prompt. An empty answer is a
    /// valid "dismiss" (the server releases the wait with an empty string).
    func respondToPrompt(_ answer: String) async {
        guard let sessionId, let prompt = pendingPrompt else { return }
        guard canCall(prompt.responseMethod, action: "Prompt responses") else { return }
        let interaction = PendingInteraction.prompt(prompt)
        let generation = bootstrapGeneration
        do {
            switch prompt.kind {
            case .clarify:
                try await api.respondToClarify(
                    sessionId: sessionId,
                    requestId: prompt.requestId,
                    answer: answer
                )
            case .sudo:
                try await api.respondToSudo(
                    sessionId: sessionId,
                    requestId: prompt.requestId,
                    password: answer
                )
            case .secret:
                try await api.respondToSecret(
                    sessionId: sessionId,
                    requestId: prompt.requestId,
                    value: answer
                )
            }
            guard generation == bootstrapGeneration else { return }
            removeInteraction(interaction)
        } catch {
            guard generation == bootstrapGeneration else { return }
            messages.append(TranscriptMessage(
                role: .system,
                text: ChatPresentationSafety.userVisibleFailure(
                    for: error,
                    fallback: "The prompt reply couldn't be sent. Check the gateway connection, then try again."
                )
            ))
        }
    }

    // MARK: - Event folding

    private func subscribeToEvents() {
        guard unsubscribe == nil else { return }
        let client = api.client
        let previous = client.onEvent
        // The client dispatches events on the main queue; assumeIsolated keeps
        // delivery synchronous so streaming deltas stay ordered.
        client.onEvent = { [weak self] event in
            previous?(event)
            MainActor.assumeIsolated {
                self?.handle(event)
            }
        }
        unsubscribe = { client.onEvent = previous }
    }

    private func handle(_ event: GatewayEvent) {
        guard sessionId != nil else {
            // `session.resume` and live events share one socket. Buffer anything
            // that arrives while the resume RPC is in flight, then replay it
            // after the stored transcript is installed so history is not
            // overwritten and live deltas are not lost.
            pendingEvents.append(event)
            return
        }
        // Events carry the runtime session id; ignore other sessions' traffic.
        if let eventSession = event.sessionId, let ours = sessionId, eventSession != ours {
            return
        }

        switch event.type {
        case "session.info":
            // A refreshed snapshot may carry a new profile namespace. If the
            // gateway provides an invalid *or missing* one, fail closed by
            // clearing the old binding rather than retaining a stale profile
            // namespace. A legacy gateway cannot manufacture a Work identity.
            installWorkIdentity(FabricWorkSessionIdentity.from(sessionInfo: event.payload))
            mergeUsage(from: event.payload)

        case "work.changed":
            // A hint never mutates local Job state by itself. It only wakes a
            // typed bootstrap/delta reconciliation; the helper applies its
            // own capability, session, and profile-identity gates.
            Task { [weak self] in
                await self?.syncDurableWork()
                await self?.refreshDurableBackgroundJobs()
            }

        case "message.start":
            busy = true
            statusLine = nil
            petActivity.toolRunning = false
            petActivity.reasoning = false
            clearInteractions()
            messages.append(TranscriptMessage(role: .assistant, text: "", streaming: true))

        case "message.delta", "reasoning.delta", "reasoning.available",
             "tool.start", "tool.progress", "tool.generating", "tool.complete":
            guard let turnEvent = AssistantTurnReducer.event(from: event) else { return }
            busy = true
            updatePetSteadyFlags(for: event.type)
            foldIntoStreamingAssistant(turnEvent)
            fetchGatewayImageArtifactIfNeeded(from: turnEvent)

        case "message.complete":
            busy = false
            statusLine = nil
            mergeUsage(from: event.payload)
            petActivity.toolRunning = false
            petActivity.reasoning = false
            triggerPetBeat(.celebrate)
            guard let turnEvent = AssistantTurnReducer.event(from: event) else { return }
            foldIntoStreamingAssistant(turnEvent, createWhenMissing: event.payloadText?.isEmpty == false)
            if event.payload["history_persisted"] is Bool {
                persistenceWarning = Self.persistenceWarning(from: event)
            }
            replacePresentationCache()


        case "thinking.delta":
            statusLine = "Thinking…"
            updatePetSteadyFlags(for: event.type)

        case "status.update":
            let kind = event.payload["kind"] as? String
            let text = event.payload["text"] as? String
            statusLine = ChatPresentationSafety.activityDetail(text ?? kind)

        case "approval.request":
            guard let approval = Self.approval(from: event) else { return }
            enqueueInteraction(.approval(approval))

        case "clarify.request":
            guard
                let requestId = event.payload["request_id"] as? String,
                !requestId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { return }
            enqueueInteraction(.prompt(PendingPrompt(
                kind: .clarify,
                requestId: requestId,
                question: event.payload["question"] as? String ?? "The agent has a question.",
                choices: event.payload["choices"] as? [String] ?? []
            )))

        case "sudo.request":
            guard
                let requestId = event.payload["request_id"] as? String,
                !requestId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { return }
            enqueueInteraction(.prompt(PendingPrompt(
                kind: .sudo,
                requestId: requestId,
                question: event.payload["prompt"] as? String ?? "Administrator password requested.",
                choices: []
            )))

        case "secret.request":
            guard
                let requestId = event.payload["request_id"] as? String,
                !requestId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { return }
            enqueueInteraction(.prompt(PendingPrompt(
                kind: .secret,
                requestId: requestId,
                question: event.payload["prompt"] as? String ?? "A secret value was requested.",
                choices: []
            )))

        case "background.complete":
            let taskId = event.payload["task_id"] as? String
            let jobID = event.payload["job_id"] as? String
            let safeTaskID = ChatPresentationSafety.activityDetail(taskId)
            let safeText = ChatPresentationSafety.activityDetail(event.payloadText)
                ?? "Background work completed."
            let notice = ChatPresentationSafety.sanitized(
                "Background task\(safeTaskID.map { " \($0)" } ?? "") finished:\n\(safeText)",
                maximumCharacters: ChatPresentationSafety.maximumActivityDetailCharacters
            )
            messages.append(TranscriptMessage(
                role: .info,
                text: notice
            ))
            if let jobID, durableBackgroundJobs[jobID] != nil {
                Task { [weak self] in
                    await self?.syncDurableWork()
                    await self?.refreshDurableBackgroundJobs()
                }
            }

        case "error":
            busy = false
            petActivity.toolRunning = false
            petActivity.reasoning = false
            triggerPetBeat(.error)
            messages.append(TranscriptMessage(
                role: .system,
                text: Self.safeGatewayErrorMessage(from: event)
            ))
            replacePresentationCache()

        default:
            break
        }
    }

    private func fetchGatewayImageArtifactIfNeeded(from event: AssistantTurnEvent) {
        guard case .toolCompleted(_, _, _, false, _, let generatedImage) = event,
              let generatedImage else {
            return
        }
        fetchGatewayImageArtifactIfNeeded(generatedImage)
    }

    private func fetchGatewayImageArtifactsIfNeeded() {
        for message in messages where message.role == .assistant {
            for part in message.assistantParts {
                guard case .generatedImage(let image) = part.content else { continue }
                fetchGatewayImageArtifactIfNeeded(image)
            }
        }
    }

    private func fetchGatewayImageArtifactIfNeeded(_ generatedImage: AssistantTurnPart.GeneratedImage) {
        guard case .gatewayArtifact = generatedImage.source,
              let callID = generatedImage.callID,
              let sessionId,
              !pendingImageArtifactFetches.contains(callID) else {
            return
        }
        guard supportsMethod("artifact.fetch") else {
            replaceGatewayImageArtifactUnavailable(callID: callID)
            return
        }
        pendingImageArtifactFetches.insert(callID)
        let generation = bootstrapGeneration
        Task { [weak self] in
            guard let self else { return }
            defer { self.pendingImageArtifactFetches.remove(callID) }
            do {
                let artifact = try await self.api.fetchImageArtifact(
                    sessionId: sessionId,
                    artifactID: callID
                )
                guard generation == self.bootstrapGeneration,
                      self.sessionId == sessionId,
                      !Task.isCancelled else { return }
                self.replaceGatewayImageArtifact(
                    callID: callID,
                    data: artifact.data,
                    mimeType: artifact.mimeType
                )
            } catch {
                guard generation == self.bootstrapGeneration,
                      self.sessionId == sessionId,
                      !Task.isCancelled else { return }
                self.replaceGatewayImageArtifactUnavailable(callID: callID)
            }
        }
    }

    private func replaceGatewayImageArtifactUnavailable(callID: String) {
        replaceGatewayImageArtifact(callID: callID, source: .unavailable)
    }

    private func replaceGatewayImageArtifact(callID: String, data: Data, mimeType: String) {
        replaceGatewayImageArtifact(callID: callID, source: .data(data, mimeType: mimeType))
    }

    private func replaceGatewayImageArtifact(
        callID: String,
        source: AssistantTurnPart.GeneratedImageSource
    ) {
        for messageIndex in messages.indices.reversed() {
            guard messages[messageIndex].role == .assistant else { continue }
            guard let partIndex = messages[messageIndex].assistantParts.firstIndex(where: { part in
                guard case .generatedImage(let image) = part.content else { return false }
                return image.callID == callID && image.source == .gatewayArtifact
            }) else { continue }
            let original = messages[messageIndex].assistantParts[partIndex]
            messages[messageIndex].assistantParts[partIndex] = AssistantTurnPart(
                id: original.id,
                content: .generatedImage(.init(source: source, callID: callID))
            )
            return
        }
    }

    private func foldIntoStreamingAssistant(
        _ event: AssistantTurnEvent,
        createWhenMissing: Bool = true
    ) {
        if let index = messages.lastIndex(where: { message in
            message.role == .assistant && message.streaming
        }) {
            messages[index] = AssistantTurnReducer.reducing(messages[index], event: event)
            return
        }
        guard createWhenMissing else { return }
        var message = TranscriptMessage(role: .assistant, text: "", streaming: true)
        message = AssistantTurnReducer.reducing(message, event: event)
        messages.append(message)
    }

    private var presentationCacheKey: String? {
        guard let gatewayID = workGatewayID()?.trimmingCharacters(in: .whitespacesAndNewlines),
              !gatewayID.isEmpty,
              let storedSessionId = storedSessionId?.trimmingCharacters(in: .whitespacesAndNewlines),
              !storedSessionId.isEmpty else { return nil }
        return gatewayID + "\u{1F}" + storedSessionId
    }

    private func restoreCachedPresentationIfAvailable() {
        guard messages.isEmpty, let key = presentationCacheKey else { return }
        let cached = presentationCache.load(key: key)
        guard !cached.isEmpty else { return }
        messages = cached
        showingCachedTranscript = true
    }

    private func replacePresentationCache() {
        guard let key = presentationCacheKey else { return }
        presentationCache.replace(key: key, messages: messages)
    }

    /// Rebuild a renderable transcript from a resume snapshot with the same
    /// shape a live stream would have produced: stored tool rows become
    /// completed activity cards inside their assistant turn, and stored
    /// reasoning becomes the turn's disclosure — instead of the flat mono
    /// "ledger rows" that made reopened conversations look degraded.
    static func restoredMessages(from live: LiveSession) -> [TranscriptMessage] {
        var restored: [TranscriptMessage] = []
        var pendingParts: [AssistantTurnPart] = []
        var partSequence = 0

        func nextPartID(_ prefix: String) -> String {
            partSequence += 1
            return "restored-\(prefix):\(partSequence)"
        }

        func appendPendingPart(_ part: AssistantTurnPart) {
            pendingParts.append(part)
            // The same activity bound the live reducer enforces; text parts
            // never accumulate here, so a plain count check is equivalent.
            if pendingParts.count > AssistantTurnReducer.maximumActivityParts {
                pendingParts.removeFirst(
                    pendingParts.count - AssistantTurnReducer.maximumActivityParts
                )
            }
        }

        func flushPendingParts() {
            guard !pendingParts.isEmpty else { return }
            restored.append(TranscriptMessage(
                role: .assistant,
                text: "",
                assistantParts: pendingParts
            ))
            pendingParts.removeAll()
        }

        func reasoningPart(_ source: String?) -> AssistantTurnPart? {
            guard let trimmed = source?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !trimmed.isEmpty else { return nil }
            return AssistantTurnPart(
                id: nextPartID("reasoning"),
                content: .reasoning(.init(
                    text: ChatPresentationSafety.sanitized(
                        trimmed,
                        maximumCharacters: ChatPresentationSafety.maximumReasoningCharacters
                    ),
                    wasTruncated: trimmed.count > ChatPresentationSafety.maximumReasoningCharacters
                ))
            )
        }

        for message in live.messages {
            switch message.role {
            case .tool:
                appendPendingPart(AssistantTurnPart(
                    id: nextPartID("tool"),
                    content: .tool(.init(
                        callID: nil,
                        name: ChatPresentationSafety.toolName(message.toolName),
                        detail: ChatPresentationSafety.activityDetail(message.text),
                        state: .complete,
                        durationSeconds: nil
                    ))
                ))
                if ChatPresentationSafety.toolName(message.toolName) == "image_generate",
                   let artifactID = message.imageArtifactID {
                    appendPendingPart(AssistantTurnPart(
                        id: nextPartID("generated-image"),
                        content: .generatedImage(.init(source: .gatewayArtifact, callID: artifactID))
                    ))
                }
            case .assistant:
                let reasoning = reasoningPart(message.reasoning)
                if message.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    // A reasoning-only turn (extended thinking) stays a
                    // disclosure inside the turn it introduced.
                    if let reasoning { appendPendingPart(reasoning) }
                } else {
                    var parts = pendingParts
                    pendingParts.removeAll()
                    if let reasoning { parts.append(reasoning) }
                    parts.append(AssistantTurnPart(
                        id: nextPartID("text"),
                        content: .text(message.text)
                    ))
                    // The appended reasoning can push the turn one past the
                    // activity bound; apply the live reducer's exact trim.
                    AssistantTurnReducer.trimActivityParts(in: &parts)
                    restored.append(TranscriptMessage(
                        role: .assistant,
                        text: message.text,
                        assistantParts: parts
                    ))
                }
            case .user:
                flushPendingParts()
                restored.append(TranscriptMessage(role: .user, text: message.text))
            case .system:
                // Stored system rows are transcript context, not failures.
                flushPendingParts()
                restored.append(TranscriptMessage(role: .info, text: message.text))
            }
        }
        flushPendingParts()

        if let inflight = live.inflight {
            if !inflight.user.isEmpty {
                restored.append(TranscriptMessage(role: .user, text: inflight.user))
            }
            if !inflight.assistant.isEmpty || inflight.streaming {
                restored.append(TranscriptMessage(
                    role: .assistant,
                    text: inflight.assistant,
                    streaming: inflight.streaming
                ))
            }
        }
        return restored
    }

    static func persistenceWarning(from event: GatewayEvent) -> String? {
        guard event.payload["history_persisted"] as? Bool == false else { return nil }
        if let warning = event.payload["warning"] as? String {
            if let safe = ChatPresentationSafety.activityDetail(warning) { return safe }
        }
        return "This response completed but could not be saved to session history."
    }

    /// Remove only stream frames already represented by the resume snapshot.
    /// This is boundary-scoped; identical replies from separate turns remain.
    static func eventsForReplay(
        _ events: [GatewayEvent],
        live: LiveSession,
        restoredMessages: [TranscriptMessage]
    ) -> [GatewayEvent] {
        if live.inflight != nil {
            var completingSnapshotTurn = true
            return events.filter { event in
                guard event.sessionId == nil || event.sessionId == live.sessionId else { return true }
                guard completingSnapshotTurn else { return true }
                switch event.type {
                case "message.start", "message.delta":
                    return false
                case "message.complete":
                    completingSnapshotTurn = false
                    return true
                default:
                    return true
                }
            }
        }

        let bufferedTurnTypes = Set([
            "approval.request", "clarify.request", "message.delta", "message.start",
            "reasoning.available", "reasoning.delta", "secret.request", "status.update",
            "sudo.request", "thinking.delta", "tool.complete", "tool.generating",
            "tool.progress", "tool.start",
        ])
        var replay: [GatewayEvent] = []
        var turn: [GatewayEvent] = []

        func flushTurn() {
            replay.append(contentsOf: turn)
            turn.removeAll(keepingCapacity: true)
        }

        for event in events {
            guard event.sessionId == nil || event.sessionId == live.sessionId else {
                replay.append(event)
                continue
            }

            if event.type == "message.complete" {
                let covered: Bool
                if let snapshotVersion = live.historyVersion,
                   event.payload["history_persisted"] as? Bool == true,
                   let eventVersion = (event.payload["history_version"] as? NSNumber)?.intValue {
                    covered = eventVersion <= snapshotVersion
                } else {
                    covered = false
                }

                if covered {
                    turn.removeAll(keepingCapacity: true)
                    continue
                }
                flushTurn()
                replay.append(event)
                continue
            }

            if bufferedTurnTypes.contains(event.type) {
                turn.append(event)
            } else {
                flushTurn()
                replay.append(event)
            }
        }

        flushTurn()
        return replay
    }
}
