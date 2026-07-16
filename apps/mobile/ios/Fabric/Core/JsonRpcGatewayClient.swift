import Foundation

/// Connection lifecycle, mirroring `ConnectionState` in
/// `apps/shared/src/json-rpc-gateway.ts`.
enum GatewayConnectionState: String {
    case idle
    case connecting
    case open
    case closed
    case error
}

/// A server-pushed frame: `{"jsonrpc":"2.0","method":"event","params":{...}}`.
/// `type` values are the `GatewayEventName` strings shared with the desktop
/// renderer (`message.delta`, `tool.start`, `approval.request`, ...).
struct GatewayEvent {
    let type: String
    let sessionId: String?
    let payload: [String: Any]

    var payloadText: String? { payload["text"] as? String }
}

enum GatewayClientError: LocalizedError {
    case notConnected
    case connectFailed(underlying: String?)
    case socketClosed
    case requestTimedOut(method: String)
    case rpc(message: String)

    var errorDescription: String? {
        switch self {
        case .notConnected:
            return "gateway not connected"
        case .connectFailed(let underlying):
            let suffix = underlying.map { ": \($0)" } ?? ""
            return "WebSocket connection failed\(suffix)"
        case .socketClosed:
            return "WebSocket closed"
        case .requestTimedOut(let method):
            return "request timed out: \(method)"
        case .rpc(let message):
            return message
        }
    }
}

/// JSON-RPC 2.0 client over a single WebSocket.
///
/// Swift port of `apps/shared/src/json-rpc-gateway.ts` — same wire contract
/// the desktop renderer uses against `fabric serve` (`/api/ws`): string ids
/// with an `"r"` prefix, a pending-request map with per-request timeouts,
/// response frames keyed by id, and unsolicited `method == "event"` frames
/// fanned out to subscribers.
///
/// All mutable state is confined to `stateQueue`. Event and state callbacks
/// are delivered on the main queue so SwiftUI observers can consume them
/// directly.
final class JsonRpcGatewayClient: NSObject {
    static let defaultRequestTimeout: TimeInterval = 120
    static let defaultConnectTimeout: TimeInterval = 15

    var onEvent: ((GatewayEvent) -> Void)?
    var onStateChange: ((GatewayConnectionState) -> Void)?

    private let stateQueue = DispatchQueue(label: "io.github.obliviousodin.fabric.gateway-client")
    private lazy var urlSession = URLSession(
        configuration: .default,
        delegate: self,
        delegateQueue: nil
    )

    private var socket: URLSessionWebSocketTask?
    private var state: GatewayConnectionState = .idle
    private var nextId = 0
    private var pendingRequests: [String: (Result<Any?, Error>) -> Void] = [:]
    private var pendingTimeouts: [String: DispatchWorkItem] = [:]
    private var connectContinuation: CheckedContinuation<Void, Error>?
    private var connectTimeoutItem: DispatchWorkItem?

    var connectionState: GatewayConnectionState {
        stateQueue.sync { state }
    }

    // MARK: - Connect / close

    func connect(to wsURL: URL, timeout: TimeInterval = JsonRpcGatewayClient.defaultConnectTimeout) async throws {
        let shouldProceed: Bool = stateQueue.sync {
            if state == .connecting { return false }
            if let socket, socket.state == .running, state == .open { return false }
            return true
        }
        guard shouldProceed else { return }

        setState(.connecting)

        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            stateQueue.async {
                let task = self.urlSession.webSocketTask(with: wsURL)
                self.socket = task
                self.connectContinuation = continuation

                // A reconnect after sleep/wake must not hang in `.connecting`
                // forever (same rationale as DEFAULT_CONNECT_TIMEOUT_MS in the
                // shared TS client): fail to `.error` so callers can retry.
                let timeoutItem = DispatchWorkItem { [weak self] in
                    guard let self else { return }
                    guard let pending = self.connectContinuation else { return }
                    self.connectContinuation = nil
                    self.socket?.cancel()
                    self.socket = nil
                    self.setStateLocked(.error)
                    pending.resume(throwing: GatewayClientError.connectFailed(underlying: "timed out"))
                }
                self.connectTimeoutItem = timeoutItem
                self.stateQueue.asyncAfter(deadline: .now() + timeout, execute: timeoutItem)

                task.resume()
            }
        }
    }

    func close() {
        stateQueue.async {
            guard let socket = self.socket else { return }
            socket.cancel(with: .normalClosure, reason: nil)
            self.socket = nil
            self.setStateLocked(.closed)
            self.rejectAllPendingLocked(with: GatewayClientError.socketClosed)
        }
    }

    // MARK: - Requests

    /// Send a JSON-RPC request and await its response frame. `params` must be
    /// JSON-encodable. Returns the raw `result` value (dictionary for every
    /// Fabric method used here).
    func request(
        _ method: String,
        params: [String: Any] = [:],
        timeout: TimeInterval = JsonRpcGatewayClient.defaultRequestTimeout
    ) async throws -> Any? {
        try await withCheckedThrowingContinuation { continuation in
            stateQueue.async {
                guard let socket = self.socket, self.state == .open else {
                    continuation.resume(throwing: GatewayClientError.notConnected)
                    return
                }

                self.nextId += 1
                let id = "r\(self.nextId)"
                let frame: [String: Any] = [
                    "jsonrpc": "2.0",
                    "id": id,
                    "method": method,
                    "params": params,
                ]

                let data: Data
                do {
                    data = try JSONSerialization.data(withJSONObject: frame)
                } catch {
                    continuation.resume(throwing: error)
                    return
                }

                self.pendingRequests[id] = { result in
                    continuation.resume(with: result)
                }

                if timeout > 0 {
                    let timeoutItem = DispatchWorkItem { [weak self] in
                        guard let self else { return }
                        if let pending = self.pendingRequests.removeValue(forKey: id) {
                            self.pendingTimeouts.removeValue(forKey: id)
                            pending(.failure(GatewayClientError.requestTimedOut(method: method)))
                        }
                    }
                    self.pendingTimeouts[id] = timeoutItem
                    self.stateQueue.asyncAfter(deadline: .now() + timeout, execute: timeoutItem)
                }

                socket.send(.string(String(decoding: data, as: UTF8.self))) { [weak self] error in
                    guard let error, let self else { return }
                    self.stateQueue.async {
                        self.pendingTimeouts.removeValue(forKey: id)?.cancel()
                        if let pending = self.pendingRequests.removeValue(forKey: id) {
                            pending(.failure(error))
                        }
                    }
                }
            }
        }
    }

    /// Typed convenience: request expecting a JSON-object result.
    func requestObject(
        _ method: String,
        params: [String: Any] = [:],
        timeout: TimeInterval = JsonRpcGatewayClient.defaultRequestTimeout
    ) async throws -> [String: Any] {
        let raw = try await request(method, params: params, timeout: timeout)
        return raw as? [String: Any] ?? [:]
    }

    // MARK: - Receive loop

    private func startReceiveLoop(for socket: URLSessionWebSocketTask) {
        socket.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure:
                // The delegate close/error callbacks own state transitions;
                // stopping the loop here is enough.
                break
            case .success(let message):
                switch message {
                case .string(let text):
                    self.handleMessage(text)
                case .data(let data):
                    self.handleMessage(String(decoding: data, as: UTF8.self))
                @unknown default:
                    break
                }
                self.stateQueue.async {
                    guard self.socket === socket else { return }
                    self.startReceiveLoop(for: socket)
                }
            }
        }
    }

    private func handleMessage(_ text: String) {
        guard
            let data = text.data(using: .utf8),
            let frame = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        // Response frame: routed to the matching pending request.
        if let id = frame["id"] as? String {
            stateQueue.async {
                self.pendingTimeouts.removeValue(forKey: id)?.cancel()
                guard let pending = self.pendingRequests.removeValue(forKey: id) else { return }
                if let errorBody = frame["error"] as? [String: Any] {
                    let message = errorBody["message"] as? String ?? "Fabric RPC failed"
                    pending(.failure(GatewayClientError.rpc(message: message)))
                } else {
                    pending(.success(frame["result"]))
                }
            }
            return
        }

        // Event frame.
        guard
            frame["method"] as? String == "event",
            let params = frame["params"] as? [String: Any],
            let type = params["type"] as? String
        else { return }

        let event = GatewayEvent(
            type: type,
            sessionId: params["session_id"] as? String,
            payload: params["payload"] as? [String: Any] ?? [:]
        )
        DispatchQueue.main.async {
            self.onEvent?(event)
        }
    }

    // MARK: - State plumbing

    private func setState(_ newState: GatewayConnectionState) {
        stateQueue.async { self.setStateLocked(newState) }
    }

    /// Must run on `stateQueue`.
    private func setStateLocked(_ newState: GatewayConnectionState) {
        guard state != newState else { return }
        state = newState
        let handler = onStateChange
        DispatchQueue.main.async { handler?(newState) }
    }

    /// Must run on `stateQueue`.
    private func rejectAllPendingLocked(with error: Error) {
        for (_, item) in pendingTimeouts { item.cancel() }
        pendingTimeouts.removeAll()
        let callbacks = pendingRequests.values
        pendingRequests.removeAll()
        for callback in callbacks {
            callback(.failure(error))
        }
    }
}

// MARK: - URLSessionWebSocketDelegate

extension JsonRpcGatewayClient: URLSessionWebSocketDelegate {
    func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didOpenWithProtocol protocol: String?
    ) {
        stateQueue.async {
            guard self.socket === webSocketTask else { return }
            self.connectTimeoutItem?.cancel()
            self.connectTimeoutItem = nil
            self.setStateLocked(.open)
            self.startReceiveLoop(for: webSocketTask)
            self.connectContinuation?.resume()
            self.connectContinuation = nil
        }
    }

    func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
        reason: Data?
    ) {
        stateQueue.async {
            guard self.socket === webSocketTask else { return }
            self.socket = nil
            self.connectTimeoutItem?.cancel()
            self.connectTimeoutItem = nil
            if let pending = self.connectContinuation {
                self.connectContinuation = nil
                self.setStateLocked(.error)
                pending.resume(throwing: GatewayClientError.connectFailed(underlying: "closed (code \(closeCode.rawValue))"))
            } else {
                self.setStateLocked(.closed)
            }
            self.rejectAllPendingLocked(with: GatewayClientError.socketClosed)
        }
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        guard let error else { return }
        stateQueue.async {
            guard self.socket === task else { return }
            self.socket = nil
            self.connectTimeoutItem?.cancel()
            self.connectTimeoutItem = nil
            if let pending = self.connectContinuation {
                self.connectContinuation = nil
                self.setStateLocked(.error)
                pending.resume(throwing: GatewayClientError.connectFailed(underlying: error.localizedDescription))
            } else {
                self.setStateLocked(.error)
            }
            self.rejectAllPendingLocked(with: error)
        }
    }
}
