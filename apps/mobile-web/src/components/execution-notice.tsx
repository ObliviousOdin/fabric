import { GATEWAY_CLIENT_CONTRACT_VERSION } from "@fabric/shared";
import {
  IconAlertCircle,
  IconAlertTriangle,
  IconCloudCheck,
  IconLoader2,
  IconRefresh,
} from "@tabler/icons-react";

import type { MobileGatewayCapabilityState } from "../gateway/capabilities";

interface ExecutionNoticeProps {
  onRetry: () => void;
  state: MobileGatewayCapabilityState;
}

export function ExecutionNotice({ onRetry, state }: ExecutionNoticeProps) {
  if (!state) {
    return null;
  }

  if (state.kind === "negotiating") {
    return (
      <section
        className="execution-notice negotiating"
        role="status"
        aria-live="polite"
      >
        <IconLoader2 className="notice-spinner" size={17} />
        <div>
          <strong>Checking gateway compatibility</strong>
          <p>Session controls unlock after this connection is verified.</p>
        </div>
      </section>
    );
  }

  if (state.kind === "verified") {
    return (
      <section className="execution-notice verified" role="status">
        <IconCloudCheck size={17} />
        <div>
          <strong>Runs on this gateway</strong>
          <p>
            Active work survives a phone disconnect. The gateway host must
            remain online; a gateway restart interrupts non-durable work.
          </p>
        </div>
        <span className="execution-version">
          v{state.capabilities.server.version}
        </span>
      </section>
    );
  }

  if (state.kind === "legacy") {
    return (
      <section className="execution-notice warning" role="status">
        <IconAlertTriangle size={17} />
        <div>
          <strong>Gateway compatibility unverified</strong>
          <p>
            Update Fabric for verified mobile controls. Existing mobile chat
            remains available.
          </p>
        </div>
        <button type="button" onClick={onRetry}>
          <IconRefresh size={14} /> Retry
        </button>
      </section>
    );
  }

  if (state.kind === "incompatible") {
    return (
      <section className="execution-notice blocking" role="alert">
        <IconAlertTriangle size={17} />
        <div>
          <strong>Fabric mobile update required</strong>
          <p>
            This gateway requires contract {state.minimum}; this app supports{" "}
            {GATEWAY_CLIENT_CONTRACT_VERSION}. Session changes are blocked.
          </p>
        </div>
        <button type="button" onClick={onRetry}>
          <IconRefresh size={14} /> Retry after update
        </button>
      </section>
    );
  }

  return (
    <section className="execution-notice blocking" role="alert">
      <IconAlertCircle size={17} />
      <div>
        <strong>Gateway contract invalid</strong>
        <p>{state.message} Session changes are blocked.</p>
      </div>
      <button type="button" onClick={onRetry}>
        <IconRefresh size={14} /> Reconnect
      </button>
    </section>
  );
}
