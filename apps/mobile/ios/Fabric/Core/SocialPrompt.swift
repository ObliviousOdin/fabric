import Foundation

/// Swift port of the shared Social Studio prompt builder
/// (apps/shared/src/social.ts -> buildSocialPrompt). Produces the same prompt
/// text so the "compose a post" handoff is identical across every front-end.

enum SocialChannel: String, CaseIterable, Identifiable {
    case linkedin
    var id: String { rawValue }
    var label: String {
        switch self {
        case .linkedin: return "LinkedIn"
        }
    }
}

enum SocialGoal: String, CaseIterable, Identifiable {
    case authority, engagement, announcement, lesson, hiring
    var id: String { rawValue }
    var label: String {
        switch self {
        case .authority: return "Build authority"
        case .engagement: return "Spark discussion"
        case .announcement: return "Announce something"
        case .lesson: return "Share a lesson"
        case .hiring: return "Attract talent"
        }
    }
}

enum SocialTone: String, CaseIterable, Identifiable {
    case candid, bold, warm, analytical, playful
    var id: String { rawValue }
    var label: String {
        switch self {
        case .candid: return "Personal & candid"
        case .bold: return "Punchy & bold"
        case .warm: return "Warm & encouraging"
        case .analytical: return "Analytical"
        case .playful: return "Playful"
        }
    }
}

enum SocialFormat: String, CaseIterable, Identifiable {
    case hookStory = "hook-story"
    case tips
    case contrarian
    case announcement
    case caseStudy = "case-study"
    var id: String { rawValue }
    var label: String {
        switch self {
        case .hookStory: return "Hook + short story"
        case .tips: return "List of tips"
        case .contrarian: return "Contrarian take"
        case .announcement: return "Announcement"
        case .caseStudy: return "Case study"
        }
    }
}

struct SocialRequest {
    var brief: String
    var channel: SocialChannel = .linkedin
    var goal: SocialGoal = .authority
    var tone: SocialTone = .candid
    var format: SocialFormat = .hookStory
    var includeImage: Bool = true
}

enum SocialPrompt {
    static let postFence = "linkedin-post"

    private static func goalInstruction(_ goal: SocialGoal) -> String {
        switch goal {
        case .announcement:
            return "Land a clear announcement and make readers feel the momentum behind it."
        case .authority:
            return "Demonstrate a credible, specific point of view that makes the author worth following."
        case .engagement:
            return "Earn comments and reshares by ending on a genuine, answerable question."
        case .hiring:
            return "Make the reader want to work with or for the author, without sounding like a job ad."
        case .lesson:
            return "Turn a real experience into one sharp, reusable takeaway."
        }
    }

    private static func toneInstruction(_ tone: SocialTone) -> String {
        switch tone {
        case .analytical: return "clear and analytical, with concrete numbers and no fluff"
        case .bold: return "confident and punchy, with short declarative sentences"
        case .candid: return "personal and candid, first-person and honestly a little vulnerable"
        case .playful: return "light and playful, witty but still substantive"
        case .warm: return "warm and encouraging, generous and human"
        }
    }

    private static func formatInstruction(_ format: SocialFormat) -> String {
        switch format {
        case .announcement:
            return "Lead with the news in the first line, then explain why it matters."
        case .caseStudy:
            return "Structure it as problem, what you did, and a measurable outcome."
        case .contrarian:
            return "Open by challenging a widely held belief, then justify the contrarian view."
        case .hookStory:
            return "Open with a scroll-stopping first line, then tell one tight story."
        case .tips:
            return "Deliver a short, scannable list of concrete, numbered takeaways."
        }
    }

    /// Collapse whitespace, drop control characters, and bound the brief length.
    private static func normalizeBrief(_ value: String) -> String {
        var out = ""
        for scalar in value.unicodeScalars {
            let code = scalar.value
            if code < 0x20 || (code >= 0x7F && code <= 0x9F) {
                out.append(" ")
            } else {
                out.unicodeScalars.append(scalar)
            }
        }
        let collapsed = out.replacingOccurrences(
            of: "\\s+", with: " ", options: .regularExpression
        ).trimmingCharacters(in: .whitespacesAndNewlines)
        return String(collapsed.prefix(2000))
    }

    /// Build the chat prompt for a social post. Pure and deterministic.
    static func build(_ request: SocialRequest) -> String {
        let brief = normalizeBrief(request.brief)
        let channel = request.channel.label

        var lines = [
            "Write a ready-to-post \(channel) post about: \(brief)",
            "Goal: \(goalInstruction(request.goal))",
            "Voice: Write in the first person in \(toneInstruction(request.tone)). "
                + "Use the author's authentic voice; if a writing-voice skill or profile is available, apply it.",
            "Format: \(formatInstruction(request.format))",
            "Craft: Open with a strong first line (avoid cliches like \"I'm excited to announce\"). "
                + "Keep it scannable with short lines and whitespace. Use at most three relevant hashtags at "
                + "the very end, and only if they add reach. No emoji unless one clearly earns its place.",
            "Output: Put the final post EXACTLY as it should be pasted into \(channel) inside a single fenced "
                + "code block tagged `\(postFence)`. Put nothing else inside that block: no commentary, "
                + "no surrounding quotes.",
        ]

        if request.includeImage {
            lines.append(
                "Image: Create one on-brand square (1200x1200) image that fits the post, save it into the "
                    + "workspace, and finish with an \"Artifacts\" heading that lists its workspace-relative path "
                    + "and shows it with a markdown image so Fabric can index and preview it."
            )
        } else {
            lines.append("Image: No image is needed for this post; deliver text only.")
        }

        return lines.joined(separator: "\n")
    }
}
