package io.github.obliviousodin.fabric.mobile.core

/**
 * Kotlin port of the shared Social Studio prompt builder
 * (apps/shared/src/social.ts -> buildSocialPrompt). It produces the same prompt
 * text so the "compose a post" handoff is identical across every front-end.
 */

enum class SocialChannel(val id: String, val label: String) {
    LINKEDIN("linkedin", "LinkedIn"),
}

enum class SocialGoal(val id: String, val label: String) {
    AUTHORITY("authority", "Build authority"),
    ENGAGEMENT("engagement", "Spark discussion"),
    ANNOUNCEMENT("announcement", "Announce something"),
    LESSON("lesson", "Share a lesson"),
    HIRING("hiring", "Attract talent"),
}

enum class SocialTone(val id: String, val label: String) {
    CANDID("candid", "Personal & candid"),
    BOLD("bold", "Punchy & bold"),
    WARM("warm", "Warm & encouraging"),
    ANALYTICAL("analytical", "Analytical"),
    PLAYFUL("playful", "Playful"),
}

enum class SocialFormat(val id: String, val label: String) {
    HOOK_STORY("hook-story", "Hook + short story"),
    TIPS("tips", "List of tips"),
    CONTRARIAN("contrarian", "Contrarian take"),
    ANNOUNCEMENT("announcement", "Announcement"),
    CASE_STUDY("case-study", "Case study"),
}

data class SocialRequest(
    val brief: String,
    val channel: SocialChannel = SocialChannel.LINKEDIN,
    val goal: SocialGoal = SocialGoal.AUTHORITY,
    val tone: SocialTone = SocialTone.CANDID,
    val format: SocialFormat = SocialFormat.HOOK_STORY,
    val includeImage: Boolean = true,
)

const val SOCIAL_POST_FENCE = "linkedin-post"

private fun goalInstruction(goal: SocialGoal): String =
    when (goal) {
        SocialGoal.ANNOUNCEMENT ->
            "Land a clear announcement and make readers feel the momentum behind it."
        SocialGoal.AUTHORITY ->
            "Demonstrate a credible, specific point of view that makes the author worth following."
        SocialGoal.ENGAGEMENT ->
            "Earn comments and reshares by ending on a genuine, answerable question."
        SocialGoal.HIRING ->
            "Make the reader want to work with or for the author, without sounding like a job ad."
        SocialGoal.LESSON ->
            "Turn a real experience into one sharp, reusable takeaway."
    }

private fun toneInstruction(tone: SocialTone): String =
    when (tone) {
        SocialTone.ANALYTICAL -> "clear and analytical, with concrete numbers and no fluff"
        SocialTone.BOLD -> "confident and punchy, with short declarative sentences"
        SocialTone.CANDID -> "personal and candid, first-person and honestly a little vulnerable"
        SocialTone.PLAYFUL -> "light and playful, witty but still substantive"
        SocialTone.WARM -> "warm and encouraging, generous and human"
    }

private fun formatInstruction(format: SocialFormat): String =
    when (format) {
        SocialFormat.ANNOUNCEMENT ->
            "Lead with the news in the first line, then explain why it matters."
        SocialFormat.CASE_STUDY ->
            "Structure it as problem, what you did, and a measurable outcome."
        SocialFormat.CONTRARIAN ->
            "Open by challenging a widely held belief, then justify the contrarian view."
        SocialFormat.HOOK_STORY ->
            "Open with a scroll-stopping first line, then tell one tight story."
        SocialFormat.TIPS ->
            "Deliver a short, scannable list of concrete, numbered takeaways."
    }

/** Collapse whitespace, drop control characters, and bound the brief length. */
private fun normalizeBrief(value: String): String {
    val out = StringBuilder()
    for (ch in value) {
        val code = ch.code
        if (code < 0x20 || code in 0x7f..0x9f) out.append(' ') else out.append(ch)
    }
    return out.toString().replace(Regex("""\s+"""), " ").trim().take(2000)
}

/** Build the chat prompt for a social post. Pure and deterministic. */
fun buildSocialPrompt(request: SocialRequest): String {
    val brief = normalizeBrief(request.brief)
    val channel = request.channel.label

    val lines = mutableListOf(
        "Write a ready-to-post $channel post about: $brief",
        "Goal: ${goalInstruction(request.goal)}",
        "Voice: Write in the first person in ${toneInstruction(request.tone)}. " +
            "Use the author's authentic voice; if a writing-voice skill or profile is available, apply it.",
        "Format: ${formatInstruction(request.format)}",
        "Craft: Open with a strong first line (avoid cliches like \"I'm excited to announce\"). " +
            "Keep it scannable with short lines and whitespace. Use at most three relevant hashtags at " +
            "the very end, and only if they add reach. No emoji unless one clearly earns its place.",
        "Output: Put the final post EXACTLY as it should be pasted into $channel inside a single fenced " +
            "code block tagged `$SOCIAL_POST_FENCE`. Put nothing else inside that block: no commentary, " +
            "no surrounding quotes.",
    )

    if (request.includeImage) {
        lines.add(
            "Image: Create one on-brand square (1200x1200) image that fits the post, save it into the " +
                "workspace, and finish with an \"Artifacts\" heading that lists its workspace-relative path " +
                "and shows it with a markdown image so Fabric can index and preview it.",
        )
    } else {
        lines.add("Image: No image is needed for this post; deliver text only.")
    }

    return lines.joinToString("\n")
}
