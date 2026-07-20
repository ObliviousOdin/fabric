import type { RemoteBlockingPrompt, WorkAttentionAction } from "@fabric/shared";
import {
  IconAlertTriangle,
  IconKey,
  IconQuestionMark,
} from "@tabler/icons-react";
import { useEffect, useState, type FormEvent } from "react";

interface BlockingPromptProps {
  allowedActions?: readonly WorkAttentionAction[];
  disabled?: boolean;
  onRespond: (value: string, approvalChoice?: string) => Promise<void>;
  prompt: RemoteBlockingPrompt;
  resetKey?: string;
}

export function BlockingPrompt({
  allowedActions,
  disabled = false,
  onRespond,
  prompt,
  resetKey,
}: BlockingPromptProps) {
  const [answer, setAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<null | string>(null);
  const promptIdentity = resetKey ?? `${prompt.type}:${prompt.requestId}`;

  useEffect(() => {
    setAnswer("");
    setError(null);
  }, [promptIdentity]);

  const submit = async (value: string, approvalChoice?: string) => {
    setSubmitting(true);
    setError(null);
    try {
      await onRespond(value, approvalChoice);
      setAnswer("");
    } catch (responseError) {
      setError(
        responseError instanceof Error
          ? responseError.message
          : String(responseError),
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (prompt.type === "approval") {
    const actions = new Set<WorkAttentionAction>(
      allowedActions ?? [
        "deny",
        "once",
        ...(prompt.allowPermanent ? ["always" as const] : []),
      ],
    );
    const hasAction = ["deny", "session", "always", "once"].some((action) =>
      actions.has(action as WorkAttentionAction),
    );
    return (
      <section
        className="blocking-prompt approval-prompt"
        aria-labelledby="approval-title"
      >
        <div className="blocking-icon">
          <IconAlertTriangle size={19} />
        </div>
        <div className="blocking-copy">
          <p className="eyebrow">Approval needed</p>
          <h3 id="approval-title">{prompt.description}</h3>
          {prompt.command && <code>{prompt.command}</code>}
          <div className="prompt-actions">
            {actions.has("deny") && (
              <button
                disabled={disabled || submitting}
                type="button"
                onClick={() => void submit("", "deny")}
              >
                Reject
              </button>
            )}
            {actions.has("session") && (
              <button
                disabled={disabled || submitting}
                type="button"
                onClick={() => void submit("", "session")}
              >
                Allow for session
              </button>
            )}
            {actions.has("always") && (
              <button
                disabled={disabled || submitting}
                type="button"
                onClick={() => void submit("", "always")}
              >
                Always allow
              </button>
            )}
            {actions.has("once") && (
              <button
                className="primary"
                disabled={disabled || submitting}
                type="button"
                onClick={() => void submit("", "once")}
              >
                {submitting ? "Responding…" : "Run once"}
              </button>
            )}
          </div>
          {!hasAction && (
            <p className="form-error">
              This Attention item has no compatible response action.
            </p>
          )}
          {error && <p className="form-error">{error}</p>}
          {disabled && (
            <p className="form-error">
              This response is unavailable on the connected gateway.
            </p>
          )}
        </div>
      </section>
    );
  }

  const isSecret = prompt.type === "secret" || prompt.type === "sudo";
  const actions = new Set<WorkAttentionAction>(allowedActions ?? ["submit"]);
  const canSubmit = actions.has("submit");
  const canCancel = actions.has("cancel");
  const title =
    prompt.type === "clarify"
      ? prompt.question
      : prompt.type === "sudo"
        ? "Administrator password required"
        : prompt.prompt || `Enter ${prompt.envVar}`;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (canSubmit && (answer.trim() || isSecret)) {
      void submit(answer);
    }
  };

  return (
    <section className="blocking-prompt" aria-labelledby="blocking-title">
      <div className="blocking-icon">
        {isSecret ? <IconKey size={19} /> : <IconQuestionMark size={19} />}
      </div>
      <form className="blocking-copy" onSubmit={onSubmit}>
        <p className="eyebrow">
          {isSecret ? "Private input" : "Fabric needs your input"}
        </p>
        <h3 id="blocking-title">{title}</h3>
        {canSubmit && prompt.type === "clarify" && prompt.choices?.length ? (
          <div className="choice-list">
            {prompt.choices.map((choice) => (
              <button
                disabled={disabled || submitting}
                key={choice}
                type="button"
                onClick={() => void submit(choice)}
              >
                {choice}
              </button>
            ))}
          </div>
        ) : null}
        {canSubmit && (
          <div className="prompt-answer-row">
            <input
              autoFocus
              autoComplete="off"
              disabled={disabled}
              type={isSecret ? "password" : "text"}
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              placeholder={
                isSecret
                  ? "Value is sent directly to Fabric"
                  : "Type your answer"
              }
            />
            <button
              className="primary"
              disabled={disabled || submitting || (!answer.trim() && !isSecret)}
              type="submit"
            >
              {submitting ? "Sending…" : "Send"}
            </button>
          </div>
        )}
        {canCancel && (
          <div className="prompt-actions">
            <button
              disabled={disabled || submitting}
              type="button"
              onClick={() => void submit("", "cancel")}
            >
              Cancel
            </button>
          </div>
        )}
        {!canSubmit && !canCancel && (
          <p className="form-error">
            This Attention item has no compatible response action.
          </p>
        )}
        {error && <p className="form-error">{error}</p>}
        {disabled && (
          <p className="form-error">
            This response is unavailable on the connected gateway.
          </p>
        )}
      </form>
    </section>
  );
}
