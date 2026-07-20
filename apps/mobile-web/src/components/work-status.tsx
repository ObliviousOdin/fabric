import {
  WORK_ATTENTION_ACTIONS,
  type WorkAttention,
  type WorkAttentionAction,
  type WorkJsonValue,
  type WorkProjection,
  type RemoteBlockingPrompt,
} from "@fabric/shared";
import { IconBriefcase, IconRefresh, IconX } from "@tabler/icons-react";

import type {
  MobileBackgroundSubmission,
  MobileWorkStatus,
} from "../gateway/use-mobile-gateway";
import { BlockingPrompt } from "./blocking-prompt";

interface WorkStatusProps {
  activeRequestIds: ReadonlySet<string>;
  background: MobileBackgroundSubmission;
  onAbandonBackground: () => void;
  onRespond: (
    attentionId: string,
    action: WorkAttentionAction,
    value?: string,
  ) => Promise<void>;
  onRetryBackground: () => Promise<void>;
  projection: WorkProjection | null;
  showAttention: boolean;
  status: MobileWorkStatus;
}

const ACTIVE_JOB_STATES = new Set([
  "queued",
  "claimed",
  "running",
  "waiting_attention",
  "cancel_requested",
]);
const KNOWN_ATTENTION_ACTIONS = new Set<string>(WORK_ATTENTION_ACTIONS);

function knownAttentionActions(
  actions: readonly string[],
): WorkAttentionAction[] {
  return actions.filter((action): action is WorkAttentionAction =>
    KNOWN_ATTENTION_ACTIONS.has(action),
  );
}

function payloadString(
  payload: Readonly<Record<string, WorkJsonValue>>,
  key: string,
): string {
  const value = payload[key];
  return typeof value === "string" ? value : "";
}

function payloadChoices(
  payload: Readonly<Record<string, WorkJsonValue>>,
): string[] | null {
  const choices = payload.choices;
  if (
    !Array.isArray(choices) ||
    choices.some((choice) => typeof choice !== "string")
  ) {
    return null;
  }
  return choices as string[];
}

function toBlockingPrompt(
  attention: WorkAttention,
): RemoteBlockingPrompt | null {
  if (attention.kind === "approval") {
    return {
      allowPermanent: attention.allowed_actions.includes("always"),
      command:
        payloadString(attention.public_payload, "command") ||
        payloadString(attention.public_payload, "target"),
      description:
        payloadString(attention.public_payload, "description") ||
        attention.title,
      requestId: attention.request_id,
      type: "approval",
    };
  }
  if (attention.kind === "clarify") {
    return {
      choices: payloadChoices(attention.public_payload),
      question:
        payloadString(attention.public_payload, "question") || attention.title,
      requestId: attention.request_id,
      type: "clarify",
    };
  }
  if (attention.kind === "sudo") {
    return { requestId: attention.request_id, type: "sudo" };
  }
  if (attention.kind === "secret") {
    return {
      envVar: payloadString(attention.public_payload, "env_var"),
      prompt:
        payloadString(attention.public_payload, "prompt") || attention.title,
      requestId: attention.request_id,
      type: "secret",
    };
  }
  return null;
}

export function WorkStatus({
  activeRequestIds,
  background,
  onAbandonBackground,
  onRespond,
  onRetryBackground,
  projection,
  showAttention,
  status,
}: WorkStatusProps) {
  const activeJobs = Object.values(projection?.jobs ?? {}).filter((job) =>
    ACTIVE_JOB_STATES.has(job.status),
  );
  const pendingAttention = Object.values(projection?.attention ?? {}).filter(
    (attention) =>
      attention.state === "pending" &&
      attention.actionable &&
      !activeRequestIds.has(attention.request_id),
  );
  const firstAttention =
    showAttention && status === "current" ? pendingAttention[0] : undefined;
  const blockingPrompt = firstAttention
    ? toBlockingPrompt(firstAttention)
    : null;
  const allowedActions = firstAttention
    ? knownAttentionActions(firstAttention.allowed_actions)
    : [];

  return (
    <>
      {(background.status === "retryable" ||
        background.status === "failed") && (
        <div className="work-status error" role="alert">
          <IconBriefcase size={17} />
          <span>{background.error || "Background submission failed."}</span>
          {background.retryable && (
            <button type="button" onClick={() => void onRetryBackground()}>
              <IconRefresh size={15} /> Retry
            </button>
          )}
          <button
            type="button"
            aria-label="Dismiss pending background submission"
            onClick={onAbandonBackground}
          >
            <IconX size={15} />
          </button>
        </div>
      )}

      {status === "current" &&
        (activeJobs.length > 0 || pendingAttention.length > 0) && (
          <div className="work-status" role="status">
            <IconBriefcase size={17} />
            <span>
              {activeJobs.length > 0
                ? `${activeJobs.length} background ${activeJobs.length === 1 ? "job" : "jobs"}`
                : "No active background jobs"}
              {pendingAttention.length > 0
                ? ` · ${pendingAttention.length} need${pendingAttention.length === 1 ? "s" : ""} attention`
                : ""}
            </span>
          </div>
        )}

      {firstAttention && blockingPrompt && (
        <BlockingPrompt
          allowedActions={allowedActions}
          prompt={blockingPrompt}
          resetKey={`${firstAttention.attention_id}:${firstAttention.version}`}
          onRespond={(value, approvalChoice) => {
            const action: WorkAttentionAction =
              firstAttention.kind === "approval"
                ? ((approvalChoice || "deny") as WorkAttentionAction)
                : approvalChoice === "cancel"
                  ? "cancel"
                  : "submit";
            if (!allowedActions.includes(action)) {
              return Promise.reject(
                new Error(
                  "This response is not allowed for the current Attention item.",
                ),
              );
            }
            return onRespond(
              firstAttention.attention_id,
              action,
              action === "submit" ? value : undefined,
            );
          }}
        />
      )}
    </>
  );
}
