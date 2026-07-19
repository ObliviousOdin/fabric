package io.github.obliviousodin.fabric.mobile

import io.github.obliviousodin.fabric.mobile.core.GatewayApi
import io.github.obliviousodin.fabric.mobile.core.GatewayEvent
import io.github.obliviousodin.fabric.mobile.core.LiveSession
import io.github.obliviousodin.fabric.mobile.core.SessionTranscriptMessage
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull

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

internal fun SessionTranscriptMessage.toTranscriptMessage(): TranscriptMessage? {
    if (text.isBlank()) {
        val restoredReasoning = reasoning?.takeIf { it.isNotBlank() } ?: return null
        return TranscriptMessage(role = Role.INFO, text = "Thinking…\n$restoredReasoning")
    }
    return TranscriptMessage(
        role = when (role) {
            SessionTranscriptMessage.Role.USER -> Role.USER
            SessionTranscriptMessage.Role.ASSISTANT -> Role.ASSISTANT
            SessionTranscriptMessage.Role.SYSTEM,
            SessionTranscriptMessage.Role.TOOL -> Role.INFO
        },
        text = text,
    )
}

/** A pending `approval.request` (command arrives pre-redacted server-side). */
data class PendingApproval(
    val command: String?,
    val requestId: String,
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

internal sealed interface PendingInteraction {
    val identity: String

    data class Approval(val value: PendingApproval) : PendingInteraction {
        override val identity = "approval:${value.requestId}"
    }

    data class Prompt(val value: PendingPrompt) : PendingInteraction {
        override val identity = "${value.kind}:${value.requestId}"
    }
}

internal class PendingInteractionQueue {
    private val mutableItems = mutableListOf<PendingInteraction>()
    val items: List<PendingInteraction> get() = mutableItems
    val first: PendingInteraction? get() = mutableItems.firstOrNull()

    fun enqueue(interaction: PendingInteraction) {
        mutableItems.removeAll { it.identity == interaction.identity }
        mutableItems += interaction
    }

    fun remove(interaction: PendingInteraction) {
        mutableItems.removeAll { it.identity == interaction.identity }
    }

    fun clear() {
        mutableItems.clear()
    }
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
    resumeStoredSessionId: String?,
) {
    companion object {
        internal fun persistenceWarning(event: GatewayEvent): String? {
            val persisted = (event.payload["history_persisted"] as? JsonPrimitive)?.booleanOrNull
            if (persisted != false) return null
            return event.payload.stringValue("warning")?.trim()?.takeIf { it.isNotEmpty() }
                ?: "This response completed but could not be saved to session history."
        }

        internal fun restoredMessages(
            live: LiveSession,
        ): List<TranscriptMessage> {
            val restored = live.messages.mapNotNull { it.toTranscriptMessage() }.toMutableList()
            live.inflight?.let { inflight ->
                if (inflight.user.isNotEmpty()) {
                    restored += TranscriptMessage(role = Role.USER, text = inflight.user)
                }
                if (inflight.assistant.isNotEmpty() || inflight.streaming) {
                    restored += TranscriptMessage(
                        role = Role.ASSISTANT,
                        text = inflight.assistant,
                        streaming = inflight.streaming,
                    )
                }
            }
            return restored
        }

        /** Remove only buffered turns already represented by the resume snapshot. */
        internal fun eventsForReplay(
            events: List<GatewayEvent>,
            live: LiveSession,
            restoredMessages: List<TranscriptMessage>,
        ): List<GatewayEvent> {
            if (live.inflight != null) {
                var completingSnapshotTurn = true
                return events.filter { event ->
                    if (event.sessionId != null && event.sessionId != live.sessionId) return@filter true
                    if (!completingSnapshotTurn) return@filter true
                    when (event.type) {
                        "message.start", "message.delta" -> false
                        "message.complete" -> {
                            completingSnapshotTurn = false
                            true
                        }
                        else -> true
                    }
                }
            }

            val bufferedTurnTypes = setOf(
                "approval.request", "clarify.request", "message.delta", "message.start",
                "reasoning.available", "reasoning.delta", "secret.request", "status.update",
                "sudo.request", "thinking.delta", "tool.complete", "tool.generating",
                "tool.progress", "tool.start",
            )
            val replay = mutableListOf<GatewayEvent>()
            val turn = mutableListOf<GatewayEvent>()

            fun flushTurn() {
                replay += turn
                turn.clear()
            }

            events.forEach { event ->
                if (event.sessionId != null && event.sessionId != live.sessionId) {
                    replay += event
                    return@forEach
                }

                if (event.type == "message.complete") {
                    val eventVersion = (event.payload["history_version"] as? JsonPrimitive)?.intOrNull
                    val covered = when {
                        live.historyVersion != null &&
                            (event.payload["history_persisted"] as? JsonPrimitive)?.booleanOrNull == true &&
                            eventVersion != null -> eventVersion <= live.historyVersion
                        else -> false
                    }
                    if (covered) {
                        turn.clear()
                    } else {
                        flushTurn()
                        replay += event
                    }
                    return@forEach
                }

                if (event.type in bufferedTurnTypes) {
                    turn += event
                } else {
                    flushTurn()
                    replay += event
                }
            }

            flushTurn()
            return replay
        }
    }

    private val _messages = MutableStateFlow<List<TranscriptMessage>>(emptyList())
    val messages: StateFlow<List<TranscriptMessage>> = _messages.asStateFlow()

    private val _statusLine = MutableStateFlow<String?>(null)
    val statusLine: StateFlow<String?> = _statusLine.asStateFlow()

    private val _persistenceWarning = MutableStateFlow<String?>(null)
    val persistenceWarning: StateFlow<String?> = _persistenceWarning.asStateFlow()

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
    var storedSessionId: String? = resumeStoredSessionId
        private set
    private var eventJob: Job? = null
    private var setupJob: Job? = null
    private var started = false
    private var transportGeneration = 0L
    private val pendingEvents = mutableListOf<GatewayEvent>()
    private val interactionQueue = PendingInteractionQueue()

    private fun enqueueInteraction(interaction: PendingInteraction) {
        interactionQueue.enqueue(interaction)
        publishActiveInteraction()
    }

    private fun removeInteraction(interaction: PendingInteraction) {
        interactionQueue.remove(interaction)
        publishActiveInteraction()
    }

    private fun clearInteractions() {
        interactionQueue.clear()
        publishActiveInteraction()
    }

    private fun publishActiveInteraction() {
        _pendingApproval.value = null
        _pendingPrompt.value = null
        when (val interaction = interactionQueue.first) {
            is PendingInteraction.Approval -> _pendingApproval.value = interaction.value
            is PendingInteraction.Prompt -> _pendingPrompt.value = interaction.value
            null -> Unit
        }
    }

    fun start() {
        if (started) return
        started = true

        eventJob = scope.launch {
            api.client.events.collect { event -> handle(event) }
        }

        setupJob = scope.launch {
            val generation = transportGeneration
            try {
                val restoring = storedSessionId != null
                val live = storedSessionId?.let { api.resumeSession(it) } ?: api.createSession()
                if (generation != transportGeneration) return@launch
                if (live.sessionId.isEmpty()) {
                    pendingEvents.clear()
                    _fatalError.value = "Gateway returned no session id."
                    return@launch
                }
                val durableId = live.storedSessionId
                if (durableId.isNullOrEmpty()) {
                    pendingEvents.clear()
                    _fatalError.value =
                        "Gateway returned no durable session key. Check Active sessions before starting another chat."
                    return@launch
                }
                storedSessionId = durableId
                if (restoring) {
                    _messages.value = restoredMessages(live)
                    _busy.value = live.running
                }
                clearInteractions()
                sessionId = live.sessionId
                val events = eventsForReplay(pendingEvents, live, _messages.value) +
                    live.pendingInteractions
                pendingEvents.clear()
                events.forEach(::handle)
                _sessionReady.value = true
                _fatalError.value = null
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (generation != transportGeneration) return@launch
                pendingEvents.clear()
                _fatalError.value = if (storedSessionId == null) {
                    "Session creation outcome is unknown. Check Active sessions before starting another chat."
                } else {
                    e.message ?: e.toString()
                }
            } finally {
                setupJob = null
            }
        }
    }

    fun onTransportLost() {
        transportGeneration++
        setupJob?.cancel()
        setupJob = null
        sessionId = null
        _sessionReady.value = false
        pendingEvents.clear()
        clearInteractions()
        _statusLine.value = null
    }

    suspend fun resumeAfterReconnect(): Result<Unit> {
        val durableId = storedSessionId
        if (durableId.isNullOrEmpty()) {
            val message = "Session creation outcome is unknown. Check Active sessions before starting another chat."
            _fatalError.value = message
            return Result.failure(IllegalStateException(message))
        }

        val generation = transportGeneration
        return try {
            val live = api.resumeSession(durableId)
            if (generation != transportGeneration) {
                Result.failure(CancellationException("Transport changed during session resume"))
            } else if (live.sessionId.isEmpty() || live.storedSessionId.isNullOrEmpty()) {
                val message = "Gateway returned an invalid resume snapshot."
                _fatalError.value = message
                Result.failure(IllegalStateException(message))
            } else {
                val restored = restoredMessages(live)
                _messages.value = restored
                _busy.value = live.running
                clearInteractions()
                _statusLine.value = null
                storedSessionId = live.storedSessionId
                sessionId = live.sessionId
                val events = eventsForReplay(pendingEvents, live, restored) + live.pendingInteractions
                pendingEvents.clear()
                events.forEach(::handle)
                _sessionReady.value = true
                _fatalError.value = null
                Result.success(Unit)
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            if (generation == transportGeneration) {
                pendingEvents.clear()
                _fatalError.value = e.message ?: e.toString()
            }
            Result.failure(e)
        }
    }

    fun stop() {
        transportGeneration++
        setupJob?.cancel()
        setupJob = null
        eventJob?.cancel()
        eventJob = null
        pendingEvents.clear()
        clearInteractions()
        started = false
        sessionId = null
        _sessionReady.value = false
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
        val approval = _pendingApproval.value ?: return
        val interaction = PendingInteraction.Approval(approval)
        val generation = transportGeneration
        scope.launch {
            try {
                api.respondToApproval(
                    sid,
                    approval.requestId,
                    if (allow) "allow" else "deny",
                )
                if (generation == transportGeneration) removeInteraction(interaction)
            } catch (e: Exception) {
                if (generation != transportGeneration) return@launch
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
        val interaction = PendingInteraction.Prompt(prompt)
        val generation = transportGeneration
        scope.launch {
            try {
                when (prompt.kind) {
                    PendingPrompt.Kind.CLARIFY -> api.respondToClarify(prompt.requestId, answer)
                    PendingPrompt.Kind.SUDO -> api.respondToSudo(prompt.requestId, answer)
                    PendingPrompt.Kind.SECRET -> api.respondToSecret(prompt.requestId, answer)
                }
                if (generation == transportGeneration) removeInteraction(interaction)
            } catch (e: Exception) {
                if (generation != transportGeneration) return@launch
                _messages.value += TranscriptMessage(
                    role = Role.SYSTEM,
                    text = "Prompt reply failed: ${e.message ?: e}",
                )
            }
        }
    }

    // -- Event folding --------------------------------------------------------

    private fun handle(event: GatewayEvent) {
        if (sessionId == null) {
            // `session.resume` and live events share one socket. Buffer anything
            // that arrives while the resume RPC is in flight, then replay it
            // after the stored transcript is installed so history is not
            // overwritten and live deltas are not lost.
            pendingEvents += event
            return
        }
        // Events carry the runtime session id; ignore other sessions' traffic.
        val ours = sessionId
        if (event.sessionId != null && ours != null && event.sessionId != ours) return

        when (event.type) {
            "message.start" -> {
                _busy.value = true
                _statusLine.value = null
                clearInteractions()
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
                    // The complete frame is authoritative. This also repairs a
                    // resumed in-flight turn when deltas emitted before reconnect
                    // are absent from the local streaming buffer.
                    val finalText = event.payloadText?.takeIf { it.isNotEmpty() } ?: last.text
                    _messages.value = current.dropLast(1) +
                        last.copy(text = finalText, streaming = false)
                } else {
                    val text = event.payloadText
                    if (!text.isNullOrEmpty()) {
                        _messages.value = current + TranscriptMessage(role = Role.ASSISTANT, text = text)
                    }
                }
                if (event.payload["history_persisted"] is JsonPrimitive) {
                    _persistenceWarning.value = persistenceWarning(event)
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
                val command = event.payload.stringValue("command")
                val summary = event.payload.stringValue("summary")
                    ?: event.payload.stringValue("description")
                val requestId = event.payload.stringValue("request_id")
                    ?: "legacy:${command.orEmpty()}:${summary.orEmpty()}"
                enqueueInteraction(PendingInteraction.Approval(PendingApproval(
                    command = command,
                    requestId = requestId,
                    summary = summary,
                )))
            }

            "clarify.request" -> {
                val requestId = event.payload.stringValue("request_id") ?: return
                val choices = (event.payload["choices"] as? kotlinx.serialization.json.JsonArray)
                    ?.mapNotNull { (it as? JsonPrimitive)?.content }
                    ?: emptyList()
                enqueueInteraction(PendingInteraction.Prompt(PendingPrompt(
                    kind = PendingPrompt.Kind.CLARIFY,
                    requestId = requestId,
                    question = event.payload.stringValue("question")
                        ?: "The agent has a question.",
                    choices = choices,
                )))
            }

            "sudo.request" -> {
                val requestId = event.payload.stringValue("request_id") ?: return
                enqueueInteraction(PendingInteraction.Prompt(PendingPrompt(
                    kind = PendingPrompt.Kind.SUDO,
                    requestId = requestId,
                    question = event.payload.stringValue("prompt")
                        ?: "Administrator password requested.",
                    choices = emptyList(),
                )))
            }

            "secret.request" -> {
                val requestId = event.payload.stringValue("request_id") ?: return
                enqueueInteraction(PendingInteraction.Prompt(PendingPrompt(
                    kind = PendingPrompt.Kind.SECRET,
                    requestId = requestId,
                    question = event.payload.stringValue("prompt")
                        ?: "A secret value was requested.",
                    choices = emptyList(),
                )))
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
