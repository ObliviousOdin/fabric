package io.github.obliviousodin.fabric.mobile.core

import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** JVM conformance tests against the shared fabric.work v1 fixture corpus. */
class WorkContractTest {
    @Test
    fun fixtureCorpusMatchesItsDeclaredParseOutcomes() {
        val cases = (fixture("manifest.json") as JsonObject)["cases"]
            ?.let { it as? kotlinx.serialization.json.JsonArray }
            ?: error("Work fixture manifest is missing cases")

        cases.forEach { item ->
            val row = item as JsonObject
            val file = row.getValue("file").toString().trim('"')
            val kind = row.getValue("kind").toString().trim('"')
            val expected = row.getValue("expected").toString().trim('"')
            val outcome = when (kind) {
                "page" -> when (parseWorkSyncPage(fixture(file))) {
                    is WorkContractParseResult.Verified -> "verified"
                    is WorkContractParseResult.Incompatible -> "incompatible"
                    is WorkContractParseResult.Invalid -> "invalid"
                }
                "reset" -> when (parseWorkCursorReset(fixture(file))) {
                    is WorkCursorResetParseResult.Verified -> "verified"
                    is WorkCursorResetParseResult.Invalid -> "invalid"
                }
                else -> error("Unknown Work fixture kind $kind")
            }
            assertEquals("fixture $file", expected, outcome)
        }
    }

    @Test
    fun malformedIncompatibleAndAdditiveFixturesFailClosedAtTheRightBoundary() {
        val malformed = parseWorkSyncPage(fixture("malformed.json"))
        assertTrue(malformed is WorkContractParseResult.Invalid)

        val incompatible = parseWorkSyncPage(fixture("incompatible.json"))
        assertEquals(2L, (incompatible as WorkContractParseResult.Incompatible).minimum)

        val additive = page("additive-future.json")
        assertTrue(additive.actionable)
        assertEquals(2L, additive.contract.version)
        assertFalse(additive.jobs.single().actionable)
        assertEquals("future_workflow", additive.jobs.single().kind)
        assertTrue(additive.jobs.single().unknownEnums.any { it.raw == "future_workflow" })
    }

    @Test
    fun appliesBootstrapDeltaTombstoneSensitiveAndTerminalFixturesAtomically() {
        val first = page("bootstrap-page-1.json")
        val second = page("bootstrap-page-2.json")
        val delta = page("delta.json")
        val tombstone = page("tombstone.json")
        val sensitive = page("sensitive-attention.json")
        val terminal = page("terminal.json")
        val scope = WorkSyncScope(gatewayId = "gateway-fixture", profileId = first.workProfileId)

        var projection = createWorkProjection(scope)
        projection = applyWorkSyncPage(
            projection,
            first,
            WorkSyncRequestContext(scope.gatewayId, scope.profileId),
        )
        assertEquals(WorkProjectionPhase.BOOTSTRAPPING, projection.phase)
        assertNull(projection.cursor)
        assertEquals(first.nextPageToken, projection.nextPageToken)

        projection = applyWorkSyncPage(
            projection,
            second,
            WorkSyncRequestContext(scope.gatewayId, scope.profileId, pageToken = first.nextPageToken),
        )
        assertEquals(WorkProjectionPhase.CURRENT, projection.phase)
        assertEquals(100L, projection.cursor)
        assertEquals(2, projection.jobs.size)
        assertEquals(1, projection.attention.size)

        projection = applyWorkSyncPage(
            projection,
            delta,
            WorkSyncRequestContext(scope.gatewayId, scope.profileId, after = projection.cursor),
        )
        assertEquals(101L, projection.cursor)
        assertEquals("running", projection.jobs.getValue(delta.events.single().subjectId).status)

        projection = applyWorkSyncPage(
            projection,
            tombstone,
            WorkSyncRequestContext(scope.gatewayId, scope.profileId, after = projection.cursor),
        )
        assertEquals(103L, projection.cursor)
        assertFalse(projection.jobs.containsKey("job_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"))
        assertFalse(projection.attention.containsKey("attn_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"))
        assertEquals(5L, projection.subjectVersions["job:job_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"])
        assertEquals(3L, projection.subjectVersions["attention:attn_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"])

        projection = applyWorkSyncPage(
            projection,
            sensitive,
            WorkSyncRequestContext(scope.gatewayId, scope.profileId, after = projection.cursor),
        )
        val pending = projection.attention.getValue("attn_ffffffffffffffffffffffffffffffff")
        assertTrue(pending.sensitive)
        assertTrue(pending.actionable)
        assertEquals(listOf("submit", "cancel"), pending.allowedActions)
        assertFalse(pending.publicPayload.containsKey("value"))
        assertEquals(104L, projection.cursor)

        projection = applyWorkSyncPage(
            projection,
            terminal,
            WorkSyncRequestContext(scope.gatewayId, scope.profileId, after = projection.cursor),
        )
        assertEquals(105L, projection.cursor)
        assertEquals("succeeded", projection.jobs.getValue("job_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb").status)
        assertEquals(WorkProjectionPhase.CURRENT, projection.phase)
    }

    @Test
    fun replacedLedgerResetDropsAllOldProjectionStateBeforeBootstrap() {
        val first = page("bootstrap-page-1.json")
        val scope = WorkSyncScope("gateway-fixture", first.workProfileId)
        val bootstrapped = applyWorkSyncPage(
            createWorkProjection(scope),
            first,
            WorkSyncRequestContext(scope.gatewayId, scope.profileId),
        )
        val replaced = (parseWorkCursorReset(fixture("replaced-ledger.json"))
            as WorkCursorResetParseResult.Verified).reset
        val reset = applyWorkCursorReset(bootstrapped, replaced, scope)

        assertEquals(WorkProjectionPhase.EMPTY, reset.phase)
        assertNull(reset.ledgerId)
        assertNull(reset.cursor)
        assertTrue(reset.jobs.isEmpty())
        assertTrue(reset.attention.isEmpty())
        assertEquals("ledger_22222222222222222222222222222222", reset.resetLedgerHint)
    }

    @Test
    fun cursorExpiredResetFixtureRetainsOnlySanitizedReplacementHint() {
        val reset = (parseWorkCursorReset(fixture("cursor-expired.json"))
            as WorkCursorResetParseResult.Verified).reset
        assertEquals(-32047, reset.code)
        assertEquals("retention_floor", reset.data.reason)
        assertEquals(80L, reset.data.eventFloor)
        assertEquals(105L, reset.data.highWater)
        assertEquals("ledger_11111111111111111111111111111111", reset.data.ledgerId)
    }

    @Test
    fun jobDetailKeepsLargeBodiesOutOfTheSummaryBoundary() {
        val job = bootstrapJob()
        val detail = JsonObject(
            job + mapOf(
                "prompt_preview" to JsonPrimitive("redacted prompt preview"),
                "result" to JsonPrimitive("x".repeat(33 * 1024)),
                "error_detail" to buildJsonObject { put("code", "detail") },
            ),
        )

        val parsed = decodeWorkJobDetail(detail)
        assertEquals(job.getValue("job_id").toString().trim('"'), parsed.job.jobId)
        assertEquals("redacted prompt preview", parsed.promptPreview)
        assertEquals(33 * 1024, (parsed.result as JsonPrimitive).content.length)
        assertTrue(parsed.errorDetail is JsonObject)

        assertThrows(WorkContractDecodeException::class.java) {
            decodeWorkJobSummary(detail)
        }
    }

    @Test
    fun jobDetailEnforcesPerBodyAndOmissionBoundaries() {
        val job = bootstrapJob()
        val exact = "x".repeat(FABRIC_WORK_JOB_DETAIL_BODY_MAX_BYTES - 2)
        val atLimit = JsonObject(job + ("result" to JsonPrimitive(exact)))
        assertEquals(exact.length, (decodeWorkJobDetail(atLimit).result as JsonPrimitive).content.length)

        val overLimit = JsonObject(job + ("result" to JsonPrimitive("${exact}x")))
        assertThrows(WorkContractDecodeException::class.java) {
            decodeWorkJobDetail(overLimit)
        }

        val omitted = JsonObject(
            job + mapOf(
                "result_preview" to JsonNull,
                "result_omitted_reason" to JsonPrimitive("sensitive_input"),
                "result" to JsonNull,
            ),
        )
        assertNull(decodeWorkJobDetail(omitted).result)
        assertThrows(WorkContractDecodeException::class.java) {
            decodeWorkJobDetail(JsonObject(omitted + ("result" to JsonPrimitive("not allowed"))))
        }
    }

    @Test
    fun jobDetailRejectsMalformedPreviewAndUnsafeSummaryMetadata() {
        val job = bootstrapJob()
        assertThrows(WorkContractDecodeException::class.java) {
            decodeWorkJobDetail(JsonObject(job + ("prompt_preview" to JsonPrimitive("x".repeat(1_001)))))
        }
        assertThrows(WorkContractDecodeException::class.java) {
            decodeWorkJobDetail(
                JsonObject(
                    job + ("version" to JsonPrimitive(FABRIC_WORK_MAXIMUM_SAFE_INTEGER + 1)),
                ),
            )
        }
    }

    @Test
    fun sessionInfoRetainsOnlyValidatedWorkProfileIdentity() {
        val profileId = "profile_11111111111111111111111111111111"
        val identity = FabricWorkSessionIdentity.fromSessionInfo(
            buildJsonObject { put("work_profile_id", profileId) },
        )
        assertEquals(profileId, identity?.profileId)
        assertEquals(profileId, identity?.syncScope("gateway-local")?.profileId)
        assertNull(identity?.syncScope("   "))
        assertNull(FabricWorkSessionIdentity.fromSessionInfo(buildJsonObject {}))
        assertNull(
            FabricWorkSessionIdentity.fromSessionInfo(
                buildJsonObject { put("work_profile_id", "profile-not-valid") },
            ),
        )

        val live = LiveSession.fromResumePayload(
            buildJsonObject {
                put("session_id", "runtime-1")
                put("session_key", "stored-1")
                put("messages", kotlinx.serialization.json.JsonArray(emptyList()))
                put("info", buildJsonObject { put("work_profile_id", profileId) })
            },
            storedSessionId = "stored-1",
        )
        assertEquals(identity, live.workIdentity)
    }

    private fun page(name: String): WorkSyncPage = when (val parsed = parseWorkSyncPage(fixture(name))) {
        is WorkContractParseResult.Verified -> parsed.page
        is WorkContractParseResult.Incompatible -> error("$name unexpectedly incompatible: ${parsed.minimum}")
        is WorkContractParseResult.Invalid -> error("$name unexpectedly invalid: ${parsed.message}")
    }

    private fun bootstrapJob(): JsonObject =
        ((fixture("bootstrap-page-1.json") as JsonObject)["jobs"]
            as kotlinx.serialization.json.JsonArray)
            .first() as JsonObject

    private fun fixture(name: String) = Json.parseToJsonElement(
        generateSequence(File(System.getProperty("user.dir"))) { it.parentFile }
            .map { root -> File(root, "apps/mobile/contracts/fabric-work-v1/$name") }
            .firstOrNull(File::isFile)
            ?.readText()
            ?: error("Cannot find canonical fabric.work fixture $name"),
    )
}
