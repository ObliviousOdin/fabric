import Foundation

// Swift port of the desktop artifact extractor
// (apps/desktop/src/app/artifacts/artifact-utils.ts -> collectArtifactsForSession),
// bounded to the iOS transcript shape. The iOS transcript has no structured
// `tool_calls` and no session `cwd`, so this drops the desktop's tool-argument
// walk and its relative-path resolution: only assistant/tool message *text* is
// scanned, and only absolute paths or URLs survive (a relative path cannot be
// resolved without a working directory). Tool rows carry their compact call
// context in `text`, which is scanned like any other message body.

enum TranscriptArtifactKind: String, Equatable, CaseIterable {
    case image
    case file
    case link
}

struct TranscriptArtifact: Identifiable, Equatable {
    /// Stable within a session render: "<sessionID>:<value>".
    let id: String
    let kind: TranscriptArtifactKind
    /// Absolute path or URL as it appeared in the transcript.
    let value: String
    /// Filename or last URL/path component, for display.
    let label: String
    let sessionID: String
    let sessionTitle: String
}

enum TranscriptArtifactExtraction {
    // Ported regexes. NSRegularExpression mirrors the SocialArtifact idiom.
    private static let markdownImageRe = re("!\\[[^\\]]*\\]\\(([^)\\s]+)\\)")
    private static let markdownLinkRe = re("\\[[^\\]]+\\]\\(([^)\\s]+)\\)")
    private static let inlineCodeRe = re("`([^`\\n]+)`")
    private static let urlRe = re("https?://[^\\s<>\"')]+")
    private static let pathRe = re("(?:^|[\\s(\"'`])((?:/|~/|\\.\\.?/)[^\\s\"'`<>]+)")
    private static let imageExtRe = re(
        "\\.(?:png|jpe?g|gif|webp|svg|bmp|ico|avif)(?:[?#].*)?$",
        options: [.caseInsensitive]
    )
    private static let fileExtRe = re(
        "\\.(?:png|jpe?g|gif|webp|svg|bmp|ico|avif|pdf|txt|html?|json|md|csv|zip|tar|gz|mp3|wav|mp4|mov)(?:[?#].*)?$",
        options: [.caseInsensitive]
    )

    private static func re(
        _ pattern: String,
        options: NSRegularExpression.Options = []
    ) -> NSRegularExpression {
        // Patterns are compile-time constants; a failure here is a programmer
        // error surfaced during development, exactly like SocialExtraction.
        try! NSRegularExpression(pattern: pattern, options: options)
    }

    private static func group(_ match: NSTextCheckingResult, _ index: Int, in text: String) -> String? {
        guard index < match.numberOfRanges else { return nil }
        let range = match.range(at: index)
        guard range.location != NSNotFound, let swift = Range(range, in: text) else { return nil }
        return String(text[swift])
    }

    private static func matches(
        _ regex: NSRegularExpression,
        in text: String,
        group index: Int
    ) -> [String] {
        let full = NSRange(text.startIndex..., in: text)
        return regex.matches(in: text, range: full).compactMap { group($0, index, in: text) }
    }

    /// Trim surrounding whitespace and strip trailing sentence punctuation that a
    /// URL/path is unlikely to end with.
    static func normalize(_ value: String) -> String {
        var trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        while let last = trimmed.last, ")],.;".contains(last) {
            trimmed.removeLast()
        }
        return trimmed
    }

    /// Whether a candidate looks like something worth surfacing.
    static func looksLikeArtifact(_ value: String) -> Bool {
        let lower = value.lowercased()
        if lower.hasPrefix("http://") || lower.hasPrefix("https://") || lower.hasPrefix("data:image/") {
            return true
        }
        if fileExtRe.firstMatch(in: value, range: NSRange(value.startIndex..., in: value)) != nil {
            return true
        }
        return value.hasPrefix("/") && value.contains(".")
    }

    /// Absolute paths and URLs pass through; a relative path cannot be resolved
    /// without a working directory, so it is dropped (nil).
    static func resolve(_ value: String) -> String? {
        let lower = value.lowercased()
        if lower.hasPrefix("http://") || lower.hasPrefix("https://")
            || lower.hasPrefix("data:") || lower.hasPrefix("file:")
            || value.hasPrefix("/") || value.hasPrefix("~/") {
            return value
        }
        return nil
    }

    static func kind(of value: String) -> TranscriptArtifactKind {
        let full = NSRange(value.startIndex..., in: value)
        if value.lowercased().hasPrefix("data:image/") || imageExtRe.firstMatch(in: value, range: full) != nil {
            return .image
        }
        if value.hasPrefix("/") || value.hasPrefix("./") || value.hasPrefix("../")
            || value.hasPrefix("~/") || value.lowercased().hasPrefix("file://") {
            return .file
        }
        return .link
    }

    static func label(for value: String) -> String {
        if let url = URL(string: value), let host = url.host, url.scheme != nil {
            let last = url.pathComponents.last(where: { $0 != "/" && !$0.isEmpty })
            return last ?? host
        }
        let parts = value.split(whereSeparator: { $0 == "/" || $0 == "\\" })
        return parts.last.map(String.init) ?? value
    }

    /// Collect the distinct artifacts referenced by one session's transcript,
    /// in first-seen order, deduped by resolved value.
    static func collect(
        session: SessionSummary,
        messages: [SessionTranscriptMessage]
    ) -> [TranscriptArtifact] {
        var seen = Set<String>()
        var result: [TranscriptArtifact] = []

        for message in messages where message.role == .assistant || message.role == .tool {
            for candidate in candidates(in: message.text) {
                let normalized = normalize(candidate)
                guard !normalized.isEmpty, looksLikeArtifact(normalized),
                      let value = resolve(normalized) else { continue }
                let key = "\(session.id):\(value)"
                guard seen.insert(key).inserted else { continue }
                result.append(
                    TranscriptArtifact(
                        id: key,
                        kind: kind(of: value),
                        value: value,
                        label: label(for: value),
                        sessionID: session.id,
                        sessionTitle: session.displayTitle
                    )
                )
            }
        }
        return result
    }

    /// Raw candidate strings in one message body, in a stable scan order.
    private static func candidates(in text: String) -> [String] {
        guard !text.isEmpty else { return [] }
        var found: [String] = []
        found.append(contentsOf: matches(markdownImageRe, in: text, group: 1))
        found.append(contentsOf: matches(markdownLinkRe, in: text, group: 1).filter(looksLikeArtifact))
        found.append(contentsOf: matches(urlRe, in: text, group: 0).filter(looksLikeArtifact))
        found.append(contentsOf: matches(inlineCodeRe, in: text, group: 1).filter(looksLikeArtifact))
        found.append(contentsOf: matches(pathRe, in: text, group: 1))
        return found
    }
}
