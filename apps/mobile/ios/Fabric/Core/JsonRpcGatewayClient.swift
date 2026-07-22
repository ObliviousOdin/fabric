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
    case rpc(message: String, code: Int? = nil, data: Any? = nil)

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
        case .rpc(let message, _, _):
            return message
        }
    }

    static func rpc(body: [String: Any]) -> GatewayClientError {
        .rpc(
            message: body["message"] as? String ?? "Fabric RPC failed",
            code: body["code"] as? Int,
            data: body["data"]
        )
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

    /// Foundation defaults WebSocket messages to 1 MiB. Some expected Fabric
    /// responses (notably an enabled pet spritesheet) legitimately exceed that
    /// and otherwise make iOS close an already-authenticated socket with 1009.
    /// Keep explicit headroom without accepting unbounded gateway frames.
    private static let maximumInboundMessageSize = 8 * 1024 * 1024

    var onEvent: ((GatewayEvent) -> Void)?
    var onStateChange: ((GatewayConnectionState) -> Void)?

    private let stateQueue = DispatchQueue(label: "io.github.obliviousodin.fabric.gateway-client")
    private lazy var urlSession = URLSession(
        configuration: .default,
        delegate: self,
        delegateQueue: nil
    )

    private var socket: URLSessionWebSocketTask?
    private var socketURL: URL?
    private var state: GatewayConnectionState = .idle
    private var nextId = 0
    private var pendingRequests: [String: (Result<Any?, Error>) -> Void] = [:]
    private var pendingTimeouts: [String: DispatchWorkItem] = [:]
    private var connectAttemptId = 0
    private var connectContinuation: (id: Int, continuation: CheckedContinuation<Void, Error>)?
    private var connectTimeoutItem: DispatchWorkItem?

    var connectionState: GatewayConnectionState {
        stateQueue.sync { state }
    }

    // MARK: - Connect / close

    func connect(to wsURL: URL, timeout: TimeInterval = JsonRpcGatewayClient.defaultConnectTimeout) async throws {
        let attemptId: Int? = stateQueue.sync {
            if let socket,
               socket.state == .running,
               state == .open,
               socketURL == wsURL {
                return nil
            }

            connectAttemptId += 1
            let attemptId = connectAttemptId
            connectTimeoutItem?.cancel()
            connectTimeoutItem = nil
            let previousConnect = connectContinuation
            connectContinuation = nil
            socket?.cancel()
            socket = nil
            socketURL = nil
            previousConnect?.continuation.resume(
                throwing: GatewayClientError.connectFailed(
                    underlying: "superseded by a newer connection"
                )
            )
            rejectAllPendingLocked(with: GatewayClientError.socketClosed)
            setStateLocked(.connecting)
            return attemptId
        }
        guard let attemptId else { return }

        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            stateQueue.async {
                guard self.state == .connecting,
                      self.connectAttemptId == attemptId else {
                    continuation.resume(throwing: GatewayClientError.socketClosed)
                    return
                }
                let task = self.urlSession.webSocketTask(with: wsURL)
                Self.configureWebSocket(task)
                self.socket = task
                self.socketURL = wsURL
                self.connectContinuation = (attemptId, continuation)

                // A reconnect after sleep/wake must not hang in `.connecting`
                // forever (same rationale as DEFAULT_CONNECT_TIMEOUT_MS in the
                // shared TS client): fail to `.error` so callers can retry.
                let timeoutItem = DispatchWorkItem { [weak self] in
                    guard let self else { return }
                    guard self.connectAttemptId == attemptId,
                          self.socket === task,
                          let pending = self.connectContinuation,
                          pending.id == attemptId else { return }
                    self.connectContinuation = nil
                    self.connectTimeoutItem = nil
                    task.cancel()
                    self.socket = nil
                    self.socketURL = nil
                    self.setStateLocked(.error)
                    pending.continuation.resume(
                        throwing: GatewayClientError.connectFailed(underlying: "timed out")
                    )
                }
                self.connectTimeoutItem = timeoutItem
                self.stateQueue.asyncAfter(deadline: .now() + timeout, execute: timeoutItem)

                task.resume()
            }
        }
    }

    static func configureWebSocket(_ task: URLSessionWebSocketTask) {
        task.maximumMessageSize = maximumInboundMessageSize
    }

    func close() {
        stateQueue.async {
            self.connectAttemptId += 1
            self.connectTimeoutItem?.cancel()
            self.connectTimeoutItem = nil
            let pendingConnect = self.connectContinuation
            self.connectContinuation = nil
            self.socket?.cancel(with: .normalClosure, reason: nil)
            self.socket = nil
            self.socketURL = nil
            self.setStateLocked(.closed)
            pendingConnect?.continuation.resume(throwing: GatewayClientError.socketClosed)
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
            self.stateQueue.async {
                guard self.socket === socket else { return }
                switch result {
                case .failure:
                    // The delegate close/error callbacks own state transitions;
                    // stopping the loop here is enough.
                    break
                case .success(let message):
                    switch message {
                    case .string(let text):
                        self.handleMessageLocked(text)
                    case .data(let data):
                        self.handleMessageLocked(String(decoding: data, as: UTF8.self))
                    @unknown default:
                        break
                    }
                    guard self.socket === socket else { return }
                    self.startReceiveLoop(for: socket)
                }
            }
        }
    }

    /// Parses a frame only after the receive loop has proved it belongs to the
    /// current socket. Must run on `stateQueue`.
    private func handleMessageLocked(_ text: String) {
        guard
            let data = text.data(using: .utf8),
            let frame = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        // Response frame: routed to the matching pending request.
        if let id = frame["id"] as? String {
            pendingTimeouts.removeValue(forKey: id)?.cancel()
            guard let pending = pendingRequests.removeValue(forKey: id) else { return }
            if let errorBody = frame["error"] as? [String: Any] {
                pending(.failure(GatewayClientError.rpc(body: errorBody)))
            } else {
                pending(.success(frame["result"]))
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
        let handler = onEvent
        DispatchQueue.main.async { handler?(event) }
    }

    // MARK: - State plumbing

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
            self.connectContinuation?.continuation.resume()
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
            self.socketURL = nil
            self.connectTimeoutItem?.cancel()
            self.connectTimeoutItem = nil
            if let pending = self.connectContinuation {
                self.connectContinuation = nil
                self.setStateLocked(.error)
                pending.continuation.resume(
                    throwing: GatewayClientError.connectFailed(
                        underlying: "closed (code \(closeCode.rawValue))"
                    )
                )
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
            self.socketURL = nil
            self.connectTimeoutItem?.cancel()
            self.connectTimeoutItem = nil
            if let pending = self.connectContinuation {
                self.connectContinuation = nil
                self.setStateLocked(.error)
                pending.continuation.resume(
                    throwing: GatewayClientError.connectFailed(underlying: error.localizedDescription)
                )
            } else {
                self.setStateLocked(.error)
            }
            self.rejectAllPendingLocked(with: error)
        }
    }
}
