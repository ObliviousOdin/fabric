/** Transport-safe provider-account ownership DTOs shared by every client. */

export type ProviderAccountId = "openai-codex" | "xai-oauth";

export type ProviderAccountOwnership =
  | "personal"
  | "fabric_managed"
  | "unselected";

export type ProviderAccountRequestStatus =
  | "awaiting"
  | "cancelled"
  | "expired"
  | "rejected"
  | "requested";

export interface ProviderAccountRequest {
  decision_at: null | string;
  decision_reason: null | string;
  decision_source: null | string;
  device_label: string;
  expires_at: string;
  handoff_state: "launch_attempted_unverified" | "offered";
  notification_handoff_at: null | string;
  provider_id: ProviderAccountId;
  request_id: string;
  requested_at: string;
  status: ProviderAccountRequestStatus;
  updated_at: string;
}

export interface ProviderAccountHandoff {
  channel: "email";
  delivery_verified: false;
  uri: string;
}

export interface ProviderAccountSnapshot {
  active_request: null | ProviderAccountRequest;
  active_request_id: null | string;
  desired_ownership: ProviderAccountOwnership;
  handoff: null | ProviderAccountHandoff;
  ownership_epoch: number;
  provider_id: ProviderAccountId;
  pruned_terminal_count: number;
  requests: ProviderAccountRequest[];
  revision: number;
}

export interface ProviderAccountResult {
  created: boolean | null;
  request: null | ProviderAccountRequest;
  snapshot: ProviderAccountSnapshot;
}

export interface ProviderAccountsResult {
  accounts: ProviderAccountSnapshot[];
}

export interface ProviderAccountRpcErrorData {
  code:
    | "commit_uncertain"
    | "illegal_transition"
    | "invalid_input"
    | "invalid_provider"
    | "invalid_state"
    | "io_unavailable"
    | "lock_timeout"
    | "newer_schema"
    | "not_authorized"
    | "not_found"
    | "oauth_in_progress"
    | "path_redirect"
    | "runtime_mode_unavailable"
    | "stale_revision";
  retryable: boolean;
}
