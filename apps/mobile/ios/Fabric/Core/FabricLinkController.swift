import CryptoKit
import FabricLinkCore
import Foundation
import Observation

struct FabricLinkMachine: Codable, Hashable, Identifiable {
    enum Status: String, Codable {
        case pending
        case active
    }

    let id: String
    var label: String
    let relayOrigin: String
    let routeID: Data
    let machinePublicKey: Data
    var grants: [String]
    var status: Status
    let createdAt: Int
    var updatedAt: Int

    var machineFingerprint: String {
        FabricLinkWire.fingerprint(machinePublicKey)
    }
}

private struct FabricLinkPendingApplication {
    let requestID: Data
    let messageID: Data
    let expiresAt: Int
    let method: String
    let envelope: Data
}

private struct FabricLinkControllerSecretBundle {
    let opaqueState: Data
    let relayPrivateKey: Data
    let pairingPayload: Data?
    let enrollmentRequest: Data?
    let credentialSerial: Data?
    let admissionCertificate: Data?
    let grants: [String]
    let pendingApplication: FabricLinkPendingApplication?

    func encoded() throws -> Data {
        let pending: FabricLinkCBOR = if let pendingApplication {
            .map([
                "request_id": .bytes(pendingApplication.requestID),
                "message_id": .bytes(pendingApplication.messageID),
                "expires_at": .integer(pendingApplication.expiresAt),
                "method": .string(pendingApplication.method),
                "envelope": .bytes(pendingApplication.envelope),
            ])
        } else {
            .null
        }
        let encoded = try FabricLinkCanonicalCBOR.encode(.map([
            "v": .integer(1),
            "opaque_state": .bytes(opaqueState),
            "relay_private_key": .bytes(relayPrivateKey),
            "pairing_payload": pairingPayload.map(FabricLinkCBOR.bytes) ?? .null,
            "enrollment_request": enrollmentRequest.map(FabricLinkCBOR.bytes) ?? .null,
            "credential_serial": credentialSerial.map(FabricLinkCBOR.bytes) ?? .null,
            "admission_certificate": admissionCertificate.map(FabricLinkCBOR.bytes) ?? .null,
            "grants": .array(grants.map(FabricLinkCBOR.string)),
            "pending_application": pending,
        ]))
        guard encoded.count <= 20 * 1024 * 1024 else {
            throw FabricLinkError.protectedStateUnavailable
        }
        return encoded
    }

    static func decode(_ encoded: Data) throws -> FabricLinkControllerSecretBundle {
        let value = try FabricLinkCanonicalCBOR.decode(
            encoded,
            maximum: 20 * 1024 * 1024
        )
        let map = try FabricLinkWire.exactMap(
            value,
            keys: [
                "v", "opaque_state", "relay_private_key", "pairing_payload",
                "enrollment_request", "credential_serial",
                "admission_certificate", "grants", "pending_application",
            ]
        )
        guard try FabricLinkWire.integer(map["v"]) == 1 else {
            throw FabricLinkError.invalidRecord
        }
        let pairing = try optionalBytes(map["pairing_payload"])
        let request = try optionalBytes(map["enrollment_request"])
        let serial = try optionalBytes(map["credential_serial"])
        let certificate = try optionalBytes(map["admission_certificate"])
        let grants: [String]
        if let rows = map["grants"]?.arrayValue {
            grants = try FabricLinkWire.normalizedGrants(
                rows.map { try FabricLinkWire.string($0) },
                allowEmpty: true
            )
        } else {
            throw FabricLinkError.invalidRecord
        }
        let pending: FabricLinkPendingApplication?
        if case .null? = map["pending_application"] {
            pending = nil
        } else {
            let pendingMap = try FabricLinkWire.exactMap(
                map["pending_application"] ?? .null,
                keys: ["request_id", "message_id", "expires_at", "method", "envelope"]
            )
            let method = try FabricLinkWire.string(pendingMap["method"])
            guard FabricLinkWire.validMethod(method) else {
                throw FabricLinkError.invalidRecord
            }
            pending = FabricLinkPendingApplication(
                requestID: try FabricLinkWire.bytes(
                    pendingMap["request_id"],
                    count: 16
                ),
                messageID: try FabricLinkWire.bytes(
                    pendingMap["message_id"],
                    count: 16
                ),
                expiresAt: try FabricLinkWire.integer(pendingMap["expires_at"]),
                method: method,
                envelope: try FabricLinkWire.bytes(
                    pendingMap["envelope"],
                    allowEmpty: false
                )
            )
        }
        guard !((pairing == nil) != (request == nil)),
              !((serial == nil) != (certificate == nil)),
              (pairing != nil) != (serial != nil),
              serial == nil || serial?.count == 16,
              pairing == nil || pairing!.count <= 4096,
              request == nil || request!.count <= FabricLinkWire.maxEnrollmentRecord,
              certificate == nil || certificate!.count <= 16 * 1024,
              !encoded.isEmpty else {
            throw FabricLinkError.invalidRecord
        }
        if serial == nil {
            guard grants.isEmpty, pending == nil else {
                throw FabricLinkError.invalidRecord
            }
        } else {
            guard !grants.isEmpty else { throw FabricLinkError.invalidRecord }
        }
        return FabricLinkControllerSecretBundle(
            opaqueState: try FabricLinkWire.bytes(
                map["opaque_state"],
                allowEmpty: false
            ),
            relayPrivateKey: try FabricLinkWire.bytes(
                map["relay_private_key"],
                count: 32
            ),
            pairingPayload: pairing,
            enrollmentRequest: request,
            credentialSerial: serial,
            admissionCertificate: certificate,
            grants: grants,
            pendingApplication: pending
        )
    }

    private static func optionalBytes(_ value: FabricLinkCBOR?) throws -> Data? {
        if case .null? = value { return nil }
        return try FabricLinkWire.bytes(value, allowEmpty: false)
    }

    func replacing(
        opaqueState: Data? = nil,
        pairingPayload: Data?? = nil,
        enrollmentRequest: Data?? = nil,
        credentialSerial: Data?? = nil,
        admissionCertificate: Data?? = nil,
        grants: [String]? = nil,
        pendingApplication: FabricLinkPendingApplication?? = nil
    ) -> FabricLinkControllerSecretBundle {
        FabricLinkControllerSecretBundle(
            opaqueState: opaqueState ?? self.opaqueState,
            relayPrivateKey: relayPrivateKey,
            pairingPayload: pairingPayload ?? self.pairingPayload,
            enrollmentRequest: enrollmentRequest ?? self.enrollmentRequest,
            credentialSerial: credentialSerial ?? self.credentialSerial,
            admissionCertificate: admissionCertificate ?? self.admissionCertificate,
            grants: grants ?? self.grants,
            pendingApplication: pendingApplication ?? self.pendingApplication
        )
    }
}

enum FabricLinkMachineStore {
    private static let defaultsKey = "fabric.link.machine-profiles.v1"

    static func all(defaults: UserDefaults = .standard) -> [FabricLinkMachine] {
        guard let data = defaults.data(forKey: defaultsKey),
              let decoded = try? JSONDecoder().decode(
                [FabricLinkMachine].self,
                from: data
              ) else {
            return []
        }
        return decoded.sorted {
            ($0.updatedAt, $0.id) > ($1.updatedAt, $1.id)
        }
    }

    static func upsert(
        _ machine: FabricLinkMachine,
        defaults: UserDefaults = .standard
    ) {
        var machines = all(defaults: defaults)
        machines.removeAll { $0.id == machine.id }
        machines.append(machine)
        machines.sort { ($0.updatedAt, $0.id) > ($1.updatedAt, $1.id) }
        if let data = try? JSONEncoder().encode(machines) {
            defaults.set(data, forKey: defaultsKey)
        }
    }

    static func remove(
        id: String,
        defaults: UserDefaults = .standard
    ) throws {
        try LinkControllerStore.remove(controllerID: id)
        var machines = all(defaults: defaults)
        machines.removeAll { $0.id == id }
        if machines.isEmpty {
            defaults.removeObject(forKey: defaultsKey)
        } else if let data = try? JSONEncoder().encode(machines) {
            defaults.set(data, forKey: defaultsKey)
        }
    }

    static func removeAll(defaults: UserDefaults = .standard) throws {
        let machines = all(defaults: defaults)
        for machine in machines {
            try LinkControllerStore.remove(controllerID: machine.id)
        }
        defaults.removeObject(forKey: defaultsKey)
    }
}

private struct FabricLinkRelayMailbox: Equatable {
    let routeID: Data
    let credentialSerial: Data?
    let pairingHandle: Data?
    let recipient: String

    static func application(
        routeID: Data,
        credentialSerial: Data,
        recipient: String
    ) -> FabricLinkRelayMailbox {
        FabricLinkRelayMailbox(
            routeID: routeID,
            credentialSerial: credentialSerial,
            pairingHandle: nil,
            recipient: recipient
        )
    }

    static func enrollment(
        routeID: Data,
        pairingHandle: Data,
        recipient: String
    ) -> FabricLinkRelayMailbox {
        FabricLinkRelayMailbox(
            routeID: routeID,
            credentialSerial: nil,
            pairingHandle: pairingHandle,
            recipient: recipient
        )
    }

    var cbor: FabricLinkCBOR {
        if let credentialSerial {
            return .map([
                "route": .bytes(routeID),
                "credential_serial": .bytes(credentialSerial),
                "recipient": .string(recipient),
            ])
        }
        return .map([
            "route": .bytes(routeID),
            "pairing_handle": .bytes(pairingHandle ?? Data()),
            "recipient": .string(recipient),
        ])
    }

    static func decode(
        _ value: FabricLinkCBOR,
        enrollment: Bool
    ) throws -> FabricLinkRelayMailbox {
        let keys = enrollment
            ? Set(["route", "pairing_handle", "recipient"])
            : Set(["route", "credential_serial", "recipient"])
        let map = try FabricLinkWire.exactMap(value, keys: keys)
        let recipient = try FabricLinkWire.string(map["recipient"])
        guard recipient == "host" || recipient == "controller" else {
            throw FabricLinkError.invalidRecord
        }
        if enrollment {
            return .enrollment(
                routeID: try FabricLinkWire.bytes(map["route"], count: 32),
                pairingHandle: try FabricLinkWire.bytes(
                    map["pairing_handle"],
                    count: 32
                ),
                recipient: recipient
            )
        }
        return .application(
            routeID: try FabricLinkWire.bytes(map["route"], count: 32),
            credentialSerial: try FabricLinkWire.bytes(
                map["credential_serial"],
                count: 16
            ),
            recipient: recipient
        )
    }
}

private struct FabricLinkRelayChallenge {
    let nonce: Data
    let expiresAt: Int
}

private struct FabricLinkRelayDelivery {
    let mailbox: FabricLinkRelayMailbox
    let sequence: Int
    let messageID: Data
    let expiresAt: Int
    let opaqueRecord: Data
}

func fabricLinkAdvanceBoundedCursor(
    afterSequence: Int,
    deliveredSequences: [Int],
    highWatermark: Int
) -> Int {
    if let lastDelivered = deliveredSequences.last {
        return max(afterSequence, lastDelivered)
    }
    return max(afterSequence, highWatermark)
}

private enum FabricLinkRelayFrame {
    case challenge(FabricLinkRelayChallenge)
    case ready
    case receipt(messageID: Data, sequence: Int)
    case delivery(FabricLinkRelayDelivery, enrollment: Bool)
    case sync(requestID: Data, count: Int, highWatermark: Int)
}

private final class FabricLinkRelayConnection {
    private static let subprotocolName = "fabric-link-relay-v1"

    private let origin: String
    private let session: URLSession
    private var task: URLSessionWebSocketTask?

    init(origin: String) throws {
        self.origin = try FabricLinkWire.normalizedRelayOrigin(
            origin,
            allowLoopbackHTTP: true
        )
        let configuration = URLSessionConfiguration.ephemeral
        configuration.waitsForConnectivity = false
        configuration.timeoutIntervalForRequest = 15
        configuration.timeoutIntervalForResource = 360
        configuration.httpCookieStorage = nil
        configuration.urlCache = nil
        session = URLSession(configuration: configuration)
    }

    deinit {
        close()
    }

    func connect(authentication: FabricLinkControllerSecretBundle? = nil) async throws {
        guard task == nil else { throw FabricLinkError.relayUnavailable }
        let parsed = try FabricLinkWire.normalizedRelayOrigin(
            origin,
            allowLoopbackHTTP: true
        )
        guard let components = URLComponents(string: parsed),
              let host = components.host else {
            throw FabricLinkError.relayUnavailable
        }
        var socketComponents = URLComponents()
        socketComponents.scheme = components.scheme == "https" ? "wss" : "ws"
        socketComponents.host = host
        socketComponents.port = components.port
        socketComponents.path = "/link"
        guard let socketURL = socketComponents.url else {
            throw FabricLinkError.relayUnavailable
        }
        let webSocket = session.webSocketTask(
            with: socketURL,
            protocols: [Self.subprotocolName]
        )
        task = webSocket
        webSocket.resume()
        do {
            let first = try await receive()
            guard case .challenge(let challenge) = first else {
                throw FabricLinkError.invalidRecord
            }
            guard let response = webSocket.response as? HTTPURLResponse,
                  response.value(
                    forHTTPHeaderField: "Sec-WebSocket-Protocol"
                  ) == Self.subprotocolName else {
                throw FabricLinkError.relayUnavailable
            }
            guard let authentication else { return }
            let auth = try authenticationFrame(
                bundle: authentication,
                challenge: challenge
            )
            try await send(auth)
            guard case .ready = try await receive() else {
                throw FabricLinkError.invalidRecord
            }
        } catch {
            close()
            throw mapRelayError(error)
        }
    }

    func sendExpectReceipt(
        _ frame: FabricLinkCBOR,
        messageID: Data
    ) async throws {
        try await send(frame)
        guard case .receipt(let returnedID, _) = try await receive(),
              returnedID == messageID else {
            throw FabricLinkError.invalidRecord
        }
    }

    func poll(
        _ frame: FabricLinkCBOR,
        requestID: Data
    ) async throws -> ([FabricLinkRelayDelivery], Int) {
        try await send(frame)
        var deliveries: [FabricLinkRelayDelivery] = []
        while true {
            switch try await receive() {
            case .delivery(let delivery, _):
                deliveries.append(delivery)
            case .sync(let returnedID, let count, let highWatermark):
                guard returnedID == requestID, count == deliveries.count else {
                    throw FabricLinkError.invalidRecord
                }
                return (deliveries, highWatermark)
            default:
                throw FabricLinkError.invalidRecord
            }
        }
    }

    func close() {
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        session.invalidateAndCancel()
    }

    private func send(_ value: FabricLinkCBOR) async throws {
        guard let task else { throw FabricLinkError.relayUnavailable }
        let encoded = try FabricLinkCanonicalCBOR.encode(value)
        guard encoded.count <= FabricLinkWire.maxRelayFrame else {
            throw FabricLinkError.invalidRecord
        }
        do {
            try await task.send(.data(encoded))
        } catch {
            throw mapRelayError(error)
        }
    }

    private func receive() async throws -> FabricLinkRelayFrame {
        guard let task else { throw FabricLinkError.relayUnavailable }
        do {
            let message = try await task.receive()
            guard case .data(let encoded) = message,
                  !encoded.isEmpty,
                  encoded.count <= FabricLinkWire.maxRelayFrame else {
                throw FabricLinkError.invalidRecord
            }
            let value = try FabricLinkCanonicalCBOR.decode(
                encoded,
                maximum: FabricLinkWire.maxRelayFrame
            )
            return try decodeFrame(value)
        } catch {
            throw mapRelayError(error)
        }
    }

    private func decodeFrame(_ value: FabricLinkCBOR) throws -> FabricLinkRelayFrame {
        guard let map = value.mapValue,
              try FabricLinkWire.integer(map["v"]) == FabricLinkWire.relayProtocolVersion else {
            throw FabricLinkError.invalidRecord
        }
        let type = try FabricLinkWire.string(map["t"])
        switch type {
        case "challenge":
            let exact = try FabricLinkWire.exactMap(
                value,
                keys: ["v", "t", "nonce", "server_time", "expires_at", "versions"]
            )
            let serverTime = try FabricLinkWire.integer(exact["server_time"])
            let expiresAt = try FabricLinkWire.integer(exact["expires_at"])
            guard expiresAt > serverTime,
                  expiresAt - serverTime <= 300,
                  let versions = exact["versions"]?.arrayValue,
                  versions.map(\.intValue) == [1] else {
                throw FabricLinkError.invalidRecord
            }
            return .challenge(FabricLinkRelayChallenge(
                nonce: try FabricLinkWire.bytes(exact["nonce"], count: 32),
                expiresAt: expiresAt
            ))
        case "ready":
            let exact = try FabricLinkWire.exactMap(
                value,
                keys: ["v", "t", "role"]
            )
            guard try FabricLinkWire.string(exact["role"]) == "controller" else {
                throw FabricLinkError.invalidRecord
            }
            return .ready
        case "receipt":
            let exact = try FabricLinkWire.exactMap(
                value,
                keys: ["v", "t", "message_id", "sequence"]
            )
            let sequence = try FabricLinkWire.integer(exact["sequence"])
            guard sequence >= 1 else { throw FabricLinkError.invalidRecord }
            return .receipt(
                messageID: try FabricLinkWire.bytes(
                    exact["message_id"],
                    count: 16
                ),
                sequence: sequence
            )
        case "delivery", "enrollment_delivery":
            let enrollment = type == "enrollment_delivery"
            let exact = try FabricLinkWire.exactMap(
                value,
                keys: [
                    "v", "t", "mailbox", "sequence", "message_id",
                    "expires_at", "opaque_record",
                ]
            )
            let sequence = try FabricLinkWire.integer(exact["sequence"])
            guard sequence >= 1 else { throw FabricLinkError.invalidRecord }
            return .delivery(
                FabricLinkRelayDelivery(
                    mailbox: try FabricLinkRelayMailbox.decode(
                        exact["mailbox"] ?? .null,
                        enrollment: enrollment
                    ),
                    sequence: sequence,
                    messageID: try FabricLinkWire.bytes(
                        exact["message_id"],
                        count: 16
                    ),
                    expiresAt: try FabricLinkWire.integer(exact["expires_at"]),
                    opaqueRecord: try FabricLinkWire.bytes(
                        exact["opaque_record"],
                        allowEmpty: false
                    )
                ),
                enrollment: enrollment
            )
        case "sync":
            let exact = try FabricLinkWire.exactMap(
                value,
                keys: ["v", "t", "request_id", "count", "high_watermark"]
            )
            let count = try FabricLinkWire.integer(exact["count"])
            let watermark = try FabricLinkWire.integer(exact["high_watermark"])
            guard count >= 0, watermark >= 0 else {
                throw FabricLinkError.invalidRecord
            }
            return .sync(
                requestID: try FabricLinkWire.bytes(
                    exact["request_id"],
                    count: 16
                ),
                count: count,
                highWatermark: watermark
            )
        case "failure":
            let exact = try FabricLinkWire.exactMap(
                value,
                keys: ["v", "t", "code", "correlation_id"]
            )
            let code = try FabricLinkWire.string(exact["code"])
            guard FabricLinkWire.validMethod(code.replacingOccurrences(
                of: "_",
                with: "."
            )) else {
                throw FabricLinkError.invalidRecord
            }
            throw FabricLinkError.relayRejected(code)
        default:
            throw FabricLinkError.invalidRecord
        }
    }

    private func authenticationFrame(
        bundle: FabricLinkControllerSecretBundle,
        challenge: FabricLinkRelayChallenge
    ) throws -> FabricLinkCBOR {
        let now = Int(Date().timeIntervalSince1970)
        guard challenge.expiresAt >= now,
              let serial = bundle.credentialSerial,
              let certificate = bundle.admissionCertificate else {
            throw FabricLinkError.invalidRecord
        }
        let privateKey = try Curve25519.Signing.PrivateKey(
            rawRepresentation: bundle.relayPrivateKey
        )
        let unsigned: FabricLinkCBOR = .map([
            "v": .integer(FabricLinkWire.relayProtocolVersion),
            "t": .string("auth"),
            "route": .bytes(try routeID(from: certificate)),
            "role": .string("controller"),
            "nonce": .bytes(challenge.nonce),
            "credential_serial": .bytes(serial),
            "controller_public_key": .bytes(privateKey.publicKey.rawRepresentation),
            "admission_certificate": .bytes(certificate),
        ])
        let signatureInput = Data("fabric-link-relay-auth-v1\0".utf8)
            + (try FabricLinkCanonicalCBOR.encode(.map([
                "relay": .string(origin),
                "authentication": unsigned,
            ])))
        let signature = try privateKey.signature(for: signatureInput)
        guard var map = unsigned.mapValue else {
            throw FabricLinkError.invalidRecord
        }
        map["signature"] = .bytes(signature)
        return .map(map)
    }

    private func routeID(from signedCertificate: Data) throws -> Data {
        let signed = try FabricLinkWire.exactMap(
            FabricLinkCanonicalCBOR.decode(signedCertificate, maximum: 16 * 1024),
            keys: ["certificate", "signature"]
        )
        let certificateCBOR = try FabricLinkWire.bytes(
            signed["certificate"],
            allowEmpty: false
        )
        let certificate = try FabricLinkWire.exactMap(
            FabricLinkCanonicalCBOR.decode(certificateCBOR, maximum: 4096),
            keys: [
                "v", "route_id", "relay_public_key", "credential_serial",
                "not_before", "not_after",
            ]
        )
        return try FabricLinkWire.bytes(certificate["route_id"], count: 32)
    }

    private func mapRelayError(_ error: Error) -> Error {
        if let linkError = error as? FabricLinkError {
            return linkError
        }
        if error is CancellationError {
            return error
        }
        return FabricLinkError.relayUnavailable
    }
}

@Observable
@MainActor
final class FabricLinkControllerModel {
    private(set) var machines: [FabricLinkMachine] = FabricLinkMachineStore.all()
    private(set) var isWorking = false
    private(set) var lastError: String?

    func reload() {
        machines = FabricLinkMachineStore.all()
    }

    func pair(
        _ pairing: FabricLinkPairing,
        name: String,
        grants: [String] = ["observe", "chat", "dispatch"],
        onAuthenticationString: (String) -> Void
    ) async throws -> FabricLinkMachine {
        guard !isWorking else { throw FabricLinkError.requestInFlight }
        isWorking = true
        lastError = nil
        defer { isWorking = false }
        do {
            try FabricLinkWire.requireCore()
            let now = Int(Date().timeIntervalSince1970)
            guard pairing.expiresAt > now else {
                throw FabricLinkError.pairingExpired
            }
            let relayKey = Curve25519.Signing.PrivateKey()
            let identity = Data("fabric-link-controller:".utf8)
                + (try FabricLinkWire.randomBytes(count: 32))
            let bootstrap = try fabricLinkCreateController(identity: identity)
            let request = try FabricLinkEnrollmentRequest.make(
                pairing: pairing,
                name: name,
                grants: grants,
                relayPublicKey: relayKey.publicKey.rawRepresentation,
                keyPackage: bootstrap.keyPackage,
                now: now
            )
            let authenticationString = try FabricLinkEnrollmentVerifier
                .shortAuthenticationString(pairing: pairing, request: request)
            let controllerID = "controller_"
                + (try FabricLinkWire.randomBytes(count: 12)).map {
                    String(format: "%02x", $0)
                }.joined()
            let pendingBundle = FabricLinkControllerSecretBundle(
                opaqueState: bootstrap.opaqueState,
                relayPrivateKey: relayKey.rawRepresentation,
                pairingPayload: try pairing.cbor(),
                enrollmentRequest: try request.cbor(),
                credentialSerial: nil,
                admissionCertificate: nil,
                grants: [],
                pendingApplication: nil
            )
            try saveSecret(pendingBundle, id: controllerID)
            var machine = FabricLinkMachine(
                id: controllerID,
                label: try FabricLinkWire.normalizedControllerName(name),
                relayOrigin: pairing.relayOrigin,
                routeID: pairing.routeID,
                machinePublicKey: pairing.machinePublicKey,
                grants: [],
                status: .pending,
                createdAt: now,
                updatedAt: now
            )
            FabricLinkMachineStore.upsert(machine)
            reload()
            onAuthenticationString(authenticationString)

            let connection = try FabricLinkRelayConnection(
                origin: pairing.relayOrigin
            )
            defer { connection.close() }
            try await connection.connect()
            let requestMessageID = try FabricLinkWire.randomBytes(count: 16)
            let requestMailbox = FabricLinkRelayMailbox.enrollment(
                routeID: pairing.routeID,
                pairingHandle: pairing.handle,
                recipient: "host"
            )
            try await connection.sendExpectReceipt(
                .map([
                    "v": .integer(1),
                    "t": .string("enrollment_publish"),
                    "mailbox": requestMailbox.cbor,
                    "message_id": .bytes(requestMessageID),
                    "expires_at": .integer(pairing.expiresAt),
                    "opaque_record": .bytes(
                        try request.encryptedEnvelope(pairing: pairing)
                    ),
                ]),
                messageID: requestMessageID
            )
            let responseMailbox = FabricLinkRelayMailbox.enrollment(
                routeID: pairing.routeID,
                pairingHandle: pairing.handle,
                recipient: "controller"
            )
            var afterSequence = 0
            while Int(Date().timeIntervalSince1970) < pairing.expiresAt {
                try Task.checkCancellation()
                let pollID = try FabricLinkWire.randomBytes(count: 16)
                let (deliveries, watermark) = try await connection.poll(
                    .map([
                        "v": .integer(1),
                        "t": .string("enrollment_poll"),
                        "mailbox": responseMailbox.cbor,
                        "request_id": .bytes(pollID),
                        "after_sequence": .integer(afterSequence),
                        "limit": .integer(4),
                    ]),
                    requestID: pollID
                )
                afterSequence = fabricLinkAdvanceBoundedCursor(
                    afterSequence: afterSequence,
                    deliveredSequences: deliveries.map(\.sequence),
                    highWatermark: watermark
                )
                if let delivery = deliveries.first {
                    guard delivery.mailbox == responseMailbox else {
                        throw FabricLinkError.invalidRecord
                    }
                    let result = try FabricLinkEnrollmentVerifier.decrypt(
                        pairing: pairing,
                        request: request,
                        encrypted: delivery.opaqueRecord,
                        now: Int(Date().timeIntervalSince1970)
                    )
                    let joined = try fabricLinkControllerJoin(
                        opaqueState: bootstrap.opaqueState,
                        welcome: result.welcome
                    )
                    let activeBundle = FabricLinkControllerSecretBundle(
                        opaqueState: joined,
                        relayPrivateKey: relayKey.rawRepresentation,
                        pairingPayload: nil,
                        enrollmentRequest: nil,
                        credentialSerial: result.credentialSerial,
                        admissionCertificate: result.admissionCertificate,
                        grants: result.grants,
                        pendingApplication: nil
                    )
                    // Protected authority commits before public metadata. A
                    // crash can leave a harmless pending row, never an active
                    // row pointing at old or absent MLS private state.
                    try saveSecret(activeBundle, id: controllerID)
                    machine.status = .active
                    machine.grants = result.grants
                    machine.updatedAt = Int(Date().timeIntervalSince1970)
                    FabricLinkMachineStore.upsert(machine)
                    reload()
                    try await connection.sendExpectReceipt(
                        .map([
                            "v": .integer(1),
                            "t": .string("enrollment_ack"),
                            "mailbox": responseMailbox.cbor,
                            "sequence": .integer(delivery.sequence),
                            "message_id": .bytes(delivery.messageID),
                        ]),
                        messageID: delivery.messageID
                    )
                    return machine
                }
                try await Task.sleep(for: .milliseconds(500))
            }
            throw FabricLinkError.pairingNotApproved
        } catch {
            let mapped = mapError(error)
            lastError = mapped.localizedDescription
            throw mapped
        }
    }

    func forget(_ machine: FabricLinkMachine) throws {
        do {
            try FabricLinkMachineStore.remove(id: machine.id)
            reload()
        } catch {
            throw FabricLinkError.protectedStateUnavailable
        }
    }

    func dispatch(
        to machine: FabricLinkMachine,
        prompt: String,
        title: String
    ) async throws -> FabricLinkCBOR {
        let text = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { throw FabricLinkError.invalidRecord }
        return try await invoke(
            machine: machine,
            method: "job.create",
            params: .map([
                "idempotency_key": .string(UUID().uuidString.lowercased()),
                "kind": .string("background_prompt"),
                "text": .string(text),
                "title": .string(
                    title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        ? "Dispatched from Fabric Mobile"
                        : title.trimmingCharacters(in: .whitespacesAndNewlines)
                ),
            ]),
            timeoutSeconds: 120
        )
    }

    func invoke(
        machine: FabricLinkMachine,
        method: String,
        params: FabricLinkCBOR,
        timeoutSeconds: Int = 60
    ) async throws -> FabricLinkCBOR {
        guard machine.status == .active else {
            throw FabricLinkError.invalidRecord
        }
        guard !isWorking else { throw FabricLinkError.requestInFlight }
        isWorking = true
        lastError = nil
        defer { isWorking = false }
        do {
            try FabricLinkWire.requireCore()
            guard case .map = params,
                  FabricLinkWire.validMethod(method),
                  (1...290).contains(timeoutSeconds) else {
                throw FabricLinkError.invalidRecord
            }
            var bundle = try loadSecret(id: machine.id)
            guard let serial = bundle.credentialSerial,
                  bundle.admissionCertificate != nil else {
                throw FabricLinkError.invalidRecord
            }
            let now = Int(Date().timeIntervalSince1970)
            let pending: FabricLinkPendingApplication
            if let existing = bundle.pendingApplication {
                if existing.expiresAt <= now {
                    bundle = bundle.replacing(pendingApplication: .some(nil))
                    try saveSecret(bundle, id: machine.id)
                    pending = try createPending(
                        machine: machine,
                        method: method,
                        params: params,
                        timeoutSeconds: timeoutSeconds,
                        bundle: &bundle
                    )
                } else if existing.method == method {
                    pending = existing
                } else {
                    throw FabricLinkError.requestInFlight
                }
            } else {
                pending = try createPending(
                    machine: machine,
                    method: method,
                    params: params,
                    timeoutSeconds: timeoutSeconds,
                    bundle: &bundle
                )
            }

            let connection = try FabricLinkRelayConnection(
                origin: machine.relayOrigin
            )
            defer { connection.close() }
            try await connection.connect(authentication: bundle)
            let hostMailbox = FabricLinkRelayMailbox.application(
                routeID: machine.routeID,
                credentialSerial: serial,
                recipient: "host"
            )
            try await connection.sendExpectReceipt(
                .map([
                    "v": .integer(1),
                    "t": .string("publish"),
                    "mailbox": hostMailbox.cbor,
                    "message_id": .bytes(pending.messageID),
                    "expires_at": .integer(pending.expiresAt),
                    "opaque_record": .bytes(pending.envelope),
                ]),
                messageID: pending.messageID
            )
            let responseMailbox = FabricLinkRelayMailbox.application(
                routeID: machine.routeID,
                credentialSerial: serial,
                recipient: "controller"
            )
            var afterSequence = 0
            while Int(Date().timeIntervalSince1970) < pending.expiresAt {
                try Task.checkCancellation()
                let pollID = try FabricLinkWire.randomBytes(count: 16)
                let (deliveries, watermark) = try await connection.poll(
                    .map([
                        "v": .integer(1),
                        "t": .string("poll"),
                        "mailbox": responseMailbox.cbor,
                        "request_id": .bytes(pollID),
                        "after_sequence": .integer(afterSequence),
                        "limit": .integer(10),
                    ]),
                    requestID: pollID
                )
                afterSequence = fabricLinkAdvanceBoundedCursor(
                    afterSequence: afterSequence,
                    deliveredSequences: deliveries.map(\.sequence),
                    highWatermark: watermark
                )
                for delivery in deliveries {
                    guard delivery.mailbox == responseMailbox else {
                        throw FabricLinkError.invalidRecord
                    }
                    let envelope = try FabricLinkApplicationEnvelope.decode(
                        delivery.opaqueRecord
                    )
                    guard envelope.routeID == machine.routeID,
                          envelope.credentialSerial == serial else {
                        throw FabricLinkError.invalidRecord
                    }
                    let decrypted = try fabricLinkControllerDecrypt(
                        opaqueState: bundle.opaqueState,
                        message: envelope.ciphertext
                    )
                    let response = try FabricLinkApplicationResponse.decode(
                        decrypted.plaintext
                    )
                    if response.requestID != pending.requestID {
                        bundle = bundle.replacing(
                            opaqueState: decrypted.opaqueState
                        )
                        try saveSecret(bundle, id: machine.id)
                        try await acknowledge(
                            connection,
                            mailbox: responseMailbox,
                            delivery: delivery
                        )
                        continue
                    }
                    bundle = bundle.replacing(
                        opaqueState: decrypted.opaqueState,
                        pendingApplication: .some(nil)
                    )
                    try saveSecret(bundle, id: machine.id)
                    try await acknowledge(
                        connection,
                        mailbox: responseMailbox,
                        delivery: delivery
                    )
                    guard response.ok, let result = response.result else {
                        throw FabricLinkError.requestRejected(
                            response.errorCode ?? "remote_request_failed"
                        )
                    }
                    return result
                }
                try await Task.sleep(for: deliveries.isEmpty
                    ? .milliseconds(500)
                    : .milliseconds(100))
            }
            throw FabricLinkError.requestTimedOut
        } catch {
            let mapped = mapError(error)
            lastError = mapped.localizedDescription
            throw mapped
        }
    }

    private func createPending(
        machine: FabricLinkMachine,
        method: String,
        params: FabricLinkCBOR,
        timeoutSeconds: Int,
        bundle: inout FabricLinkControllerSecretBundle
    ) throws -> FabricLinkPendingApplication {
        guard let serial = bundle.credentialSerial else {
            throw FabricLinkError.invalidRecord
        }
        let now = Int(Date().timeIntervalSince1970)
        let request = FabricLinkApplicationRequest(
            requestID: try FabricLinkWire.randomBytes(count: 16),
            idempotencyKey: try FabricLinkWire.randomBytes(count: 16),
            issuedAt: now,
            expiresAt: now + min(300, max(30, timeoutSeconds + 10)),
            method: method,
            paramsCBOR: try FabricLinkCanonicalCBOR.encode(params)
        )
        let update = try fabricLinkControllerEncrypt(
            opaqueState: bundle.opaqueState,
            plaintext: request.cbor()
        )
        let envelope = try FabricLinkApplicationEnvelope(
            routeID: machine.routeID,
            credentialSerial: serial,
            ciphertext: update.message
        ).cbor()
        let pending = FabricLinkPendingApplication(
            requestID: request.requestID,
            messageID: try FabricLinkWire.randomBytes(count: 16),
            expiresAt: request.expiresAt,
            method: method,
            envelope: envelope
        )
        bundle = bundle.replacing(
            opaqueState: update.opaqueState,
            pendingApplication: .some(pending)
        )
        // Save the evolved MLS state and exact ciphertext before the first
        // network write. Relaunch/retry can resend; it can never reuse old MLS
        // state to create a different ciphertext.
        try saveSecret(bundle, id: machine.id)
        return pending
    }

    private func acknowledge(
        _ connection: FabricLinkRelayConnection,
        mailbox: FabricLinkRelayMailbox,
        delivery: FabricLinkRelayDelivery
    ) async throws {
        try await connection.sendExpectReceipt(
            .map([
                "v": .integer(1),
                "t": .string("ack"),
                "mailbox": mailbox.cbor,
                "sequence": .integer(delivery.sequence),
                "message_id": .bytes(delivery.messageID),
            ]),
            messageID: delivery.messageID
        )
    }

    private func loadSecret(id: String) throws -> FabricLinkControllerSecretBundle {
        do {
            guard let encoded = try LinkControllerStore.load(controllerID: id) else {
                throw FabricLinkError.protectedStateUnavailable
            }
            return try FabricLinkControllerSecretBundle.decode(encoded)
        } catch let error as FabricLinkError {
            throw error
        } catch {
            throw FabricLinkError.protectedStateUnavailable
        }
    }

    private func saveSecret(
        _ bundle: FabricLinkControllerSecretBundle,
        id: String
    ) throws {
        do {
            try LinkControllerStore.save(bundle.encoded(), controllerID: id)
        } catch let error as FabricLinkError {
            throw error
        } catch {
            throw FabricLinkError.protectedStateUnavailable
        }
    }

    private func mapError(_ error: Error) -> FabricLinkError {
        if let linkError = error as? FabricLinkError {
            if case .relayRejected(let code) = linkError,
               code.contains("revoked") {
                return .controllerRevoked
            }
            return linkError
        }
        if error is CancellationError {
            return .relayUnavailable
        }
        return .invalidRecord
    }
}
