package io.github.obliviousodin.fabric.mobile

import io.github.obliviousodin.fabric.mobile.core.GatewayApi
import io.github.obliviousodin.fabric.mobile.core.GatewayCapabilityNegotiation
import io.github.obliviousodin.fabric.mobile.core.GatewayConnectException
import io.github.obliviousodin.fabric.mobile.core.GatewayEvent
import io.github.obliviousodin.fabric.mobile.core.GatewayNotConnectedException
import io.github.obliviousodin.fabric.mobile.core.GatewayRequestTimeoutException
import io.github.obliviousodin.fabric.mobile.core.GatewayResponseUncertainException
import io.github.obliviousodin.fabric.mobile.core.GatewayRpcException
import io.github.obliviousodin.fabric.mobile.core.FabricWorkCursorResetException
import io.github.obliviousodin.fabric.mobile.core.FabricWorkSessionIdentity
import io.github.obliviousodin.fabric.mobile.core.FABRIC_WORK_SYNC_MAX_ITEMS
import io.github.obliviousodin.fabric.mobile.core.LiveSession
import io.github.obliviousodin.fabric.mobile.core.SessionTranscriptMessage
import io.github.obliviousodin.fabric.mobile.core.WorkJobSummary
import io.github.obliviousodin.fabric.mobile.core.WorkProjection
import io.github.obliviousodin.fabric.mobile.core.WorkProjectionPhase
import io.github.obliviousodin.fabric.mobile.core.WorkSyncRequestContext
import io.github.obliviousodin.fabric.mobile.core.WorkSyncScope
import io.github.obliviousodin.fabric.mobile.core.applyWorkCursorReset
import io.github.obliviousodin.fabric.mobile.core.applyWorkSyncPage
import io.github.obliviousodin.fabric.mobile.core.createWorkProjection
import io.github.obliviousodin.fabric.mobile.core.supportsDurableWork
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
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

/** One exact gateway/profile Work namespace plus its local identity epoch. */
private data class DurableWorkScope(
    val generation: Long,
    val syncScope: WorkSyncScope,
)

/** One exact user intent whose durable create outcome may need recovery. */
private data class PendingDurableBackgroundMutation(
    val text: String,
    val title: String,
    val idempotencyKey: String,
    val scope: DurableWorkScope,
)

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
    private val supportsMethod: (String) -> Boolean = { true },
    private val durableWorkNegotiation: () -> GatewayCapabilityNegotiation? = { null },
    private val workGatewayId: () -> String? = { null },
) {
    companion object {
        internal fun approvalFromEvent(event: GatewayEvent): PendingApproval? {
            val requestId = event.payload.stringValue("request_id")
                ?.takeIf { it.isNotBlank() }
                ?: return null
            return PendingApproval(
                command = event.payload.stringValue("command"),
                requestId = requestId,
                summary = event.payload.stringValue("summary")
                    ?: event.payload.stringValue("description"),
            )
        }

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

    /** Validated, server-issued Work namespace for this session only. */
    private val _workIdentity = MutableStateFlow<FabricWorkSessionIdentity?>(null)
    val workIdentity: StateFlow<FabricWorkSessionIdentity?> = _workIdentity.asStateFlow()

    /** Public, sanitized Job after-states. Detail bodies never enter this map. */
    private val _durableBackgroundJobs = MutableStateFlow<Map<String, WorkJobSummary>>(emptyMap())
    val durableBackgroundJobs: StateFlow<Map<String, WorkJobSummary>> =
        _durableBackgroundJobs.asStateFlow()

    /** Fenced projection populated exclusively by validated `job.sync` pages. */
    private val _durableWorkProjection = MutableStateFlow<WorkProjection?>(null)
    val durableWorkProjection: StateFlow<WorkProjection?> = _durableWorkProjection.asStateFlow()

    /** Compose-visible availability, re-evaluated at capability/identity boundaries. */
    private val _backgroundAvailable = MutableStateFlow(false)
    val backgroundAvailable: StateFlow<Boolean> = _backgroundAvailable.asStateFlow()

    var sessionId: String? = null
        private set
    var storedSessionId: String? = resumeStoredSessionId
        private set
    private var eventJob: Job? = null
    private var setupJob: Job? = null
    private var started = false
    private var transportGeneration = 0L
    /** Fences async Work responses when `session.info` selects a new profile. */
    private var workScopeGeneration = 0L
    private val pendingEvents = mutableListOf<GatewayEvent>()
    private val interactionQueue = PendingInteractionQueue()
    private val pendingDurableBackgroundMutations = mutableListOf<PendingDurableBackgroundMutation>()
    private var workSyncInFlight = false
    private var workSyncNeedsAnotherPass = false
    private var workRecoveryRequested = false

    init {
        refreshBackgroundAvailability()
    }

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

    private fun durableWorkAvailable(): Boolean = durableWorkNegotiation().supportsDurableWork()

    private fun refreshBackgroundAvailability() {
        val sessionIsLive = _sessionReady.value && sessionId != null
        _backgroundAvailable.value = when {
            !sessionIsLive -> false
            durableWorkAvailable() -> currentDurableWorkScope()?.let(::isWorkProjectionCurrent) == true
            else -> supportsMethod("prompt.background")
        }
    }

    /**
     * A profile transition is a new Work namespace. Do not carry projection
     * state, known Job IDs, or raw retry text across it.
     */
    private fun installWorkIdentity(identity: FabricWorkSessionIdentity?) {
        if (_workIdentity.value?.profileId != identity?.profileId) {
            workScopeGeneration += 1
            _durableBackgroundJobs.value = emptyMap()
            _durableWorkProjection.value = null
            pendingDurableBackgroundMutations.clear()
            workRecoveryRequested = false
        }
        _workIdentity.value = identity
        refreshBackgroundAvailability()
    }

    private fun currentWorkScope(): WorkSyncScope? = _workIdentity.value
        ?.syncScope(workGatewayId().orEmpty())

    private fun currentDurableWorkScope(): DurableWorkScope? = currentWorkScope()
        ?.let { DurableWorkScope(generation = workScopeGeneration, syncScope = it) }

    private fun isWorkProjectionCurrent(scope: DurableWorkScope): Boolean {
        val projection = _durableWorkProjection.value ?: return false
        return projection.phase == WorkProjectionPhase.CURRENT &&
            projection.gatewayId == scope.syncScope.gatewayId &&
            projection.profileId == scope.syncScope.profileId
    }

    /** Mark a projection stale before a fresh authoritative reconciliation. */
    private fun invalidateDurableWorkProjection() {
        val scope = currentDurableWorkScope()
        val projection = _durableWorkProjection.value
        if (scope != null && projection != null &&
            projection.gatewayId == scope.syncScope.gatewayId &&
            projection.profileId == scope.syncScope.profileId &&
            projection.phase == WorkProjectionPhase.CURRENT
        ) {
            _durableWorkProjection.value = projection.copy(phase = WorkProjectionPhase.SYNCING)
        }
        refreshBackgroundAvailability()
    }

    /**
     * A Work response is publishable only for the exact transport, session,
     * profile epoch, and (when syncing) physical gateway/profile namespace
     * that issued it. This prevents a late response from an old profile from
     * restoring rows after `session.info` has fenced that namespace.
     */
    private fun isCurrentWorkScope(
        transportGeneration: Long,
        sessionId: String,
        expectedScope: DurableWorkScope,
    ): Boolean {
        if (transportGeneration != this.transportGeneration ||
            this.sessionId != sessionId
        ) return false
        return currentDurableWorkScope() == expectedScope
    }

    private fun scheduleDurableWorkRecovery() {
        workRecoveryRequested = true
        scope.launch { syncDurableWork() }
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
                installWorkIdentity(live.workIdentity)
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
                refreshBackgroundAvailability()
                _fatalError.value = null
                scheduleDurableWorkRecovery()
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
        invalidateDurableWorkProjection()
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
                installWorkIdentity(live.workIdentity)
                sessionId = live.sessionId
                val events = eventsForReplay(pendingEvents, live, restored) + live.pendingInteractions
                pendingEvents.clear()
                events.forEach(::handle)
                _sessionReady.value = true
                refreshBackgroundAvailability()
                _fatalError.value = null
                scheduleDurableWorkRecovery()
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
        // Invalidate every Work request even if the identity was already
        // cleared by an earlier transport transition.
        workScopeGeneration++
        setupJob?.cancel()
        setupJob = null
        eventJob?.cancel()
        eventJob = null
        pendingEvents.clear()
        clearInteractions()
        // Retry keys and their raw prompt text never outlive this chat
        // surface. The server-led ledger remains the only durable record.
        pendingDurableBackgroundMutations.clear()
        workRecoveryRequested = false
        _durableBackgroundJobs.value = emptyMap()
        _durableWorkProjection.value = null
        _workIdentity.value = null
        started = false
        sessionId = null
        _sessionReady.value = false
        refreshBackgroundAvailability()
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
            if (!canCall("session.steer", "Steering")) return
            steer(trimmed)
            return
        }

        if (trimmed.startsWith("/")) {
            execSlash(trimmed)
            return
        }

        if (!canCall("prompt.submit", "Sending messages")) return

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
        if (!canCall("session.steer", "Steering")) return
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
        if (!canCall("slash.exec", "Slash commands")) return
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
     * Run the text as a detached background task. A truthfully advertised
     * Durable Work gateway uses a fenced, idempotent `job.create`; legacy
     * `prompt.background` remains only when the feature is absent entirely.
     * The caller keeps a draft unless this controller accepts ownership, so a
     * reconnect or stale Work projection cannot silently lose an intent.
     */
    fun sendInBackground(text: String): Boolean {
        val trimmed = text.trim()
        val sid = sessionId ?: return false
        if (!_sessionReady.value || trimmed.isEmpty()) return false

        val negotiation = durableWorkNegotiation()
        if (negotiation != null && negotiation.supportsDurableWork()) {
            val durableScope = currentDurableWorkScope()
            if (durableScope == null) {
                _messages.value += TranscriptMessage(
                    role = Role.SYSTEM,
                    text = "Durable background work is unavailable until this session provides a valid Work gateway and profile identity.",
                )
                return false
            }
            if (!isWorkProjectionCurrent(durableScope)) {
                scheduleDurableWorkRecovery()
                _messages.value += TranscriptMessage(
                    role = Role.SYSTEM,
                    text = "Durable background work is reconciling. Keep the draft and try again when Work is current.",
                )
                return false
            }
            // Fresh user requests always receive a fresh key. Only reconnect
            // recovery passes an existing mutation back into the sender.
            val mutation = PendingDurableBackgroundMutation(
                text = trimmed,
                title = "Background work",
                idempotencyKey = UUID.randomUUID().toString(),
                scope = durableScope,
            )
            pendingDurableBackgroundMutations += mutation
            _messages.value += TranscriptMessage(role = Role.USER, text = trimmed)
            // Reserve the current projection before the request leaves the
            // device so the menu cannot start a second durable mutation from
            // a stale ledger snapshot.
            invalidateDurableWorkProjection()
            val generation = transportGeneration
            scope.launch {
                submitDurableBackgroundWork(
                    sessionId = sid,
                    mutation = mutation,
                    negotiation = negotiation,
                    transportGeneration = generation,
                    recoveryReplay = false,
                )
            }
            return true
        }

        if (!canCall("prompt.background", "Background work")) return false
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
        return true
    }

    private suspend fun submitDurableBackgroundWork(
        sessionId: String,
        mutation: PendingDurableBackgroundMutation,
        negotiation: GatewayCapabilityNegotiation,
        transportGeneration: Long,
        recoveryReplay: Boolean,
    ) {
        if (!isCurrentWorkScope(transportGeneration, sessionId, mutation.scope) ||
            mutation !in pendingDurableBackgroundMutations
        ) return
        try {
            val receipt = api.createBackgroundWork(
                negotiation = negotiation,
                sessionId = sessionId,
                text = mutation.text,
                title = mutation.title,
                idempotencyKey = mutation.idempotencyKey,
            )
            if (!isCurrentWorkScope(transportGeneration, sessionId, mutation.scope)) return
            pendingDurableBackgroundMutations.removeAll {
                it.idempotencyKey == mutation.idempotencyKey
            }
            _durableBackgroundJobs.value = _durableBackgroundJobs.value + (receipt.job.jobId to receipt.job)
            // A mutation receipt is authoritative for that Job but does not
            // replace the ledger projection. Reconcile before enabling the
            // next durable mutation.
            invalidateDurableWorkProjection()
            if (recoveryReplay) {
                scheduleDurableWorkRecovery()
            } else {
                scope.launch { syncDurableWork() }
            }
            val taskId = receipt.taskId ?: receipt.job.runtimeSessionId
            _messages.value += TranscriptMessage(
                role = Role.INFO,
                text = "Background Job started ${receipt.job.jobId}${taskId?.let { " ($it)" }.orEmpty()}.",
            )
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            if (!isCurrentWorkScope(transportGeneration, sessionId, mutation.scope)) return
            // Preserve the exact key only where the create outcome may be
            // unknown. Reconnect recovery can then replay the original intent;
            // a durable error never falls back to prompt.background.
            if (!mayNeedDurableBackgroundRetry(error)) {
                pendingDurableBackgroundMutations.removeAll {
                    it.idempotencyKey == mutation.idempotencyKey
                }
                scope.launch { syncDurableWork() }
            } else {
                // The server may have accepted the request. Keep the exact
                // key, but fence new durable creates until a later sync. A
                // fresh uncertain request gets one bounded same-key replay
                // after that sync; a replay itself waits for a later gateway
                // recovery signal instead of spinning indefinitely.
                invalidateDurableWorkProjection()
                if (recoveryReplay) {
                    scope.launch { syncDurableWork() }
                } else {
                    scheduleDurableWorkRecovery()
                }
            }
            _messages.value += TranscriptMessage(
                role = Role.SYSTEM,
                text = "Background Job failed: ${error.message ?: error}",
            )
        }
    }

    private suspend fun retryPendingDurableBackgroundMutations() {
        val sid = sessionId ?: return
        val durableScope = currentDurableWorkScope() ?: return
        if (!isWorkProjectionCurrent(durableScope)) return
        val negotiation = durableWorkNegotiation() ?: return
        if (!negotiation.supportsDurableWork()) return
        val generation = transportGeneration

        // Snapshot before awaiting: a successful receipt removes its entry.
        val mutations = pendingDurableBackgroundMutations
            .filter { it.scope == durableScope }
        for (mutation in mutations) {
            if (!isWorkProjectionCurrent(durableScope)) return
            invalidateDurableWorkProjection()
            submitDurableBackgroundWork(
                sessionId = sid,
                mutation = mutation,
                negotiation = negotiation,
                transportGeneration = generation,
                recoveryReplay = true,
            )
            if (!isWorkProjectionCurrent(durableScope)) return
        }
    }

    private suspend fun refreshDurableBackgroundJobs() {
        val sid = sessionId ?: return
        val durableScope = currentDurableWorkScope() ?: return
        if (!isWorkProjectionCurrent(durableScope)) return
        val negotiation = durableWorkNegotiation() ?: return
        if (!negotiation.supportsDurableWork()) return

        val generation = transportGeneration
        val jobIds = _durableBackgroundJobs.value.keys.toList()
        for (jobId in jobIds) {
            try {
                val job = api.getWorkJob(
                    negotiation = negotiation,
                    sessionId = sid,
                    jobId = jobId,
                )
                if (!isCurrentWorkScope(generation, sid, durableScope) ||
                    !isWorkProjectionCurrent(durableScope)
                ) return
                _durableBackgroundJobs.value = _durableBackgroundJobs.value + (jobId to job)
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                // The ledger stays authoritative. A later hint/reconnect can
                // refresh this public after-state; never route through legacy.
            }
        }
    }

    /**
     * Bootstrap or advance one fenced Work projection. `work.changed` only
     * schedules this method; the event payload never becomes client state.
     */
    private suspend fun syncDurableWork() {
        val sid = sessionId ?: return
        val durableScope = currentDurableWorkScope() ?: return
        val workScope = durableScope.syncScope
        val negotiation = durableWorkNegotiation() ?: return
        if (!negotiation.supportsDurableWork()) return

        if (workSyncInFlight) {
            workSyncNeedsAnotherPass = true
            return
        }
        workSyncInFlight = true
        val generation = transportGeneration
        try {
            // A live controller normally never changes gateways, but do not
            // retain raw retry text if an embedding host swaps that identity.
            pendingDurableBackgroundMutations.removeAll { it.scope != durableScope }
            val prior = _durableWorkProjection.value
            if (prior != null &&
                (prior.gatewayId != workScope.gatewayId || prior.profileId != workScope.profileId)
            ) {
                _durableBackgroundJobs.value = emptyMap()
                _durableWorkProjection.value = null
                refreshBackgroundAvailability()
            }
            var state = prior
                ?.takeIf { it.gatewayId == workScope.gatewayId && it.profileId == workScope.profileId }
                ?: createWorkProjection(workScope)
            var mode = if (
                state.phase == WorkProjectionPhase.EMPTY ||
                state.phase == WorkProjectionPhase.BOOTSTRAPPING
            ) {
                WorkProjectionPhase.BOOTSTRAPPING
            } else {
                WorkProjectionPhase.SYNCING
            }
            var pages = 0

            while (pages < 1_000) {
                pages += 1
                val context: WorkSyncRequestContext
                val page = try {
                    when (mode) {
                        WorkProjectionPhase.BOOTSTRAPPING -> {
                            val token = state.nextPageToken
                            context = WorkSyncRequestContext(
                                gatewayId = workScope.gatewayId,
                                profileId = workScope.profileId,
                                pageToken = token,
                            )
                            api.syncWork(
                                negotiation = negotiation,
                                sessionId = sid,
                                pageToken = token,
                                limit = FABRIC_WORK_SYNC_MAX_ITEMS,
                            )
                        }

                        WorkProjectionPhase.SYNCING -> {
                            val ledgerId = state.ledgerId
                            val cursor = state.cursor
                            if (ledgerId == null || cursor == null) {
                                mode = WorkProjectionPhase.BOOTSTRAPPING
                                continue
                            }
                            context = WorkSyncRequestContext(
                                gatewayId = workScope.gatewayId,
                                profileId = workScope.profileId,
                                after = cursor,
                            )
                            api.syncWork(
                                negotiation = negotiation,
                                sessionId = sid,
                                after = cursor,
                                ledgerId = ledgerId,
                                limit = FABRIC_WORK_SYNC_MAX_ITEMS,
                            )
                        }

                        WorkProjectionPhase.EMPTY,
                        WorkProjectionPhase.CURRENT,
                        -> return
                    }
                } catch (reset: FabricWorkCursorResetException) {
                    if (!isCurrentWorkScope(generation, sid, durableScope)) return
                    state = applyWorkCursorReset(state, reset.reset, workScope)
                    _durableWorkProjection.value = state
                    _durableBackgroundJobs.value = emptyMap()
                    refreshBackgroundAvailability()
                    mode = WorkProjectionPhase.BOOTSTRAPPING
                    continue
                }

                if (!isCurrentWorkScope(generation, sid, durableScope)) return
                state = applyWorkSyncPage(state, page, context)
                if (!isCurrentWorkScope(generation, sid, durableScope)) return
                _durableWorkProjection.value = state
                refreshKnownJobStates(state)
                refreshBackgroundAvailability()
                if (state.phase == WorkProjectionPhase.CURRENT) {
                    if (workRecoveryRequested) {
                        workRecoveryRequested = false
                        retryPendingDurableBackgroundMutations()
                    }
                    refreshDurableBackgroundJobs()
                    return
                }
                mode = if (page.mode == "bootstrap") {
                    WorkProjectionPhase.BOOTSTRAPPING
                } else {
                    WorkProjectionPhase.SYNCING
                }
            }
            if (isCurrentWorkScope(generation, sid, durableScope)) {
                // Bound each pass while still ensuring a very large valid
                // ledger cannot strand the projection short of CURRENT.
                workSyncNeedsAnotherPass = true
                refreshBackgroundAvailability()
            }
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
            // Invalid pages and ordinary RPC failures cannot publish partial
            // state: the reducer only returns after a full page has applied.
            refreshBackgroundAvailability()
        } finally {
            workSyncInFlight = false
            if (workSyncNeedsAnotherPass) {
                workSyncNeedsAnotherPass = false
                scope.launch { syncDurableWork() }
            }
        }
    }

    private fun refreshKnownJobStates(projection: WorkProjection) {
        val known = _durableBackgroundJobs.value
        if (known.isEmpty()) return
        val refreshed = known.mapValues { (jobId, previous) -> projection.jobs[jobId] ?: previous }
        if (refreshed != known) _durableBackgroundJobs.value = refreshed
    }

    private fun mayNeedDurableBackgroundRetry(error: Exception): Boolean = when (error) {
        is GatewayNotConnectedException,
        is GatewayConnectException,
        is GatewayRequestTimeoutException,
        is GatewayResponseUncertainException,
        -> true

        is GatewayRpcException -> {
            val retryable = ((error.data as? JsonObject)?.get("retryable") as? JsonPrimitive)
                ?.booleanOrNull
            retryable == true
        }

        else -> false
    }

    fun interrupt() {
        if (!canCall("session.interrupt", "Interrupting a turn")) return
        val sid = sessionId ?: return
        scope.launch {
            runCatching { api.interrupt(sid) }
        }
    }

    fun respondToApproval(allow: Boolean) {
        if (!canCall("approval.respond", "Approval responses")) return
        val sid = sessionId ?: return
        val approval = _pendingApproval.value ?: return
        val interaction = PendingInteraction.Approval(approval)
        val generation = transportGeneration
        scope.launch {
            try {
                api.respondToApproval(
                    sid,
                    approval.requestId,
                    if (allow) "once" else "deny",
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
        val sid = sessionId ?: return
        val prompt = _pendingPrompt.value ?: return
        val responseMethod = when (prompt.kind) {
            PendingPrompt.Kind.CLARIFY -> "clarify.respond"
            PendingPrompt.Kind.SUDO -> "sudo.respond"
            PendingPrompt.Kind.SECRET -> "secret.respond"
        }
        if (!canCall(responseMethod, "Prompt responses")) return
        val interaction = PendingInteraction.Prompt(prompt)
        val generation = transportGeneration
        scope.launch {
            try {
                when (prompt.kind) {
                    PendingPrompt.Kind.CLARIFY -> api.respondToClarify(sid, prompt.requestId, answer)
                    PendingPrompt.Kind.SUDO -> api.respondToSudo(sid, prompt.requestId, answer)
                    PendingPrompt.Kind.SECRET -> api.respondToSecret(sid, prompt.requestId, answer)
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

    private fun canCall(method: String, action: String): Boolean {
        if (supportsMethod(method)) return true
        _messages.value += TranscriptMessage(
            role = Role.SYSTEM,
            text = "$action is unavailable on this gateway.",
        )
        return false
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
            "session.info" -> {
                // Missing or malformed identity deliberately clears the
                // previous binding, rather than retaining a stale namespace.
                installWorkIdentity(FabricWorkSessionIdentity.fromSessionInfo(event.payload))
                // A profile announcement is also an invalidation boundary;
                // it may be the only signal after reconnect, so reconcile
                // from the ledger rather than trusting the event payload.
                scheduleDurableWorkRecovery()
            }

            "work.changed" -> {
                // This is only an invalidation hint. The canonical sync
                // response owns every projection and Job after-state change.
                invalidateDurableWorkProjection()
                val currentScope = currentDurableWorkScope()
                if (currentScope != null && pendingDurableBackgroundMutations.any {
                        it.scope == currentScope
                    }
                ) {
                    scheduleDurableWorkRecovery()
                } else {
                    scope.launch { syncDurableWork() }
                }
            }

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
                val approval = approvalFromEvent(event) ?: return
                enqueueInteraction(PendingInteraction.Approval(approval))
            }

            "clarify.request" -> {
                val requestId = event.payload.stringValue("request_id")
                    ?.takeIf { it.isNotBlank() }
                    ?: return
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
                val requestId = event.payload.stringValue("request_id")
                    ?.takeIf { it.isNotBlank() }
                    ?: return
                enqueueInteraction(PendingInteraction.Prompt(PendingPrompt(
                    kind = PendingPrompt.Kind.SUDO,
                    requestId = requestId,
                    question = event.payload.stringValue("prompt")
                        ?: "Administrator password requested.",
                    choices = emptyList(),
                )))
            }

            "secret.request" -> {
                val requestId = event.payload.stringValue("request_id")
                    ?.takeIf { it.isNotBlank() }
                    ?: return
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
                val jobId = event.payload.stringValue("job_id")
                val text = event.payloadText.orEmpty()
                _messages.value += TranscriptMessage(
                    role = Role.INFO,
                    text = "Background task${taskId?.let { " $it" }.orEmpty()} finished:\n$text",
                )
                if (jobId != null && _durableBackgroundJobs.value.containsKey(jobId)) {
                    scope.launch {
                        syncDurableWork()
                        refreshDurableBackgroundJobs()
                    }
                }
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
