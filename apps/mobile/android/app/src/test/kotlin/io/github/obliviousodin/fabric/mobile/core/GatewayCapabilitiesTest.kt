package io.github.obliviousodin.fabric.mobile.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class GatewayCapabilitiesTest {
    private val newOptionalFamilies = listOf(
        "artifact_fetch",
        "connected_nodes",
        "device_node",
        "node_invoke",
        "push",
        "session_admin",
        "trust_center",
        "workspace_read",
    )

    @Test
    fun acceptsCurrentContractAndExecutionTruth() {
        val result = parseGatewayCapabilities(contractFixture("gateway-capabilities-v1.json"))

        assertTrue(result is GatewayCapabilityNegotiation.Verified)
        val capabilities = (result as GatewayCapabilityNegotiation.Verified).capabilities
        assertEquals(1, capabilities.contractVersion)
        assertEquals("gateway", capabilities.execution.location)
        assertEquals("gateway", capabilities.execution.toolExecution)
        assertTrue(capabilities.execution.survivesClientDisconnect)
        assertFalse(capabilities.execution.survivesGatewayRestart)
        assertTrue(capabilities.execution.requiresGatewayHostOnline)
        assertTrue(result.supportsGatewayMethod("prompt.submit"))
        assertFalse(result.supportsGatewayMethod("voice.record"))
        assertFalse("voice" in capabilities.features)
        assertFalse("code" in capabilities.features)
        assertEquals(true, capabilities.features["code_session_baseline"])
        assertEquals(false, capabilities.features["durable_work"])
        assertFalse(result.supportsDurableWork())
        assertFalse(result.supportsGatewayMethod("future.method"))
    }

    @Test
    fun acceptsAdditiveFutureContractWhenMinimumRemainsCompatible() {
        val result =
            parseGatewayCapabilities(
                capabilitiesPayload(version = 3, minimumCompatible = 1, includeUnknown = true),
            )

        assertTrue(result is GatewayCapabilityNegotiation.Verified)
        assertEquals(
            3,
            (result as GatewayCapabilityNegotiation.Verified).capabilities.contractVersion,
        )
    }

    @Test
    fun blocksContractThatRequiresNewerClient() {
        val result =
            parseGatewayCapabilities(
                contractFixture("gateway-capabilities-incompatible.json"),
            )

        assertEquals(GatewayCapabilityNegotiation.Incompatible(2), result)
        assertFalse(result.allowsBaselineSessionCalls())
    }

    @Test
    fun rejectsMalformedExecutionAndDisablesMissingBaselineMethods() {
        val malformedExecution = contractFixture("gateway-capabilities-malformed.json")
        assertTrue(parseGatewayCapabilities(malformedExecution) is GatewayCapabilityNegotiation.Invalid)

        val missingBaseline = capabilitiesPayload(methods = listOf("session.list"))
        val parsed = parseGatewayCapabilities(missingBaseline)
        assertTrue(parsed is GatewayCapabilityNegotiation.Verified)
        assertFalse(parsed.allowsBaselineSessionCalls())
    }

    @Test
    fun legacyModePreservesOnlyTheShippedMobileControlSet() {
        val legacy = GatewayCapabilityNegotiation.Legacy
        val fixture = contractFixtureElement("legacy-mobile-methods.json") as JsonArray
        assertEquals(fixture.map { it.toString().trim('"') }.toSet(), LEGACY_MOBILE_METHODS)

        assertTrue(legacy.allowsBaselineSessionCalls())
        assertTrue(legacy.supportsGatewayMethod("session.active_list"))
        assertTrue(legacy.supportsGatewayMethod("session.close"))
        assertTrue(legacy.supportsGatewayMethod("prompt.background"))
        assertTrue(legacy.supportsGatewayMethod("approval.respond"))
        assertTrue(legacy.supportsGatewayMethod("computer.screenshot"))
        assertFalse(legacy.supportsGatewayMethod("voice.record"))
        assertFalse(legacy.supportsGatewayMethod("session.branch"))
    }

    @Test
    fun onlyMethodNotFoundCanEnterLegacyMode() {
        assertEquals(
            GatewayCapabilityNegotiation.Legacy,
            legacyCapabilityFallback(GatewayRpcException("not found", code = -32601)),
        )
        assertEquals(null, legacyCapabilityFallback(GatewayRpcException("server", code = 5000)))
        assertEquals(null, legacyCapabilityFallback(GatewayRpcException("timeout")))
    }

    @Test
    fun durableWorkRequiresItsExplicitFeatureAndEveryReviewedMethod() {
        val methods = listOf(
            "session.create",
            "session.resume",
            "session.list",
            "session.active_list",
            "prompt.submit",
            "session.interrupt",
        ) + DURABLE_WORK_GATEWAY_METHODS
        val verified = parseGatewayCapabilities(
            capabilitiesPayload(methods = methods, durableWork = true),
        )
        assertTrue(verified is GatewayCapabilityNegotiation.Verified)
        assertTrue(verified.supportsDurableWork())

        val contradiction = parseGatewayCapabilities(
            capabilitiesPayload(durableWork = true),
        )
        assertTrue(contradiction is GatewayCapabilityNegotiation.Invalid)
        assertFalse(GatewayCapabilityNegotiation.Legacy.supportsDurableWork())
    }

    @Test
    fun featureRegistryFixtureMatchesTheCompiledRegistry() {
        val registry = contractFixture("gateway-feature-registry-v1.json")
        val contract = registry["contract"] as JsonObject
        assertEquals(GATEWAY_CAPABILITY_CONTRACT_NAME, contract["name"]?.toString()?.trim('"'))
        assertEquals(GATEWAY_CLIENT_CONTRACT_VERSION, contract["version"]?.toString()?.toInt())
        assertEquals(
            GATEWAY_FEATURE_METHODS,
            (registry["baseline_features"] as JsonObject).mapValues { (_, methods) ->
                (methods as JsonArray).map { it.toString().trim('"') }.toSet()
            },
        )
        assertEquals(
            OPTIONAL_GATEWAY_FEATURE_METHODS,
            (registry["optional_features"] as JsonObject).mapValues { (_, methods) ->
                (methods as JsonArray).map { it.toString().trim('"') }.toSet()
            },
        )
        assertEquals(
            OPTIONAL_GATEWAY_FEATURE_FLAGS,
            (registry["flag_only_optional_features"] as JsonArray)
                .map { it.toString().trim('"') }
                .toSet(),
        )
        assertEquals(
            LEGACY_MOBILE_METHODS,
            (registry["legacy_mobile_methods"] as JsonArray)
                .map { it.toString().trim('"') }
                .toSet(),
        )
    }

    @Test
    fun familiesFixtureVerifiesEveryNewFamilyTrueAndKeepsDurableWorkDark() {
        val result = parseGatewayCapabilities(
            contractFixture("gateway-capabilities-families-v1.json"),
        )

        assertTrue(result is GatewayCapabilityNegotiation.Verified)
        val features = (result as GatewayCapabilityNegotiation.Verified).capabilities.features
        for (family in newOptionalFamilies) {
            assertEquals(true, features[family])
        }
        assertEquals(true, features["scoped_grants"])
        assertEquals(false, features["durable_work"])
        assertFalse(result.supportsDurableWork())
    }

    @Test
    fun rejectsFamilyWhoseRequiredMethodSetIsMissing() {
        val result = parseGatewayCapabilities(
            contractFixture("gateway-capabilities-family-contradiction.json"),
        )

        assertTrue(result is GatewayCapabilityNegotiation.Invalid)
        assertTrue((result as GatewayCapabilityNegotiation.Invalid).reason.contains("trust_center"))
    }

    @Test
    fun originalV1FixtureStillVerifiesWithEveryNewFamilyFalse() {
        val result = parseGatewayCapabilities(contractFixture("gateway-capabilities-v1.json"))

        assertTrue(result is GatewayCapabilityNegotiation.Verified)
        val features = (result as GatewayCapabilityNegotiation.Verified).capabilities.features
        for (family in newOptionalFamilies) {
            assertEquals(false, features[family])
        }
        assertEquals(false, features["scoped_grants"])
    }

    @Test
    fun rejectsAdvertisedFalseFamilyWhoseMethodsAreAllPresent() {
        val contradictory = withFeature(
            contractFixture("gateway-capabilities-families-v1.json"),
            "push",
            JsonPrimitive(false),
        )

        val result = parseGatewayCapabilities(contradictory)
        assertTrue(result is GatewayCapabilityNegotiation.Invalid)
        assertTrue((result as GatewayCapabilityNegotiation.Invalid).reason.contains("push"))
    }

    @Test
    fun treatsScopedGrantsAsAPureFlagWithNoMethodSetCheck() {
        val base = contractFixture("gateway-capabilities-v1.json")

        val absent = parseGatewayCapabilities(base)
        assertTrue(absent is GatewayCapabilityNegotiation.Verified)
        assertEquals(
            false,
            (absent as GatewayCapabilityNegotiation.Verified).capabilities.features["scoped_grants"],
        )

        val nonBoolean = parseGatewayCapabilities(
            withFeature(base, "scoped_grants", JsonPrimitive("yes")),
        )
        assertTrue(nonBoolean is GatewayCapabilityNegotiation.Invalid)
        assertTrue(
            (nonBoolean as GatewayCapabilityNegotiation.Invalid).reason.contains("scoped_grants"),
        )

        val explicitFalse = parseGatewayCapabilities(
            withFeature(base, "scoped_grants", JsonPrimitive(false)),
        )
        assertTrue(explicitFalse is GatewayCapabilityNegotiation.Verified)
        assertEquals(
            false,
            (explicitFalse as GatewayCapabilityNegotiation.Verified)
                .capabilities.features["scoped_grants"],
        )
    }

    @Test
    fun supportsGatewayFeatureOnlyOnVerifiedContractsAdvertisingTrue() {
        val families = parseGatewayCapabilities(
            contractFixture("gateway-capabilities-families-v1.json"),
        )
        assertTrue(families.supportsGatewayFeature("trust_center"))
        assertTrue(families.supportsGatewayFeature("scoped_grants"))
        assertFalse(families.supportsGatewayFeature("durable_work"))

        val verified = parseGatewayCapabilities(contractFixture("gateway-capabilities-v1.json"))
        assertTrue(verified.supportsGatewayFeature("baseline_chat"))
        assertFalse(verified.supportsGatewayFeature("trust_center"))

        assertFalse(GatewayCapabilityNegotiation.Legacy.supportsGatewayFeature("baseline_chat"))
        assertFalse(GatewayCapabilityNegotiation.Legacy.supportsGatewayFeature("trust_center"))
        assertFalse(
            GatewayCapabilityNegotiation.Incompatible(2).supportsGatewayFeature("baseline_chat"),
        )
        assertFalse(
            GatewayCapabilityNegotiation.Invalid("bad").supportsGatewayFeature("baseline_chat"),
        )
        assertFalse(GatewayCapabilityNegotiation.Negotiating.supportsGatewayFeature("baseline_chat"))
    }

    private fun withFeature(payload: JsonObject, name: String, value: JsonElement): JsonObject =
        buildJsonObject {
            payload.forEach { (key, element) ->
                if (key == "features") {
                    put(
                        "features",
                        buildJsonObject {
                            (element as JsonObject).forEach { (feature, advertised) ->
                                put(feature, advertised)
                            }
                            put(name, value)
                        },
                    )
                } else {
                    put(key, element)
                }
            }
        }

    private fun capabilitiesPayload(
        version: Int = 1,
        minimumCompatible: Int = 1,
        methods: List<String> =
            listOf(
                "session.create",
                "session.resume",
                "session.list",
                "session.active_list",
                "prompt.submit",
                "session.interrupt",
        ),
        includeUnknown: Boolean = false,
        durableWork: Boolean? = null,
    ): JsonObject =
        buildJsonObject {
            putJsonObject("contract") {
                put("name", "fabric.gateway")
                put("version", version)
                put("min_compatible", minimumCompatible)
                if (includeUnknown) put("future_rule", "ignored")
            }
            putJsonObject("server") {
                put("version", "0.21.0")
                put("release_date", "2026.7.16")
            }
            put(
                "execution",
                buildJsonObject {
                    put("location", "gateway")
                    put("tool_execution", "gateway")
                    put("survives_client_disconnect", true)
                    put("survives_gateway_restart", false)
                    put("requires_gateway_host_online", true)
                },
            )
            putJsonObject("features") {
                GATEWAY_FEATURE_METHODS.forEach { (name, requiredMethods) ->
                    put(name, methods.toSet().containsAll(requiredMethods))
                }
                if (durableWork != null) put("durable_work", durableWork)
                if (includeUnknown) put("future_feature", true)
            }
            put("methods", buildJsonArray { methods.forEach { add(it) } })
            if (includeUnknown) put("future_section", "ignored")
        }

    private fun contractFixture(name: String): JsonObject = contractFixtureElement(name) as JsonObject

    private fun contractFixtureElement(name: String) =
        Json.parseToJsonElement(
            generateSequence(File(System.getProperty("user.dir"))) { it.parentFile }
                .map { root -> File(root, "apps/mobile/contracts/$name") }
                .firstOrNull(File::isFile)
                ?.readText()
                ?: error("Cannot find canonical mobile contract fixture $name"),
        )
}
