export type SlashResolution =
  | { type: "display"; text: string }
  | { type: "prefill"; text: string }
  | { type: "send"; text: string };

export type GatewayRequest = <T>(
  method: string,
  params?: Record<string, unknown>,
) => Promise<T>;

interface SlashExecResponse {
  output?: unknown;
  warning?: unknown;
}

interface CommandDispatchResponse {
  arg?: unknown;
  command?: unknown;
  message?: unknown;
  output?: unknown;
  text?: unknown;
  type?: unknown;
}

function splitCommand(command: string): { arg: string; name: string } {
  const parts = command.trim().replace(/^\//, "").split(/\s+/, 2);
  const name = parts[0]?.toLowerCase() ?? "";
  const arg = command
    .trim()
    .replace(/^\//, "")
    .slice(parts[0]?.length ?? 0)
    .trim();
  return { arg, name };
}

async function dispatchCommand(
  request: GatewayRequest,
  sessionId: string,
  command: string,
  depth: number,
): Promise<SlashResolution> {
  const { arg, name } = splitCommand(command);
  if (!name) {
    return { text: "", type: "display" };
  }

  const result = await request<CommandDispatchResponse>("command.dispatch", {
    arg,
    name,
    session_id: sessionId,
  });
  const type = typeof result.type === "string" ? result.type : "";
  const message =
    typeof result.message === "string"
      ? result.message
      : typeof result.text === "string"
        ? result.text
        : "";

  if ((type === "send" || type === "skill") && message) {
    return { text: message, type: "send" };
  }
  if (type === "prefill") {
    return { text: message || arg, type: "prefill" };
  }
  if (type === "alias" && depth < 3) {
    const alias =
      typeof result.command === "string"
        ? result.command
        : typeof result.arg === "string"
          ? result.arg
          : message;
    if (alias) {
      return resolveMobileSlashCommand(request, sessionId, alias, depth + 1);
    }
  }

  const output =
    typeof result.output === "string" ? result.output : message || "Command completed.";
  return { text: output, type: "display" };
}

export async function resolveMobileSlashCommand(
  request: GatewayRequest,
  sessionId: string,
  command: string,
  depth = 0,
): Promise<SlashResolution> {
  try {
    const result = await request<SlashExecResponse>("slash.exec", {
      command,
      session_id: sessionId,
    });
    const output = typeof result.output === "string" ? result.output : "";
    const warning = typeof result.warning === "string" ? result.warning : "";
    return {
      text: [output, warning].filter(Boolean).join("\n\n") || "Command completed.",
      type: "display",
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const shouldDispatch =
      /command\.dispatch|skill command|pending input|unsupported|unknown command/i.test(
        message,
      );
    if (!shouldDispatch) {
      throw error;
    }
    return dispatchCommand(request, sessionId, command, depth);
  }
}
