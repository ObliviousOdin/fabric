/**
 * Pure helpers shared by the Telegram/WhatsApp QR onboarding panels
 * (H4 — the flows themselves are frozen, N23; only their location moved
 * out of the ChannelsPage monolith).
 */

export const TELEGRAM_USER_ID_RE = /^\d+$/;

/** `mm:ss` countdown to an ISO expiry, or `"expired"` once past. */
export function formatExpiry(expiresAt: string): string {
  const ms = Date.parse(expiresAt) - Date.now();
  if (!Number.isFinite(ms) || ms <= 0) return "expired";
  const seconds = Math.ceil(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${rest.toString().padStart(2, "0")}`;
}

export function isTerminalTelegramOnboardingError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /\b410\b/.test(message) && /\b(expired|claimed|gone)\b/i.test(message);
}

export function isTerminalWhatsAppOnboardingError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /\b410\b/.test(message) && /\b(expired|gone)\b/i.test(message);
}

export function normalizeWhatsAppMode(mode: unknown): "bot" | "self-chat" | null {
  return mode === "bot" || mode === "self-chat" ? mode : null;
}
