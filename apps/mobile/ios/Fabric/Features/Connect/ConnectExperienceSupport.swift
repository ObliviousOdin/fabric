import AVFoundation
import SwiftUI

/// The states the Connect UI can claim from data it already owns. These are
/// intentionally about saved credentials, not network reachability: the app
/// does not call a server "online" until it has actually connected.
enum ConnectGatewayAvailability: Equatable {
    case ready
    case savedSignIn
    case credentialRequired
    case secureTransportRequired

    init(
        authMode: GatewayAuthMode,
        canAutoConnect: Bool,
        allowsTokenCredential: Bool = true,
        hasStoredPassword: Bool = false
    ) {
        switch authMode {
        case .gated where hasStoredPassword:
            self = .ready
        case .gated:
            self = .savedSignIn
        case .token where !allowsTokenCredential:
            self = .secureTransportRequired
        case .token where canAutoConnect:
            self = .ready
        case .token:
            self = .credentialRequired
        }
    }

    var label: String {
        switch self {
        case .ready: "Ready to connect"
        case .savedSignIn: "Saved sign-in"
        case .credentialRequired: "Credential required"
        case .secureTransportRequired: "Secure address required"
        }
    }

    var detail: String {
        switch self {
        case .ready: "A protected credential is saved on this iPhone."
        case .savedSignIn: "Fabric may ask you to sign in when you connect."
        case .credentialRequired: "Scan a new pairing code to restore access."
        case .secureTransportRequired: "Re-pair with a trusted HTTPS or Tailscale Serve address."
        }
    }

    var systemImage: String {
        switch self {
        case .ready: "checkmark.circle.fill"
        case .savedSignIn: "person.crop.circle.badge.checkmark"
        case .credentialRequired: "exclamationmark.circle.fill"
        case .secureTransportRequired: "lock.trianglebadge.exclamationmark.fill"
        }
    }
}

enum ConnectCameraPermissionState: Equatable {
    case notDetermined
    case authorized
    case denied
    case restricted
    case unavailable

    init(_ status: AVAuthorizationStatus) {
        switch status {
        case .notDetermined: self = .notDetermined
        case .authorized: self = .authorized
        case .denied: self = .denied
        case .restricted: self = .restricted
        @unknown default: self = .unavailable
        }
    }
}

struct ConnectCameraRecoveryCopy: Equatable {
    let title: String
    let message: String
    let showsSettingsAction: Bool

    static func value(for state: ConnectCameraPermissionState) -> Self {
        switch state {
        case .denied:
            Self(
                title: "Camera access is off",
                message: "Allow camera access in Settings, then return to scan your Fabric pairing code.",
                showsSettingsAction: true
            )
        case .restricted:
            Self(
                title: "Camera access is restricted",
                message: "This iPhone does not currently allow camera access. You can still connect with Advanced setup.",
                showsSettingsAction: false
            )
        case .unavailable:
            Self(
                title: "Camera is unavailable",
                message: "Fabric could not start the camera on this device. You can still connect with Advanced setup.",
                showsSettingsAction: false
            )
        case .notDetermined, .authorized:
            Self(title: "Scan your pairing code", message: "", showsSettingsAction: false)
        }
    }
}

enum ConnectRouteDiagnosis {
    /// Pairing failures explain the next useful checks without echoing an
    /// endpoint credential or surfacing low-level networking text.
    static func message(for error: Error) -> String {
        guard let urlError = error as? URLError else {
            return "Fabric couldn’t reach this computer. Make sure Fabric is running, then check that this iPhone is on the same network or tailnet."
        }
        switch urlError.code {
        case .notConnectedToInternet:
            return "This iPhone is offline. Reconnect to Wi-Fi or your tailnet, then try again."
        case .secureConnectionFailed, .serverCertificateUntrusted,
             .serverCertificateHasBadDate, .serverCertificateHasUnknownRoot:
            return "Fabric couldn’t establish a trusted HTTPS connection. Check the server address and certificate, then try again."
        case .timedOut, .cannotFindHost, .cannotConnectToHost,
             .dnsLookupFailed, .networkConnectionLost:
            return "Fabric couldn’t find this computer. Make sure Fabric is running and this iPhone is on the same network or tailnet."
        default:
            return "Fabric couldn’t reach this computer. Check the address and network, then try again."
        }
    }
}

enum GatewayTransportPresentation {
    static func isHTTPS(_ url: URL) -> Bool {
        url.scheme?.lowercased() == "https"
    }

    static func allowsTokenCredential(_ url: URL) -> Bool {
        GatewayBaseURL.allowsTokenCredential(url)
    }

    static func warning(for url: URL) -> String? {
        guard !isHTTPS(url) else { return nil }
        return "This address uses HTTP, which does not provide end-to-end encryption. Continue only over an encrypted private network such as Tailscale—never over the public internet."
    }

    static func label(for url: URL) -> String {
        isHTTPS(url)
            ? "HTTPS encrypted transport"
            : "HTTP transport over a private encrypted network only"
    }
}

/// Manual credentials and a saved pairing-retry handle are authorized for one
/// normalized endpoint only. Any real endpoint edit clears every bound value,
/// even when its field is currently hidden by the authentication picker.
/// Cosmetic edits that normalize to the same endpoint may keep the values.
struct GatewayEndpointCredentialState: Equatable {
    var token = ""
    var username = ""
    var password = ""
    var otp = ""
    var scannedGatewayID: String?

    @discardableResult
    mutating func resetIfEndpointChanged(from oldValue: String, to newValue: String) -> Bool {
        guard Self.endpointChanged(from: oldValue, to: newValue) else { return false }
        self = Self()
        return true
    }

    private static func endpointChanged(from oldValue: String, to newValue: String) -> Bool {
        guard oldValue != newValue else { return false }
        let oldKey = GatewayBaseURL.parse(oldValue).map(SavedGateway.endpointKey(for:))
        let newKey = GatewayBaseURL.parse(newValue).map(SavedGateway.endpointKey(for:))
        guard let oldKey, let newKey else {
            // An invalid/partial edit has no stable authority. Clear instead
            // of carrying a credential across an ambiguous transition.
            return true
        }
        return oldKey != newKey
    }
}

/// Generation + endpoint fence for async setup requests. URL edits can move
/// the form from gateway A to B (or A → B → A) while discovery is in flight;
/// endpoint equality alone cannot distinguish that stale response.
struct GatewayEndpointRequestFence: Equatable {
    struct Request: Equatable {
        let generation: UInt
        let endpointKey: String
    }

    private(set) var generation: UInt = 0

    mutating func begin(for url: URL) -> Request {
        generation &+= 1
        return Request(
            generation: generation,
            endpointKey: SavedGateway.endpointKey(for: url)
        )
    }

    mutating func invalidate() {
        generation &+= 1
    }

    func accepts(
        _ request: Request,
        currentURL: URL?,
        applicable: Bool = true
    ) -> Bool {
        guard applicable, request.generation == generation, let currentURL else {
            return false
        }
        return request.endpointKey == SavedGateway.endpointKey(for: currentURL)
    }
}

struct ConnectPrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(FabricTheme.textOnBrand)
            .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
            .background(FabricTheme.action, in: RoundedRectangle(cornerRadius: FabricTheme.radius))
            .opacity(isEnabled ? (configuration.isPressed ? 0.82 : 1) : 0.45)
    }
}

struct ConnectSecondaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(FabricTheme.action)
            .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
            .background(FabricTheme.surface, in: RoundedRectangle(cornerRadius: FabricTheme.radius))
            .overlay {
                RoundedRectangle(cornerRadius: FabricTheme.radius)
                    .stroke(FabricTheme.controlBorder, lineWidth: 1)
            }
            .opacity(isEnabled ? (configuration.isPressed ? 0.75 : 1) : 0.45)
    }
}
