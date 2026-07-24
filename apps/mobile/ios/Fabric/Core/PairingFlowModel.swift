import Foundation

/// The two native entry points for a machine-issued pairing payload. Both are
/// intentionally reduced to the same wire value before classification so a QR
/// scan and a `fabric://` handoff cannot drift into different auth behavior.
///
/// Pairing URLs can contain a session token. Descriptions therefore identify
/// only the transport and never interpolate the raw value.
enum PairingFlowInput: Equatable, CustomStringConvertible, CustomDebugStringConvertible {
    case scan(String)
    case deepLink(URL)

    fileprivate var rawValue: String {
        switch self {
        case .scan(let raw): raw
        case .deepLink(let url): url.absoluteString
        }
    }

    var description: String {
        switch self {
        case .scan: "pairing scan <redacted>"
        case .deepLink: "pairing deep link <redacted>"
        }
    }

    var debugDescription: String { description }
}

/// Whether accepting a valid v1 payload creates a new library entry or
/// replaces the credentials/auth mode for an already-known endpoint.
enum PairingFlowTarget: Equatable {
    case new(baseURL: URL)
    case rePair(existingGatewayID: String, baseURL: URL)

    var baseURL: URL {
        switch self {
        case .new(let baseURL), .rePair(_, let baseURL): baseURL
        }
    }

    var existingGatewayID: String? {
        guard case .rePair(let existingGatewayID, _) = self else { return nil }
        return existingGatewayID
    }

    /// Reuse saved gated metadata for both scanner and deep-link entry. A new
    /// endpoint deliberately returns an empty value so stale form state cannot
    /// leak from a previously edited server.
    func existingUsername(in gateways: [SavedGateway]) -> String {
        guard let existingGatewayID else { return "" }
        return gateways.first { $0.id == existingGatewayID }?.username ?? ""
    }
}

/// An accepted token-mode pairing. The token is intentionally private and
/// redacted from both normal and debug descriptions. Code that persists it
/// must opt into the narrowly-scoped closure; production immediately writes
/// the value to Keychain through `GatewayStore` and does not copy it into an
/// observable model.
struct PairingTokenAcceptance: Equatable, CustomStringConvertible, CustomDebugStringConvertible {
    let target: PairingFlowTarget
    private let token: String

    fileprivate init(target: PairingFlowTarget, token: String) {
        self.target = target
        self.token = token
    }

    func withUnsafeToken<Result>(_ body: (String) throws -> Result) rethrows -> Result {
        try body(token)
    }

    var description: String {
        target.existingGatewayID == nil
            ? "token pairing for new endpoint <credential redacted>"
            : "token re-pair for existing endpoint <credential redacted>"
    }

    var debugDescription: String { description }
}

/// Observable result of attempting the token-pairing boundary. Duplicate
/// entry is explicit instead of silently discarding a newly delivered QR or
/// deep link while the same endpoint is already connecting.
enum PairingTokenConnectResult: Equatable {
    case attempted(SavedGateway)
    case alreadyInFlight
}

/// Complete, fail-closed result of classifying a native pairing input.
/// Unsupported enrollment intentionally carries no opaque enrollment handle;
/// invalid input intentionally carries no raw payload.
enum PairingFlowOutcome: Equatable, CustomStringConvertible, CustomDebugStringConvertible {
    case link(FabricLinkPairing)
    case token(PairingTokenAcceptance)
    case gated(PairingFlowTarget)
    case unsupportedEnrollment(PairingFlowTarget)
    case invalid

    var description: String {
        switch self {
        case .link(let pairing): pairing.description
        case .token(let acceptance): acceptance.description
        case .gated(let target):
            target.existingGatewayID == nil ? "gated pairing for new endpoint" : "gated re-pair for existing endpoint"
        case .unsupportedEnrollment:
            "unsupported device enrollment"
        case .invalid:
            "invalid pairing payload"
        }
    }

    var debugDescription: String { description }
}

/// Pure classification for pairing input. Storage, authentication, networking,
/// and presentation remain outside this type. Its only knowledge of the saved
/// library is the non-secret endpoint/id mapping needed to identify a re-pair.
struct PairingFlowModel {
    private let gatewayIDByEndpoint: [String: String]

    init(gateways: [SavedGateway]) {
        var index: [String: String] = [:]
        for gateway in gateways where index[gateway.endpointKey] == nil {
            index[gateway.endpointKey] = gateway.id
        }
        gatewayIDByEndpoint = index
    }

    func accept(_ input: PairingFlowInput) -> PairingFlowOutcome {
        // Fabric Link v3 is an independent device-enrollment protocol. Check
        // its exact HTTPS QR shape before the legacy fabric:// gateway parser;
        // neither path can reinterpret the other's credential material.
        if let pairing = try? FabricLinkPairing.parse(input.rawValue) {
            return .link(pairing)
        }
        guard let payload = PairingPayload.parse(input.rawValue) else { return .invalid }

        let endpointKey = SavedGateway.endpointKey(for: payload.baseURL)
        let target: PairingFlowTarget
        if let existingGatewayID = gatewayIDByEndpoint[endpointKey] {
            target = .rePair(existingGatewayID: existingGatewayID, baseURL: payload.baseURL)
        } else {
            target = .new(baseURL: payload.baseURL)
        }

        guard payload.enrollment == nil else {
            return .unsupportedEnrollment(target)
        }
        if let token = payload.token {
            return .token(PairingTokenAcceptance(target: target, token: token))
        }
        guard payload.gated else { return .invalid }
        return .gated(target)
    }
}

/// Prevents the camera and universal-link entry points from executing the
/// same endpoint pairing concurrently. The key is derived only from the
/// non-secret endpoint; no token or enrollment handle is retained.
final class PairingFlowExecutionGate {
    private var endpointKeysInFlight = Set<String>()

    /// Run the complete storage + connection boundary while holding the
    /// endpoint permit. Keeping acquire/defer/release here makes cleanup after
    /// either storage or network failure directly testable.
    func execute(
        _ target: PairingFlowTarget,
        operation: () async throws -> PairingTokenConnectResult
    ) async rethrows -> PairingTokenConnectResult {
        let endpointKey = SavedGateway.endpointKey(for: target.baseURL)
        guard endpointKeysInFlight.insert(endpointKey).inserted else {
            return .alreadyInFlight
        }
        defer { endpointKeysInFlight.remove(endpointKey) }

        return try await operation()
    }
}
