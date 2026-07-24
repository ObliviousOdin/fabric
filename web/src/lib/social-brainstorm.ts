/**
 * Social Studio brainstorm — the sequence-setup flow that fronts the Social
 * surface. Instead of landing on a blank composer, the user answers a short
 * progressive interview (topic → goal → voice → rhythm → images) and Fabric
 * turns the answers into a brainstorm prompt for a fresh Chat: the agent
 * proposes post ideas first and only drafts what the user picks. Drafted posts
 * keep the shared `linkedin-post` fence convention so the Library finds them.
 *
 * The page's stages unlock progressively: Compose opens after the first
 * brainstorm handoff (persisted per browser, like the Social Studio enable
 * preference), and Library opens once a conversation actually contains a
 * post-ready artifact.
 */

import {
  SOCIAL_GOAL_OPTIONS,
  SOCIAL_POST_FENCE,
  SOCIAL_TONE_OPTIONS,
  type SocialGoal,
  type SocialOption,
  type SocialTone,
} from "@fabric/shared";

// ── Stage progression ─────────────────────────────────────────────────────

export type SocialStage = "brainstorm" | "compose" | "library";

export interface SocialStageAccess {
  /** Stage the page should land on. */
  initialStage: SocialStage;
  composeUnlocked: boolean;
  libraryUnlocked: boolean;
}

/**
 * Pure unlock rules for the staged Social page. The Library unlocks only when
 * a scanned conversation actually contains a post artifact — an empty library
 * is never shown as a destination. Compose unlocks once the user has run (or
 * explicitly skipped past) a brainstorm.
 */
export function resolveSocialStages(input: {
  hasArtifacts: boolean;
  hasBrainstormed: boolean;
}): SocialStageAccess {
  const libraryUnlocked = input.hasArtifacts;
  const composeUnlocked = input.hasArtifacts || input.hasBrainstormed;
  return {
    composeUnlocked,
    initialStage: libraryUnlocked ? "library" : "brainstorm",
    libraryUnlocked,
  };
}

export const SOCIAL_BRAINSTORMED_KEY = "fabric.social-studio.brainstormed";

/** Whether this browser has ever handed a brainstorm (or skip) off to Chat. */
export function hasBrainstormed(): boolean {
  try {
    return localStorage.getItem(SOCIAL_BRAINSTORMED_KEY) === "true";
  } catch {
    // localStorage can throw in private-browsing / sandboxed contexts.
    return false;
  }
}

export function markBrainstormed(): void {
  try {
    localStorage.setItem(SOCIAL_BRAINSTORMED_KEY, "true");
  } catch {
    // Ignore persistence failures — the in-memory state still unlocks Compose
    // for the current visit.
  }
}

// ── Sequence plan ─────────────────────────────────────────────────────────

export type SocialSequenceLength = 3 | 5 | 7;

export type SocialCadence = "daily" | "weekdays" | "weekly";

export const SOCIAL_SEQUENCE_LENGTH_OPTIONS: readonly SocialOption<`${SocialSequenceLength}`>[] =
  [
    {
      id: "3",
      label: "3 posts",
      description: "A short arc — test one theme.",
    },
    {
      id: "5",
      label: "5 posts",
      description: "A full working week of takes.",
    },
    {
      id: "7",
      label: "7 posts",
      description: "A longer arc with room to explore.",
    },
  ];

export const SOCIAL_CADENCE_OPTIONS: readonly SocialOption<SocialCadence>[] = [
  {
    id: "daily",
    label: "Daily",
    description: "One post every day.",
  },
  {
    id: "weekdays",
    label: "Weekdays",
    description: "Monday to Friday, weekends off.",
  },
  {
    id: "weekly",
    label: "Weekly",
    description: "One considered post a week.",
  },
];

export interface SocialBrainstormPlan {
  topic: string;
  goal: SocialGoal;
  tone: SocialTone;
  postCount: SocialSequenceLength;
  cadence: SocialCadence;
  includeImage: boolean;
}

const CADENCE_PHRASES: Record<SocialCadence, string> = {
  daily: "one post a day",
  weekdays: "one post each weekday",
  weekly: "one post a week",
};

/** Collapse whitespace, drop control characters, and bound the topic length. */
function normalizeTopic(value: string): string {
  let out = "";
  for (const ch of value) {
    const code = ch.codePointAt(0) ?? 0;
    if (code < 0x20 || (code >= 0x7f && code <= 0x9f)) {
      out += " ";
    } else {
      out += ch;
    }
  }
  return out.replace(/\s+/g, " ").trim().slice(0, 2_000);
}

/**
 * Build the brainstorm chat prompt for a post sequence. Pure and deterministic
 * so it can be unit-tested and the same plan always yields the same handoff.
 * Mirrors `buildSocialPrompt` in `@fabric/shared`, but asks the agent to run a
 * working session (questions → ideas → picked drafts) instead of a one-shot
 * draft. Drafted posts reuse the shared fence so every Library keeps working.
 */
export function buildSocialBrainstormPrompt(plan: SocialBrainstormPlan): string {
  const topic = normalizeTopic(plan.topic);
  const goal = SOCIAL_GOAL_OPTIONS.find((option) => option.id === plan.goal);
  const tone = SOCIAL_TONE_OPTIONS.find((option) => option.id === plan.tone);

  const lines = [
    `Help me brainstorm and set up a sequence of ${plan.postCount} LinkedIn posts. Raw material: ${topic}`,
    `Goal: ${goal?.label ?? plan.goal} — ${goal?.description ?? ""}`.trim(),
    `Voice: ${tone?.label ?? plan.tone} — ${tone?.description ?? ""} Write in the first person; if a writing-voice skill or profile is available, apply it.`,
    `Cadence: ${CADENCE_PHRASES[plan.cadence]}.`,
    "Run this as a brainstorm, not a one-shot draft:",
    "1. Ask me up to three sharp questions that would make the sequence stronger. If the raw material already answers them, skip ahead.",
    `2. Propose ${plan.postCount} post ideas as a numbered list — for each, a scroll-stopping hook line, the angle in one sentence, and how it advances the goal.`,
    "3. Let me react and pick before you draft anything.",
    `4. When I ask for a draft, put the final paste-ready post inside a single fenced code block tagged \`${SOCIAL_POST_FENCE}\` — one block per post, nothing else inside the block.`,
  ];

  if (plan.includeImage) {
    lines.push(
      '5. For each drafted post, create one on-brand square (1200x1200) image that fits it, save it into the workspace, and finish with an "Artifacts" heading that lists its workspace-relative path and shows it with a markdown image so Fabric can index and preview it.',
    );
  } else {
    lines.push("5. These posts are text only; no images are needed.");
  }

  return lines.join("\n");
}
