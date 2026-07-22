/**
 * Social Studio prompt builder.
 *
 * The composer collects a short brief plus a few structured choices and turns
 * them into a single chat prompt, the same handoff shape the Design surface uses
 * (`apps/shared/src/design.ts` -> `buildDesignPrompt`): the dashboard drops a
 * prepared prompt into a fresh Chat so the user can review before sending.
 *
 * Two conventions make the result readable back by the Library gallery:
 *   1. The agent is told to emit the final, paste-ready post inside a fenced
 *      block tagged `linkedin-post`, with nothing else in the block. The parser
 *      (`social-artifacts.ts`) keys off that fence, so the "copy exactly this"
 *      text is unambiguous.
 *   2. If it produces an image, it lists the workspace-relative path under an
 *      "Artifacts" heading and shows it with a markdown image, reusing the
 *      existing artifact-handoff convention so Fabric can index and preview it.
 *
 * This lives in the web zone (not `apps/shared`) on purpose: it is dashboard-only
 * and keeps the change inside a single ownership zone.
 */

export const SOCIAL_POST_FENCE = "linkedin-post";

export type SocialChannel = "linkedin";

export type SocialGoal =
  | "authority"
  | "engagement"
  | "announcement"
  | "lesson"
  | "hiring";

export type SocialTone =
  | "candid"
  | "bold"
  | "warm"
  | "analytical"
  | "playful";

export type SocialFormat =
  | "hook-story"
  | "tips"
  | "contrarian"
  | "announcement"
  | "case-study";

export interface SocialOption<T extends string> {
  description: string;
  id: T;
  label: string;
}

export interface SocialRequest {
  brief: string;
  channel: SocialChannel;
  format: SocialFormat;
  goal: SocialGoal;
  includeImage: boolean;
  tone: SocialTone;
}

export const SOCIAL_CHANNEL_OPTIONS: readonly SocialOption<SocialChannel>[] = [
  {
    id: "linkedin",
    label: "LinkedIn",
    description: "A professional post optimized for the LinkedIn feed.",
  },
];

export const SOCIAL_GOAL_OPTIONS: readonly SocialOption<SocialGoal>[] = [
  {
    id: "authority",
    label: "Build authority",
    description: "Show expertise and a point of view worth following.",
  },
  {
    id: "engagement",
    label: "Spark discussion",
    description: "Invite comments, opinions, and reshares.",
  },
  {
    id: "announcement",
    label: "Announce something",
    description: "Share a launch, milestone, or update with momentum.",
  },
  {
    id: "lesson",
    label: "Share a lesson",
    description: "Turn an experience into a takeaway others can use.",
  },
  {
    id: "hiring",
    label: "Attract talent",
    description: "Make people want to work with or for you.",
  },
];

export const SOCIAL_TONE_OPTIONS: readonly SocialOption<SocialTone>[] = [
  {
    id: "candid",
    label: "Personal & candid",
    description: "First-person, honest, a little vulnerable.",
  },
  {
    id: "bold",
    label: "Punchy & bold",
    description: "Confident, opinionated, short sentences.",
  },
  {
    id: "warm",
    label: "Warm & encouraging",
    description: "Generous, supportive, human.",
  },
  {
    id: "analytical",
    label: "Analytical",
    description: "Clear reasoning, concrete numbers, no fluff.",
  },
  {
    id: "playful",
    label: "Playful",
    description: "Light, witty, still substantive.",
  },
];

export const SOCIAL_FORMAT_OPTIONS: readonly SocialOption<SocialFormat>[] = [
  {
    id: "hook-story",
    label: "Hook + short story",
    description: "A scroll-stopping opener into a tight narrative.",
  },
  {
    id: "tips",
    label: "List of tips",
    description: "A scannable set of concrete, numbered takeaways.",
  },
  {
    id: "contrarian",
    label: "Contrarian take",
    description: "Challenge a common belief, then back it up.",
  },
  {
    id: "announcement",
    label: "Announcement",
    description: "Lead with the news, then the why-it-matters.",
  },
  {
    id: "case-study",
    label: "Case study",
    description: "Problem, what you did, measurable outcome.",
  },
];

const GOAL_INSTRUCTIONS: Record<SocialGoal, string> = {
  announcement:
    "Land a clear announcement and make readers feel the momentum behind it.",
  authority:
    "Demonstrate a credible, specific point of view that makes the author worth following.",
  engagement:
    "Earn comments and reshares by ending on a genuine, answerable question.",
  hiring:
    "Make the reader want to work with or for the author, without sounding like a job ad.",
  lesson: "Turn a real experience into one sharp, reusable takeaway.",
};

const TONE_INSTRUCTIONS: Record<SocialTone, string> = {
  analytical: "clear and analytical, with concrete numbers and no fluff",
  bold: "confident and punchy, with short declarative sentences",
  candid: "personal and candid, first-person and honestly a little vulnerable",
  playful: "light and playful, witty but still substantive",
  warm: "warm and encouraging, generous and human",
};

const FORMAT_INSTRUCTIONS: Record<SocialFormat, string> = {
  announcement:
    "Lead with the news in the first line, then explain why it matters.",
  "case-study":
    "Structure it as problem, what you did, and a measurable outcome.",
  contrarian:
    "Open by challenging a widely held belief, then justify the contrarian view.",
  "hook-story":
    "Open with a scroll-stopping first line, then tell one tight story.",
  tips: "Deliver a short, scannable list of concrete, numbered takeaways.",
};

const CHANNEL_LABELS: Record<SocialChannel, string> = {
  linkedin: "LinkedIn",
};

/** Collapse whitespace, drop control characters, and bound the brief length. */
function normalizeBrief(value: string): string {
  let out = "";
  for (const ch of value) {
    const code = ch.codePointAt(0) ?? 0;
    // Replace C0/C1 control characters (including tabs and newlines) with a
    // space; keep all normal text. Avoids embedding raw control bytes.
    if (code < 0x20 || (code >= 0x7f && code <= 0x9f)) {
      out += " ";
    } else {
      out += ch;
    }
  }
  return out.replace(/\s+/g, " ").trim().slice(0, 2_000);
}

/**
 * Build the chat prompt for a social post. Pure and deterministic so it can be
 * unit-tested and so the same brief always yields the same handoff.
 */
export function buildSocialPrompt(request: SocialRequest): string {
  const brief = normalizeBrief(request.brief);
  const channel = CHANNEL_LABELS[request.channel] ?? "LinkedIn";

  const lines = [
    `Write a ready-to-post ${channel} post about: ${brief}`,
    `Goal: ${GOAL_INSTRUCTIONS[request.goal]}`,
    `Voice: Write in the first person in ${TONE_INSTRUCTIONS[request.tone]}. Use the author's authentic voice; if a writing-voice skill or profile is available, apply it.`,
    `Format: ${FORMAT_INSTRUCTIONS[request.format]}`,
    'Craft: Open with a strong first line (avoid cliches like "I\'m excited to announce"). Keep it scannable with short lines and whitespace. Use at most three relevant hashtags at the very end, and only if they add reach. No emoji unless one clearly earns its place.',
    `Output: Put the final post EXACTLY as it should be pasted into ${channel} inside a single fenced code block tagged \`${SOCIAL_POST_FENCE}\`. Put nothing else inside that block: no commentary, no surrounding quotes.`,
  ];

  if (request.includeImage) {
    lines.push(
      'Image: Create one on-brand square (1200x1200) image that fits the post, save it into the workspace, and finish with an "Artifacts" heading that lists its workspace-relative path and shows it with a markdown image so Fabric can index and preview it.',
    );
  } else {
    lines.push("Image: No image is needed for this post; deliver text only.");
  }

  return lines.join("\n");
}
