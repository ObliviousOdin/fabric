/// <reference types="vite/client" />

interface Window {
  __FABRIC_AUTH_REQUIRED__?: boolean;
  __FABRIC_BASE_PATH__?: string;
  // Compatibility with gateways that predate the Fabric public globals.
  __HERMES_AUTH_REQUIRED__?: boolean;
  __HERMES_BASE_PATH__?: string;
}
