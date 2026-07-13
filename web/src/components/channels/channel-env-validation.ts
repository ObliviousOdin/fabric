import type { MessagingPlatformEnvVar } from "@/lib/api";

/**
 * Client-side mirrors of the gateway's messaging-credential parsing (H3 —
 * behavior frozen). Component-free so `ChannelConfigModal` stays a
 * components-only module (react-refresh) and the mirrors stay
 * unit-testable.
 */

const SLACK_MEMBER_ID_RE = /^[UW][A-Z0-9]{2,}$/;
const SLACK_TOKEN_PREFIXES: Record<string, string> = {
  SLACK_BOT_TOKEN: "xoxb-",
  SLACK_APP_TOKEN: "xapp-",
};

export function validateMessagingEnvField(
  field: MessagingPlatformEnvVar,
  value: string,
): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;

  const expectedPrefix = SLACK_TOKEN_PREFIXES[field.key];
  if (expectedPrefix && !trimmed.startsWith(expectedPrefix)) {
    return `${field.prompt || field.key} must start with ${expectedPrefix}`;
  }

  if (field.key === "SLACK_ALLOWED_USERS") {
    // Mirror the gateway's parse (gateway/platforms/slack.py): drop empty
    // entries so a trailing/interior comma isn't rejected here. "*" is the
    // allow-all wildcard the gateway honors.
    const parts = trimmed
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
    const invalid = parts.find((part) => part !== "*" && !SLACK_MEMBER_ID_RE.test(part));
    if (invalid) {
      return `${invalid} does not look like a Slack member ID. Use IDs like U01ABC2DEF3.`;
    }
  }

  return null;
}
