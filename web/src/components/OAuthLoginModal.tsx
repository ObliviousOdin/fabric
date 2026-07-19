import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ExternalLink, X, Check, Copy } from "lucide-react";
import * as QRCode from "qrcode";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@nous-research/ui/ui/components/typography/h2";
import {
  api,
  getManagementProfile,
  type OAuthProvider,
  type OAuthStartResponse,
} from "@/lib/api";
import { copyTextToClipboard } from "@/lib/clipboard";
import { Input } from "@nous-research/ui/ui/components/input";
import { useI18n } from "@/i18n";
import {
  managedProviderDocsUrl,
  supportsAccountOwnershipChoice,
} from "@/lib/provider-account-route";
import { cn, themedBody } from "@/lib/utils";

interface Props {
  initialAuthWindow?: Window | null;
  provider: OAuthProvider;
  onClose: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

type Phase =
  | "choosing_account"
  | "managed_info"
  | "starting"
  | "awaiting_user"
  | "submitting"
  | "polling"
  | "approved"
  | "error";

export function OAuthLoginModal({
  initialAuthWindow = null,
  provider,
  onClose,
  onSuccess,
}: Props) {
  const hasAccountChoice = supportsAccountOwnershipChoice(provider.id);
  const [phase, setPhase] = useState<Phase>(() =>
    hasAccountChoice ? "choosing_account" : "starting",
  );
  const [start, setStart] = useState<OAuthStartResponse | null>(null);
  const [verificationQr, setVerificationQr] = useState<{
    dataUrl: string;
    verificationUrl: string;
  } | null>(null);
  const [pkceCode, setPkceCode] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">(
    "idle",
  );
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const [deviceName, setDeviceName] = useState<string | undefined>();
  const [managedRequestBusy, setManagedRequestBusy] = useState(false);
  const [managedRequestError, setManagedRequestError] = useState<string | null>(
    null,
  );
  const [takeoverAvailable, setTakeoverAvailable] = useState(false);
  const isMounted = useRef(true);
  const pollTimer = useRef<number | null>(null);
  const copyResetTimer = useRef<number | null>(null);
  const activeSessionId = useRef<string | null>(null);
  const sessionCompleted = useRef(false);
  const flowEpoch = useRef(0);
  const managedRequestEpoch = useRef(0);
  const pollInFlightEpoch = useRef<number | null>(null);
  const initialAuthWindowRef = useRef(initialAuthWindow);
  const initiatingProfileRef = useRef(getManagementProfile() || "current");
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const { t } = useI18n();

  const beginLogin = async (fromUserGesture = false, takeover = false) => {
    managedRequestEpoch.current += 1;
    const epoch = ++flowEpoch.current;
    const previousSessionId = activeSessionId.current;
    activeSessionId.current = null;
    sessionCompleted.current = false;
    pollInFlightEpoch.current = null;
    if (previousSessionId) {
      void api
        .cancelOAuthSession(
          provider.id,
          previousSessionId,
          initiatingProfileRef.current,
        )
        .catch(() => {});
    }

    // Open a placeholder synchronously while we are still inside the click
    // gesture. Navigating it after /start resolves avoids browser popup
    // blockers without exposing the provider URL before the user chooses the
    // personal-account lane.
    const authWindow = fromUserGesture
      ? window.open("about:blank", "_blank")
      : initialAuthWindowRef.current;
    initialAuthWindowRef.current = null;
    if (authWindow) authWindow.opener = null;

    setErrorMsg(null);
    setStart(null);
    setPkceCode("");
    setSecondsLeft(null);
    setTakeoverAvailable(false);
    setPhase("starting");

    let startedSessionId: string | null = null;
    try {
      let expectedRevision: number | undefined;
      if (hasAccountChoice) {
        const account = await api.getProviderAccount(
          provider.id,
          initiatingProfileRef.current,
        );
        if (!isMounted.current || epoch !== flowEpoch.current) {
          authWindow?.close();
          return;
        }
        expectedRevision = account.snapshot.revision;
      }
      const resp = await api.startOAuthLogin(
        provider.id,
        initiatingProfileRef.current,
        {
          ...(expectedRevision === undefined ? {} : { expectedRevision }),
          ...(takeover ? { takeover: true } : {}),
        },
      );
      startedSessionId = resp.session_id;

      // The dialog may have closed while the backend was creating the device
      // session. Cancel the newly-created session instead of leaking a worker
      // that can authorize after the UI is gone.
      if (!isMounted.current || epoch !== flowEpoch.current) {
        authWindow?.close();
        await api
          .cancelOAuthSession(
            provider.id,
            resp.session_id,
            initiatingProfileRef.current,
          )
          .catch(() => {});
        return;
      }

      activeSessionId.current = resp.session_id;
      setStart(resp);
      setSecondsLeft(resp.expires_in);
      setPhase(resp.flow === "device_code" ? "polling" : "awaiting_user");
      const target =
        resp.flow === "pkce" ? resp.auth_url : resp.verification_url;

      if (authWindow && !authWindow.closed) {
        const navigated = (
          authWindow.location.replace as (url: string) => unknown
        )(target);
        if (navigated === false) {
          throw new Error("The sign-in page could not be opened.");
        }
      } else {
        const opened = window.open(target, "_blank", "noopener,noreferrer");
        if (!opened) {
          throw new Error(
            "The sign-in page was blocked. Allow pop-ups and try again.",
          );
        }
      }
    } catch (e) {
      authWindow?.close();
      if (!isMounted.current || epoch !== flowEpoch.current) return;
      if (startedSessionId) {
        activeSessionId.current = null;
        void api
          .cancelOAuthSession(
            provider.id,
            startedSessionId,
            initiatingProfileRef.current,
          )
          .catch(() => {});
      }
      const conflict = String(e).includes("oauth_in_progress");
      const nousClientIdRequired =
        provider.id === "nous" && String(e).includes("nous_client_id_required");
      setTakeoverAvailable(conflict);
      setPhase("error");
      setErrorMsg(
        conflict
          ? "Another sign-in is already in progress for this account."
          : nousClientIdRequired
            ? "Nous Portal OAuth requires a registered client ID. Run `fabric auth add nous --client-id <registered-client-id>`."
            : `Failed to start login: ${e}`,
      );
    }
  };

  // Providers without an ownership decision keep their existing one-click
  // behavior. ChatGPT and Grok wait until the user chooses personal vs managed.
  useEffect(() => {
    isMounted.current = true;
    const initiatingProfile = initiatingProfileRef.current;
    const autoStartTimer = !hasAccountChoice
      ? window.setTimeout(() => void beginLogin(), 0)
      : null;

    return () => {
      isMounted.current = false;
      flowEpoch.current += 1;
      managedRequestEpoch.current += 1;
      pollInFlightEpoch.current = null;
      if (autoStartTimer !== null) window.clearTimeout(autoStartTimer);
      if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
      if (copyResetTimer.current !== null)
        window.clearTimeout(copyResetTimer.current);
      initialAuthWindowRef.current?.close();
      initialAuthWindowRef.current = null;
      const sessionId = activeSessionId.current;
      activeSessionId.current = null;
      if (sessionId && !sessionCompleted.current) {
        void api
          .cancelOAuthSession(provider.id, sessionId, initiatingProfile)
          .catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Tick the countdown
  useEffect(() => {
    if (secondsLeft === null) return;
    if (phase === "approved" || phase === "error") return;
    const tick = window.setInterval(() => {
      if (!isMounted.current) return;
      setSecondsLeft((s) => {
        if (s !== null && s <= 1) {
          setPhase("error");
          setErrorMsg(t.oauth.sessionExpired);
          return 0;
        }
        return s !== null && s > 0 ? s - 1 : 0;
      });
    }, 1000);
    return () => window.clearInterval(tick);
  }, [secondsLeft, phase, t]);

  // A failed or expired UI flow must not leave a backend worker able to
  // complete authorization after the user has been told the attempt stopped.
  useEffect(() => {
    if (phase !== "error") return;
    flowEpoch.current += 1;
    const sessionId = activeSessionId.current;
    activeSessionId.current = null;
    if (sessionId && !sessionCompleted.current) {
      void api
        .cancelOAuthSession(
          provider.id,
          sessionId,
          initiatingProfileRef.current,
        )
        .catch(() => {});
    }
  }, [phase, provider.id]);

  // Device-code: poll backend every 2s
  useEffect(() => {
    if (!start || start.flow !== "device_code" || phase !== "polling") return;
    const sid = start.session_id;
    const epoch = flowEpoch.current;
    pollTimer.current = window.setInterval(async () => {
      if (pollInFlightEpoch.current === epoch) return;
      pollInFlightEpoch.current = epoch;
      try {
        const resp = await api.pollOAuthSession(
          provider.id,
          sid,
          initiatingProfileRef.current,
        );
        if (!isMounted.current || epoch !== flowEpoch.current) return;
        if (resp.status === "approved") {
          sessionCompleted.current = true;
          activeSessionId.current = null;
          setPhase("approved");
          if (pollTimer.current !== null)
            window.clearInterval(pollTimer.current);
          onSuccess(`${provider.name} connected`);
          window.setTimeout(() => isMounted.current && onClose(), 1500);
        } else if (resp.status !== "pending") {
          setPhase("error");
          setErrorMsg(resp.error_message || `Login ${resp.status}`);
          if (pollTimer.current !== null)
            window.clearInterval(pollTimer.current);
        }
      } catch (e) {
        if (!isMounted.current || epoch !== flowEpoch.current) return;
        setPhase("error");
        setErrorMsg(`Polling failed: ${e}`);
        if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
      } finally {
        if (pollInFlightEpoch.current === epoch) {
          pollInFlightEpoch.current = null;
        }
      }
    }, 2000);
    return () => {
      if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
    };
  }, [start, phase, provider.id, provider.name, onSuccess, onClose]);

  const handleSubmitPkceCode = async () => {
    if (!start || start.flow !== "pkce") return;
    if (!pkceCode.trim()) return;
    const epoch = flowEpoch.current;
    setPhase("submitting");
    setErrorMsg(null);
    try {
      const resp = await api.submitOAuthCode(
        provider.id,
        start.session_id,
        pkceCode.trim(),
        initiatingProfileRef.current,
      );
      if (!isMounted.current || epoch !== flowEpoch.current) return;
      if (resp.ok && resp.status === "approved") {
        sessionCompleted.current = true;
        activeSessionId.current = null;
        setPhase("approved");
        onSuccess(`${provider.name} connected`);
        window.setTimeout(() => isMounted.current && onClose(), 1500);
      } else {
        setPhase("error");
        setErrorMsg(resp.message || "Token exchange failed");
      }
    } catch (e) {
      if (!isMounted.current || epoch !== flowEpoch.current) return;
      setPhase("error");
      setErrorMsg(`Submit failed: ${e}`);
    }
  };

  const handleClose = () => {
    flowEpoch.current += 1;
    managedRequestEpoch.current += 1;
    initialAuthWindowRef.current?.close();
    initialAuthWindowRef.current = null;
    const sessionId = activeSessionId.current;
    activeSessionId.current = null;
    if (sessionId && !sessionCompleted.current) {
      void api
        .cancelOAuthSession(
          provider.id,
          sessionId,
          initiatingProfileRef.current,
        )
        .catch(() => {});
    }
    onClose();
  };

  const handleBackdrop = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) handleClose();
  };

  const fmtTime = (s: number | null) => {
    if (s === null) return "";
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${String(r).padStart(2, "0")}`;
  };

  const handleCopyDeviceCode = async (code: string) => {
    if (copyResetTimer.current !== null) {
      window.clearTimeout(copyResetTimer.current);
      copyResetTimer.current = null;
    }
    const copied = await copyTextToClipboard(code);
    if (!isMounted.current) return;
    setCopyStatus(copied ? "copied" : "failed");
    copyResetTimer.current = window.setTimeout(() => {
      if (isMounted.current) setCopyStatus("idle");
      copyResetTimer.current = null;
    }, 2000);
  };

  const deviceCode = start?.flow === "device_code" ? start.user_code : "";
  const verificationUrl =
    start?.flow === "device_code" ? start.verification_url : "";

  useEffect(() => {
    let current = true;
    if (!verificationUrl) {
      return () => {
        current = false;
      };
    }

    void QRCode.toDataURL(verificationUrl, {
      errorCorrectionLevel: "M",
      margin: 1,
      width: 208,
    })
      .then((dataUrl) => {
        if (current && isMounted.current) {
          setVerificationQr({ dataUrl, verificationUrl });
        }
      })
      .catch(() => {
        if (current && isMounted.current) setVerificationQr(null);
      });

    return () => {
      current = false;
    };
  }, [verificationUrl]);

  const verificationQrDataUrl =
    verificationQr?.verificationUrl === verificationUrl
      ? verificationQr.dataUrl
      : null;

  const managedInstructions =
    provider.id === "openai-codex"
      ? t.oauth.managedOpenAIInstructions
      : t.oauth.managedXaiInstructions;

  const showManagedAccess = () => {
    managedRequestEpoch.current += 1;
    setManagedRequestError(null);
    setDeviceName(window.location.hostname || "Fabric dashboard");
    setPhase("managed_info");
    void api
      .getSystemStats()
      .then((stats) => {
        if (isMounted.current) setDeviceName(stats.hostname);
      })
      .catch(() => {});
  };

  const requestManagedAccess = async () => {
    if (managedRequestBusy) return;
    const epoch = ++managedRequestEpoch.current;

    // Preserve the click gesture while the durable request is created. The
    // server, not this client, owns the recipient and mail body.
    const handoffWindow = window.open("about:blank", "_blank");
    if (handoffWindow) handoffWindow.opener = null;
    setManagedRequestBusy(true);
    setManagedRequestError(null);
    try {
      const profile = initiatingProfileRef.current;
      const current = await api.getProviderAccount(provider.id, profile);
      const created = await api.createProviderManagedRequest(
        provider.id,
        deviceName || window.location.hostname || "Fabric dashboard",
        current.snapshot.revision,
        profile,
      );
      const request = created.request;
      const handoff = created.snapshot.handoff;
      if (
        !request ||
        !handoff ||
        handoff.channel !== "email" ||
        handoff.delivery_verified !== false ||
        !handoff.uri.startsWith("mailto:")
      ) {
        throw new Error("Fabric returned an invalid managed-access handoff");
      }

      if (!isMounted.current || epoch !== managedRequestEpoch.current) {
        handoffWindow?.close();
        return;
      }
      if (handoffWindow && !handoffWindow.closed) {
        handoffWindow.location.replace(handoff.uri);
      } else {
        window.location.assign(handoff.uri);
      }
      void api
        .recordProviderAccountHandoff(
          provider.id,
          request.request_id,
          created.snapshot.revision,
          profile,
        )
        .catch(() => {});
    } catch (error) {
      handoffWindow?.close();
      if (isMounted.current && epoch === managedRequestEpoch.current) {
        setManagedRequestError(`Could not create request: ${error}`);
      }
    } finally {
      if (isMounted.current && epoch === managedRequestEpoch.current) {
        setManagedRequestBusy(false);
      }
    }
  };

  useEffect(() => {
    const dialog = dialogRef.current;
    const priorFocus = document.activeElement;
    const firstFocusable = dialog?.querySelector<HTMLElement>(
      'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    (firstFocusable || dialog)?.focus();
    return () => {
      if (priorFocus instanceof HTMLElement && priorFocus.isConnected) {
        priorFocus.focus();
      }
    };
  }, []);

  const handleDialogKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      handleClose();
      return;
    }
    if (event.key !== "Tab") return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    );
    if (focusable.length === 0) {
      event.preventDefault();
      dialog.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <div
      ref={dialogRef}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
      onClick={handleBackdrop}
      onKeyDown={handleDialogKeyDown}
      role="dialog"
      aria-modal="true"
      aria-labelledby="oauth-modal-title"
      tabIndex={-1}
    >
      <div
        className={cn(
          themedBody,
          "relative w-full max-w-md border border-border bg-card shadow-2xl",
        )}
      >
        <Button
          ghost
          size="icon"
          onClick={handleClose}
          className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
          aria-label={t.common.close}
        >
          <X />
        </Button>
        <div className="p-6 flex flex-col gap-4">
          <div>
            <H2
              id="oauth-modal-title"
              variant="sm"
              mondwest
              className="tracking-wider uppercase"
            >
              {t.oauth.connect} {provider.name}
            </H2>
            {secondsLeft !== null &&
              phase !== "approved" &&
              phase !== "error" && (
                <p className="text-xs text-muted-foreground mt-1">
                  {t.oauth.sessionExpires.replace(
                    "{time}",
                    fmtTime(secondsLeft),
                  )}
                </p>
              )}
          </div>

          {phase === "choosing_account" && (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">
                {t.oauth.chooseAccountOwner}
              </p>
              <button
                type="button"
                className="group border border-border bg-secondary/20 p-4 text-left transition-colors hover:bg-secondary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => void beginLogin(true)}
              >
                <span className="block text-sm font-medium text-foreground">
                  {t.oauth.personalAccount}
                </span>
                <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                  {t.oauth.personalAccountDescription}
                </span>
              </button>
              <button
                type="button"
                className="group border border-border bg-secondary/20 p-4 text-left transition-colors hover:bg-secondary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={showManagedAccess}
              >
                <span className="block text-sm font-medium text-foreground">
                  {t.oauth.managedAccount}
                </span>
                <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                  {t.oauth.managedAccountDescription}
                </span>
              </button>
            </div>
          )}

          {phase === "managed_info" && (
            <div className="flex flex-col gap-4">
              <div className="border border-border bg-secondary/20 p-4">
                <p className="text-sm font-medium text-foreground">
                  {t.oauth.managedUnavailableTitle}
                </p>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">
                  {managedInstructions}
                </p>
              </div>
              {managedRequestError && (
                <p className="border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
                  {managedRequestError}
                </p>
              )}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Button
                  ghost
                  size="sm"
                  disabled={managedRequestBusy}
                  onClick={() => {
                    managedRequestEpoch.current += 1;
                    setPhase("choosing_account");
                  }}
                >
                  {t.oauth.backToAccountChoice}
                </Button>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    outlined
                    size="sm"
                    prefix={<ExternalLink />}
                    onClick={() =>
                      window.open(
                        managedProviderDocsUrl(provider.id),
                        "_blank",
                        "noopener,noreferrer",
                      )
                    }
                  >
                    {t.oauth.continueToProvider}
                  </Button>
                  <Button
                    size="sm"
                    disabled={managedRequestBusy}
                    onClick={() => void requestManagedAccess()}
                  >
                    {managedRequestBusy
                      ? t.oauth.initiatingLogin
                      : t.oauth.emailFabric}
                  </Button>
                </div>
              </div>
            </div>
          )}

          {phase === "starting" && (
            <div className="flex items-center gap-3 py-6 text-sm text-muted-foreground">
              <Spinner />
              {t.oauth.initiatingLogin}
            </div>
          )}

          {start?.flow === "pkce" && phase === "awaiting_user" && (
            <>
              <ol className="text-sm space-y-2 list-decimal list-inside text-muted-foreground">
                <li>{t.oauth.pkceStep1}</li>
                <li>{t.oauth.pkceStep2}</li>
                <li>{t.oauth.pkceStep3}</li>
              </ol>
              <div className="flex flex-col gap-2">
                <Input
                  value={pkceCode}
                  onChange={(e) => setPkceCode(e.target.value)}
                  placeholder={t.oauth.pasteCode}
                  onKeyDown={(e) => e.key === "Enter" && handleSubmitPkceCode()}
                  autoFocus
                />
                <div className="flex items-center gap-2 justify-between">
                  <a
                    href={
                      (start as Extract<OAuthStartResponse, { flow: "pkce" }>)
                        .auth_url
                    }
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
                  >
                    <ExternalLink className="h-3 w-3" />
                    {t.oauth.reOpenAuth}
                  </a>
                  <Button
                    onClick={handleSubmitPkceCode}
                    disabled={!pkceCode.trim()}
                  >
                    {t.oauth.submitCode}
                  </Button>
                </div>
              </div>
            </>
          )}

          {phase === "submitting" && (
            <div className="flex items-center gap-3 py-6 text-sm text-muted-foreground">
              <Spinner />
              {t.oauth.exchangingCode}
            </div>
          )}

          {start?.flow === "device_code" && phase === "polling" && (
            <>
              {verificationQrDataUrl && (
                <div className="flex flex-col items-center gap-2">
                  <img
                    alt={`Scan QR code to open ${provider.name} verification`}
                    className="size-52 border border-border bg-white p-2"
                    height={208}
                    src={verificationQrDataUrl}
                    width={208}
                  />
                  <span className="text-xs text-muted-foreground">
                    Scan with your phone
                  </span>
                </div>
              )}
              <p className="text-sm text-muted-foreground">
                {t.oauth.enterCodePrompt}
              </p>
              <div className="flex items-center justify-between gap-2 border border-border bg-secondary/30 p-4">
                <code className="font-mono-ui text-2xl tracking-widest text-foreground">
                  {deviceCode}
                </code>
                <Button
                  size="sm"
                  outlined
                  className="shrink-0 uppercase"
                  onClick={() => void handleCopyDeviceCode(deviceCode)}
                  prefix={
                    copyStatus === "copied" ? (
                      <Check className="h-4 w-4" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )
                  }
                  aria-label={t.oauth.copyCode}
                >
                  {copyStatus === "copied" ? t.oauth.copied : t.oauth.copyCode}
                </Button>
              </div>
              {copyStatus === "failed" && (
                <p className="text-xs text-destructive">{t.oauth.copyFailed}</p>
              )}
              <p className="border border-warning/30 bg-warning/10 p-3 text-xs leading-5 text-foreground">
                {t.oauth.deviceCodeSecurityWarning}
              </p>
              <a
                href={verificationUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
              >
                <ExternalLink className="h-3 w-3" />
                {t.oauth.reOpenVerification}
              </a>
              <div className="flex items-center gap-2 text-xs text-muted-foreground border-t border-border pt-3">
                <Spinner className="text-xs" />
                {t.oauth.waitingAuth}
              </div>
            </>
          )}

          {phase === "approved" && (
            <div className="flex items-center gap-3 py-6 text-sm text-success">
              <Check className="h-5 w-5" />
              {t.oauth.connectedClosing}
            </div>
          )}

          {phase === "error" && (
            <>
              <div className="border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                {errorMsg || t.oauth.loginFailed}
              </div>
              <div className="flex justify-end gap-2">
                <Button outlined onClick={handleClose}>
                  {t.common.close}
                </Button>
                <Button
                  onClick={() => {
                    void beginLogin(true, takeoverAvailable);
                  }}
                >
                  {takeoverAvailable ? "Take over sign-in" : t.common.retry}
                </Button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
