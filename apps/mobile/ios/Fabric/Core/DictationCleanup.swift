import Foundation

/// Explicit, on-device cleanup of a message draft — the composer's "Clean up"
/// button invokes it. It removes standalone filler words, collapses immediate
/// word repetition, tidies whitespace, sentence-cases, and ensures terminal
/// punctuation. It never calls a model or the gateway and never runs
/// automatically. URLs and backtick-fenced code spans are preserved verbatim.
///
/// The transform is deterministic and idempotent: `apply(apply(x)) == apply(x)`.
enum DictationCleanup {
    /// `@AppStorage` key for the "clean up dictation" preference (default on).
    static let enabledKey = "deviceVoice.cleanupDictation"

    /// Private-use delimiter for protected-span placeholders. It is neither a
    /// word character nor whitespace, so filler/dedup/casing passes never touch
    /// it.
    private static let sentinel = "\u{E000}"

    static func apply(_ input: String) -> String {
        guard !input.isEmpty else { return input }

        var protectedSpans: [String] = []
        var text = protect(input, into: &protectedSpans)

        text = removeFillers(text)
        text = collapseRepeats(text)
        text = normalizeWhitespace(text)
        text = sentenceCase(text)
        text = ensureTerminalPunctuation(text)

        return restore(text, from: protectedSpans)
    }

    // MARK: - Protection

    private static let protectedPatterns = [
        "`[^`]*`",              // backtick-fenced code spans
        "https?://[^\\s]+",     // URLs
    ]

    private static func placeholder(_ index: Int) -> String {
        "\(sentinel)\(index)\(sentinel)"
    }

    private static func protect(_ input: String, into spans: inout [String]) -> String {
        var result = input
        for pattern in protectedPatterns {
            let regex = try! NSRegularExpression(pattern: pattern)
            let source = result as NSString
            let matches = regex.matches(
                in: result,
                range: NSRange(location: 0, length: source.length)
            )
            guard !matches.isEmpty else { continue }

            var rebuilt = ""
            var cursor = 0
            for match in matches {
                let range = match.range
                rebuilt += source.substring(
                    with: NSRange(location: cursor, length: range.location - cursor)
                )
                spans.append(source.substring(with: range))
                rebuilt += placeholder(spans.count - 1)
                cursor = range.location + range.length
            }
            rebuilt += source.substring(from: cursor)
            result = rebuilt
        }
        return result
    }

    private static func restore(_ text: String, from spans: [String]) -> String {
        var result = text
        // Reverse order so placeholder "10" is restored before "1" can match a
        // prefix of it.
        for index in spans.indices.reversed() {
            result = result.replacingOccurrences(of: placeholder(index), with: spans[index])
        }
        return result
    }

    // MARK: - Passes

    private static func replacing(
        _ text: String,
        pattern: String,
        template: String,
        options: NSRegularExpression.Options = []
    ) -> String {
        let regex = try! NSRegularExpression(pattern: pattern, options: options)
        let range = NSRange(location: 0, length: (text as NSString).length)
        return regex.stringByReplacingMatches(
            in: text,
            range: range,
            withTemplate: template
        )
    }

    private static func removeFillers(_ text: String) -> String {
        // Conservative set — whole words only, so "umbrella" and "5 mm" survive.
        replacing(
            text,
            pattern: "\\b(?:um|uh|uhm|erm|hmm)\\b",
            template: "",
            options: [.caseInsensitive]
        )
    }

    private static func collapseRepeats(_ text: String) -> String {
        // Collapse an immediately repeated word ("the the" -> "the"), keeping the
        // first occurrence's casing. Loop to a fixed point for triples+.
        var result = text
        for _ in 0..<8 {
            let next = replacing(
                result,
                pattern: "\\b(\\w+)(\\s+)\\1\\b",
                template: "$1",
                options: [.caseInsensitive]
            )
            if next == result { break }
            result = next
        }
        return result
    }

    private static func normalizeWhitespace(_ text: String) -> String {
        var result = replacing(text, pattern: "[ \\t]+", template: " ")
        result = replacing(result, pattern: " *\\n *", template: "\n")
        result = replacing(result, pattern: "\\n{3,}", template: "\n\n")
        return result.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func sentenceCase(_ text: String) -> String {
        // Build a new string rather than mutating characters in place: uppercasing
        // one Character can yield several (e.g. "ß" -> "SS"), which a Character
        // slot cannot hold.
        var result = ""
        var capitalizeNext = true
        for character in text {
            if capitalizeNext, character.isLetter {
                result += String(character).uppercased()
                capitalizeNext = false
                continue
            }
            result.append(character)
            if character == "." || character == "!" || character == "?" || character == "\n" {
                capitalizeNext = true
            } else if character.isLetter || character.isNumber {
                capitalizeNext = false
            }
            // Whitespace and other punctuation leave `capitalizeNext` unchanged.
        }
        return result
    }

    private static func ensureTerminalPunctuation(_ text: String) -> String {
        guard let last = text.last else { return text }
        if last.isLetter || last.isNumber {
            return text + "."
        }
        return text
    }
}
