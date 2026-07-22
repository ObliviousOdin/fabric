import { Sparkles, WandSparkles } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@nous-research/ui/ui/components/button";
import { Label } from "@nous-research/ui/ui/components/label";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";

import {
  createFreshChatRequestId,
  FRESH_CHAT_QUERY_PARAM,
} from "@/components/chat/usePersistentChatIdentity";
import { useI18n } from "@/i18n";
import { en } from "@/i18n/en";
import {
  buildSocialPrompt,
  SOCIAL_CHANNEL_OPTIONS,
  SOCIAL_FORMAT_OPTIONS,
  SOCIAL_GOAL_OPTIONS,
  SOCIAL_TONE_OPTIONS,
  type SocialChannel,
  type SocialFormat,
  type SocialGoal,
  type SocialTone,
} from "@/lib/social-prompt";

/**
 * The Social Studio composer. Same handoff shape as the Design surface: collect
 * a brief plus a few structured choices, build a prompt, and drop it into a
 * fresh Chat for review. The resulting conversation's post is read back by the
 * Library.
 */
export function SocialComposer() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const s = t.social ?? en.social!;

  const [brief, setBrief] = useState("");
  const [channel, setChannel] = useState<SocialChannel>("linkedin");
  const [goal, setGoal] = useState<SocialGoal>("authority");
  const [tone, setTone] = useState<SocialTone>("candid");
  const [format, setFormat] = useState<SocialFormat>("hook-story");
  const [includeImage, setIncludeImage] = useState(true);

  const start = () => {
    if (!brief.trim()) return;
    const draft = buildSocialPrompt({
      brief,
      channel,
      format,
      goal,
      includeImage,
      tone,
    });
    const params = new URLSearchParams({
      [FRESH_CHAT_QUERY_PARAM]: createFreshChatRequestId(),
      draft,
    });
    navigate(`/workspace/chat?${params.toString()}`);
  };

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem] lg:gap-10">
      <form
        className="min-w-0 space-y-6"
        onSubmit={(event) => {
          event.preventDefault();
          start();
        }}
      >
        <div className="space-y-2">
          <Label htmlFor="social-brief">{s.briefLabel}</Label>
          <textarea
            autoFocus
            className="flex min-h-36 w-full resize-y border border-border bg-background/40 px-3 py-2.5 text-sm leading-6 text-text-primary shadow-sm placeholder:text-muted-foreground focus-visible:border-foreground/25 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30"
            id="social-brief"
            maxLength={2000}
            onChange={(event) => setBrief(event.target.value)}
            placeholder={s.briefPlaceholder}
            value={brief}
          />
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="social-channel">{s.channelLabel}</Label>
            <Select
              id="social-channel"
              onValueChange={(value) => setChannel(value as SocialChannel)}
              value={channel}
            >
              {SOCIAL_CHANNEL_OPTIONS.map((option) => (
                <SelectOption key={option.id} value={option.id}>
                  {option.label}
                </SelectOption>
              ))}
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="social-goal">{s.goalLabel}</Label>
            <Select
              id="social-goal"
              onValueChange={(value) => setGoal(value as SocialGoal)}
              value={goal}
            >
              {SOCIAL_GOAL_OPTIONS.map((option) => (
                <SelectOption key={option.id} value={option.id}>
                  {option.label}
                </SelectOption>
              ))}
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="social-tone">{s.toneLabel}</Label>
            <Select
              id="social-tone"
              onValueChange={(value) => setTone(value as SocialTone)}
              value={tone}
            >
              {SOCIAL_TONE_OPTIONS.map((option) => (
                <SelectOption key={option.id} value={option.id}>
                  {option.label}
                </SelectOption>
              ))}
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="social-format">{s.formatLabel}</Label>
            <Select
              id="social-format"
              onValueChange={(value) => setFormat(value as SocialFormat)}
              value={format}
            >
              {SOCIAL_FORMAT_OPTIONS.map((option) => (
                <SelectOption key={option.id} value={option.id}>
                  {option.label}
                </SelectOption>
              ))}
            </Select>
          </div>
        </div>

        <label className="flex cursor-pointer items-start gap-3 border border-border bg-background-surface/60 p-3">
          <input
            checked={includeImage}
            className="mt-0.5 size-4 accent-primary"
            onChange={(event) => setIncludeImage(event.target.checked)}
            type="checkbox"
          />
          <span className="min-w-0">
            <span className="block text-sm font-medium text-text-primary">
              {s.imageLabel}
            </span>
            <span className="mt-0.5 block text-xs leading-5 text-text-secondary">
              {s.imageHint}
            </span>
          </span>
        </label>

        <div className="flex flex-wrap items-center gap-3 border-t border-border pt-5">
          <Button disabled={!brief.trim()} type="submit">
            <WandSparkles className="size-4" aria-hidden />
            {s.start}
          </Button>
          <span className="max-w-sm text-xs leading-5 text-text-secondary">
            {s.reviewHint}
          </span>
        </div>
      </form>

      <aside className="border-t border-border pt-6 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
        <div className="mb-3 flex size-9 items-center justify-center border border-border bg-background-surface text-text-secondary">
          <Sparkles className="size-4" aria-hidden />
        </div>
        <h3 className="text-sm font-semibold text-text-primary">
          {s.howItWorksTitle}
        </h3>
        <ol className="mt-5 space-y-4">
          {s.howItWorks.map((step, index) => (
            <li
              className="grid grid-cols-[1.75rem_minmax(0,1fr)] items-start gap-2"
              key={step}
            >
              <span className="font-mono text-xs leading-5 text-text-secondary">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="text-sm leading-5 text-text-secondary">
                {step}
              </span>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}
