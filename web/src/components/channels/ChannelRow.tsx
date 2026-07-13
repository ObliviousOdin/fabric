import type { ReactNode } from "react";
import { PlugZap, Settings2 } from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import type { MessagingPlatform } from "@/lib/api";
import {
  AgentStatusBadge,
  CAPABILITY_STATE_TONES,
  CapabilityRow,
  RelativeTime,
  channelConfigState,
  channelRuntimeStatus,
  sourceIcon,
} from "@/components/ui";
import { useI18n } from "@/i18n";

export interface ChannelRowProps {
  platform: MessagingPlatform;
  /** `sessions/stats.by_source[id]` usage evidence (H6); 0/undefined hides the segment. */
  sessionsCount?: number;
  /** Toggle write in flight — the Switch's own busy pulse (H2). */
  toggling: boolean;
  testing: boolean;
  onToggle: () => void;
  onTest: () => void;
  onConfigure: () => void;
  /** Telegram/WhatsApp QR onboarding panel, rendered in the detail zone (H4). */
  onboarding?: ReactNode;
}

/**
 * Messaging-platform row (CapabilityRow consumer #6, spec H2): enable
 * Switch with the shipped optimistic semantics, monochrome source glyph
 * (CN7), and the CN1 two-axis state — runtime states (`connected |
 * disconnected | fatal | startup_failed | gateway_stopped`) render an
 * `AgentStatusBadge`, config overlays (`disabled | not_configured |
 * pending_restart`) render a CAP2-toned `Badge`; exactly one axis badge
 * shows, never merged. Unknown states render raw on the outline tone
 * (R18/R23 — never re-derived client-side).
 */
export function ChannelRow({
  platform,
  sessionsCount,
  toggling,
  testing,
  onToggle,
  onTest,
  onConfigure,
  onboarding,
}: ChannelRowProps) {
  const { t } = useI18n();
  const runtime = channelRuntimeStatus(platform.state);
  const config = runtime ? null : channelConfigState(platform.state);

  const home = platform.home_channel;
  const homeTitle = home
    ? `${home.platform}/${home.chat_id}${home.thread_id ? `#${home.thread_id}` : ""}`
    : undefined;

  const hasMeta =
    (sessionsCount ?? 0) > 0 || home !== null || (runtime !== null && !!platform.updated_at);

  return (
    <CapabilityRow
      name={platform.name}
      mono={false}
      nameTitle={platform.id}
      icon={sourceIcon(platform.id)}
      switch={{
        checked: platform.enabled,
        onChange: onToggle,
        busy: toggling,
        ariaLabel: `Enable ${platform.name}`,
      }}
      badges={
        runtime ? (
          <AgentStatusBadge status={runtime.status} label={runtime.label} />
        ) : config ? (
          <Badge
            tone={CAPABILITY_STATE_TONES[config.state]}
            title={
              platform.state === "pending_restart"
                ? "Saved — takes effect after the next gateway restart."
                : platform.state === "disabled"
                  ? "Enable the switch, then restart the gateway to connect."
                  : undefined
            }
          >
            {config.label}
          </Badge>
        ) : (
          // Unknown state from a newer backend: raw label, neutral tone (R18).
          <Badge tone="outline">{platform.state}</Badge>
        )
      }
      description={platform.description}
      meta={
        hasMeta ? (
          <>
            {(sessionsCount ?? 0) > 0 && (
              <span
                title={
                  t.channels?.sessionsEvidenceTitle ??
                  "sessions started from this channel (all time)"
                }
              >
                {sessionsCount} {sessionsCount === 1 ? "session" : "sessions"}
              </span>
            )}
            {home && (
              <>
                {(sessionsCount ?? 0) > 0 && <span aria-hidden="true">·</span>}
                <span className="min-w-0 truncate" title={homeTitle}>
                  home: {home.name || home.chat_id}
                </span>
              </>
            )}
            {runtime && platform.updated_at && (
              <>
                {((sessionsCount ?? 0) > 0 || home !== null) && (
                  <span aria-hidden="true">·</span>
                )}
                <RelativeTime value={platform.updated_at} />
              </>
            )}
          </>
        ) : undefined
      }
      detail={
        platform.error_message || onboarding ? (
          <div className="flex flex-col gap-2">
            {platform.error_message && (
              <span className="text-xs text-destructive">
                {platform.error_message}
              </span>
            )}
            {onboarding}
          </div>
        ) : undefined
      }
      actions={
        <>
          <Button
            ghost
            size="sm"
            onClick={onTest}
            disabled={testing}
            prefix={testing ? <Spinner /> : <PlugZap className="h-4 w-4" />}
          >
            Test
          </Button>
          <Button
            size="sm"
            className="uppercase"
            onClick={onConfigure}
            prefix={<Settings2 className="h-4 w-4" />}
          >
            Configure
          </Button>
        </>
      }
    />
  );
}
