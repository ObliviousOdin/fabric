/**
 * Shared vocabulary for the Models loadout surfaces: the auxiliary-task
 * slot table plus the model-id helpers used by the assignment rows, the
 * per-card "Use as" menu and the modals. Pure module — no components.
 */

// Must match _AUX_TASK_SLOTS in fabric_cli/web_server.py. (R18: frontend
// mirror of a backend table — keep this comment adjacent so drift is
// caught in review.)
export const AUX_TASKS: readonly { key: string; label: string; hint: string }[] = [
  { key: "vision", label: "Vision", hint: "Image analysis" },
  { key: "web_extract", label: "Web Extract", hint: "Page summarization" },
  { key: "compression", label: "Compression", hint: "Context compaction" },
  { key: "skills_hub", label: "Skills Hub", hint: "Skill search" },
  { key: "approval", label: "Approval", hint: "Smart auto-approve" },
  { key: "mcp", label: "MCP", hint: "MCP tool routing" },
  { key: "title_generation", label: "Title Gen", hint: "Session titles" },
  { key: "triage_specifier", label: "Triage Specifier", hint: "Kanban spec fleshing" },
  { key: "kanban_decomposer", label: "Kanban Decomposer", hint: "Task decomposition" },
  { key: "profile_describer", label: "Profile Describer", hint: "Auto profile descriptions" },
  { key: "curator", label: "Curator", hint: "Skill-usage review" },
] as const;

/** Short model name: strip vendor prefix like "openrouter/" or "anthropic/". */
export function shortModelName(model: string): string {
  const slashIdx = model.indexOf("/");
  if (slashIdx > 0) return model.slice(slashIdx + 1);
  return model;
}

/** Extract vendor prefix from a model string like "anthropic/claude-opus-4.7" → "anthropic". */
export function modelVendor(model: string, fallback?: string): string {
  const slashIdx = model.indexOf("/");
  if (slashIdx > 0) return model.slice(0, slashIdx);
  return fallback || "";
}
