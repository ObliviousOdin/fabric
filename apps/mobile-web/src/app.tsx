import {
  IconAlertCircle,
  IconCloudOff,
  IconMenu2,
  IconMessagePlus,
  IconRefresh,
  IconX,
} from "@tabler/icons-react";
import { useMemo, useState } from "react";

import { BlockingPrompt } from "./components/blocking-prompt";
import { Composer } from "./components/composer";
import { ConnectView } from "./components/connect-view";
import { ExecutionNotice } from "./components/execution-notice";
import {
  EnrollmentBrowserNotice,
  PairingLanding,
} from "./components/pairing-landing";
import { SessionDrawer } from "./components/session-drawer";
import { Transcript } from "./components/transcript";
import { WorkStatus } from "./components/work-status";
import { useMobileGateway } from "./gateway/use-mobile-gateway";
import { createCookieAutoConnectClaim } from "./gateway/probe-auth";
import { takePairingPayload } from "./pairing";

export function App() {
  const gateway = useMobileGateway();
  const [composerText, setComposerText] = useState("");
  const [claimCookieAutoConnect] = useState(createCookieAutoConnectClaim);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [pairing] = useState(takePairingPayload);
  const [showPairingLanding, setShowPairingLanding] = useState(
    Boolean(pairing),
  );

  const currentSummary = useMemo(
    () =>
      gateway.sessions.find(
        (session) => session.id === gateway.activeSession.storedSessionId,
      ),
    [gateway.activeSession.storedSessionId, gateway.sessions],
  );
  const connected = gateway.connectionState === "open";
  const showConnect =
    !gateway.connection ||
    gateway.connectionState === "idle" ||
    (gateway.connectionState === "error" &&
      !gateway.activeSession.runtimeSessionId);

  if (pairing && showPairingLanding) {
    return (
      <PairingLanding
        enrollmentRequired={pairing.kind === "enrollment"}
        pairingUri={pairing.pairingUri}
        onContinue={() => setShowPairingLanding(false)}
      />
    );
  }

  if (pairing?.kind === "enrollment") {
    return <EnrollmentBrowserNotice pairingUri={pairing.pairingUri} />;
  }

  if (showConnect) {
    return (
      <ConnectView
        claimCookieAutoConnect={claimCookieAutoConnect}
        connecting={gateway.connectionState === "connecting"}
        error={gateway.error}
        initialConnection={pairing?.connection ?? null}
        onConnect={gateway.connect}
      />
    );
  }

  const createNew = async () => {
    setDrawerOpen(false);
    setComposerText("");
    try {
      await gateway.createSession();
    } catch {
      // The gateway hook owns the actionable error banner.
    }
  };

  const selectSession = async (id: string) => {
    setDrawerOpen(false);
    setComposerText("");
    try {
      await gateway.resumeSession(id);
    } catch {
      // The gateway hook owns the actionable error banner.
    }
  };

  const title =
    currentSummary?.title ||
    (gateway.activeSession.runtimeSessionId ? "New session" : "Fabric");
  const context = [
    gateway.activeSession.info.profile_name,
    gateway.activeSession.info.cwd,
  ]
    .filter(Boolean)
    .join(" · ");
  const canCreate = gateway.supportsMethod("session.create");
  const canList = gateway.supportsMethod("session.list");
  const canResume = gateway.supportsMethod("session.resume");
  const canSend = gateway.supportsMethod("prompt.submit");
  const canInterrupt = gateway.supportsMethod("session.interrupt");
  const canRunInBackground =
    (gateway.supportsMethod("job.create") ||
      gateway.supportsMethod("prompt.background")) &&
    !["submitting", "retryable", "failed"].includes(
      gateway.backgroundSubmission.status,
    );
  const pendingPrompt = gateway.activeSession.pendingInteractions[0];
  const promptResponseMethod =
    pendingPrompt?.type === "approval"
      ? "approval.respond"
      : pendingPrompt?.type === "clarify"
        ? "clarify.respond"
        : pendingPrompt?.type === "sudo"
          ? "sudo.respond"
          : pendingPrompt?.type === "secret"
            ? "secret.respond"
            : null;
  const canRespondToPrompt = Boolean(
    promptResponseMethod && gateway.supportsMethod(promptResponseMethod),
  );
  const composerDisabled =
    !connected ||
    !canSend ||
    (!gateway.activeSession.runtimeSessionId && !canCreate);
  const composerDisabledPlaceholder = !connected
    ? "Reconnect to continue"
    : gateway.capabilityState?.kind === "negotiating"
      ? "Checking gateway compatibility"
      : "Update Fabric to continue";
  const gatewayReady = connected && canList;
  const activeRequestIds = new Set(
    gateway.activeSession.pendingInteractions.map((prompt) => prompt.requestId),
  );

  return (
    <div className="mobile-app">
      <SessionDrawer
        activeStoredId={gateway.activeSession.storedSessionId}
        canCreate={canCreate}
        canRefresh={canList}
        canResume={canResume}
        onClose={() => setDrawerOpen(false)}
        onDisconnect={gateway.disconnect}
        onNew={() => void createNew()}
        onRefresh={() => void gateway.refreshSessions()}
        onSelect={(id) => void selectSession(id)}
        open={drawerOpen}
        sessions={gateway.sessions}
      />

      <main className="chat-shell">
        <header className="chat-header">
          <button
            className="icon-button menu-button"
            type="button"
            aria-label="Open sessions"
            onClick={() => setDrawerOpen(true)}
          >
            <IconMenu2 size={22} />
          </button>
          <div className="chat-title">
            <div className="chat-title-line">
              <h1>{title}</h1>
              <span
                className={`connection-dot ${gatewayReady ? "online" : "offline"}`}
                aria-label={gatewayReady ? "Gateway ready" : "Gateway not ready"}
              />
            </div>
            <p>
              {context || gateway.activeSession.info.model || "Remote gateway"}
            </p>
          </div>
          <button
            className="icon-button header-new"
            type="button"
            aria-label="New session"
            disabled={!canCreate}
            onClick={() => void createNew()}
          >
            <IconMessagePlus size={21} />
          </button>
        </header>

        {!connected && (
          <div className="offline-banner" role="status">
            <IconCloudOff size={17} />
            <span>
              Gateway disconnected. Your draft is safe; prompts are not
              auto-retried.
            </span>
            <button type="button" onClick={() => void gateway.reconnect()}>
              <IconRefresh size={15} /> Reconnect
            </button>
          </div>
        )}

        {gateway.error && connected && (
          <div className="error-banner" role="alert">
            <IconAlertCircle size={17} />
            <span>{gateway.error}</span>
            <button
              type="button"
              aria-label="Dismiss"
              onClick={gateway.clearError}
            >
              <IconX size={16} />
            </button>
          </div>
        )}

        <ExecutionNotice
          state={gateway.capabilityState}
          onRetry={() => void gateway.reconnect()}
        />

        <WorkStatus
          activeRequestIds={activeRequestIds}
          background={gateway.backgroundSubmission}
          onAbandonBackground={gateway.abandonBackgroundRetry}
          onRespond={gateway.respondToWorkAttention}
          onRetryBackground={gateway.retryBackground}
          projection={gateway.workProjection}
          showAttention={!pendingPrompt}
          status={gateway.workStatus}
        />

        {gateway.activeSession.persistenceWarning && (
          <div className="error-banner persistence-banner" role="alert">
            <IconAlertCircle size={17} />
            <span>{gateway.activeSession.persistenceWarning}</span>
          </div>
        )}

        <Transcript
          connected={connected}
          messages={gateway.activeSession.messages}
          onSuggestion={setComposerText}
          running={gateway.activeSession.running}
        />

        {pendingPrompt && (
          <BlockingPrompt
            disabled={!canRespondToPrompt}
            prompt={pendingPrompt}
            onRespond={gateway.respondToPrompt}
          />
        )}

        {!gateway.activeSession.runtimeSessionId &&
        gateway.activeSession.messages.length === 0 ? (
          <div className="draft-session-note">
            <IconMessagePlus size={16} /> Your first message creates a saved
            Fabric session.
          </div>
        ) : null}

        <Composer
          branch={gateway.activeSession.info.branch}
          canInterrupt={canInterrupt}
          canRunInBackground={canRunInBackground}
          disabled={composerDisabled}
          disabledPlaceholder={composerDisabledPlaceholder}
          model={gateway.activeSession.info.model}
          onInterrupt={gateway.interrupt}
          onRunInBackground={gateway.runInBackground}
          onSend={gateway.send}
          onTextChange={setComposerText}
          running={gateway.activeSession.running}
          text={composerText}
        />
      </main>
    </div>
  );
}
