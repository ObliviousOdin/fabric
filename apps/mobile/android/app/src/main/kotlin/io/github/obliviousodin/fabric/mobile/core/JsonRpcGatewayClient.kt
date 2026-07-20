package io.github.obliviousodin.fabric.mobile.core

import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString

/** Connection lifecycle, mirroring `ConnectionState` in apps/shared/src/json-rpc-gateway.ts. */
enum class GatewayConnectionState { IDLE, CONNECTING, OPEN, CLOSED, ERROR }

/**
 * A server-pushed frame: `{"jsonrpc":"2.0","method":"event","params":{...}}`.
 * `type` values are the GatewayEventName strings shared with the desktop
 * renderer (message.delta, tool.start, approval.request, ...).
 */
data class GatewayEvent(
    val type: String,
    val sessionId: String?,
    val payload: JsonObject,
) {
    val payloadText: String?
        get() = (payload["text"] as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNullSafe()
}

private fun kotlinx.serialization.json.JsonPrimitive.contentOrNullSafe(): String? =
    if (this is kotlinx.serialization.json.JsonNull) null else content

class GatewayRpcException(
    message: String,
    val code: Int? = null,
    val data: JsonElement? = null,
) : Exception(message)

internal fun gatewayRpcException(error: JsonObject): GatewayRpcException {
    val message = (error["message"] as? kotlinx.serialization.json.JsonPrimitive)
        ?.contentOrNullSafe() ?: "Fabric RPC failed"
    val code = (error["code"] as? kotlinx.serialization.json.JsonPrimitive)?.content?.toIntOrNull()
    return GatewayRpcException(message, code, error["data"])
}

class GatewayNotConnectedException : Exception("gateway not connected")

class GatewayConnectException(message: String, cause: Throwable? = null) : Exception(message, cause)

/** An RPC may have reached the gateway before its response timed out. */
class GatewayRequestTimeoutException(method: String) : Exception("request timed out: $method")

/**
 * A WebSocket failed after a request was handed to OkHttp but before its
 * response arrived. Callers must treat a mutation's outcome as unknown and
 * replay it only with the original idempotency key.
 */
class GatewayResponseUncertainException(message: String, cause: Throwable? = null) :
    Exception(message, cause)

/**
 * JSON-RPC 2.0 client over a single WebSocket.
 *
 * Kotlin port of `apps/shared/src/json-rpc-gateway.ts` — the same wire
 * contract the desktop renderer uses against `fabric serve` (`/api/ws`):
 * string ids with an `"r"` prefix, a pending-request map with per-request
 * timeouts, response frames keyed by id, and unsolicited `method == "event"`
 * frames fanned out to subscribers.
 */
class JsonRpcGatewayClient(
    httpClient: OkHttpClient? = null,
) {
    companion object {
        const val DEFAULT_REQUEST_TIMEOUT_MS = 120_000L

        // A reconnect after sleep/wake must not hang in CONNECTING forever;
        // fail to ERROR so callers can retry (same rationale as the TS client).
        const val DEFAULT_CONNECT_TIMEOUT_MS = 15_000L
    }

    private val json = Json { ignoreUnknownKeys = true }

    private val client: OkHttpClient = httpClient
        ?: OkHttpClient.Builder()
            // JSON-RPC requests carry their own per-call timeouts.
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .pingInterval(30, TimeUnit.SECONDS)
            .build()

    private val nextId = AtomicInteger(0)
    private val pending = ConcurrentHashMap<String, CompletableDeferred<JsonElement?>>()

    @Volatile
    private var socket: WebSocket? = null

    @Volatile
    private var socketUrl: String? = null

    @Volatile
    private var connectHandshake: CompletableDeferred<Unit>? = null

    private val connectionLock = Any()

    private val _state = MutableStateFlow(GatewayConnectionState.IDLE)
    val state: StateFlow<GatewayConnectionState> = _state.asStateFlow()

    private val _events = MutableSharedFlow<GatewayEvent>(extraBufferCapacity = 256)
    val events: SharedFlow<GatewayEvent> = _events.asSharedFlow()

    suspend fun connect(wsUrl: String, timeoutMs: Long = DEFAULT_CONNECT_TIMEOUT_MS) {
        lateinit var handshake: CompletableDeferred<Unit>
        lateinit var attemptSocket: WebSocket
        synchronized(connectionLock) {
            if (_state.value == GatewayConnectionState.OPEN &&
                socket != null &&
                socketUrl == wsUrl
            ) return

            connectHandshake?.completeExceptionally(
                GatewayConnectException("WebSocket connection superseded")
            )
            socket?.cancel()
            rejectAllPending(GatewayNotConnectedException())
            _state.value = GatewayConnectionState.CONNECTING
            handshake = CompletableDeferred()
            connectHandshake = handshake
            socketUrl = wsUrl

            val request = Request.Builder().url(wsUrl).build()
            attemptSocket = client.newWebSocket(request, listener)
            socket = attemptSocket
        }

        try {
            withTimeout(timeoutMs) { handshake.await() }
        } catch (e: TimeoutCancellationException) {
            // Drop the half-open socket so the next connect() starts clean.
            synchronized(connectionLock) {
                if (socket === attemptSocket) {
                    attemptSocket.cancel()
                    socket = null
                    socketUrl = null
                    _state.value = GatewayConnectionState.ERROR
                }
            }
            throw GatewayConnectException("WebSocket connection timed out", e)
        } catch (e: CancellationException) {
            synchronized(connectionLock) {
                if (socket === attemptSocket) {
                    attemptSocket.cancel()
                    socket = null
                    socketUrl = null
                    _state.value = GatewayConnectionState.CLOSED
                }
            }
            throw e
        } finally {
            synchronized(connectionLock) {
                if (connectHandshake === handshake) connectHandshake = null
            }
        }
    }

    fun close() {
        synchronized(connectionLock) {
            val current = socket
            socket = null
            socketUrl = null
            val handshake = connectHandshake
            connectHandshake = null
            current?.cancel()
            _state.value = GatewayConnectionState.CLOSED
            handshake?.completeExceptionally(GatewayNotConnectedException())
            rejectAllPending(GatewayNotConnectedException())
        }
    }

    /**
     * Send a JSON-RPC request and await its response frame. Returns the raw
     * `result` element (a JsonObject for every Fabric method used here).
     */
    suspend fun request(
        method: String,
        params: JsonObject = buildJsonObject {},
        timeoutMs: Long = DEFAULT_REQUEST_TIMEOUT_MS,
    ): JsonElement? {
        val currentSocket = socket
        if (currentSocket == null || _state.value != GatewayConnectionState.OPEN) {
            throw GatewayNotConnectedException()
        }

        val id = "r${nextId.incrementAndGet()}"
        val frame = buildJsonObject {
            put("jsonrpc", "2.0")
            put("id", id)
            put("method", method)
            put("params", params)
        }

        val deferred = CompletableDeferred<JsonElement?>()
        pending[id] = deferred

        if (!currentSocket.send(frame.toString())) {
            pending.remove(id)
            throw GatewayNotConnectedException()
        }

        return try {
            if (timeoutMs > 0) {
                withTimeout(timeoutMs) { deferred.await() }
            } else {
                deferred.await()
            }
        } catch (e: TimeoutCancellationException) {
            throw GatewayRequestTimeoutException(method)
        } finally {
            pending.remove(id)
        }
    }

    suspend fun requestObject(
        method: String,
        params: JsonObject = buildJsonObject {},
        timeoutMs: Long = DEFAULT_REQUEST_TIMEOUT_MS,
    ): JsonObject = request(method, params, timeoutMs) as? JsonObject ?: buildJsonObject {}

    private val listener = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            synchronized(connectionLock) {
                if (webSocket !== socket) return
                _state.value = GatewayConnectionState.OPEN
                connectHandshake?.complete(Unit)
            }
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            if (webSocket !== socket) return
            handleFrame(text)
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            if (webSocket !== socket) return
            handleFrame(bytes.utf8())
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            synchronized(connectionLock) {
                if (webSocket !== socket) return
                socket = null
                socketUrl = null
                _state.value = GatewayConnectionState.CLOSED
                connectHandshake?.completeExceptionally(
                    GatewayConnectException("WebSocket closed during connect (code $code)")
                )
                rejectAllPending(GatewayNotConnectedException())
            }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            synchronized(connectionLock) {
                if (webSocket !== socket) return
                socket = null
                socketUrl = null
                _state.value = GatewayConnectionState.ERROR
                connectHandshake?.completeExceptionally(
                    GatewayConnectException("WebSocket connection failed", t)
                )
                rejectAllPending(
                    GatewayResponseUncertainException(
                        "WebSocket failed while awaiting a response",
                        t,
                    )
                )
            }
        }
    }

    private fun handleFrame(text: String) {
        val frame = runCatching { json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return

        // Response frame: routed to the matching pending request.
        val id = frame["id"]?.let { el ->
            (el as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNullSafe()
        }
        if (id != null) {
            val call = pending.remove(id) ?: return
            val error = frame["error"] as? JsonObject
            if (error != null) {
                call.completeExceptionally(gatewayRpcException(error))
            } else {
                call.complete(frame["result"])
            }
            return
        }

        // Event frame.
        val method = (frame["method"] as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNullSafe()
        if (method != "event") return
        val params = frame["params"] as? JsonObject ?: return
        val type = (params["type"] as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNullSafe() ?: return

        _events.tryEmit(
            GatewayEvent(
                type = type,
                sessionId = (params["session_id"] as? kotlinx.serialization.json.JsonPrimitive)
                    ?.contentOrNullSafe(),
                payload = params["payload"] as? JsonObject ?: buildJsonObject {},
            )
        )
    }

    private fun rejectAllPending(cause: Throwable) {
        val calls = pending.values.toList()
        pending.clear()
        calls.forEach { it.completeExceptionally(cause) }
    }
}
