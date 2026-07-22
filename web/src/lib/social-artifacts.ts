import type { SessionMessage } from "@/lib/api";

/**
 * Extract post-ready social artifacts from a conversation's messages.
 *
 * The composer (`social-prompt.ts`) instructs the agent to emit the final,
 * paste-ready post inside a fenced code block tagged `linkedin-post` and to show
 * any generated image with a markdown image reference / under an "Artifacts"
 * heading. This parser reads that convention back so the Library can show a
 * conversation as "click -> image + caption + Copy" without any new backend.
 *
 * It only reads `assistant` messages: the user's prompt mentions the fence by
 * name but never contains a real fenced block, so it can't be mistaken for a
 * deliverable.
 */

export interface SocialArtifact {
  /** Stable within a session render: `${messageIndex}:${blockIndex}`. */
  id: string;
  /** The exact text to paste into the social network. */
  caption: string;
  /** Workspace-relative path or absolute URL of an accompanying image. */
  imagePath: string | null;
  /** Index of the source message within the conversation. */
  messageIndex: number;
  /** Message timestamp (epoch seconds) when the model recorded one. */
  timestamp: number | null;
}

// Info strings we accept on the opening fence (case-insensitive). `linkedin-post`
// is what the composer asks for; the looser aliases catch hand-written posts.
const ACCEPTED_FENCES = new Set([
  "linkedin-post",
  "linkedinpost",
  "linkedin",
  "social-post",
  "post",
]);

// Opening fence (``` or ~~~), optional info string, body, closing fence.
const FENCE_RE =
  /(?:^|\n)[ \t]*(?:```|~~~)[ \t]*([\w-]+)?[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*(?:```|~~~)(?=\n|$)/g;

// Markdown image: `![alt](path "title")` -> capture the path.
const MD_IMAGE_RE = /!\[[^\]]*\]\(\s*<?([^)\s>]+)>?[^)]*\)/g;

// A bare token that ends in a common image extension. The token itself has no
// spaces, so a markdown list bullet ("- path.png") is not swallowed.
const IMAGE_TOKEN_RE =
  /(?:^|[\s(])((?:https?:\/\/|\/|\.\/|[\w.-]+\/)?[-\w./]*\.(?:png|jpe?g|webp|gif|svg|avif))(?=$|[\s)"'?#])/i;

function firstImagePath(text: string): string | null {
  MD_IMAGE_RE.lastIndex = 0;
  const md = MD_IMAGE_RE.exec(text);
  if (md?.[1]) return md[1].trim();

  const token = IMAGE_TOKEN_RE.exec(text);
  if (token?.[1]) return token[1].trim();

  return null;
}

/**
 * Parse a conversation's messages into social artifacts, in conversation order.
 * Returns an empty array when the conversation has no post-ready deliverable.
 */
export function extractSocialArtifacts(
  messages: readonly SessionMessage[],
): SocialArtifact[] {
  const artifacts: SocialArtifact[] = [];

  messages.forEach((message, messageIndex) => {
    if (message.role !== "assistant") return;
    const content = message.content;
    if (!content) return;

    let blockIndex = 0;
    FENCE_RE.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = FENCE_RE.exec(content)) !== null) {
      const info = (match[1] ?? "").toLowerCase();
      if (!ACCEPTED_FENCES.has(info)) continue;

      const caption = match[2]?.trim();
      if (!caption) continue;

      // Look for an image anywhere in the same message (the composer lists it
      // under an "Artifacts" heading after the post block).
      const imagePath = firstImagePath(content);

      artifacts.push({
        id: `${messageIndex}:${blockIndex}`,
        caption,
        imagePath,
        messageIndex,
        timestamp: message.timestamp ?? null,
      });
      blockIndex += 1;
    }
  });

  return artifacts;
}

/** Whether a conversation contains at least one post-ready artifact. */
export function hasSocialArtifacts(
  messages: readonly SessionMessage[],
): boolean {
  return extractSocialArtifacts(messages).length > 0;
}

/** True when the path is an absolute http(s) URL rather than a workspace file. */
export function isRemoteImage(path: string): boolean {
  return /^https?:\/\//i.test(path);
}
