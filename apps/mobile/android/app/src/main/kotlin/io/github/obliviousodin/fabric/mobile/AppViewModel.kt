package io.github.obliviousodin.fabric.mobile

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.obliviousodin.fabric.mobile.core.GatewayApi
import io.github.obliviousodin.fabric.mobile.core.GatewayAuthMode
import io.github.obliviousodin.fabric.mobile.core.GatewayConnectionState
import io.github.obliviousodin.fabric.mobile.core.GatewayRpcException
import io.github.obliviousodin.fabric.mobile.core.GatewayStore
import io.github.obliviousodin.fabric.mobile.core.JsonRpcGatewayClient
import io.github.obliviousodin.fabric.mobile.core.SavedGateway
import java.util.UUID
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

    val activeGateway: SavedGateway?
        get() = _gateways.value.firstOrNull { it.id == _activeGatewayId.value }

    init {
        _gateways.value = GatewayStore.all(app())
        viewModelScope.launch {
            client.state.collect { state ->
                if (_phase.value == ConnectionPhase.Connected &&
                    (state == GatewayConnectionState.CLOSED || state == GatewayConnectionState.ERROR)
                ) {
                    _phase.value = ConnectionPhase.Disconnected
                    _connectError.value = "Connection lost (${state.name.lowercase()})."
                    _screen.value = Screen.Sessions
                }
            }
        }
    }

    private fun app() = getApplication<Application>()

    // ── Library management ──────────────────────────────────────────────────

    fun canAutoConnect(gateway: SavedGateway): Boolean =
        GatewayStore.canAutoConnect(app(), gateway)

    fun saveTokenGateway(label: String, baseUrl: String, token: String): SavedGateway {
        val gateway = SavedGateway(
            id = UUID.randomUUID().toString(),
            label = label.ifBlank { SavedGateway.defaultLabel(baseUrl) },
            baseUrl = baseUrl,
            authMode = GatewayAuthMode.TOKEN,
        )
        _gateways.value = GatewayStore.upsert(app(), gateway, token = token)
        return gateway
    }

    fun saveGatedGateway(label: String, baseUrl: String, username: String): SavedGateway {
        val gateway = SavedGateway(
            id = UUID.randomUUID().toString(),
            label = label.ifBlank { SavedGateway.defaultLabel(baseUrl) },
            baseUrl = baseUrl,
            authMode = GatewayAuthMode.GATED,
            username = username,
        )
        _gateways.value = GatewayStore.upsert(app(), gateway)
        return gateway
    }

    fun removeGateway(id: String) {
        GatewayStore.remove(app(), id)
        _gateways.value = GatewayStore.all(app())
        if (_activeGatewayId.value == id) disconnect()
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
     * Connect to a saved gated server. Tries the ticket mint first (a live
     * cookie session needs no password); with a password, signs in then
     * mints. A null/blank password with no live session surfaces a re-auth
     * error so the caller can prompt.
     */
    fun connectGated(gateway: SavedGateway, provider: String, password: String?, otp: String = "") {
        connect(gateway) {
            try {
                val ticket = api.mintWsTicket(gateway.baseUrl)
                GatewayApi.websocketUrlWithTicket(gateway.baseUrl, ticket)
            } catch (_: Exception) {
                if (password.isNullOrEmpty()) {
                    throw GatewayRpcException("Sign in to ${gateway.label} to connect.")
                }
                api.passwordLogin(gateway.baseUrl, provider, gateway.username, password, otp)
                val ticket = api.mintWsTicket(gateway.baseUrl)
                GatewayApi.websocketUrlWithTicket(gateway.baseUrl, ticket)
            }
        }
    }

    private fun connect(gateway: SavedGateway, resolveWsUrl: suspend () -> String) {
        if (_phase.value == ConnectionPhase.Connecting) return
        if (_phase.value == ConnectionPhase.Connected) client.close()
        _phase.value = ConnectionPhase.Connecting
        _connectError.value = null
        viewModelScope.launch {
            try {
                client.connect(resolveWsUrl())
                _activeGatewayId.value = gateway.id
                GatewayStore.setLastActive(app(), gateway.id)
                _phase.value = ConnectionPhase.Connected
                _screen.value = Screen.Sessions
            } catch (e: Exception) {
                _connectError.value = e.message ?: e.toString()
                _phase.value = ConnectionPhase.Disconnected
            }
        }
    }

    fun disconnect() {
        activeChat()?.stop()
        client.close()
        _activeGatewayId.value = null
        _screen.value = Screen.Sessions
        _phase.value = ConnectionPhase.Disconnected
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
