const MAX_COMPOSER_DRAFT_LENGTH = 8_000;

/**
 * A dashboard draft crosses the browser → PTY boundary. Strip bytes that can
 * become terminal control sequences while preserving ordinary multiline text.
 */
export function sanitizeComposerDraft(value: string | null): string {
  return (
    (value ?? "")
      .replace(/\r\n?/g, "\n")
      // eslint-disable-next-line no-control-regex -- terminal control bytes are the explicit trust boundary here
      .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/g, "")
      .trim()
      .slice(0, MAX_COMPOSER_DRAFT_LENGTH)
  );
}

export function composerDraftPayload(value: string): string {
  return `\u001b[200~${value}\u001b[201~`;
}
