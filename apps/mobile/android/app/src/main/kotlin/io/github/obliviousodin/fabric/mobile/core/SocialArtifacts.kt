package io.github.obliviousodin.fabric.mobile.core

/**
 * Kotlin port of the shared Social Studio artifact parser
 * (apps/shared/src/social.ts -> extractSocialArtifacts). It must produce the
 * same output as the TypeScript implementation for every case in
 * apps/mobile/contracts/social-extraction-v1.json.
 *
 * The composer asks the agent to emit the final, paste-ready post inside a
 * fenced block tagged `linkedin-post`, and to show any image with a markdown
 * image / under an "Artifacts" heading. This reads that convention back so a
 * conversation can be shown as image + copyable caption without any new backend.
 */

/** One post-ready artifact extracted from a conversation. */
data class SocialArtifact(
    /** Stable within a session render: "<messageIndex>:<blockIndex>". */
    val id: String,
    /** The exact text to paste into the social network. */
    val caption: String,
    /** Workspace-relative path or absolute URL of an accompanying image. */
    val imagePath: String?,
    /** Index of the source message within the conversation. */
    val messageIndex: Int,
    /** Message timestamp (epoch seconds) when the model recorded one. */
    val timestamp: Long?,
)

/**
 * Minimal message shape the parser needs. The app's transcript message type can
 * adapt onto this so the parser stays independent of gateway wire types.
 */
interface SocialSourceMessage {
    val role: String
    val content: String?
    val timestamp: Long?
}

private val ACCEPTED_FENCES =
    setOf("linkedin-post", "linkedinpost", "linkedin", "social-post", "post")

// Opening fence (``` or ~~~), optional info string, body, closing fence.
private val FENCE_RE =
    Regex("""(?:^|\n)[ \t]*(?:```|~~~)[ \t]*([\w-]+)?[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*(?:```|~~~)(?=\n|$)""")

// Markdown image: ![alt](path "title") -> capture the path.
private val MD_IMAGE_RE = Regex("""!\[[^\]]*\]\(\s*<?([^)\s>]+)>?[^)]*\)""")

// A bare token that ends in a common image extension (no spaces, so a markdown
// list bullet "- path.png" is not swallowed).
private val IMAGE_TOKEN_RE =
    Regex(
        """(?:^|[\s(])((?:https?://|/|\./|[\w.-]+/)?[-\w./]*\.(?:png|jpe?g|webp|gif|svg|avif))(?=$|[\s)"'?#])""",
        RegexOption.IGNORE_CASE,
    )

private fun firstImagePath(text: String): String? {
    MD_IMAGE_RE.find(text)?.groupValues?.getOrNull(1)?.let {
        if (it.isNotBlank()) return it.trim()
    }
    IMAGE_TOKEN_RE.find(text)?.groupValues?.getOrNull(1)?.let {
        if (it.isNotBlank()) return it.trim()
    }
    return null
}

/**
 * Parse a conversation's messages into social artifacts, in conversation order.
 * Only `assistant` messages are read.
 */
fun extractSocialArtifacts(messages: List<SocialSourceMessage>): List<SocialArtifact> {
    val artifacts = mutableListOf<SocialArtifact>()

    messages.forEachIndexed { messageIndex, message ->
        if (message.role != "assistant") return@forEachIndexed
        val content = message.content ?: return@forEachIndexed

        var blockIndex = 0
        for (match in FENCE_RE.findAll(content)) {
            val info = match.groupValues[1].lowercase()
            if (info !in ACCEPTED_FENCES) continue

            val caption = match.groupValues[2].trim()
            if (caption.isEmpty()) continue

            artifacts.add(
                SocialArtifact(
                    id = "$messageIndex:$blockIndex",
                    caption = caption,
                    imagePath = firstImagePath(content),
                    messageIndex = messageIndex,
                    timestamp = message.timestamp,
                ),
            )
            blockIndex++
        }
    }

    return artifacts
}

/** Whether a conversation contains at least one post-ready artifact. */
fun hasSocialArtifacts(messages: List<SocialSourceMessage>): Boolean =
    extractSocialArtifacts(messages).isNotEmpty()

/** True when the path is an absolute http(s) URL rather than a workspace file. */
fun isRemoteImage(path: String): Boolean =
    Regex("^https?://", RegexOption.IGNORE_CASE).containsMatchIn(path)
