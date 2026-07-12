const LEGACY_CLI_PREFIX = /^hermes(?=\s|$)/i;
const LEGACY_CONSOLE_PROMPT = /^hermes(?=>)/i;

/** Render a backend-supplied CLI command using the public Fabric executable. */
export function publicCliCommand(
  command: string | null | undefined,
  fallback = "fabric update",
): string {
  const value = command?.trim() || fallback;
  return value.replace(LEGACY_CLI_PREFIX, "fabric");
}

/** Hide the legacy console prompt while accepting older backend frames. */
export function publicConsolePrompt(prompt?: string): string {
  return (prompt || "fabric> ").replace(LEGACY_CONSOLE_PROMPT, "fabric");
}
