package io.github.obliviousodin.fabric.mobile

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.obliviousodin.fabric.mobile.core.GatewayApi
import io.github.obliviousodin.fabric.mobile.core.GatewayAuthMode
import io.github.obliviousodin.fabric.mobile.core.GatewayConnectionState
import io.github.obliviousodin.fabric.mobile.core.GatewayHttpException
import io.github.obliviousodin.fabric.mobile.core.GatewayRpcException
import io.github.obliviousodin.fabric.mobile.core.GatewayStore
import io.github.obliviousodin.fabric.mobile.core.JsonRpcGatewayClient
import io.github.obliviousodin.fabric.mobile.core.PairingPayload
import io.github.obliviousodin.fabric.mobile.core.SavedGateway
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** Root navigation destinations; state-driven to avoid a nav dependency. */
sealed interface Screen {
    data object Sessions : Screen
    data class Chat(val controller: ChatSessionController, val title: String) : Screen
}

sealed interface ConnectionPhase {
    data object Disconnected : ConnectionPhase
    data object Connecting : ConnectionPhase
    data object Reconnecting : ConnectionPhase
    data object Connected : ConnectionPhase
}

/**
 * App-level state: the saved-gateway library, one shared client/socket, the
 * connect/disconnect lifecycle, and which screen is showing. One socket is
 * active at a time (the desktop renderer is single-socket too); switching
 * servers closes the current socket and opens the next.
 */
class AppViewModel(application: Application) : AndroidViewModel(application) {
    val client = JsonRpcGatewayClient()
    val api = GatewayApi(client)

    private val _phase = MutableStateFlow<ConnectionPhase>(ConnectionPhase.Disconnected)
    val phase: StateFlow<ConnectionPhase> = _phase.asStateFlow()

    private val _screen = MutableStateFlow<Screen>(Screen.Sessions)
    val screen: StateFlow<Screen> = _screen.asStateFlow()

    private val _connectError = MutableStateFlow<String?>(null)
    val connectError: StateFlow<String?> = _connectError.asStateFlow()

    private val _gateways = MutableStateFlow<List<SavedGateway>>(emptyList())
    val gateways: StateFlow<List<SavedGateway>> = _gateways.asStateFlow()

    private val _activeGatewayId = MutableStateFlow<String?>(null)
    val activeGatewayId: StateFlow<String?> = _activeGatewayId.asStateFlow()
    private val _pendingSignInGateway = MutableStateFlow<SavedGateway?>(null)
    val pendingSignInGateway: StateFlow<SavedGateway?> = _pendingSignInGateway.asStateFlow()
    private var connectionAttempt = 0
    private var connectingGatewayId: String? = null
    private var reconnectJob: Job? = null
    private var reconnectFailures = 0
    private var isForeground = true
    private var permitsAutomaticReconnect = false

    val activeGateway: SavedGateway?
        get() = _gateways.value.firstOrNull { it.id == _activeGatewayId.value }

    init {
        _gateways.value = GatewayStore.all(app())
        viewModelScope.launch {
            client.state.collect { state ->
                if (_phase.value == ConnectionPhase.Connected &&
                    (state == GatewayConnectionState.CLOSED || state == GatewayConnectionState.ERROR)
                ) {
                    activeChat()?.onTransportLost()
                    _phase.value = ConnectionPhase.Reconnecting
                    _connectError.value = "Connection lost (${state.name.lowercase()})."
                    permitsAutomaticReconnect = true
                    scheduleReconnect()
                }
            }
        }
    }

    private fun app() = getApplication<Application>()

    // ── Library management ──────────────────────────────────────────────────

    fun canAutoConnect(gateway: SavedGateway): Boolean =
        GatewayStore.canAutoConnect(app(), gateway)

    fun saveTokenGateway(label: String, baseUrl: String, token: String): SavedGateway {
        val existing = _gateways.value.firstOrNull {
            SavedGateway.endpointKey(it.baseUrl) == SavedGateway.endpointKey(baseUrl)
        }
        val gateway = SavedGateway(
            id = existing?.id ?: UUID.randomUUID().toString(),
            label = label.ifBlank { existing?.label ?: SavedGateway.defaultLabel(baseUrl) },
            baseUrl = baseUrl,
            authMode = GatewayAuthMode.TOKEN,
        )
        _gateways.value = GatewayStore.upsert(app(), gateway, token = token)
        return gateway
    }

    fun saveGatedGateway(label: String, baseUrl: String, username: String): SavedGateway {
        val existing = _gateways.value.firstOrNull {
            SavedGateway.endpointKey(it.baseUrl) == SavedGateway.endpointKey(baseUrl)
        }
        val gateway = SavedGateway(
            id = existing?.id ?: UUID.randomUUID().toString(),
            label = label.ifBlank { existing?.label ?: SavedGateway.defaultLabel(baseUrl) },
            baseUrl = baseUrl,
            authMode = GatewayAuthMode.GATED,
            username = username,
        )
        _gateways.value = GatewayStore.upsert(app(), gateway)
        return gateway
    }

    fun removeGateway(id: String) {
        if (_activeGatewayId.value == id || connectingGatewayId == id) disconnect()
        GatewayStore.remove(app(), id)
        _gateways.value = GatewayStore.all(app())
    }

    /** Accept a browser/native pairing deep link without persisting passwords. */
    fun receivePairingUrl(raw: String?) {
        val payload = raw?.let(PairingPayload::parse)
        if (payload == null) {
            _connectError.value = "This link is not a valid Fabric pairing link."
            return
        }
        if (!payload.token.isNullOrEmpty()) {
            val gateway = saveTokenGateway("", payload.baseUrl, payload.token)
            connectToken(gateway)
        } else {
            _pendingSignInGateway.value = saveGatedGateway("", payload.baseUrl, "")
        }
    }

    fun consumePendingSignInGateway() {
        _pendingSignInGateway.value = null
    }

    // ── Connect ─────────────────────────────────────────────────────────────

    /** Connect to a saved token server using its stored token (one-tap). */
    fun connectToken(gateway: SavedGateway) {
        val token = GatewayStore.token(app(), gateway.id)
        if (token.isNullOrEmpty()) {
            _connectError.value = "No saved token for ${gateway.label}."
            return
        }
        connect(gateway) {
            val status = GatewayApi.probeStatus(gateway.baseUrl)
            if (status.authRequired) {
                throw GatewayRpcException(
                    "This server now requires sign-in — edit it and switch to a username and password."
                )
            }
            GatewayApi.websocketUrl(gateway.baseUrl, token)
        }
    }

    /**
     * Connect to a saved gated server. A supplied password signs in directly,
     * avoiding an expected failed ticket request for fresh/expired sessions.
     * With no password, reuse a live cookie session or ask the caller to re-auth.
     */
    fun connectGated(gateway: SavedGateway, provider: String, password: String?, otp: String = "") {
        connect(gateway) {
            if (!password.isNullOrEmpty()) {
                api.passwordLogin(gateway.baseUrl, provider, gateway.username, password, otp)
                val ticket = api.mintWsTicket(gateway.baseUrl)
                return@connect GatewayApi.websocketUrlWithTicket(gateway.baseUrl, ticket)
            }

            try {
                val ticket = api.mintWsTicket(gateway.baseUrl)
                GatewayApi.websocketUrlWithTicket(gateway.baseUrl, ticket)
            } catch (e: GatewayHttpException) {
                if (e.statusCode != 401 && e.statusCode != 403) throw e
                throw GatewayRpcException("Sign in to ${gateway.label} to connect.")
            }
        }
    }

    private fun connect(
        gateway: SavedGateway,
        automaticReconnect: Boolean = false,
        resolveWsUrl: suspend () -> String,
    ) {
        if (_phase.value == ConnectionPhase.Connecting) return
        if (automaticReconnect && _phase.value != ConnectionPhase.Reconnecting) return
        if (!automaticReconnect) {
            reconnectJob?.cancel()
            reconnectJob = null
            reconnectFailures = 0
            permitsAutomaticReconnect = false
        }
        // Cancel an open or half-open transport before resolving the new
        // target. JsonRpcGatewayClient also binds reuse to the exact URL and
        // supersedes any older handshake.
        client.close()
        connectionAttempt++
        val attempt = connectionAttempt
        _phase.value = if (automaticReconnect) {
            ConnectionPhase.Reconnecting
        } else {
            ConnectionPhase.Connecting
        }
        connectingGatewayId = gateway.id
        if (!automaticReconnect) _activeGatewayId.value = null
        _connectError.value = null
        viewModelScope.launch {
            try {
                val url = resolveWsUrl()
                val expectedPhase = if (automaticReconnect) {
                    ConnectionPhase.Reconnecting
                } else {
                    ConnectionPhase.Connecting
                }
                if (attempt != connectionAttempt || _phase.value != expectedPhase) return@launch
                client.connect(url)
                if (attempt != connectionAttempt || _phase.value != expectedPhase) return@launch
                if (automaticReconnect) {
                    activeChat()?.resumeAfterReconnect()?.getOrThrow()
                    if (attempt != connectionAttempt || _phase.value != expectedPhase) return@launch
                }
                connectingGatewayId = null
                _activeGatewayId.value = gateway.id
                GatewayStore.setLastActive(app(), gateway.id)
                reconnectFailures = 0
                permitsAutomaticReconnect = true
                _phase.value = ConnectionPhase.Connected
                if (!automaticReconnect) _screen.value = Screen.Sessions
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (attempt != connectionAttempt) return@launch
                connectingGatewayId = null
                _connectError.value = e.message ?: e.toString()
                if (automaticReconnect &&
                    permitsAutomaticReconnect &&
                    _activeGatewayId.value == gateway.id &&
                    reconnectFailures < 4
                ) {
                    reconnectFailures++
                    _phase.value = ConnectionPhase.Reconnecting
                    scheduleReconnect()
                } else {
                    permitsAutomaticReconnect = false
                    if (!automaticReconnect) _activeGatewayId.value = null
                    _phase.value = ConnectionPhase.Disconnected
                }
            }
        }
    }

    fun onForeground() {
        isForeground = true
        if (_phase.value == ConnectionPhase.Reconnecting) scheduleReconnect(immediate = true)
    }

    fun onBackground() {
        isForeground = false
        reconnectJob?.cancel()
        reconnectJob = null
        if (_phase.value == ConnectionPhase.Connected) {
            permitsAutomaticReconnect = true
            activeChat()?.onTransportLost()
            _phase.value = ConnectionPhase.Reconnecting
            client.close()
        }
    }

    fun retryConnection() {
        if (activeGateway == null ||
            _phase.value == ConnectionPhase.Connected ||
            _phase.value == ConnectionPhase.Connecting
        ) return
        reconnectFailures = 0
        permitsAutomaticReconnect = true
        _phase.value = ConnectionPhase.Reconnecting
        scheduleReconnect(immediate = true)
    }

    private fun scheduleReconnect(immediate: Boolean = false) {
        if (!isForeground ||
            !permitsAutomaticReconnect ||
            _phase.value != ConnectionPhase.Reconnecting ||
            activeGateway == null ||
            reconnectJob != null
        ) return

        val delayMs = if (immediate) 0L else minOf(500L shl reconnectFailures, 8_000L)
        reconnectJob = viewModelScope.launch {
            delay(delayMs)
            reconnectJob = null
            reconnectActiveGateway()
        }
    }

    private fun reconnectActiveGateway() {
        val gateway = activeGateway ?: return
        when (gateway.authMode) {
            GatewayAuthMode.TOKEN -> {
                val token = GatewayStore.token(app(), gateway.id)
                if (token.isNullOrEmpty()) {
                    permitsAutomaticReconnect = false
                    _phase.value = ConnectionPhase.Disconnected
                    _connectError.value = "The saved credential is unavailable. Add this server again."
                    return
                }
                connect(gateway, automaticReconnect = true) {
                    val status = GatewayApi.probeStatus(gateway.baseUrl)
                    if (status.authRequired) {
                        throw GatewayRpcException("This server now requires sign-in.")
                    }
                    GatewayApi.websocketUrl(gateway.baseUrl, token)
                }
            }
            GatewayAuthMode.GATED -> connect(gateway, automaticReconnect = true) {
                val ticket = api.mintWsTicket(gateway.baseUrl)
                GatewayApi.websocketUrlWithTicket(gateway.baseUrl, ticket)
            }
        }
    }

    fun disconnect() {
        connectionAttempt++
        permitsAutomaticReconnect = false
        reconnectJob?.cancel()
        reconnectJob = null
        reconnectFailures = 0
        connectingGatewayId = null
        activeChat()?.stop()
        _activeGatewayId.value = null
        _screen.value = Screen.Sessions
        _phase.value = ConnectionPhase.Disconnected
        client.close()
    }

    // ── In-server navigation ─────────────────────────────────────────────────

    fun openNewChat() = openChat(resumeStoredSessionId = null, title = "New chat")

    fun openSession(storedSessionId: String, title: String) =
        openChat(resumeStoredSessionId = storedSessionId, title = title)

    fun backToSessions() {
        activeChat()?.stop()
        _screen.value = Screen.Sessions
    }

    private fun openChat(resumeStoredSessionId: String?, title: String) {
        val controller = ChatSessionController(
            api = api,
            scope = viewModelScope,
            resumeStoredSessionId = resumeStoredSessionId,
        )
        controller.start()
        _screen.value = Screen.Chat(controller, title)
    }

    private fun activeChat(): ChatSessionController? =
        (_screen.value as? Screen.Chat)?.controller

    override fun onCleared() {
        activeChat()?.stop()
        client.close()
    }
}
