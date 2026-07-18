import type { RemoteBlockingPrompt } from "@fabric/shared";
import { IconAlertTriangle, IconKey, IconQuestionMark } from "@tabler/icons-react";
import { useEffect, useState, type FormEvent } from "react";

interface BlockingPromptProps {
  onRespond: (value: string, approvalChoice?: string) => Promise<void>;
  prompt: RemoteBlockingPrompt;
}

export function BlockingPrompt({ onRespond, prompt }: BlockingPromptProps) {
  const [answer, setAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<null | string>(null);

  useEffect(() => {
    setAnswer("");
    setError(null);
  }, [prompt]);

  const submit = async (value: string, approvalChoice?: string) => {
    setSubmitting(true);
    setError(null);
    try {
      await onRespond(value, approvalChoice);
      setAnswer("");
    } catch (responseError) {
      setError(responseError instanceof Error ? responseError.message : String(responseError));
    } finally {
      setSubmitting(false);
    }
  };

  if (prompt.type === "approval") {
    return (
      <section className="blocking-prompt approval-prompt" aria-labelledby="approval-title">
        <div className="blocking-icon"><IconAlertTriangle size={19} /></div>
        <div className="blocking-copy">
          <p className="eyebrow">Approval needed</p>
          <h3 id="approval-title">{prompt.description}</h3>
          {prompt.command && <code>{prompt.command}</code>}
          <div className="prompt-actions">
            <button disabled={submitting} type="button" onClick={() => void submit("", "deny")}>
              Reject
            </button>
            {prompt.allowPermanent && (
              <button disabled={submitting} type="button" onClick={() => void submit("", "always")}>
                Always allow
              </button>
            )}
            <button className="primary" disabled={submitting} type="button" onClick={() => void submit("", "once")}>
              {submitting ? "Responding…" : "Run once"}
            </button>
          </div>
          {error && <p className="form-error">{error}</p>}
        </div>
      </section>
    );
  }

  const isSecret = prompt.type === "secret" || prompt.type === "sudo";
  const title =
    prompt.type === "clarify"
      ? prompt.question
      : prompt.type === "sudo"
        ? "Administrator password required"
        : prompt.prompt || `Enter ${prompt.envVar}`;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (answer.trim() || isSecret) {
      void submit(answer);
    }
  };

  return (
    <section className="blocking-prompt" aria-labelledby="blocking-title">
      <div className="blocking-icon">
        {isSecret ? <IconKey size={19} /> : <IconQuestionMark size={19} />}
      </div>
      <form className="blocking-copy" onSubmit={onSubmit}>
        <p className="eyebrow">{isSecret ? "Private input" : "Fabric needs your input"}</p>
        <h3 id="blocking-title">{title}</h3>
        {prompt.type === "clarify" && prompt.choices?.length ? (
          <div className="choice-list">
            {prompt.choices.map((choice) => (
              <button disabled={submitting} key={choice} type="button" onClick={() => void submit(choice)}>
                {choice}
              </button>
            ))}
          </div>
        ) : null}
        <div className="prompt-answer-row">
          <input
            autoFocus
            autoComplete="off"
            type={isSecret ? "password" : "text"}
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            placeholder={isSecret ? "Value is sent directly to Fabric" : "Type your answer"}
          />
          <button className="primary" disabled={submitting || (!answer.trim() && !isSecret)} type="submit">
            {submitting ? "Sending…" : "Send"}
          </button>
        </div>
        {error && <p className="form-error">{error}</p>}
      </form>
    </section>
  );
}
