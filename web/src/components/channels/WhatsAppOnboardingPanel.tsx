import { useCallback, useEffect, useMemo, useState } from "react";
import { ExternalLink, QrCode, Save } from "lucide-react";
import * as QRCode from "qrcode";
import { Badge } from "@/components/fabric/Badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { api } from "@/lib/api";
import type {
  MessagingPlatform,
  WhatsAppOnboardingStartResponse,
} from "@/lib/api";
import type { GatewayRestartControls } from "@/hooks/useGatewayRestart";
import {
  formatExpiry,
  isTerminalWhatsAppOnboardingError,
  normalizeWhatsAppMode,
} from "./onboarding";

export interface WhatsAppOnboardingPanelProps {
  platform: MessagingPlatform;
  onChanged: () => Promise<void>;
  /** The page's shared gateway-restart lifecycle (CN3) — replaces the
   *  panel's hand-rolled `watchRestartOutcome` copy. */
  restart: Pick<GatewayRestartControls, "markRestartNeeded" | "noteRestartStarted">;
  showToast: (message: string, type: "success" | "error") => void;
}

/**
 * WhatsApp QR onboarding (H4 — flow frozen, N23): mode bot/self-chat,
 * allowed-numbers input, `installing/starting/waiting` copy states, QR
 * refresh on payload change (width 240/margin 3), 1.5–2 s poll, expiry/410
 * reset, linked-account panel, apply → restart. The only change from the
 * shipped panel: restart watching goes through `useGatewayRestart`
 * (`restart.noteRestartStarted` schedules the 4 s reload and watches the
 * `gateway-restart` action outcome).
 */
export function WhatsAppOnboardingPanel({
  platform,
  onChanged,
  restart,
  showToast,
}: WhatsAppOnboardingPanelProps) {
  const configuredMode = useMemo(
    () => normalizeWhatsAppMode(platform.whatsapp_setup?.mode),
    [platform.whatsapp_setup?.mode],
  );
  const [setup, setSetup] = useState<WhatsAppOnboardingStartResponse | null>(
    null,
  );
  const [qrDataUrl, setQrDataUrl] = useState("");
  const [phase, setPhase] = useState<
    "idle" | "starting" | "waiting" | "connected" | "applying"
  >("idle");
  const [mode, setMode] = useState<"bot" | "self-chat">(
    configuredMode ?? "bot",
  );
  const [allowedUsers, setAllowedUsers] = useState("");
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!setup && phase === "idle" && configuredMode) {
      // Frozen shipped behavior (N23): whenever the panel sits idle with no
      // active setup, the mode picker re-syncs to the saved configuration.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMode(configuredMode);
    }
  }, [configuredMode, phase, setup]);

  const updateQr = useCallback(async (payload?: string | null) => {
    if (!payload) return;
    const dataUrl = await QRCode.toDataURL(payload, {
      errorCorrectionLevel: "M",
      margin: 3,
      width: 240,
    });
    setQrDataUrl(dataUrl);
  }, []);

  useEffect(() => {
    if (!setup || phase !== "waiting") return;
    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const status = await api.getWhatsAppOnboardingStatus(setup.pairing_id);
        if (cancelled) return;
        setSetup(status);
        if (status.qr_payload && status.qr_payload !== setup.qr_payload) {
          await updateQr(status.qr_payload);
        }
        if (cancelled) return;
        if (status.status === "connected") {
          setPhase("connected");
          setError("");
          return;
        }
        if (status.status === "error") {
          setError(status.error || "WhatsApp setup failed.");
          setSetup(null);
          setQrDataUrl("");
          setPhase("idle");
          return;
        }
        setError("");
        timeout = setTimeout(poll, 1500);
      } catch (pollError) {
        if (cancelled) return;
        const expiresAt = Date.parse(setup.expires_at);
        const expired =
          Number.isFinite(expiresAt) && Date.now() >= expiresAt;
        if (isTerminalWhatsAppOnboardingError(pollError) || expired) {
          setSetup(null);
          setQrDataUrl("");
          setPhase("idle");
          setError("WhatsApp QR setup expired. Start a new QR setup to try again.");
          return;
        }
        setError(`Still waiting for WhatsApp. Retrying after: ${pollError}`);
        timeout = setTimeout(poll, 2000);
      }
    };

    timeout = setTimeout(poll, 1000);
    return () => {
      cancelled = true;
      if (timeout) clearTimeout(timeout);
    };
  }, [phase, setup, updateQr]);

  useEffect(() => {
    if (!setup) return;
    const timer = setInterval(() => setTick((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, [setup]);

  const resetSetup = () => {
    setSetup(null);
    setQrDataUrl("");
    setPhase("idle");
    setError("");
  };

  const start = async () => {
    setPhase("starting");
    setError("");
    setQrDataUrl("");
    try {
      const res = await api.startWhatsAppOnboarding({
        mode,
        allowed_users: allowedUsers,
      });
      setSetup(res);
      if (res.qr_payload) {
        await updateQr(res.qr_payload);
      }
      if (res.status === "error") {
        setError(res.error || "WhatsApp setup failed.");
        setSetup(null);
        setPhase("idle");
      } else {
        setPhase(res.status === "connected" ? "connected" : "waiting");
      }
    } catch (startError) {
      setPhase("idle");
      setError(String(startError));
    }
  };

  const cancel = async () => {
    if (setup) {
      try {
        await api.cancelWhatsAppOnboarding(setup.pairing_id);
      } catch {
        /* local cleanup still wins */
      }
    }
    resetSetup();
  };

  const apply = async () => {
    if (!setup) return;
    setPhase("applying");
    setError("");
    try {
      const result = await api.applyWhatsAppOnboarding(setup.pairing_id, {
        mode,
        allowed_users: allowedUsers,
      });
      resetSetup();
      if (result.restart_started) {
        // The server already spawned `gateway-restart`: the hook schedules
        // the delayed reload and watches the outcome (CN3/R25 — the exit
        // semantics live in `lib/gateway-restart.ts`).
        showToast("WhatsApp saved; gateway restarting…", "success");
        restart.noteRestartStarted("WhatsApp saved; gateway restarting…");
      } else {
        restart.markRestartNeeded();
        const detail = result.restart_error ? `: ${result.restart_error}` : "";
        showToast(`WhatsApp saved; gateway restart failed${detail}`, "error");
      }
      await onChanged();
    } catch (applyError) {
      setPhase("connected");
      setError(String(applyError));
    }
  };

  const expiresIn = useMemo(
    () => (setup ? formatExpiry(setup.expires_at) : ""),
    // tick keeps the memo fresh without recalculating on every render branch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setup, tick],
  );
  const setupStatusLabel =
    setup?.status === "installing"
      ? "preparing"
      : setup?.status === "starting"
        ? "starting"
        : "waiting";
  const setupHelp =
    phase === "connected" || phase === "applying"
      ? "WhatsApp is linked but Fabric is not listening yet. Save and restart the gateway to finish setup."
      : setup?.status === "installing"
        ? "Preparing the WhatsApp bridge. The QR code will appear here when it is ready."
        : setup?.status === "starting"
          ? "Starting the WhatsApp pairing bridge. The QR code will appear here when it is ready."
          : "Open WhatsApp on your phone, then go to Linked Devices and scan from there. This QR is not a browser URL.";
  const linkedAccountLabel = setup?.account_phone
    ? `+${setup.account_phone}`
    : setup?.account_name || setup?.account_id || "";
  const linkedAccountDetail =
    setup?.account_phone || setup?.account_id
      ? "This is the WhatsApp account Fabric is now logged into."
      : "Fabric is logged into the WhatsApp account that scanned the QR code.";
  const linkedAccountChatUrl = setup?.account_phone
    ? `https://wa.me/${setup.account_phone}`
    : "";
  const messageInstruction =
    mode === "self-chat"
      ? "After the restart, open Message Yourself on the linked account and send Fabric a message."
      : "After the restart, start a chat from another WhatsApp account with the linked account and send Fabric a message.";
  const hasSavedAllowedUsers = Boolean(platform.whatsapp_setup?.allowed_users_set);
  const pairingInstruction =
    mode === "self-chat" && !allowedUsers.trim()
      ? hasSavedAllowedUsers
        ? "Fabric will keep the saved WhatsApp allowlist."
        : "Self-chat mode will allow the linked account automatically when you save."
      : !allowedUsers.trim() && hasSavedAllowedUsers
        ? "Fabric will keep the saved WhatsApp allowlist."
        : "If no allowed numbers were entered, Fabric replies with a pairing code. Approve it from the dashboard Pairing page.";

  return (
    <div className="rounded-sm border border-border bg-background/35 p-4">
      <div className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            className="uppercase"
            onClick={() => void start()}
            disabled={phase === "starting" || phase === "waiting" || phase === "applying"}
            prefix={phase === "starting" ? <Spinner /> : <QrCode className="h-4 w-4" />}
          >
            {phase === "starting" ? "Starting…" : "Pair with QR"}
          </Button>
          {platform.configured && (
            <span className="text-xs text-muted-foreground">
              Existing WhatsApp settings are configured.
            </span>
          )}
        </div>

        <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
          <div className="grid gap-1.5">
            <span className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Mode
            </span>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                outlined={mode !== "bot"}
                onClick={() => setMode("bot")}
                disabled={phase === "waiting" || phase === "applying"}
              >
                Bot
              </Button>
              <Button
                size="sm"
                outlined={mode !== "self-chat"}
                onClick={() => setMode("self-chat")}
                disabled={phase === "waiting" || phase === "applying"}
              >
                Self-chat
              </Button>
            </div>
          </div>
          <div className="grid min-w-0 flex-1 gap-1.5">
            <Label htmlFor="whatsapp-allowed-users">Allowed WhatsApp numbers</Label>
            <Input
              id="whatsapp-allowed-users"
              value={allowedUsers}
              onChange={(event) => setAllowedUsers(event.target.value)}
              disabled={phase === "waiting" || phase === "applying"}
              placeholder="15551234567,15557654321"
            />
          </div>
        </div>

        {error && (
          <div className="border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        {setup && (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
            <div className="grid gap-3">
              <div className="flex flex-wrap items-center gap-2">
                {phase === "connected" || phase === "applying" ? (
                  <Badge tone="success">Connected</Badge>
                ) : (
                  <Badge tone="warning">{setupStatusLabel}</Badge>
                )}
                <Badge tone={expiresIn === "expired" ? "destructive" : "outline"}>
                  {expiresIn}
                </Badge>
              </div>

              <div className="text-sm text-muted-foreground">{setupHelp}</div>

              {phase === "waiting" && (
                <div className="text-xs text-muted-foreground">
                  After saving, unknown DMs use Fabric pairing codes unless their
                  number is already allowed.
                </div>
              )}

              {(phase === "connected" || phase === "applying") && (
                <div className="grid gap-3">
                  <div className="border border-border bg-background/45 p-3 text-sm">
                    <div className="font-medium">
                      {linkedAccountLabel
                        ? `Linked as ${linkedAccountLabel}`
                        : "WhatsApp device linked"}
                    </div>
                    <div className="mt-1 text-muted-foreground">{linkedAccountDetail}</div>
                    <ol className="mt-3 list-decimal space-y-1 pl-5 text-muted-foreground">
                      <li>Save and restart the gateway.</li>
                      <li>{messageInstruction}</li>
                      <li>{pairingInstruction}</li>
                    </ol>
                    {linkedAccountChatUrl && (
                      <a
                        className="mt-3 inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline"
                        href={linkedAccountChatUrl}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open chat link
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      className="uppercase"
                      onClick={() => void apply()}
                      disabled={phase === "applying"}
                      prefix={phase === "applying" ? <Spinner /> : <Save className="h-4 w-4" />}
                    >
                      {phase === "applying" ? "Saving…" : "Save and restart"}
                    </Button>
                    <Button size="sm" ghost onClick={() => void cancel()}>
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>

            <div className="flex flex-col items-center justify-center gap-3">
              {qrDataUrl ? (
                <img
                  src={qrDataUrl}
                  alt="WhatsApp setup QR code"
                  className="h-60 w-60 bg-white p-2"
                />
              ) : phase === "connected" || phase === "applying" ? (
                <div className="flex h-60 w-60 flex-col items-center justify-center gap-2 border border-border bg-background/50 p-4 text-center">
                  <Badge tone="success">Linked</Badge>
                  <div className="text-sm text-muted-foreground">
                    {linkedAccountLabel || "Existing WhatsApp session found"}
                  </div>
                </div>
              ) : (
                <div className="flex h-60 w-60 flex-col items-center justify-center gap-3 border border-border bg-background/50 p-4 text-center">
                  <Spinner className="text-2xl" />
                  <div className="text-xs text-muted-foreground">
                    Waiting for WhatsApp to provide a QR code…
                  </div>
                </div>
              )}
              {phase === "waiting" && (
                <span className="text-center text-xs text-muted-foreground">
                  Scan with WhatsApp Linked Devices, not the camera app.
                </span>
              )}
              <Button size="sm" ghost onClick={() => void cancel()}>
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
