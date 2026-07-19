package io.github.obliviousodin.fabric.mobile

import io.github.obliviousodin.fabric.mobile.core.ActiveSession
import io.github.obliviousodin.fabric.mobile.core.GatewayEvent
import io.github.obliviousodin.fabric.mobile.core.LiveSession
import io.github.obliviousodin.fabric.mobile.core.SessionInflight
import io.github.obliviousodin.fabric.mobile.core.SessionTranscriptMessage
import io.github.obliviousodin.fabric.mobile.core.gatewayRpcException
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ResumeHistoryTest {
    @Test
    fun resumePayloadRestoresHistoryAndInflightTurnInOrder() {
        val payload = buildJsonObject {
            put("session_id", "runtime-123")
            put("session_key", "stored-authoritative")
            put("history_version", 7)
            put("running", true)
            put("pending_interactions", buildJsonArray {
                add(buildJsonObject {
                    put("type", "clarify.request")
                    put("payload", buildJsonObject {
                        put("request_id", "clarify-1")
                        put("question", "Choose one")
                    })
                })
                add(buildJsonObject {
                    put("type", "approval.request")
                    put("payload", buildJsonObject {
                        put("request_id", "approval-1")
                        put("description", "Run a command")
                    })
                })
            })
            put("inflight", buildJsonObject {
                put("user", "Follow-up question")
                put("assistant", "Partial answer")
                put("streaming", true)
            })
            put("messages", buildJsonArray {
                add(buildJsonObject {
                    put("role", "user")
                    put("text", "Hello from the phone")
                })
                add(buildJsonObject {
                    put("role", "assistant")
                    put("text", "Hello from Fabric")
                })
                add(buildJsonObject {
                    put("role", "tool")
                    put("name", "terminal")
                    put("context", "terminal · pwd")
                })
                add(buildJsonObject {
                    put("role", "system")
                    put("text", "Conversation restored")
                })
                add(buildJsonObject {
                    put("role", "assistant")
                    put("text", "")
                    put("reasoning", "Considering the options")
                })
                add(buildJsonObject {
                    put("role", "assistant")
                    put("text", "")
                    put("codex_reasoning_items", buildJsonArray {
                        add(buildJsonObject { put("summary", "Structured thought") })
                    })
                })
                add(buildJsonObject {
                    put("role", "assistant")
                    put("text", "   ")
                })
                add(buildJsonObject {
                    put("role", "unknown")
                    put("text", "ignored")
                })
            })
        }

        val live = LiveSession.fromResumePayload(payload, "stored-456")

        assertEquals("runtime-123", live.sessionId)
        assertEquals("stored-authoritative", live.storedSessionId)
        assertEquals(7, live.historyVersion)
        assertTrue(live.running)
        assertEquals(listOf("clarify.request", "approval.request"), live.pendingInteractions.map { it.type })
        assertEquals(listOf("runtime-123", "runtime-123"), live.pendingInteractions.map { it.sessionId })
        assertEquals(
            SessionInflight("Follow-up question", "Partial answer", streaming = true),
            live.inflight,
        )
        assertEquals(
            listOf(
                SessionTranscriptMessage(SessionTranscriptMessage.Role.USER, "Hello from the phone"),
                SessionTranscriptMessage(SessionTranscriptMessage.Role.ASSISTANT, "Hello from Fabric"),
                SessionTranscriptMessage(SessionTranscriptMessage.Role.TOOL, "terminal · pwd"),
                SessionTranscriptMessage(SessionTranscriptMessage.Role.SYSTEM, "Conversation restored"),
                SessionTranscriptMessage(
                    SessionTranscriptMessage.Role.ASSISTANT,
                    "",
                    reasoning = "Considering the options",
                ),
                SessionTranscriptMessage(
                    SessionTranscriptMessage.Role.ASSISTANT,
                    "",
                    reasoning = "Structured thought",
                ),
            ),
            live.messages,
        )

        val transcript = ChatSessionController.restoredMessages(live)
        assertEquals(
            listOf(
                Role.USER,
                Role.ASSISTANT,
                Role.INFO,
                Role.INFO,
                Role.INFO,
                Role.INFO,
                Role.USER,
                Role.ASSISTANT,
            ),
            transcript.map { it.role },
        )
        assertEquals(
            listOf(
                "Hello from the phone",
                "Hello from Fabric",
                "terminal · pwd",
                "Conversation restored",
                "Thinking…\nConsidering the options",
                "Thinking…\nStructured thought",
                "Follow-up question",
                "Partial answer",
            ),
            transcript.map { it.text },
        )
        assertEquals(
            listOf(false, false, false, false, false, false, false, true),
            transcript.map { it.streaming },
        )
    }

    @Test
    fun resumePayloadFallsBackToStoredSessionId() {
        val live = LiveSession.fromResumePayload(buildJsonObject {}, "stored-session")

        assertEquals("stored-session", live.sessionId)
        assertTrue(live.messages.isEmpty())
        assertFalse(live.running)
        assertNull(live.inflight)
    }

    @Test
    fun replayDropsOnlyFramesAlreadyRepresentedByHistorySnapshot() {
        val live = LiveSession(
            sessionId = "runtime-123",
            storedSessionId = "stored-456",
            messages = listOf(
                SessionTranscriptMessage(SessionTranscriptMessage.Role.ASSISTANT, "Completed answer"),
            ),
            historyVersion = 1,
        )
        val restored = ChatSessionController.restoredMessages(live)
        val events = listOf(
            event("message.start"),
            event("message.delta", "Completed answer"),
            event("thinking.delta", "Stale thought"),
            event("tool.start", "terminal"),
            event("status.update", "Done"),
            event("message.complete", "Completed answer", historyVersion = 1, historyPersisted = true),
            event("message.start"),
            event("message.delta", "Next answer"),
        )

        val replay = ChatSessionController.eventsForReplay(events, live, restored)

        assertEquals(listOf("message.start", "message.delta"), replay.map { it.type })
    }

    @Test
    fun replayDoesNotInferSnapshotCoverageFromEqualTextWithoutHistoryVersion() {
        val live = LiveSession(
            sessionId = "runtime-123",
            storedSessionId = "stored-456",
            messages = listOf(
                SessionTranscriptMessage(SessionTranscriptMessage.Role.ASSISTANT, "Repeated answer"),
            ),
        )
        val events = listOf(
            event("message.start"),
            event("message.delta", "Repeated answer"),
            event("message.complete", "Repeated answer"),
        )

        val replay = ChatSessionController.eventsForReplay(events, live, emptyList())

        assertEquals(listOf("message.start", "message.delta", "message.complete"), replay.map { it.type })
    }

    @Test
    fun inflightSnapshotKeepsAuthoritativeCompletionForRepeatedReply() {
        val live = LiveSession(
            sessionId = "runtime-123",
            storedSessionId = "stored-456",
            messages = listOf(
                SessionTranscriptMessage(SessionTranscriptMessage.Role.ASSISTANT, "Same answer"),
            ),
            running = true,
            inflight = SessionInflight("Ask again", "Same answer", streaming = true),
        )
        val restored = ChatSessionController.restoredMessages(live)
        val events = listOf(
            event("message.start"),
            event("message.delta", "Same answer"),
            event("message.complete", "Same answer"),
        )

        val replay = ChatSessionController.eventsForReplay(events, live, restored)

        assertEquals(listOf(Role.ASSISTANT, Role.USER, Role.ASSISTANT), restored.map { it.role })
        assertEquals(listOf("message.complete"), replay.map { it.type })
    }

    @Test
    fun inflightReplayIgnoresOtherSessionsAsCompletionBoundaries() {
        val live = LiveSession(
            sessionId = "runtime-123",
            storedSessionId = "stored-456",
            running = true,
            inflight = SessionInflight("Question", "Partial", streaming = true),
        )
        val events = listOf(
            event("message.complete", "Other", sessionId = "other-session"),
            event("message.start"),
            event("message.delta", "Partial"),
            event("message.complete", "Final"),
        )

        val replay = ChatSessionController.eventsForReplay(events, live, emptyList())

        assertEquals(listOf("other-session", live.sessionId), replay.map { it.sessionId })
        assertEquals(listOf("message.complete", "message.complete"), replay.map { it.type })
    }

    @Test
    fun historyVersionPreservesLegitimateRepeatedReplyAfterSnapshot() {
        val live = LiveSession(
            sessionId = "runtime-123",
            storedSessionId = "stored-456",
            messages = listOf(
                SessionTranscriptMessage(SessionTranscriptMessage.Role.ASSISTANT, "Same answer"),
            ),
            historyVersion = 3,
        )
        val restored = ChatSessionController.restoredMessages(live)
        val events = listOf(
            event("message.start"),
            event("message.delta", "Same answer"),
            event("message.complete", "Same answer", historyVersion = 4, historyPersisted = true),
        )

        val replay = ChatSessionController.eventsForReplay(events, live, restored)

        assertEquals(listOf("message.start", "message.delta", "message.complete"), replay.map { it.type })
    }

    @Test
    fun historyVersionDropsCompletionAlreadyCoveredBySnapshot() {
        val live = LiveSession(
            sessionId = "runtime-123",
            storedSessionId = "stored-456",
            messages = listOf(
                SessionTranscriptMessage(SessionTranscriptMessage.Role.ASSISTANT, "Completed answer"),
            ),
            historyVersion = 3,
        )
        val restored = ChatSessionController.restoredMessages(live)
        val events = listOf(
            event("message.start"),
            event("message.delta", "Completed answer"),
            event("message.complete", "Completed answer", historyVersion = 3, historyPersisted = true),
            event("status.update", "Done"),
        )

        val replay = ChatSessionController.eventsForReplay(events, live, restored)

        assertEquals(listOf("status.update"), replay.map { it.type })
    }

    @Test
    fun unpersistedCompletionIsNotHiddenByHistoryVersion() {
        val live = LiveSession(
            sessionId = "runtime-123",
            storedSessionId = "stored-456",
            messages = listOf(
                SessionTranscriptMessage(SessionTranscriptMessage.Role.ASSISTANT, "Earlier answer"),
            ),
            historyVersion = 3,
        )
        val restored = ChatSessionController.restoredMessages(live)
        val completion = event(
            "message.complete",
            "Unsaved response",
            historyVersion = 3,
            historyPersisted = false,
        )

        val replay = ChatSessionController.eventsForReplay(listOf(completion), live, restored)

        assertEquals(listOf("message.complete"), replay.map { it.type })
    }

    @Test
    fun unpersistedCompletionSurfacesServerWarning() {
        val unsaved = event(
            "message.complete",
            historyPersisted = false,
            warning = "History storage is unavailable.",
        )
        val saved = event("message.complete", historyPersisted = true)

        assertEquals(
            "History storage is unavailable.",
            ChatSessionController.persistenceWarning(unsaved),
        )
        assertNull(ChatSessionController.persistenceWarning(saved))
    }

    @Test
    fun rpcErrorPreservesCodeAndData() {
        val error = gatewayRpcException(buildJsonObject {
            put("message", "Approval required")
            put("code", 4091)
            put("data", buildJsonObject { put("retryable", false) })
        })

        assertEquals("Approval required", error.message)
        assertEquals(4091, error.code)
        assertEquals(buildJsonObject { put("retryable", false) }, error.data)
    }

    @Test
    fun pendingInteractionQueuePreservesOrderAndDeduplicatesByIdentity() {
        val approval = PendingInteraction.Approval(PendingApproval("pwd", "approval-1", "Run command"))
        val duplicateCommandApproval = PendingInteraction.Approval(
            PendingApproval("pwd", "approval-2", "Run command"),
        )
        val promptOne = PendingInteraction.Prompt(PendingPrompt(
            PendingPrompt.Kind.CLARIFY,
            "prompt-1",
            "First version",
            emptyList(),
        ))
        val promptTwo = PendingInteraction.Prompt(PendingPrompt(
            PendingPrompt.Kind.SECRET,
            "prompt-2",
            "Secret",
            emptyList(),
        ))
        val updatedPromptOne = PendingInteraction.Prompt(PendingPrompt(
            PendingPrompt.Kind.CLARIFY,
            "prompt-1",
            "Updated version",
            listOf("Yes"),
        ))

        val queue = PendingInteractionQueue()
        queue.enqueue(approval)
        queue.enqueue(duplicateCommandApproval)
        queue.enqueue(promptOne)
        queue.enqueue(promptTwo)
        queue.enqueue(updatedPromptOne)

        assertEquals(
            listOf(
                approval.identity,
                duplicateCommandApproval.identity,
                promptTwo.identity,
                updatedPromptOne.identity,
            ),
            queue.items.map { it.identity },
        )
        assertEquals(updatedPromptOne, queue.items.last())
        queue.remove(approval)
        assertEquals(duplicateCommandApproval, queue.first)
        queue.clear()
        assertTrue(queue.items.isEmpty())
    }

    @Test
    fun approvalEventsRequireAnAuthoritativeRequestId() {
        val missing = GatewayEvent(
            type = "approval.request",
            sessionId = "runtime-123",
            payload = buildJsonObject { put("description", "Run a command") },
        )
        val blank = GatewayEvent(
            type = "approval.request",
            sessionId = "runtime-123",
            payload = buildJsonObject { put("request_id", "  ") },
        )
        val valid = GatewayEvent(
            type = "approval.request",
            sessionId = "runtime-123",
            payload = buildJsonObject {
                put("request_id", "approval-1")
                put("command", "pwd")
            },
        )

        assertNull(ChatSessionController.approvalFromEvent(missing))
        assertNull(ChatSessionController.approvalFromEvent(blank))
        assertEquals("approval-1", ChatSessionController.approvalFromEvent(valid)?.requestId)
    }

    @Test
    fun activeSessionUsesStableSessionKeyForNavigation() {
        val session = ActiveSession.fromJson(buildJsonObject {
            put("id", "runtime-123")
            put("session_key", "stored-456")
            put("title", "Active chat")
            put("status", "working")
        })

        assertEquals("runtime-123", session?.id)
        assertEquals("stored-456", session?.sessionKey)
    }

    private fun event(
        type: String,
        text: String? = null,
        historyVersion: Int? = null,
        historyPersisted: Boolean? = null,
        warning: String? = null,
        sessionId: String = "runtime-123",
    ) = GatewayEvent(
        type = type,
        sessionId = sessionId,
        payload = buildJsonObject {
            if (text != null) put("text", text)
            if (historyVersion != null) put("history_version", historyVersion)
            if (historyPersisted != null) put("history_persisted", historyPersisted)
            if (warning != null) put("warning", warning)
        },
    )
}
