import { MessagesSquare } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@nous-research/ui/ui/components/button";

import {
  createFreshChatRequestId,
  FRESH_CHAT_QUERY_PARAM,
} from "@/components/chat/usePersistentChatIdentity";
import { useI18n } from "@/i18n";
import { en } from "@/i18n/en";
import {
  buildSocialBrainstormPrompt,
  markBrainstormed,
  SOCIAL_CADENCE_OPTIONS,
  SOCIAL_SEQUENCE_LENGTH_OPTIONS,
  type SocialCadence,
  type SocialSequenceLength,
} from "@/lib/social-brainstorm";
import { cn } from "@/lib/utils";
import {
  SOCIAL_GOAL_OPTIONS,
  SOCIAL_TONE_OPTIONS,
  type SocialGoal,
  type SocialOption,
  type SocialTone,
} from "@fabric/shared";

type StepId = "topic" | "goal" | "tone" | "rhythm" | "image";

const STEPS: readonly StepId[] = ["topic", "goal", "tone", "rhythm", "image"];

function truncate(value: string, max = 96): string {
  const flat = value.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

function ChoiceGrid<T extends string>({
  onSelect,
  options,
  value,
}: {
  onSelect: (id: T) => void;
  options: readonly SocialOption<T>[];
  value: T | null;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {options.map((option) => (
        <button
          aria-pressed={value === option.id}
          className={cn(
            "min-h-11 border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
            value === option.id
              ? "border-primary bg-primary/[0.08]"
              : "border-border bg-background-surface/40 hover:border-primary/50",
          )}
          key={option.id}
          onClick={() => onSelect(option.id)}
          type="button"
        >
          <span className="block text-sm font-medium text-text-primary">
            {option.label}
          </span>
          <span className="mt-0.5 block text-xs leading-5 text-text-secondary">
            {option.description}
          </span>
        </button>
      ))}
    </div>
  );
}

/**
 * The sequence brainstorm: a progressive, chat-style interview. One question is
 * open at a time; answering it reveals the next, and answered questions
 * collapse into editable answer rows. The finished plan is handed to a fresh
 * Chat as a brainstorm prompt (ideas first, drafts on request) — the same
 * handoff shape as the single-post composer.
 */
export function SocialBrainstorm({
  onLaunched,
  onSkip,
}: {
  /** Called just before navigating to Chat, so the page can unlock Compose. */
  onLaunched: () => void;
  /** "Just need one post" escape hatch — unlocks and switches to Compose. */
  onSkip: () => void;
}) {
  const navigate = useNavigate();
  const { t } = useI18n();
  const s = t.social ?? en.social!;

  const [topic, setTopic] = useState("");
  const [goal, setGoal] = useState<SocialGoal | null>(null);
  const [tone, setTone] = useState<SocialTone | null>(null);
  const [postCount, setPostCount] = useState<SocialSequenceLength | null>(null);
  const [cadence, setCadence] = useState<SocialCadence | null>(null);
  const [includeImage, setIncludeImage] = useState<boolean | null>(null);

  // `reached` is the furthest point unlocked so far (STEPS.length = review);
  // `active` is the question currently open, which drops below `reached` while
  // the user edits an earlier answer.
  const [reached, setReached] = useState(0);
  const [active, setActive] = useState(0);

  const advance = (index: number) => {
    const next = Math.max(reached, index + 1);
    setReached(next);
    setActive(next);
  };

  const questions: Record<StepId, string> = {
    topic: s.bsTopicQuestion,
    goal: s.bsGoalQuestion,
    tone: s.bsToneQuestion,
    rhythm: s.bsRhythmQuestion,
    image: s.bsImageQuestion,
  };

  const imageOptions: readonly SocialOption<"yes" | "no">[] = [
    { id: "yes", label: s.bsImageYes, description: s.bsImageYesHint },
    { id: "no", label: s.bsImageNo, description: s.bsImageNoHint },
  ];

  const answerFor = (step: StepId): string | null => {
    switch (step) {
      case "topic":
        return topic.trim() ? truncate(topic) : null;
      case "goal":
        return (
          SOCIAL_GOAL_OPTIONS.find((option) => option.id === goal)?.label ?? null
        );
      case "tone":
        return (
          SOCIAL_TONE_OPTIONS.find((option) => option.id === tone)?.label ?? null
        );
      case "rhythm": {
        if (postCount === null || cadence === null) return null;
        const count = SOCIAL_SEQUENCE_LENGTH_OPTIONS.find(
          (option) => option.id === String(postCount),
        )?.label;
        const rhythm = SOCIAL_CADENCE_OPTIONS.find(
          (option) => option.id === cadence,
        )?.label;
        return count && rhythm ? `${count} · ${rhythm}` : null;
      }
      case "image":
        if (includeImage === null) return null;
        return includeImage ? s.bsImageYes : s.bsImageNo;
    }
  };

  const planReady =
    topic.trim().length > 0 &&
    goal !== null &&
    tone !== null &&
    postCount !== null &&
    cadence !== null &&
    includeImage !== null;

  const start = () => {
    if (!planReady) return;
    const draft = buildSocialBrainstormPrompt({
      cadence: cadence!,
      goal: goal!,
      includeImage: includeImage!,
      postCount: postCount!,
      tone: tone!,
      topic,
    });
    markBrainstormed();
    onLaunched();
    const params = new URLSearchParams({
      [FRESH_CHAT_QUERY_PARAM]: createFreshChatRequestId(),
      draft,
    });
    navigate(`/workspace/chat?${params.toString()}`);
  };

  const renderControl = (step: StepId) => {
    switch (step) {
      case "topic":
        return (
          <div className="space-y-4">
            <textarea
              autoFocus
              className="flex min-h-32 w-full resize-y border border-border bg-background/40 px-3 py-2.5 text-sm leading-6 text-text-primary shadow-sm placeholder:text-muted-foreground focus-visible:border-foreground/25 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30"
              id="social-brainstorm-topic"
              maxLength={2000}
              onChange={(event) => setTopic(event.target.value)}
              placeholder={s.bsTopicPlaceholder}
              value={topic}
            />
            <Button
              disabled={!topic.trim()}
              onClick={() => advance(0)}
              size="sm"
              type="button"
            >
              {s.bsContinue}
            </Button>
          </div>
        );
      case "goal":
        return (
          <ChoiceGrid
            onSelect={(id) => {
              setGoal(id);
              advance(1);
            }}
            options={SOCIAL_GOAL_OPTIONS}
            value={goal}
          />
        );
      case "tone":
        return (
          <ChoiceGrid
            onSelect={(id) => {
              setTone(id);
              advance(2);
            }}
            options={SOCIAL_TONE_OPTIONS}
            value={tone}
          />
        );
      case "rhythm":
        return (
          <div className="space-y-4">
            <ChoiceGrid
              onSelect={(id) =>
                setPostCount(Number(id) as SocialSequenceLength)
              }
              options={SOCIAL_SEQUENCE_LENGTH_OPTIONS}
              value={postCount === null ? null : (`${postCount}` as const)}
            />
            {postCount !== null && (
              <div className="space-y-2 border-t border-border pt-4">
                <p className="text-sm font-medium text-text-primary">
                  {s.bsCadenceQuestion}
                </p>
                <ChoiceGrid
                  onSelect={(id) => {
                    setCadence(id);
                    advance(3);
                  }}
                  options={SOCIAL_CADENCE_OPTIONS}
                  value={cadence}
                />
              </div>
            )}
          </div>
        );
      case "image":
        return (
          <ChoiceGrid
            onSelect={(id) => {
              setIncludeImage(id === "yes");
              advance(4);
            }}
            options={imageOptions}
            value={includeImage === null ? null : includeImage ? "yes" : "no"}
          />
        );
    }
  };

  return (
    <div className="mx-auto w-full max-w-2xl">
      <ol className="fabric-thread space-y-1">
        {STEPS.map((step, index) => {
          if (index > reached) return null;

          if (index === active) {
            return (
              <li className="py-2" key={step}>
                <div className="fabric-bracket border border-border bg-background-surface/40 p-4 sm:p-5">
                  <p className="font-mono text-xs text-text-tertiary">
                    {s.bsStepOf
                      .replace("{step}", String(index + 1))
                      .replace("{total}", String(STEPS.length))}
                  </p>
                  <h3 className="mt-1 text-sm font-semibold text-text-primary">
                    {questions[step]}
                  </h3>
                  {step === "topic" && (
                    <p className="mt-1 text-xs leading-5 text-text-secondary">
                      {s.bsTopicHint}
                    </p>
                  )}
                  <div className="mt-4">{renderControl(step)}</div>
                </div>
              </li>
            );
          }

          const answer = answerFor(step);
          if (answer === null) return null;
          return (
            <li className="py-2" key={step}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <span className="block text-xs text-text-tertiary">
                    {questions[step]}
                  </span>
                  <span className="mt-1 inline-block max-w-full border border-border bg-background-surface/60 px-3 py-1.5 text-sm text-text-primary">
                    {answer}
                  </span>
                </div>
                <Button ghost onClick={() => setActive(index)} size="sm">
                  {s.bsEdit}
                </Button>
              </div>
            </li>
          );
        })}

        {active === STEPS.length && (
          <li className="py-2">
            <div className="fabric-bracket border border-border bg-background-surface/40 p-4 sm:p-5">
              <h3 className="text-sm font-semibold text-text-primary">
                {s.bsReviewTitle}
              </h3>
              <p className="mt-1 text-xs leading-5 text-text-secondary">
                {s.bsReviewBody.replace("{count}", String(postCount ?? 0))}
              </p>
              <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-border pt-4">
                <Button disabled={!planReady} onClick={start} type="button">
                  <MessagesSquare aria-hidden className="size-4" />
                  {s.bsStart}
                </Button>
                <span className="max-w-sm text-xs leading-5 text-text-secondary">
                  {s.reviewHint}
                </span>
              </div>
            </div>
          </li>
        )}
      </ol>

      <p className="mt-8 border-t border-border pt-4 text-xs leading-5 text-text-tertiary">
        {s.bsSkipLead}{" "}
        <button
          className="underline decoration-border underline-offset-4 hover:text-primary"
          onClick={onSkip}
          type="button"
        >
          {s.bsSkipAction}
        </button>
      </p>
    </div>
  );
}
