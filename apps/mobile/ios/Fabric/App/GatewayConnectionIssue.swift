import Foundation

/// Converts transport/auth failures into concrete recovery copy without
/// exposing server response bodies, credentials, tickets, or raw socket
/// diagnostics in the UI. The underlying error remains deliberately outside
/// observable app state.
enum GatewayConnectionIssue {
    static func message(for error: Error, gateway: SavedGateway) -> String {
        let host = gateway.baseURL.host() ?? gateway.label

        if let transportError = error as? GatewayTokenTransportError {
            return transportError.localizedDescription
        }

        if let urlError = error as? URLError {
            switch urlError.code {
            case .notConnectedToInternet, .dataNotAllowed:
                return "This iPhone is offline. Reconnect to Wi-Fi or your tailnet, then try again."
            case .cannotFindHost, .dnsLookupFailed:
                return "Couldn't find \(host). Check the server address and your DNS or tailnet connection."
            case .cannotConnectToHost, .networkConnectionLost, .timedOut,
                 .internationalRoamingOff, .callIsActive:
                return "Couldn't reach \(host). Keep Fabric running on the gateway and confirm this iPhone can reach the same network or tailnet."
            case .secureConnectionFailed, .serverCertificateHasBadDate,
                 .serverCertificateUntrusted, .serverCertificateHasUnknownRoot,
                 .serverCertificateNotYetValid, .clientCertificateRejected,
                 .clientCertificateRequired, .appTransportSecurityRequiresSecureConnection:
                return "The secure connection to \(host) couldn't be verified. Use a trusted HTTPS endpoint, then try again."
            default:
                return genericReachabilityMessage(host: host)
            }
        }

        if let apiError = error as? GatewayAPIError {
            switch apiError {
            case .badURL:
                return "Enter a complete http:// or https:// Fabric server address."
            case .httpStatus(let code, _):
                switch code {
                case 401, 403:
                    return "Sign-in failed or expired for \(gateway.label). Sign in again to reconnect."
                case 404:
                    return "Fabric isn't available at \(host). Check the address and that `fabric serve` is running."
                case 429:
                    return "Too many sign-in attempts. Wait a moment, then try again."
                case 500...599:
                    return "The Fabric gateway at \(host) returned an error. Check the gateway, then retry."
                default:
                    return genericReachabilityMessage(host: host)
                }
            }
        }

        if let clientError = error as? GatewayClientError {
            switch clientError {
            case .notConnected, .connectFailed, .socketClosed, .requestTimedOut:
                return genericReachabilityMessage(host: host)
            case .rpc(let message, let code, _):
                if code == -32_601 {
                    return "Update the Fabric gateway before connecting this version of Fabric Mobile."
                }
                let folded = message.lowercased()
                if folded.contains("sign in") || folded.contains("credential")
                    || folded.contains("unauthorized") || folded.contains("forbidden") {
                    return "Sign-in failed or expired for \(gateway.label). Sign in again to reconnect."
                }
                if folded.contains("requires mobile contract") || folded.contains("update fabric mobile") {
                    return "This gateway requires a newer Fabric Mobile contract. Update Fabric Mobile before reconnecting."
                }
                return genericReachabilityMessage(host: host)
            }
        }

        if error is GatewayStoreError {
            return GatewayStoreError.credentialStorageUnavailable.localizedDescription
        }

        return genericReachabilityMessage(host: host)
    }

    static func requiresSignIn(_ error: Error) -> Bool {
        if let apiError = error as? GatewayAPIError,
           case .httpStatus(let code, _) = apiError {
            return code == 401 || code == 403
        }
        guard let clientError = error as? GatewayClientError,
              case .rpc(let message, let code, _) = clientError else {
            return false
        }
        if code == 401 || code == 403 { return true }
        let folded = message.lowercased()
        return folded.contains("sign in") || folded.contains("unauthorized")
            || folded.contains("forbidden")
    }

    private static func genericReachabilityMessage(host: String) -> String {
        "Couldn't connect to \(host). Confirm the gateway is online and reachable, then try again."
    }
}
