/** Render a backend-supplied CLI command using the public Fabric executable. */
export function publicCliCommand(
  command: string | null | undefined,
  fallback = "fabric update",
): string {
  return command?.trim() || fallback;
}

/** Render a backend-supplied console prompt using the Fabric default. */
export function publicConsolePrompt(prompt?: string): string {
  return prompt || "fabric> ";
}
