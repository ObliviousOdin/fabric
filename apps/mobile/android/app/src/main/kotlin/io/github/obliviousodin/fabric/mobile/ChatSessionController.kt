package io.github.obliviousodin.fabric.mobile

import io.github.obliviousodin.fabric.mobile.core.GatewayApi
import io.github.obliviousodin.fabric.mobile.core.GatewayEvent
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive

enum class Role { USER, ASSISTANT, SYSTEM }

/**
 * One transcript row. Assistant messages accumulate `message.delta` text
 * while `streaming` is true; `message.complete` finalizes them.
 */
data class TranscriptMessage(
    val id: String = UUID.randomUUID().toString(),
    val role: Role,
    val text: String,
    val streaming: Boolean = false,
)

/** A pending `approval.request` (command arrives pre-redacted server-side). */
data class PendingApproval(
    val command: String?,
    val summary: String?,
)

/**
 * Wires one chat session to the gateway event stream: creates or resumes
 * the runtime session, submits prompts, and folds streaming events into a
 * renderable transcript. Event names/payloads match the shared contract in
 * apps/shared/src/json-rpc-gateway.ts and tui_gateway/server.py.
 */
class ChatSessionController(
    private val api: GatewayApi,
    private val scope: CoroutineScope,
    private val resumeStoredSessionId: String?,
) {
    private val _messages = MutableStateFlow<List<TranscriptMessage>>(emptyList())
    val messages: StateFlow<List<TranscriptMessage>> = _messages.asStateFlow()

    private val _statusLine = MutableStateFlow<String?>(null)
    val statusLine: StateFlow<String?> = _statusLine.asStateFlow()

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy.asStateFlow()

    private val _pendingApproval = MutableStateFlow<PendingApproval?>(null)
    val pendingApproval: StateFlow<PendingApproval?> = _pendingApproval.asStateFlow()

    private val _sessionReady = MutableStateFlow(false)
    val sessionReady: StateFlow<Boolean> = _sessionReady.asStateFlow()

    private val _fatalError = MutableStateFlow<String?>(null)
    val fatalError: StateFlow<String?> = _fatalError.asStateFlow()

    private var sessionId: String? = null
    private var eventJob: Job? = null
    private var started = false

    fun start() {
        if (started) return
        started = true

        eventJob = scope.launch {
            api.client.events.collect { event -> handle(event) }
        }

        scope.launch {
            try {
                val live = if (resumeStoredSessionId != null) {
                    api.resumeSession(resumeStoredSessionId)
                } else {
                    api.createSession()
                }
                if (live.sessionId.isEmpty()) {
                    _fatalError.value = "Gateway returned no session id."
                    return@launch
                }
                sessionId = live.sessionId
                _sessionReady.value = true
            } catch (e: Exception) {
                _fatalError.value = e.message ?: e.toString()
            }
        }
    }

    fun stop() {
        eventJob?.cancel()
        eventJob = null
    }

    fun send(text: String) {
        val trimmed = text.trim()
        val sid = sessionId ?: return
        if (trimmed.isEmpty()) return
        _messages.value += TranscriptMessage(role = Role.USER, text = trimmed)
        _busy.value = true
        scope.launch {
            try {
                api.submitPrompt(sid, trimmed)
            } catch (e: Exception) {
                _busy.value = false
                _messages.value += TranscriptMessage(
                    role = Role.SYSTEM,
                    text = "Send failed: ${e.message ?: e}",
                )
            }
        }
    }

    fun interrupt() {
        val sid = sessionId ?: return
        scope.launch {
            runCatching { api.interrupt(sid) }
        }
    }

    fun respondToApproval(allow: Boolean) {
        val sid = sessionId ?: return
        _pendingApproval.value = null
        scope.launch {
            try {
                api.respondToApproval(sid, if (allow) "allow" else "deny")
            } catch (e: Exception) {
                _messages.value += TranscriptMessage(
                    role = Role.SYSTEM,
                    text = "Approval reply failed: ${e.message ?: e}",
                )
            }
        }
    }

    // -- Event folding --------------------------------------------------------

    private fun handle(event: GatewayEvent) {
        // Events carry the runtime session id; ignore other sessions' traffic.
        val ours = sessionId
        if (event.sessionId != null && ours != null && event.sessionId != ours) return

        when (event.type) {
            "message.start" -> {
                _busy.value = true
                _statusLine.value = null
                _messages.value += TranscriptMessage(role = Role.ASSISTANT, text = "", streaming = true)
            }

            "message.delta" -> {
                val text = event.payloadText ?: return
                appendToStreamingAssistant(text)
            }

            "message.complete" -> {
                _busy.value = false
                _statusLine.value = null
                val current = _messages.value
                val last = current.lastOrNull()
                if (last != null && last.role == Role.ASSISTANT && last.streaming) {
                    // The complete frame carries the final text; prefer it when
                    // the streamed buffer is empty (some paths emit complete-only).
                    val finalText = last.text.ifEmpty { event.payloadText.orEmpty() }
                    _messages.value = current.dropLast(1) +
                        last.copy(text = finalText, streaming = false)
                } else {
                    val text = event.payloadText
                    if (!text.isNullOrEmpty()) {
                        _messages.value = current + TranscriptMessage(role = Role.ASSISTANT, text = text)
                    }
                }
            }

            "thinking.delta" -> _statusLine.value = "Thinking…"

            "status.update" -> {
                _statusLine.value = event.payload.stringValue("text")
                    ?: event.payload.stringValue("kind")
            }

            "tool.start" -> {
                val name = event.payload.stringValue("name")
                    ?: event.payload.stringValue("tool")
                    ?: "tool"
                _statusLine.value = "Running $name…"
            }

            "tool.complete" -> _statusLine.value = null

            "approval.request" -> {
                _pendingApproval.value = PendingApproval(
                    command = event.payload.stringValue("command"),
                    summary = event.payload.stringValue("summary"),
                )
            }

            "error" -> {
                _busy.value = false
                val message = event.payload.stringValue("message") ?: "Unknown gateway error"
                _messages.value += TranscriptMessage(role = Role.SYSTEM, text = message)
            }
        }
    }

    private fun appendToStreamingAssistant(text: String) {
        val current = _messages.value
        val last = current.lastOrNull()
        if (last != null && last.role == Role.ASSISTANT && last.streaming) {
            _messages.value = current.dropLast(1) + last.copy(text = last.text + text)
        } else {
            _messages.value = current + TranscriptMessage(role = Role.ASSISTANT, text = text, streaming = true)
        }
    }
}

private fun kotlinx.serialization.json.JsonObject.stringValue(key: String): String? =
    (this[key] as? JsonPrimitive)?.let { if (it is JsonNull) null else it.content }
