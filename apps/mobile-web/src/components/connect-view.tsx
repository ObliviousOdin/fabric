import {
  fetchRemoteAuthProviders,
  fetchRemoteGatewayStatus,
  loginRemoteGatewayWithPassword,
  normalizeRemoteGatewayBaseUrl,
  type RemoteAuthProvider,
  type RemoteGatewayConnection,
} from "@fabric/shared";
import { IconArrowRight, IconKey, IconLock, IconServer2 } from "@tabler/icons-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

interface ConnectViewProps {
  connecting: boolean;
  error: null | string;
  initialConnection: RemoteGatewayConnection | null;
  onConnect: (connection: RemoteGatewayConnection) => Promise<void>;
}

type AuthTab = "cookie" | "token";

function injectedAuthRequired(): boolean {
  return window.__FABRIC_AUTH_REQUIRED__ ?? window.__HERMES_AUTH_REQUIRED__ ?? false;
}

export function ConnectView({
  connecting,
  error,
  initialConnection,
  onConnect,
}: ConnectViewProps) {
  const [authTab, setAuthTab] = useState<AuthTab>(
    initialConnection?.authMode ?? (injectedAuthRequired() ? "cookie" : "token"),
  );
  const [baseUrl] = useState(() =>
    normalizeRemoteGatewayBaseUrl(initialConnection?.baseUrl ?? ""),
  );
  const [localError, setLocalError] = useState<null | string>(null);
  const [otp, setOtp] = useState("");
  const [password, setPassword] = useState("");
  const [probing, setProbing] = useState(false);
  const [providers, setProviders] = useState<RemoteAuthProvider[]>([]);
  const [selectedProvider, setSelectedProvider] = useState("");
  const [token, setToken] = useState(initialConnection?.token ?? "");
  const [username, setUsername] = useState("");

  const selected = useMemo(
    () => providers.find((provider) => provider.name === selectedProvider),
    [providers, selectedProvider],
  );

  useEffect(() => {
    const controller = new AbortController();
    const probe = async () => {
      setProbing(true);
      setLocalError(null);
      try {
        const normalized = normalizeRemoteGatewayBaseUrl(baseUrl);
        const status = await fetchRemoteGatewayStatus(normalized, {
          signal: controller.signal,
        });
        setAuthTab(status.auth_required ? "cookie" : "token");
        if (status.auth_required) {
          const discovered = await fetchRemoteAuthProviders(normalized, {
            signal: controller.signal,
          });
          setProviders(discovered);
          setSelectedProvider(
            discovered.find((provider) => provider.supports_password)?.name ||
              discovered[0]?.name ||
              "",
          );
        } else {
          setProviders([]);
        }
      } catch (probeError) {
        if (!(probeError instanceof DOMException && probeError.name === "AbortError")) {
          setLocalError(
            probeError instanceof Error
              ? probeError.message
              : "Could not reach this gateway.",
          );
        }
      } finally {
        setProbing(false);
      }
    };

    const timer = window.setTimeout(() => void probe(), 350);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [baseUrl]);

  const connectToken = async (event: FormEvent) => {
    event.preventDefault();
    setLocalError(null);
    try {
      const normalized = normalizeRemoteGatewayBaseUrl(baseUrl);
      await onConnect({ authMode: "token", baseUrl: normalized, token });
    } catch (connectError) {
      setLocalError(
        connectError instanceof Error ? connectError.message : String(connectError),
      );
    }
  };

  const connectCookie = async (event: FormEvent) => {
    event.preventDefault();
    setLocalError(null);
    try {
      const normalized = normalizeRemoteGatewayBaseUrl(baseUrl);
      if (selected?.supports_password) {
        await loginRemoteGatewayWithPassword(normalized, {
          otp,
          password,
          provider: selected.name,
          username,
        });
      }
      await onConnect({ authMode: "cookie", baseUrl: normalized });
      setPassword("");
      setOtp("");
    } catch (connectError) {
      setLocalError(
        connectError instanceof Error ? connectError.message : String(connectError),
      );
    }
  };

  const startOAuth = () => {
    if (!selectedProvider) {
      return;
    }
    const normalized = normalizeRemoteGatewayBaseUrl(baseUrl);
    const login = new URL("/auth/login", normalized);
    login.searchParams.set("provider", selectedProvider);
    login.searchParams.set("next", window.location.pathname);
    window.location.assign(login);
  };

  const visibleError = localError || error;

  return (
    <main className="connect-page">
      <section className="connect-intro" aria-labelledby="connect-heading">
        <div className="brand-lockup">
          <img src={`${import.meta.env.BASE_URL}fabric-mark-192.png`} alt="" />
          <span>Fabric</span>
        </div>
        <p className="eyebrow">Remote client preview</p>
        <h1 id="connect-heading">Your agent, without the desk.</h1>
        <p className="connect-lede">
          Resume the same Fabric sessions, watch tools run, and answer the prompts
          that keep work moving.
        </p>
        <dl className="connect-facts">
          <div>
            <dt>Authoritative history</dt>
            <dd>Every foreground return rehydrates from the gateway.</dd>
          </div>
          <div>
            <dt>Credentials stay transient</dt>
            <dd>Passwords and tokens are held in memory, never browser storage.</dd>
          </div>
        </dl>
      </section>

      <section className="connect-panel" aria-label="Gateway connection">
        <div className="connect-panel-heading">
          <IconServer2 size={20} stroke={1.7} />
          <div>
            <h2>Connect to Fabric</h2>
            <p>{probing ? "Checking gateway…" : "Use the gateway that owns your sessions."}</p>
          </div>
        </div>

        <div className="gateway-origin" aria-label="Gateway origin">
          <span>Gateway origin</span>
          <code>{baseUrl}</code>
        </div>

        <div className="auth-tabs" role="tablist" aria-label="Authentication method">
          <button
            className={authTab === "cookie" ? "active" : ""}
            type="button"
            role="tab"
            aria-selected={authTab === "cookie"}
            onClick={() => setAuthTab("cookie")}
          >
            <IconLock size={16} /> Sign in
          </button>
          <button
            className={authTab === "token" ? "active" : ""}
            type="button"
            role="tab"
            aria-selected={authTab === "token"}
            onClick={() => setAuthTab("token")}
          >
            <IconKey size={16} /> Session token
          </button>
        </div>

        {authTab === "token" ? (
          <form className="connect-form" onSubmit={connectToken}>
            <label className="field-label" htmlFor="session-token">
              Session token
            </label>
            <input
              id="session-token"
              className="text-input"
              type="password"
              autoComplete="off"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="Paste the gateway session token"
              required
            />
            <button className="primary-button" disabled={connecting || probing} type="submit">
              {connecting ? "Connecting…" : "Open Fabric"}
              {!connecting && <IconArrowRight size={18} />}
            </button>
          </form>
        ) : (
          <form className="connect-form" onSubmit={connectCookie}>
            {providers.length > 1 && (
              <>
                <label className="field-label" htmlFor="auth-provider">
                  Provider
                </label>
                <select
                  id="auth-provider"
                  className="text-input"
                  value={selectedProvider}
                  onChange={(event) => setSelectedProvider(event.target.value)}
                >
                  {providers.map((provider) => (
                    <option key={provider.name} value={provider.name}>
                      {provider.display_name || provider.name}
                    </option>
                  ))}
                </select>
              </>
            )}
            {selected?.supports_password ? (
              <>
                <label className="field-label" htmlFor="username">
                  Username
                </label>
                <input
                  id="username"
                  className="text-input"
                  autoCapitalize="none"
                  autoComplete="username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  required
                />
                <label className="field-label" htmlFor="password">
                  Password
                </label>
                <input
                  id="password"
                  className="text-input"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
                {selected.requires_totp && (
                  <>
                    <label className="field-label" htmlFor="otp">
                      Verification code
                    </label>
                    <input
                      id="otp"
                      className="text-input otp-input"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      value={otp}
                      onChange={(event) => setOtp(event.target.value)}
                      required
                    />
                  </>
                )}
                <button className="primary-button" disabled={connecting || probing} type="submit">
                  {connecting ? "Signing in…" : "Sign in and connect"}
                  {!connecting && <IconArrowRight size={18} />}
                </button>
              </>
            ) : selected ? (
              <button className="primary-button" type="button" onClick={startOAuth}>
                Continue with {selected.display_name || selected.name}
                <IconArrowRight size={18} />
              </button>
            ) : (
              <button className="primary-button" disabled={connecting || probing} type="submit">
                {connecting ? "Connecting…" : "Use existing session"}
                {!connecting && <IconArrowRight size={18} />}
              </button>
            )}
          </form>
        )}

        {visibleError && <p className="form-error" role="alert">{visibleError}</p>}
        <p className="connection-note">
          Browser builds should be served from the gateway origin. The development
          server uses a locked local proxy; production does not relax Fabric’s origin checks.
        </p>
      </section>
    </main>
  );
}
