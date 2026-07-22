import Foundation

/// Swift port of the shared Social Studio artifact parser
/// (apps/shared/src/social.ts -> extractSocialArtifacts). It must produce the
/// same output as the TypeScript implementation for every case in
/// apps/mobile/contracts/social-extraction-v1.json.
///
/// The composer asks the agent to emit the final, paste-ready post inside a
/// fenced block tagged `linkedin-post`, and to show any image with a markdown
/// image / under an "Artifacts" heading. This reads that convention back so a
/// conversation can be shown as image + copyable caption with no new backend.
struct SocialArtifact: Equatable, Identifiable {
    /// Stable within a session render: "<messageIndex>:<blockIndex>".
    let id: String
    /// The exact text to paste into the social network.
    let caption: String
    /// Workspace-relative path or absolute URL of an accompanying image.
    let imagePath: String?
    /// Index of the source message within the conversation.
    let messageIndex: Int
    /// Message timestamp (epoch seconds) when the model recorded one.
    let timestamp: Int?
}

/// Minimal message shape the parser needs. The app's transcript message type
/// can adapt onto this so the parser stays independent of gateway wire types.
protocol SocialSourceMessage {
    var role: String { get }
    var content: String? { get }
    var timestamp: Int? { get }
}

enum SocialExtraction {
    private static let acceptedFences: Set<String> = [
        "linkedin-post", "linkedinpost", "linkedin", "social-post", "post",
    ]

    // Opening fence (``` or ~~~), optional info string, body, closing fence.
    private static let fenceRe = try! NSRegularExpression(
        pattern: "(?:^|\\n)[ \\t]*(?:```|~~~)[ \\t]*([\\w-]+)?[ \\t]*\\r?\\n([\\s\\S]*?)\\r?\\n?[ \\t]*(?:```|~~~)(?=\\n|$)"
    )

    // Markdown image: ![alt](path "title") -> capture the path.
    private static let mdImageRe = try! NSRegularExpression(
        pattern: "!\\[[^\\]]*\\]\\(\\s*<?([^)\\s>]+)>?[^)]*\\)"
    )

    // A bare token that ends in a common image extension (no spaces, so a
    // markdown list bullet "- path.png" is not swallowed).
    private static let imageTokenRe = try! NSRegularExpression(
        pattern: "(?:^|[\\s(])((?:https?://|/|\\./|[\\w.-]+/)?[-\\w./]*\\.(?:png|jpe?g|webp|gif|svg|avif))(?=$|[\\s)\"'?#])",
        options: [.caseInsensitive]
    )

    private static func group(_ match: NSTextCheckingResult, _ index: Int, in text: String) -> String? {
        let range = match.range(at: index)
        guard range.location != NSNotFound, let swiftRange = Range(range, in: text) else { return nil }
        return String(text[swiftRange])
    }

    private static func firstImagePath(_ text: String) -> String? {
        let full = NSRange(text.startIndex..., in: text)
        if let match = mdImageRe.firstMatch(in: text, range: full),
            let path = group(match, 1, in: text)?.trimmingCharacters(in: .whitespacesAndNewlines),
            !path.isEmpty {
            return path
        }
        if let match = imageTokenRe.firstMatch(in: text, range: full),
            let path = group(match, 1, in: text)?.trimmingCharacters(in: .whitespacesAndNewlines),
            !path.isEmpty {
            return path
        }
        return nil
    }

    /// Parse a conversation's messages into social artifacts, in order. Only
    /// `assistant` messages are read.
    static func extract(_ messages: [SocialSourceMessage]) -> [SocialArtifact] {
        var artifacts: [SocialArtifact] = []

        for (messageIndex, message) in messages.enumerated() {
            guard message.role == "assistant", let content = message.content else { continue }

            let full = NSRange(content.startIndex..., in: content)
            var blockIndex = 0
            for match in fenceRe.matches(in: content, range: full) {
                let info = (group(match, 1, in: content) ?? "").lowercased()
                guard acceptedFences.contains(info) else { continue }

                let caption = (group(match, 2, in: content) ?? "")
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                guard !caption.isEmpty else { continue }

                artifacts.append(
                    SocialArtifact(
                        id: "\(messageIndex):\(blockIndex)",
                        caption: caption,
                        imagePath: firstImagePath(content),
                        messageIndex: messageIndex,
                        timestamp: message.timestamp
                    )
                )
                blockIndex += 1
            }
        }

        return artifacts
    }

    /// Whether a conversation contains at least one post-ready artifact.
    static func hasArtifacts(_ messages: [SocialSourceMessage]) -> Bool {
        !extract(messages).isEmpty
    }

    /// True when the path is an absolute http(s) URL rather than a workspace file.
    static func isRemoteImage(_ path: String) -> Bool {
        path.range(of: "^https?://", options: [.regularExpression, .caseInsensitive]) != nil
    }
}
