package io.github.obliviousodin.fabric.mobile

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.obliviousodin.fabric.mobile.core.ConnectionSettings
import io.github.obliviousodin.fabric.mobile.core.ConnectionStore
import io.github.obliviousodin.fabric.mobile.core.GatewayApi
import io.github.obliviousodin.fabric.mobile.core.GatewayAuthMode
import io.github.obliviousodin.fabric.mobile.core.GatewayConnectionState
import io.github.obliviousodin.fabric.mobile.core.GatewayRpcException
import io.github.obliviousodin.fabric.mobile.core.JsonRpcGatewayClient
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
 * App-level state: one gateway client/socket for the whole app (the desktop
 * renderer uses the same shape), connect/disconnect lifecycle, and which
 * screen is showing. Lives in a ViewModel so it survives rotation.
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

    val savedSettings: ConnectionSettings?
        get() = ConnectionStore.load(getApplication<Application>())

    init {
        // Server-side close or transport error drops back to the connect
        // screen with the socket state as context.
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

    /**
     * Token-mode connect: loopback/tunnel gateways where the session token
     * is the credential (`?token=` on the WS upgrade).
     */
    fun connect(settings: ConnectionSettings) {
        if (_phase.value == ConnectionPhase.Connecting) return
        _phase.value = ConnectionPhase.Connecting
        _connectError.value = null
        viewModelScope.launch {
            try {
                // Probe first: fail fast with a readable error and refuse the
                // token path against a gated gateway instead of dying on an
                // opaque 4401 at WS upgrade.
                val status = GatewayApi.probeStatus(settings.baseUrl)
                if (status.authRequired) {
                    throw GatewayRpcException(
                        "This gateway requires a sign-in (it rejects token auth). " +
                            "Use the username/password form."
                    )
                }
                client.connect(GatewayApi.websocketUrl(settings.baseUrl, settings.token))
                ConnectionStore.save(getApplication<Application>(), settings)
                _phase.value = ConnectionPhase.Connected
                _screen.value = Screen.Sessions
            } catch (e: Exception) {
                _connectError.value = e.message ?: e.toString()
                _phase.value = ConnectionPhase.Disconnected
            }
        }
    }

    /**
     * Gated-mode connect: provider login (username/password) → cookie
     * session → single-use WS ticket → `?ticket=` upgrade.
     *
     * Tries the ticket mint first: the cookie jar may still hold a live
     * session from an earlier connect, in which case no password round-trip
     * is needed. Falls back to `passwordLogin` on failure.
     */
    fun connectGated(baseUrl: String, provider: String, username: String, password: String) {
        if (_phase.value == ConnectionPhase.Connecting) return
        _phase.value = ConnectionPhase.Connecting
        _connectError.value = null
        viewModelScope.launch {
            try {
                val ticket = try {
                    api.mintWsTicket(baseUrl)
                } catch (_: Exception) {
                    api.passwordLogin(baseUrl, provider, username, password)
                    api.mintWsTicket(baseUrl)
                }
                client.connect(GatewayApi.websocketUrlWithTicket(baseUrl, ticket))
                ConnectionStore.save(
                    getApplication<Application>(),
                    ConnectionSettings(
                        baseUrl = baseUrl,
                        token = "",
                        authMode = GatewayAuthMode.GATED,
                        username = username,
                    ),
                )
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
        _screen.value = Screen.Sessions
        _phase.value = ConnectionPhase.Disconnected
    }

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
