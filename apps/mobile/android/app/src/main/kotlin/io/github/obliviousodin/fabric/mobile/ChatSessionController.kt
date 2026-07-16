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

enum class Role {
    USER,
    ASSISTANT,

    /** Errors and failures — rendered prominently. */
    SYSTEM,

    /** Neutral local notices (slash output, steer/background confirmations). */
    INFO,
}

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
 * A blocking prompt from the agent: `clarify.request` (question + optional
 * choices), `sudo.request` (password), or `secret.request` (secret value).
 * Answered via the matching `*.respond` RPC keyed by `requestId`.
 */
data class PendingPrompt(
    val kind: Kind,
    val requestId: String,
    val question: String,
    val choices: List<String>,
) {
    enum class Kind { CLARIFY, SUDO, SECRET }

    val isSecureEntry: Boolean get() = kind != Kind.CLARIFY
}

/**
 * Wires one chat session to the gateway event stream: creates or resumes
 * the runtime session, submits prompts, and folds streaming events into a
 * renderable transcript. Event names/payloads match the shared contract in
 * apps/shared/src/json-rpc-gateway.ts and tui_gateway/server.py.
 */
class ChatSessionController(
    val api: GatewayApi,
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

    private val _pendingPrompt = MutableStateFlow<PendingPrompt?>(null)
    val pendingPrompt: StateFlow<PendingPrompt?> = _pendingPrompt.asStateFlow()

    private val _sessionReady = MutableStateFlow(false)
    val sessionReady: StateFlow<Boolean> = _sessionReady.asStateFlow()

    private val _fatalError = MutableStateFlow<String?>(null)
    val fatalError: StateFlow<String?> = _fatalError.asStateFlow()

    var sessionId: String? = null
        private set
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

    /**
     * Route a composer submit the way the TUI does: a busy turn gets a
     * steering note, "/..." dispatches a slash command, everything else is
     * a normal prompt.
     */
    fun send(text: String) {
        val trimmed = text.trim()
        val sid = sessionId ?: return
        if (trimmed.isEmpty()) return

        if (_busy.value) {
            steer(trimmed)
            return
        }

        if (trimmed.startsWith("/")) {
            execSlash(trimmed)
            return
        }

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

    /** Inject a note into the running turn without interrupting it. */
    fun steer(text: String) {
        val sid = sessionId ?: return
        scope.launch {
            try {
                val queued = api.steer(sid, text)
                _messages.value += TranscriptMessage(
                    role = Role.INFO,
                    text = if (queued) {
                        "Steering note queued — the agent sees it on its next step."
                    } else {
                        "Steering rejected: no turn is accepting notes right now."
                    },
                )
            } catch (e: Exception) {
                _messages.value += TranscriptMessage(
                    role = Role.SYSTEM,
                    text = "Steer failed: ${e.message ?: e}",
                )
            }
        }
    }

    /** Dispatch a slash command (`/status`, `/model`, skills, quick commands…). */
    fun execSlash(command: String) {
        val sid = sessionId ?: return
        _messages.value += TranscriptMessage(role = Role.USER, text = command)
        scope.launch {
            try {
                val output = api.execSlashCommand(sid, command)
                if (!output.isNullOrEmpty()) {
                    _messages.value += TranscriptMessage(role = Role.INFO, text = output)
                }
            } catch (e: Exception) {
                _messages.value += TranscriptMessage(
                    role = Role.SYSTEM,
                    text = "Command failed: ${e.message ?: e}",
                )
            }
        }
    }

    /**
     * Run the text as a detached background task; the result comes back as
     * a `background.complete` event even while other turns run.
     */
    fun sendInBackground(text: String) {
        val trimmed = text.trim()
        val sid = sessionId ?: return
        if (trimmed.isEmpty()) return
        _messages.value += TranscriptMessage(role = Role.USER, text = trimmed)
        scope.launch {
            try {
                val taskId = api.submitBackgroundPrompt(sid, trimmed)
                _messages.value += TranscriptMessage(
                    role = Role.INFO,
                    text = "Background task started${taskId?.let { " ($it)" }.orEmpty()}.",
                )
            } catch (e: Exception) {
                _messages.value += TranscriptMessage(
                    role = Role.SYSTEM,
                    text = "Background task failed: ${e.message ?: e}",
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

    /**
     * Answer the pending clarify/sudo/secret prompt. An empty answer is a
     * valid "dismiss" (the server releases the wait with an empty string).
     */
    fun respondToPrompt(answer: String) {
        val prompt = _pendingPrompt.value ?: return
        _pendingPrompt.value = null
        scope.launch {
            try {
                when (prompt.kind) {
                    PendingPrompt.Kind.CLARIFY -> api.respondToClarify(prompt.requestId, answer)
                    PendingPrompt.Kind.SUDO -> api.respondToSudo(prompt.requestId, answer)
                    PendingPrompt.Kind.SECRET -> api.respondToSecret(prompt.requestId, answer)
                }
            } catch (e: Exception) {
                _messages.value += TranscriptMessage(
                    role = Role.SYSTEM,
                    text = "Prompt reply failed: ${e.message ?: e}",
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

            "clarify.request" -> {
                val requestId = event.payload.stringValue("request_id") ?: return
                val choices = (event.payload["choices"] as? kotlinx.serialization.json.JsonArray)
                    ?.mapNotNull { (it as? JsonPrimitive)?.content }
                    ?: emptyList()
                _pendingPrompt.value = PendingPrompt(
                    kind = PendingPrompt.Kind.CLARIFY,
                    requestId = requestId,
                    question = event.payload.stringValue("question")
                        ?: "The agent has a question.",
                    choices = choices,
                )
            }

            "sudo.request" -> {
                val requestId = event.payload.stringValue("request_id") ?: return
                _pendingPrompt.value = PendingPrompt(
                    kind = PendingPrompt.Kind.SUDO,
                    requestId = requestId,
                    question = event.payload.stringValue("prompt")
                        ?: "Administrator password requested.",
                    choices = emptyList(),
                )
            }

            "secret.request" -> {
                val requestId = event.payload.stringValue("request_id") ?: return
                _pendingPrompt.value = PendingPrompt(
                    kind = PendingPrompt.Kind.SECRET,
                    requestId = requestId,
                    question = event.payload.stringValue("prompt")
                        ?: "A secret value was requested.",
                    choices = emptyList(),
                )
            }

            "background.complete" -> {
                val taskId = event.payload.stringValue("task_id")
                val text = event.payloadText.orEmpty()
                _messages.value += TranscriptMessage(
                    role = Role.INFO,
                    text = "Background task${taskId?.let { " $it" }.orEmpty()} finished:\n$text",
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
