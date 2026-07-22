import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Row shape returned by the `session.list` RPC
/// (see `tui_gateway/server.py`, `@method("session.list")`).
struct SessionSummary: Identifiable, Hashable, Codable {
    let id: String
    let title: String
    let preview: String
    let startedAt: TimeInterval
    let messageCount: Int
    let source: String

    var displayTitle: String {
        if !title.isEmpty { return title }
        if !preview.isEmpty { return preview }
        return "Untitled session"
    }
}

/// One visible transcript row returned in `session.resume.messages`.
struct SessionTranscriptMessage: Equatable {
    enum Role: String, Equatable {
        case user
        case assistant
        case system
        case tool
    }

    let role: Role
    let text: String
    let reasoning: String?
    /// Server-reported tool name for `role == .tool` rows; `text` then holds
    /// the compact call context (`_tool_ctx` in `tui_gateway/server.py`).
    let toolName: String?

    init(role: Role, text: String, reasoning: String? = nil, toolName: String? = nil) {
        self.role = role
        self.text = text
        self.reasoning = reasoning
        self.toolName = toolName
    }

    init?(payload: [String: Any]) {
        guard
            let rawRole = payload["role"] as? String,
            let role = Role(rawValue: rawRole)
        else { return nil }

        let text: String
        if role == .tool {
            text = (payload["context"] as? String)
                ?? (payload["name"] as? String)
                ?? ""
        } else {
            text = (payload["text"] as? String)
                ?? (payload["content"] as? String)
                ?? ""
        }

        let reasoning = role == .assistant
            ? Self.firstReasoning(
                in: payload,
                keys: ["reasoning", "reasoning_content", "reasoning_details", "codex_reasoning_items"]
            )
            : nil
        guard
            !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || !(reasoning?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true)
        else {
            return nil
        }
        self.role = role
        self.text = text
        self.reasoning = reasoning
        self.toolName = role == .tool ? payload["name"] as? String : nil
    }

    private static func firstReasoning(in payload: [String: Any], keys: [String]) -> String? {
        keys.lazy.compactMap { reasoningText(payload[$0]) }.first
    }

    private static func reasoningText(_ value: Any?) -> String? {
        if let text = value as? String {
            return text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : text
        }
        if let values = value as? [Any] {
            let parts = values.compactMap(reasoningText)
            return parts.isEmpty ? nil : parts.joined(separator: "\n")
        }
        if let object = value as? [String: Any] {
            for key in ["text", "summary", "content", "reasoning"] {
                if let text = reasoningText(object[key]) { return text }
            }
            guard JSONSerialization.isValidJSONObject(object),
                  let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
            else { return nil }
            return String(data: data, encoding: .utf8)
        }
        return nil
    }
}

/// Current turn returned by `session.resume.inflight` when the agent is active.
struct SessionInflight: Equatable {
    let user: String
    let assistant: String
    let streaming: Bool

    init(user: String, assistant: String, streaming: Bool) {
        self.user = user
        self.assistant = assistant
        self.streaming = streaming
    }

    init?(payload: [String: Any]) {
        user = payload["user"] as? String ?? ""
        assistant = payload["assistant"] as? String ?? ""
        streaming = payload["streaming"] as? Bool ?? false
        guard !user.isEmpty || !assistant.isEmpty || streaming else { return nil }
    }
}

/// The opaque Work namespace selected by the gateway for a session. It is a
/// server identity, not a display-profile name: clients must validate and
/// retain it from `session.info` before they can bind a Work projection or a
/// mutation to a profile.
struct FabricWorkSessionIdentity: Equatable {
    let profileID: String

    init(sessionInfo: [String: Any]) throws {
        guard sessionInfo.keys.contains("work_profile_id") else {
            throw FabricWorkValueParseError.invalid(
                "session.info is missing work_profile_id."
            )
        }
        profileID = try FabricWorkParser.decodeProfileID(sessionInfo["work_profile_id"] as Any)
    }

    /// No Work path may infer a profile identity. A legacy or malformed
    /// session snapshot simply remains unavailable to the Work client.
    static func from(sessionInfo: [String: Any]) -> FabricWorkSessionIdentity? {
        try? FabricWorkSessionIdentity(sessionInfo: sessionInfo)
    }

    func syncScope(gatewayID: String) -> FabricWorkSyncScope? {
        guard !gatewayID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return nil
        }
        return FabricWorkSyncScope(gatewayID: gatewayID, profileID: profileID)
    }
}

/// Cumulative token/context usage for one live session, decoded from the
/// gateway's `usage` payload (`_get_usage` in `tui_gateway/server.py`).
/// The context fields are present only when the context engine reports a real
/// current-window reading — a missing gauge stays missing and is never
/// fabricated from cumulative totals.
struct SessionUsage: Equatable {
    var model: String?
    var input: Int?
    var output: Int?
    var reasoning: Int?
    var totalTokens: Int?
    var calls: Int?
    var contextUsed: Int?
    var contextMax: Int?
    var contextPercent: Int?
    var compressions: Int?
    var activeSubagents: Int?

    /// Reads the snake_case wire keys; nil when the payload carries none of
    /// them. `prompt`/`completion` are deliberately not surfaced (redundant
    /// with input/output for this UI).
    static func from(payload: [String: Any]) -> SessionUsage? {
        var usage = SessionUsage()
        usage.model = (payload["model"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        usage.input = integer(payload["input"])
        usage.output = integer(payload["output"])
        usage.reasoning = integer(payload["reasoning"])
        usage.totalTokens = integer(payload["total"])
        usage.calls = integer(payload["calls"])
        usage.contextUsed = integer(payload["context_used"])
        usage.contextMax = integer(payload["context_max"])
        usage.contextPercent = integer(payload["context_percent"])
        usage.compressions = integer(payload["compressions"])
        usage.activeSubagents = integer(payload["active_subagents"])
        guard usage != SessionUsage() else { return nil }
        return usage
    }

    /// Desktop-parity overlay (`{...current, ...payload.usage}`): a key from
    /// the newer payload wins only when it is present there.
    func merging(_ newer: SessionUsage) -> SessionUsage {
        var merged = self
        merged.model = newer.model ?? model
        merged.input = newer.input ?? input
        merged.output = newer.output ?? output
        merged.reasoning = newer.reasoning ?? reasoning
        merged.totalTokens = newer.totalTokens ?? totalTokens
        merged.calls = newer.calls ?? calls
        merged.contextUsed = newer.contextUsed ?? contextUsed
        merged.contextMax = newer.contextMax ?? contextMax
        merged.contextPercent = newer.contextPercent ?? contextPercent
        merged.compressions = newer.compressions ?? compressions
        merged.activeSubagents = newer.activeSubagents ?? activeSubagents
        return merged
    }

    private static func integer(_ value: Any?) -> Int? {
        if let int = value as? Int { return int }
        return (value as? NSNumber)?.intValue
    }
}

/// Result of `session.create` / `session.resume`.
struct LiveSession {
    let sessionId: String
    let storedSessionId: String?
    let messages: [SessionTranscriptMessage]
    let running: Bool
    let inflight: SessionInflight?
    let historyVersion: Int?
    let pendingInteractions: [GatewayEvent]
    /// Validated from the server's `session.info.work_profile_id`. It is not
    /// inferred from `profile_name`, a local path, or the durable session key.
    let workIdentity: FabricWorkSessionIdentity?
    /// Seed usage from `info.usage`; absent for lazy resumes, in which case
    /// usage arrives with the first `session.info` event instead.
    let usage: SessionUsage?

    init(
        sessionId: String,
        storedSessionId: String?,
        messages: [SessionTranscriptMessage] = [],
        running: Bool = false,
        inflight: SessionInflight? = nil,
        historyVersion: Int? = nil,
        pendingInteractions: [GatewayEvent] = [],
        workIdentity: FabricWorkSessionIdentity? = nil,
        usage: SessionUsage? = nil
    ) {
        self.sessionId = sessionId
        self.storedSessionId = storedSessionId
        self.messages = messages
        self.running = running
        self.inflight = inflight
        self.historyVersion = historyVersion
        self.pendingInteractions = pendingInteractions
        self.workIdentity = workIdentity
        self.usage = usage
    }

    init(resumePayload: [String: Any], storedSessionId: String) {
        let runtimeSessionId = resumePayload["session_id"] as? String ?? storedSessionId
        sessionId = runtimeSessionId
        self.storedSessionId = (resumePayload["session_key"] as? String)
            ?? (resumePayload["stored_session_id"] as? String)
            ?? (resumePayload["resumed"] as? String)
            ?? storedSessionId
        let rows = resumePayload["messages"] as? [[String: Any]] ?? []
        messages = rows.compactMap(SessionTranscriptMessage.init(payload:))
        running = resumePayload["running"] as? Bool ?? false
        inflight = (resumePayload["inflight"] as? [String: Any]).flatMap(SessionInflight.init(payload:))
        historyVersion = (resumePayload["history_version"] as? NSNumber)?.intValue
        let info = resumePayload["info"] as? [String: Any]
        workIdentity = info.flatMap(FabricWorkSessionIdentity.from(sessionInfo:))
        usage = (info?["usage"] as? [String: Any]).flatMap(SessionUsage.from(payload:))
        pendingInteractions = (resumePayload["pending_interactions"] as? [[String: Any]] ?? [])
            .compactMap { interaction in
                guard let type = interaction["type"] as? String else { return nil }
                return GatewayEvent(
                    type: type,
                    sessionId: runtimeSessionId,
                    payload: interaction["payload"] as? [String: Any] ?? [:]
                )
            }
    }
}

/// Row shape returned by the `session.active_list` RPC — live in-memory
/// sessions on the gateway, unlike the historical `session.list`
/// (see `_session_live_item` in `tui_gateway/server.py`).
struct ActiveSession: Identifiable, Hashable, Codable {
    let id: String
    let sessionKey: String
    let title: String
    let preview: String
    /// "working" | "waiting" | "starting" | "idle" (`_session_live_status`).
    let status: String
    let model: String
    let messageCount: Int
    let lastActive: TimeInterval
    let current: Bool

    init?(payload: [String: Any]) {
        guard let id = payload["id"] as? String else { return nil }
        self.id = id
        sessionKey = payload["session_key"] as? String ?? id
        title = payload["title"] as? String ?? ""
        preview = payload["preview"] as? String ?? ""
        status = payload["status"] as? String ?? "idle"
        model = payload["model"] as? String ?? ""
        messageCount = (payload["message_count"] as? NSNumber)?.intValue ?? 0
        lastActive = (payload["last_active"] as? NSNumber)?.doubleValue ?? 0
        current = payload["current"] as? Bool ?? false
    }
}

/// Active-pet spritesheet payload from `pet.info` (`_pet_sprite_payload` in
/// `tui_gateway/server.py`). Rows are states in the canonical `stateRows`
/// taxonomy; `framesByRow` carries the real per-row frame count because
/// ragged rows are padded with transparent frames — renderers must never
/// animate `framesPerState` blindly.
struct PetSpriteSheet: Equatable {
    let slug: String
    let displayName: String
    let mime: String
    let spritesheetRevision: String
    let spritesheetBase64: String
    let frameW: Int
    let frameH: Int
    let framesPerState: Int
    let framesByState: [String: Int]
    let framesByRow: [String: Int]
    let loopMs: Int
    let stateRows: [String]

    /// nil unless the payload is enabled and its geometry is sane (> 0).
    static func from(payload: [String: Any]) -> PetSpriteSheet? {
        guard payload["enabled"] as? Bool == true,
              let slug = payload["slug"] as? String, !slug.isEmpty,
              let spritesheetBase64 = payload["spritesheetBase64"] as? String,
              !spritesheetBase64.isEmpty,
              let frameW = integer(payload["frameW"]), frameW > 0,
              let frameH = integer(payload["frameH"]), frameH > 0,
              let framesPerState = integer(payload["framesPerState"]), framesPerState > 0,
              let loopMs = integer(payload["loopMs"]), loopMs > 0,
              let stateRows = payload["stateRows"] as? [String], !stateRows.isEmpty
        else { return nil }
        return PetSpriteSheet(
            slug: slug,
            displayName: payload["displayName"] as? String ?? slug,
            mime: payload["mime"] as? String ?? "image/webp",
            spritesheetRevision: payload["spritesheetRevision"] as? String ?? "",
            spritesheetBase64: spritesheetBase64,
            frameW: frameW,
            frameH: frameH,
            framesPerState: framesPerState,
            framesByState: frameCounts(payload["framesByState"]),
            framesByRow: frameCounts(payload["framesByRow"]),
            loopMs: loopMs,
            stateRows: stateRows
        )
    }

    private static func integer(_ value: Any?) -> Int? {
        if let int = value as? Int { return int }
        return (value as? NSNumber)?.intValue
    }

    private static func frameCounts(_ value: Any?) -> [String: Int] {
        guard let raw = value as? [String: Any] else { return [:] }
        return raw.reduce(into: [:]) { counts, entry in
            if let count = integer(entry.value) { counts[entry.key] = count }
        }
    }
}

/// One adoptable pet from `pet.gallery` (petdex manifest merged with local
/// install state).
struct PetGalleryEntry: Equatable, Identifiable {
    let slug: String
    let displayName: String
    let installed: Bool
    let curated: Bool
    let generated: Bool
    let bundled: Bool
    let spritesheetUrl: String
    var id: String { slug }
}

/// Result of `pet.gallery`: current config (enabled + active slug) plus rows.
struct PetGalleryState: Equatable {
    let enabled: Bool
    let active: String
    let pets: [PetGalleryEntry]
}

/// Cheap active-pet metadata from `pet.info.meta`, used to skip refetching an
/// unchanged spritesheet.
struct PetInfoMeta: Equatable {
    let enabled: Bool
    let slug: String?
    let displayName: String?
    let spritesheetRevision: String?
}

/// One slash command from `commands.catalog` (name includes the leading `/`).
struct SlashCommand: Identifiable, Hashable {
    let name: String
    let detail: String
    var id: String { name }
}

/// A category of slash commands, in the catalog's display order.
struct SlashCommandCategory: Identifiable, Hashable {
    let name: String
    let commands: [SlashCommand]
    var id: String { name }
}

/// A read-only screen capture from `computer.screenshot`.
struct ScreenCapture {
    let image: Data
    let width: Int
    let height: Int
}

/// A 6K-class desktop frame fits inside these production bounds while a
/// compressed-image bomb, implausible metadata, or accidental video-sized
/// payload fails before UIKit attempts raster decoding.
struct ScreenCaptureValidationLimits: Equatable {
    let maxEncodedBytes: Int
    let maxDecodedBytes: Int
    let maxDimension: Int
    let maxPixelCount: Int

    static let production = ScreenCaptureValidationLimits(
        maxEncodedBytes: 64 * 1_024 * 1_024,
        maxDecodedBytes: 48 * 1_024 * 1_024,
        maxDimension: 6_144,
        maxPixelCount: 22_000_000
    )
}

/// Row shape from `process.list` — background processes owned by a session
/// (see `_session_processes` / `tools/process_registry.py`).
struct BackgroundProcess: Identifiable, Hashable {
    let id: String
    let command: String
    let pid: Int
    /// "running" | "exited".
    let status: String
    let uptimeSeconds: Int
    let outputTail: String
}

/// Authoritative application-level receipt returned inside a successful
/// `process.kill` JSON-RPC response. Transport success alone does not prove
/// that the process mutation succeeded.
enum ProcessKillReceipt: Equatable {
    case killed
    case alreadyExited
    case rejected
}

/// Public body of `GET /api/status`. Only the fields the client needs;
/// `authRequired` distinguishes a gated gateway (provider login + WS tickets)
/// from direct token auth (`authModeFromStatus` in
/// `apps/desktop/electron/connection-config.ts`).
struct GatewayStatus {
    let authRequired: Bool
    let raw: [String: Any]
}

let gatewayClientContractVersion = 1

/// Methods available in the first shipped mobile client, before capability
/// negotiation existed. This compatibility surface is enabled only when
/// `gateway.capabilities` returns JSON-RPC `-32601`.
let legacyMobileMethods: Set<String> = [
    "approval.respond",
    "clarify.respond",
    "commands.catalog",
    "computer.screenshot",
    "process.kill",
    "process.list",
    "prompt.background",
    "prompt.submit",
    "secret.respond",
    "session.active_list",
    "session.close",
    "session.create",
    "session.interrupt",
    "session.list",
    "session.resume",
    "session.steer",
    "slash.exec",
    "sudo.respond",
]

// Gateway-host voice RPCs are intentionally absent: they record and play on
// the gateway machine, not this phone. Phone voice needs its own wire contract.
let gatewayFeatureMethods: [String: Set<String>] = [
    "automation": ["cron.manage"],
    "background_work": ["session.active_list", "prompt.background", "session.steer"],
    "baseline_chat": ["session.create", "session.list", "session.resume", "prompt.submit"],
    "code_session_baseline": ["projects.discover_repos", "session.branch", "session.undo"],
    "delegation": ["delegation.status", "spawn_tree.list"],
    "files": ["image.attach_bytes", "pdf.attach", "file.attach"],
    "handoff": ["handoff.request"],
    "live_view": ["visual.status", "visual.frame"],
]

/// `durable_work` remains an optional, server-advertised feature. The client
/// only recognizes it as usable when the server has published the complete
/// reviewed RPC surface; its absence is deliberately false, not a legacy
/// fallback or a reason to probe individual methods.
let durableWorkGatewayMethods: Set<String> = [
    "job.create",
    "job.sync",
    "job.get",
    "job.list",
    "job.events",
    "job.cancel",
    "attention.get",
    "attention.list",
    "attention.respond",
]

/// Additive feature gates introduced after the original version-1 fixture.
/// Their absence means "not advertised" so an older gateway remains a valid
/// version-1 peer; when present, the same method/feature invariant applies.
let optionalGatewayFeatureMethods: [String: Set<String>] = [
    "artifact_fetch": ["artifact.list", "artifact.fetch"],
    "connected_nodes": ["node.list", "node.revoke"],
    "device_node": ["node.enroll"],
    "durable_work": durableWorkGatewayMethods,
    "node_invoke": ["node.announce", "node.result", "node.reject"],
    "pets": ["pet.info", "pet.info.meta", "pet.gallery", "pet.select", "pet.disable", "pet.thumb"],
    "push": ["push.register_device", "push.deregister_device"],
    "session_admin": ["session.rename", "session.archive"],
    "trust_center": ["trust.audit.list", "grant.list", "grant.create", "grant.revoke"],
    "workspace_read": ["fs.list", "fs.read"],
]

/// Optional features advertised as a bare boolean with no dedicated methods
/// (scoped_grants extends approval.respond params), so no method/feature
/// consistency check applies. Absence still means "not advertised" → false.
let optionalGatewayFeatureFlags: Set<String> = ["scoped_grants"]

private let requiredMobileSessionMethods = gatewayFeatureMethods["baseline_chat"] ?? []

struct GatewayCapabilityContract: Equatable {
    let name: String
    let version: Int
    let minimumCompatibleVersion: Int
}

struct GatewayServerContract: Equatable {
    let version: String
    let releaseDate: String
}

struct GatewayExecutionContract: Equatable {
    let location: String
    let toolExecution: String
    let survivesClientDisconnect: Bool
    let survivesGatewayRestart: Bool
    let requiresGatewayHostOnline: Bool
}

struct GatewayCapabilities: Equatable {
    let contract: GatewayCapabilityContract
    let server: GatewayServerContract
    let execution: GatewayExecutionContract
    let features: [String: Bool]
    let methods: Set<String>
}

/// Result of negotiating the authenticated mobile JSON-RPC contract.
enum GatewayCapabilityNegotiation: Equatable {
    case negotiating
    case verified(GatewayCapabilities)
    case legacy
    case incompatible(minimumCompatibleVersion: Int)
    case invalid(reason: String)

    func supportsGatewayMethod(_ method: String) -> Bool {
        switch self {
        case .verified(let capabilities):
            return capabilities.methods.contains(method)
        case .legacy:
            return legacyMobileMethods.contains(method)
        case .negotiating, .incompatible, .invalid:
            return false
        }
    }

    /// Whether a feature family is usable on this gateway. Mirrors the
    /// durable_work precedent: an optional family only exists when a verified
    /// contract advertises it true — a legacy gateway predates every optional
    /// family, and a negotiating, incompatible, or invalid contract fails
    /// closed.
    func supportsGatewayFeature(_ feature: String) -> Bool {
        guard case .verified(let capabilities) = self else { return false }
        return capabilities.features[feature] == true
    }

    /// Work has no compatibility fallback. Its optional feature must be
    /// explicitly true *and* its complete reviewed method set must be present
    /// on a verified gateway contract.
    var supportsDurableWork: Bool {
        guard case .verified(let capabilities) = self else { return false }
        return capabilities.features["durable_work"] == true
            && durableWorkGatewayMethods.isSubset(of: capabilities.methods)
    }

    var allowsBaselineSessionCalls: Bool {
        switch self {
        case .verified(let capabilities):
            return requiredMobileSessionMethods.isSubset(of: capabilities.methods)
        case .legacy:
            return true
        case .negotiating, .incompatible, .invalid:
            return false
        }
    }

    var blockingMessage: String? {
        switch self {
        case .incompatible(let minimum):
            return "Update Fabric Mobile to connect. This gateway requires mobile contract \(minimum) or newer."
        case .invalid(let reason):
            return "This gateway returned an invalid capability contract: \(reason)"
        case .negotiating, .verified, .legacy:
            return nil
        }
    }
}

/// Strict parser for the versioned process-scoped gateway contract. Unknown
/// fields and method names are additive; version-1 execution semantics and
/// known feature-to-method relationships are safety invariants.
enum GatewayCapabilitiesParser {
    static func parse(_ raw: Any?) -> GatewayCapabilityNegotiation {
        guard let payload = raw as? [String: Any] else {
            return .invalid(reason: "Gateway capabilities must be an object.")
        }
        guard let contractPayload = payload["contract"] as? [String: Any] else {
            return .invalid(reason: "Gateway capabilities are missing a contract object.")
        }
        guard contractPayload["name"] as? String == "fabric.gateway" else {
            return .invalid(reason: "Gateway capability contract name must be fabric.gateway.")
        }
        guard let version = positiveInteger(contractPayload["version"]) else {
            return .invalid(reason: "Gateway capability contract version must be a positive integer.")
        }
        guard let minimumCompatible = positiveInteger(contractPayload["min_compatible"]) else {
            return .invalid(reason: "Gateway minimum compatible version must be a positive integer.")
        }
        guard minimumCompatible <= version else {
            return .invalid(reason: "Gateway minimum compatible version cannot exceed its contract version.")
        }

        guard
            let serverPayload = payload["server"] as? [String: Any],
            let serverVersion = nonemptyString(serverPayload["version"]),
            let releaseDate = nonemptyString(serverPayload["release_date"])
        else {
            return .invalid(reason: "Gateway capabilities contain invalid server metadata.")
        }

        guard let executionPayload = payload["execution"] as? [String: Any] else {
            return .invalid(reason: "Gateway capabilities are missing execution semantics.")
        }
        guard
            executionPayload["location"] as? String == "gateway",
            executionPayload["tool_execution"] as? String == "gateway",
            strictBoolean(executionPayload["survives_client_disconnect"]) == true,
            strictBoolean(executionPayload["survives_gateway_restart"]) == false,
            strictBoolean(executionPayload["requires_gateway_host_online"]) == true
        else {
            return .invalid(reason: "Gateway capabilities contradict the version-1 execution contract.")
        }

        guard let methodPayload = payload["methods"] as? [Any] else {
            return .invalid(reason: "Gateway capability methods must be an array.")
        }
        var methods = Set<String>()
        for value in methodPayload {
            guard let method = nonemptyString(value) else {
                return .invalid(reason: "Gateway capability methods must be non-empty strings.")
            }
            guard methods.insert(method).inserted else {
                return .invalid(reason: "Gateway capability method is duplicated: \(method).")
            }
        }

        guard let featurePayload = payload["features"] as? [String: Any] else {
            return .invalid(reason: "Gateway capabilities are missing feature availability.")
        }
        var features: [String: Bool] = [:]
        for (name, requiredMethods) in gatewayFeatureMethods {
            guard let advertised = strictBoolean(featurePayload[name]) else {
                return .invalid(reason: "Gateway feature \(name) must be a boolean.")
            }
            guard advertised == requiredMethods.isSubset(of: methods) else {
                return .invalid(reason: "Gateway feature \(name) contradicts its advertised methods.")
            }
            features[name] = advertised
        }
        // Unlike the baseline v1 features, the optional families were
        // introduced as additive keys. An omitted key means unavailable; a
        // present key must still truthfully describe the entire reviewed RPC
        // family. Keys are visited in sorted order so a payload contradicting
        // several families always reports the same deterministic error.
        for name in optionalGatewayFeatureMethods.keys.sorted() {
            let requiredMethods = optionalGatewayFeatureMethods[name] ?? []
            guard let raw = featurePayload[name] else {
                features[name] = false
                continue
            }
            guard let advertised = strictBoolean(raw) else {
                return .invalid(reason: "Gateway feature \(name) must be a boolean.")
            }
            guard advertised == requiredMethods.isSubset(of: methods) else {
                return .invalid(reason: "Gateway feature \(name) contradicts its advertised methods.")
            }
            features[name] = advertised
        }
        // Pure boolean flags have no method family to cross-check, so a
        // present boolean is accepted as-is. Sorted for the same deterministic
        // error precedence as above.
        for name in optionalGatewayFeatureFlags.sorted() {
            guard let raw = featurePayload[name] else {
                features[name] = false
                continue
            }
            guard let advertised = strictBoolean(raw) else {
                return .invalid(reason: "Gateway feature \(name) must be a boolean.")
            }
            features[name] = advertised
        }

        if minimumCompatible > gatewayClientContractVersion {
            return .incompatible(minimumCompatibleVersion: minimumCompatible)
        }

        return .verified(GatewayCapabilities(
            contract: GatewayCapabilityContract(
                name: "fabric.gateway",
                version: version,
                minimumCompatibleVersion: minimumCompatible
            ),
            server: GatewayServerContract(version: serverVersion, releaseDate: releaseDate),
            execution: GatewayExecutionContract(
                location: "gateway",
                toolExecution: "gateway",
                survivesClientDisconnect: true,
                survivesGatewayRestart: false,
                requiresGatewayHostOnline: true
            ),
            features: features,
            methods: methods
        ))
    }

    private static func positiveInteger(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID()
        else { return nil }
        let double = number.doubleValue
        guard double.isFinite,
              double >= 1,
              double.rounded(.towardZero) == double,
              double <= Double(Int.max)
        else { return nil }
        return Int(double)
    }

    private static func strictBoolean(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) == CFBooleanGetTypeID()
        else { return nil }
        return number.boolValue
    }

    private static func nonemptyString(_ value: Any?) -> String? {
        guard let string = value as? String,
              !string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return nil }
        return string
    }
}

enum GatewayCapabilityNegotiator {
    static func negotiate(
        request: () async throws -> Any?
    ) async throws -> GatewayCapabilityNegotiation {
        do {
            return GatewayCapabilitiesParser.parse(try await request())
        } catch GatewayClientError.rpc(_, let code, _) where code == -32_601 {
            return .legacy
        }
    }
}

/// Row from `GET /api/auth/providers` (gated gateways only).
struct AuthProviderInfo: Identifiable, Hashable {
    let name: String
    let displayName: String
    let supportsPassword: Bool
    /// Provider requires a TOTP second factor — show a code field.
    let requiresTotp: Bool
    var id: String { name }
}

/// The two mutually exclusive `job.sync` request shapes. A bootstrap page is
/// either page one (no token) or a server-issued continuation token; a delta
/// is always bound to the exact durable ledger and cursor the client applied.
enum FabricWorkSyncRequest: Equatable {
    case bootstrap(pageToken: String?, limit: Int)
    case delta(ledgerID: String, after: Int, limit: Int)

    static var bootstrap: FabricWorkSyncRequest {
        .bootstrap(pageToken: nil, limit: 500)
    }

    func parameters(sessionID: String) throws -> [String: Any] {
        guard !sessionID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw FabricWorkGatewayError.invalidRequest("session_id must be non-empty.")
        }
        switch self {
        case .bootstrap(let pageToken, let limit):
            try Self.validate(limit: limit)
            if let pageToken,
               pageToken.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                throw FabricWorkGatewayError.invalidRequest("page_token must be non-empty when supplied.")
            }
            var params: [String: Any] = ["session_id": sessionID, "limit": limit]
            if let pageToken { params["page_token"] = pageToken }
            return params
        case .delta(let ledgerID, let after, let limit):
            try Self.validate(limit: limit)
            do {
                _ = try FabricWorkParser.decodeLedgerID(ledgerID)
            } catch {
                throw FabricWorkGatewayError.invalidRequest("ledger_id must be a valid Work ledger identifier.")
            }
            guard (0...FabricWorkLimits.maximumSafeInteger).contains(after) else {
                throw FabricWorkGatewayError.invalidRequest("after must be a non-negative safe integer.")
            }
            return [
                "session_id": sessionID,
                "ledger_id": ledgerID,
                "after": after,
                "limit": limit,
            ]
        }
    }

    private static func validate(limit: Int) throws {
        guard (1...500).contains(limit) else {
            throw FabricWorkGatewayError.invalidRequest("Work sync limit must be between 1 and 500.")
        }
    }
}

enum FabricWorkGatewayResponse: Equatable {
    case page(FabricWorkSyncPage)
    case reset(FabricWorkCursorReset)
}

/// Sanitized public receipt for `job.create` and `job.cancel`. Raw prompts
/// and any execution-local control data are deliberately absent.
struct FabricWorkJobMutationReceipt: Equatable {
    let job: FabricWorkJobSummary
    let mutationID: String
    let replayed: Bool
    let runtimeStarted: Bool?
    let taskID: String?
    let newlyCancelled: Bool?
}

/// Exact-addressed result for `attention.respond`; it contains no submitted
/// sensitive value, only the authoritative terminal state.
struct FabricWorkAttentionMutationReceipt: Equatable {
    let attentionID: String
    let attentionVersion: Int
    let delivered: Bool
    let mutationID: String
    let replayed: Bool
    let state: String
}

struct FabricWorkJobListResponse: Equatable {
    let workProfileID: String
    let jobs: [FabricWorkJobSummary]
    let nextBefore: String?
}

struct FabricWorkAttentionListResponse: Equatable {
    let workProfileID: String
    let attention: [FabricWorkAttention]
    let nextBefore: String?
}

struct FabricWorkJobEventsResponse: Equatable {
    let workProfileID: String
    let cursor: Int
    let events: [FabricWorkEvent]
}

enum FabricWorkGatewayError: LocalizedError, Equatable {
    case invalidRequest(String)
    case unavailableOnGateway
    case invalidContract(String)
    case incompatibleContract(minimumCompatibleVersion: Int)
    case invalidCursorReset(String)
    case invalidResponse(String)

    var errorDescription: String? {
        switch self {
        case .invalidRequest(let message), .invalidContract(let message), .invalidCursorReset(let message),
             .invalidResponse(let message):
            return message
        case .unavailableOnGateway:
            return "Durable Work is unavailable on this gateway."
        case .incompatibleContract(let minimum):
            return "Update Fabric Mobile to read Work contract \(minimum) or newer."
        }
    }
}

enum GatewayAPIError: LocalizedError {
    case badURL
    case httpStatus(Int, body: String)

    var errorDescription: String? {
        switch self {
        case .badURL:
            return "Gateway URL must be http:// or https://"
        case .httpStatus(let code, let body):
            return body.isEmpty ? "HTTP \(code)" : "HTTP \(code): \(body)"
        }
    }
}

/// One generation of the in-memory cookie jar for a saved gated gateway.
/// A lease becomes unusable as soon as another authentication attempt for the
/// same saved gateway starts, or when that gateway is disconnected/forgotten.
struct GatewayAuthSessionLease: @unchecked Sendable {
    let gatewayID: String
    let endpointKey: String
    fileprivate let generation: UUID
    let session: URLSession
}

/// Process-only gated-auth sessions, isolated by saved gateway and endpoint.
///
/// HTTP cookies intentionally do not include a port in their scope. Sharing a
/// single URLSession would therefore send a gateway cookie to another service
/// on the same hostname and path but a different port. Every entry here owns a
/// distinct ephemeral cookie store. Replacing an entry publishes the new
/// generation before cancelling the old session, so a late superseded response
/// can mutate only an unreachable jar.
final class GatewayAuthSessionPool: @unchecked Sendable {
    private struct Entry {
        let endpointKey: String
        let generation: UUID
        let session: URLSession
    }

    private let lock = NSLock()
    private var entries: [String: Entry] = [:]
    private let makeSession: @Sendable () -> URLSession

    init(makeSession: @escaping @Sendable () -> URLSession = {
        GatewayHTTPTransport.authSession()
    }) {
        self.makeSession = makeSession
    }

    /// Start a new exclusive generation. Silent reconnects copy the existing
    /// gateway's cookies into a new jar before cancelling the old transport;
    /// explicit password sign-in starts clean.
    func beginSession(
        for gateway: SavedGateway,
        preservingExistingCookies: Bool
    ) -> GatewayAuthSessionLease {
        let endpointKey = gateway.endpointKey
        let session = makeSession()
        let generation = UUID()
        var previousSession: URLSession?

        lock.lock()
        if let previous = entries[gateway.id] {
            previousSession = previous.session
            if preservingExistingCookies, previous.endpointKey == endpointKey {
                let cookies = previous.session.configuration.httpCookieStorage?.cookies ?? []
                let storage = session.configuration.httpCookieStorage
                for cookie in cookies { storage?.setCookie(cookie) }
            }
        }
        entries[gateway.id] = Entry(
            endpointKey: endpointKey,
            generation: generation,
            session: session
        )
        lock.unlock()

        if let previousSession { Self.clearAndInvalidate(previousSession) }
        return GatewayAuthSessionLease(
            gatewayID: gateway.id,
            endpointKey: endpointKey,
            generation: generation,
            session: session
        )
    }

    func isCurrent(_ lease: GatewayAuthSessionLease, for gateway: SavedGateway) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard let entry = entries[gateway.id] else { return false }
        return lease.gatewayID == gateway.id
            && lease.endpointKey == gateway.endpointKey
            && entry.endpointKey == lease.endpointKey
            && entry.generation == lease.generation
            && entry.session === lease.session
    }

    func invalidate(gatewayID: String) {
        lock.lock()
        let session = entries.removeValue(forKey: gatewayID)?.session
        lock.unlock()
        if let session { Self.clearAndInvalidate(session) }
    }

    func invalidateAll() {
        lock.lock()
        let sessions = entries.values.map(\.session)
        entries.removeAll()
        lock.unlock()
        for session in sessions { Self.clearAndInvalidate(session) }
    }

    private static func clearAndInvalidate(_ session: URLSession) {
        let storage = session.configuration.httpCookieStorage
        storage?.cookies?.forEach { storage?.deleteCookie($0) }
        session.invalidateAndCancel()
    }
}

enum GatewayHTTPTransport {
    /// Public discovery must neither send an authenticated gateway's cookies
    /// nor accept attacker-supplied cookies for a later credentialed request.
    static func discoverySession() -> URLSession {
        let configuration = baseConfiguration()
        configuration.httpShouldSetCookies = false
        configuration.httpCookieAcceptPolicy = .never
        configuration.httpCookieStorage = nil
        return URLSession(configuration: configuration)
    }

    /// Each invocation receives URLSessionConfiguration.ephemeral's distinct,
    /// process-only HTTPCookieStorage instance.
    static func authSession() -> URLSession {
        let configuration = baseConfiguration()
        configuration.httpShouldSetCookies = true
        configuration.httpCookieAcceptPolicy = .always
        return URLSession(configuration: configuration)
    }

    private static func baseConfiguration() -> URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        configuration.urlCredentialStorage = nil
        return configuration
    }
}

/// Typed wrappers around the raw JSON-RPC client for the methods the mobile
/// slice uses. Method names and parameter shapes mirror the desktop
/// renderer's call sites (`use-session-actions`, `use-prompt-actions`).
struct GatewayAPI {
    let client: JsonRpcGatewayClient

    static func requireMatchingInteractionReceipt(
        _ result: [String: Any],
        requestId: String,
        approval: Bool = false
    ) throws {
        guard
            result["request_id"] as? String == requestId,
            !approval || (result["resolved"] as? Int) == 1
        else {
            throw GatewayClientError.rpc(message: "Response did not match the pending request.")
        }
    }

    static func requireProcessKillReceipt(
        _ result: [String: Any]
    ) throws -> ProcessKillReceipt {
        guard let rawStatus = result["status"] as? String else {
            throw GatewayClientError.rpc(
                message: "Process stop response did not include a status."
            )
        }

        switch rawStatus.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "killed":
            return .killed
        case "already_exited":
            return .alreadyExited
        case "error", "not_found":
            return .rejected
        default:
            throw GatewayClientError.rpc(
                message: "Process stop response included an unsupported status."
            )
        }
    }

    /// Cookie-disabled transport for public status/provider discovery. Gated
    /// credentials use the isolated pool below and never enter this session.
    static let httpSession = GatewayHTTPTransport.discoverySession()
    private static let authSessions = GatewayAuthSessionPool()

    static func beginAuthSession(
        for gateway: SavedGateway,
        preservingExistingCookies: Bool
    ) -> GatewayAuthSessionLease {
        authSessions.beginSession(
            for: gateway,
            preservingExistingCookies: preservingExistingCookies
        )
    }

    static func isAuthSessionCurrent(
        _ lease: GatewayAuthSessionLease,
        for gateway: SavedGateway
    ) -> Bool {
        authSessions.isCurrent(lease, for: gateway)
    }

    static func clearAuthSession(for gatewayID: String) {
        authSessions.invalidate(gatewayID: gatewayID)
    }

    static func clearAllAuthSessions() {
        authSessions.invalidateAll()
    }

    private static func requireCurrentAuthSession(
        _ lease: GatewayAuthSessionLease,
        for gateway: SavedGateway
    ) throws {
        guard isAuthSessionCurrent(lease, for: gateway) else {
            throw CancellationError()
        }
    }

    // MARK: - REST (pre-socket)

    /// Public liveness probe; also classifies the gateway's auth mode.
    static func probeStatus(baseURL: URL) async throws -> GatewayStatus {
        let statusURL = baseURL.appending(path: "api/status")
        var request = URLRequest(url: statusURL, timeoutInterval: 10)
        request.httpMethod = "GET"
        let (data, response) = try await httpSession.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw GatewayAPIError.badURL
        }
        guard (200..<300).contains(http.statusCode) else {
            throw GatewayAPIError.httpStatus(http.statusCode, body: String(decoding: data, as: UTF8.self))
        }
        let body = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        return GatewayStatus(authRequired: body["auth_required"] as? Bool ?? false, raw: body)
    }

    /// `ws(s)://host[/prefix]/api/ws?token=…` — the token-mode WS URL, same
    /// construction as `buildGatewayWsUrl` in the desktop connection config.
    static func websocketURL(baseURL: URL, token: String) throws -> URL {
        guard GatewayBaseURL.allowsTokenCredential(baseURL) else {
            throw GatewayTokenTransportError.secureTransportRequired
        }
        return try websocketURL(baseURL: baseURL, authParam: ("token", token))
    }

    /// `ws(s)://…/api/ws?ticket=…` — the gated-mode WS URL. Tickets are
    /// single-use with a 30s TTL: mint one immediately before every connect.
    static func websocketURL(baseURL: URL, ticket: String) throws -> URL {
        try websocketURL(baseURL: baseURL, authParam: ("ticket", ticket))
    }

    private static func websocketURL(baseURL: URL, authParam: (String, String)) throws -> URL {
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false),
              let rawScheme = components.scheme
        else {
            throw GatewayAPIError.badURL
        }
        let scheme = rawScheme.lowercased()
        guard scheme == "http" || scheme == "https" else {
            throw GatewayAPIError.badURL
        }
        components.scheme = scheme == "https" ? "wss" : "ws"
        let prefix = components.path.hasSuffix("/") ? String(components.path.dropLast()) : components.path
        components.path = prefix + "/api/ws"
        components.queryItems = [URLQueryItem(name: authParam.0, value: authParam.1)]
        guard let url = components.url else { throw GatewayAPIError.badURL }
        return url
    }

    // MARK: - Gated auth (provider login + WS tickets)
    // The ephemeral session stores the cookies set by `/auth/password-login`,
    // so ticket minting is authenticated without persistence across launches.

    /// `GET /api/auth/providers` — which sign-in options this gateway offers.
    static func listAuthProviders(baseURL: URL) async throws -> [AuthProviderInfo] {
        let url = baseURL.appending(path: "api/auth/providers")
        var request = URLRequest(url: url, timeoutInterval: 10)
        request.httpMethod = "GET"
        let (data, response) = try await httpSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw GatewayAPIError.httpStatus(code, body: String(decoding: data, as: UTF8.self))
        }
        let body = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        let rows = body["providers"] as? [[String: Any]] ?? []
        return rows.compactMap { row in
            guard let name = row["name"] as? String else { return nil }
            return AuthProviderInfo(
                name: name,
                displayName: row["display_name"] as? String ?? name,
                supportsPassword: row["supports_password"] as? Bool ?? false,
                requiresTotp: row["requires_totp"] as? Bool ?? false
            )
        }
    }

    /// `POST /auth/password-login` — authenticates and stores the session
    /// cookies. 401 means bad credentials; 429 rate-limited.
    static func passwordLogin(
        gateway: SavedGateway,
        using authSession: GatewayAuthSessionLease,
        provider: String,
        username: String,
        password: String,
        otp: String = ""
    ) async throws {
        try requireCurrentAuthSession(authSession, for: gateway)
        let url = gateway.baseURL.appending(path: "auth/password-login")
        var request = URLRequest(url: url, timeoutInterval: 15)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "provider": provider,
            "username": username,
            "password": password,
            "otp": otp,
        ])
        let (data, response) = try await authSession.session.data(for: request)
        try requireCurrentAuthSession(authSession, for: gateway)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw GatewayAPIError.httpStatus(code, body: detail ?? "Sign-in failed")
        }
    }

    /// `POST /api/auth/ws-ticket` — single-use 30s WS credential for the
    /// cookie session. A 401 here means the session has expired (or was
    /// never established): re-run `passwordLogin`.
    static func mintWsTicket(
        gateway: SavedGateway,
        using authSession: GatewayAuthSessionLease
    ) async throws -> String {
        try requireCurrentAuthSession(authSession, for: gateway)
        let url = gateway.baseURL.appending(path: "api/auth/ws-ticket")
        var request = URLRequest(url: url, timeoutInterval: 15)
        request.httpMethod = "POST"
        let (data, response) = try await authSession.session.data(for: request)
        try requireCurrentAuthSession(authSession, for: gateway)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw GatewayAPIError.httpStatus(code, body: String(decoding: data, as: UTF8.self))
        }
        let body = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        guard let ticket = body["ticket"] as? String, !ticket.isEmpty else {
            throw GatewayAPIError.httpStatus(500, body: "Gateway returned no ticket")
        }
        return ticket
    }

    // MARK: - Capability negotiation

    /// Negotiate the authenticated mobile contract immediately after opening
    /// the socket and before issuing any session RPC. Only method-not-found
    /// (`-32601`) is a legacy gateway; every other RPC/transport error remains
    /// a connection failure.
    func capabilities() async throws -> GatewayCapabilityNegotiation {
        try await GatewayCapabilityNegotiator.negotiate {
            try await client.request("gateway.capabilities")
        }
    }

    // MARK: - Durable Work (unadvertised until all client and operations gates ship)

    /// Fetch one authoritative Work page. The wrapper itself requires the
    /// explicitly advertised, complete Durable Work capability; it has no
    /// legacy fallback and does not alter advertised capability features. A
    /// `work.changed` event should only trigger this request, never update a
    /// projection itself.
    func syncWork(
        sessionID: String,
        request: FabricWorkSyncRequest,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkGatewayResponse {
        // Work is never a legacy fallback. Until the server explicitly
        // publishes the method in a verified contract, native clients retain
        // their current session/background behavior.
        guard negotiation.supportsDurableWork
        else {
            throw FabricWorkGatewayError.unavailableOnGateway
        }
        return try await Self.decodeWorkSyncTransport {
            try await client.request(
                "job.sync",
                params: try request.parameters(sessionID: sessionID)
            )
        }
    }

    /// Shared transport boundary for `job.sync`. Keeping the error conversion
    /// here makes it independently testable with the exact
    /// `GatewayClientError.rpc` shape emitted by the WebSocket client.
    static func decodeWorkSyncTransport(
        _ request: () async throws -> Any?
    ) async throws -> FabricWorkGatewayResponse {
        do {
            return try decodeWorkSyncResponse(try await request())
        } catch let error as GatewayClientError {
            if let reset = try Self.decodeWorkCursorReset(fromRPCError: error) {
                return reset
            }
            throw error
        }
    }

    /// Pure decode seam for fixture tests and for a transport that returns a
    /// JSON-RPC result object. Invalid or incompatible pages cannot be
    /// mistaken for an empty Work list.
    static func decodeWorkSyncResponse(_ raw: Any?) throws -> FabricWorkGatewayResponse {
        switch FabricWorkParser.parseSyncPage(raw as Any) {
        case .verified(let page):
            return .page(page)
        case .incompatible(let minimum):
            throw FabricWorkGatewayError.incompatibleContract(minimumCompatibleVersion: minimum)
        case .invalid(let message):
            throw FabricWorkGatewayError.invalidContract(message)
        }
    }

    /// Decode the one typed Work reset returned in JSON-RPC error data.
    /// Other errors stay transport/RPC errors so the caller cannot silently
    /// discard a good projection on an unrelated failure.
    static func decodeWorkCursorReset(_ raw: Any?) throws -> FabricWorkGatewayResponse {
        switch FabricWorkParser.parseCursorReset(raw as Any) {
        case .verified(let reset):
            return .reset(reset)
        case .invalid(let message):
            throw FabricWorkGatewayError.invalidCursorReset(message)
        }
    }

    /// `JsonRpcGatewayClient` retains an RPC error's `data` field separately
    /// from its code/message. Reconstruct the validated error envelope before
    /// handing it to the canonical Work reset parser; parsing `data` alone
    /// would silently turn a real cursor-expiry reset into a generic failure.
    static func decodeWorkCursorReset(
        fromRPCError error: GatewayClientError
    ) throws -> FabricWorkGatewayResponse? {
        guard case .rpc(let message, let code?, let data) = error, code == -32_047 else {
            return nil
        }
        return try decodeWorkCursorReset([
            "code": code,
            "message": message,
            "data": data ?? NSNull(),
        ])
    }

    /// Create a durable, creator-bound background Job. This is deliberately
    /// distinct from `prompt.background`: no error path retries through the
    /// legacy method, which could otherwise execute a second user intent.
    func createBackgroundWork(
        sessionID: String,
        text: String,
        title: String? = nil,
        idempotencyKey: String,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkJobMutationReceipt {
        try Self.requireDurableWork(negotiation)
        let runtimeSessionID = try Self.requireWorkSessionID(sessionID)
        let prompt = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty, prompt.unicodeScalars.count <= 200_000 else {
            throw FabricWorkGatewayError.invalidRequest(
                "Background work prompt must be 1 to 200000 characters."
            )
        }
        let resolvedTitle = (title ?? "Background work")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !resolvedTitle.isEmpty, resolvedTitle.unicodeScalars.count <= 200 else {
            throw FabricWorkGatewayError.invalidRequest("Background work title must be 1 to 200 characters.")
        }
        try Self.requireIdempotencyKey(idempotencyKey)

        let receipt = try Self.decodeWorkJobMutationReceipt(
            await client.requestObject(
                "job.create",
                params: [
                    "session_id": runtimeSessionID,
                    "kind": "background_prompt",
                    "text": prompt,
                    "title": resolvedTitle,
                    "idempotency_key": idempotencyKey,
                ]
            )
        )
        guard receipt.job.kind == "background_prompt", receipt.job.title == resolvedTitle else {
            throw FabricWorkGatewayError.invalidResponse(
                "Job creation receipt did not match the submitted durable intent."
            )
        }
        return receipt
    }

    /// Fetch exactly one current Job after verifying the full optional Work
    /// capability. The returned subject must match the requested identifier.
    func getWorkJob(
        sessionID: String,
        jobID: String,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkJobSummary {
        try await getWorkJobDetail(
            sessionID: sessionID,
            jobID: jobID,
            negotiation: negotiation
        ).job
    }

    /// `job.get` may include bounded result/error bodies. They are parsed in
    /// a typed detail object but never mixed into the sync projection.
    func getWorkJobDetail(
        sessionID: String,
        jobID: String,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkJobDetail {
        try Self.requireDurableWork(negotiation)
        let requestedID = try Self.requireJobID(jobID)
        let result = try await client.requestObject(
            "job.get",
            params: [
                "session_id": try Self.requireWorkSessionID(sessionID),
                "job_id": requestedID,
            ]
        )
        let detail = try Self.decodeWorkJobDetailResponse(result)
        guard detail.job.jobID == requestedID else {
            throw FabricWorkGatewayError.invalidResponse("Job response did not match job_id.")
        }
        return detail
    }

    func listWorkJobs(
        sessionID: String,
        statuses: [String]? = nil,
        kinds: [String]? = nil,
        sourceSessionKey: String? = nil,
        limit: Int? = nil,
        before: String? = nil,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkJobListResponse {
        try Self.requireDurableWork(negotiation)
        if let limit, !(1...100).contains(limit) {
            throw FabricWorkGatewayError.invalidRequest("Work job limit must be between 1 and 100.")
        }
        var params: [String: Any] = ["session_id": try Self.requireWorkSessionID(sessionID)]
        if let statuses { params["statuses"] = try Self.requireWorkStringList(statuses, field: "statuses") }
        if let kinds { params["kinds"] = try Self.requireWorkStringList(kinds, field: "kinds") }
        if let sourceSessionKey {
            params["source_session_key"] = try Self.requireOpaqueString(
                sourceSessionKey,
                field: "source_session_key",
                maximum: 512
            )
        }
        if let limit { params["limit"] = limit }
        if let before {
            params["before"] = try Self.requireOpaqueString(before, field: "before", maximum: 4_096)
        }
        return try Self.decodeWorkJobListResponse(
            await client.requestObject("job.list", params: params)
        )
    }

    func listWorkEvents(
        sessionID: String,
        after: Int,
        jobID: String? = nil,
        limit: Int? = nil,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkJobEventsResponse {
        try Self.requireDurableWork(negotiation)
        guard (0...Self.maximumSafeWorkInteger).contains(after) else {
            throw FabricWorkGatewayError.invalidRequest("Work event cursor must be a non-negative safe integer.")
        }
        if let limit, !(1...FabricWorkLimits.syncPageItems).contains(limit) {
            throw FabricWorkGatewayError.invalidRequest(
                "Work event limit must be between 1 and \(FabricWorkLimits.syncPageItems)."
            )
        }
        var params: [String: Any] = [
            "session_id": try Self.requireWorkSessionID(sessionID),
            "after": after,
        ]
        if let jobID { params["job_id"] = try Self.requireJobID(jobID) }
        if let limit { params["limit"] = limit }
        let response = try Self.decodeWorkJobEventsResponse(
            await client.requestObject("job.events", params: params)
        )
        guard response.cursor >= after else {
            throw FabricWorkGatewayError.invalidResponse("Work event cursor moved backwards.")
        }
        var previousID = after
        for event in response.events {
            guard event.eventID > previousID, event.eventID <= response.cursor else {
                throw FabricWorkGatewayError.invalidResponse("Work events are not an ordered cursor range.")
            }
            previousID = event.eventID
        }
        return response
    }

    func cancelWorkJob(
        sessionID: String,
        jobID: String,
        expectedVersion: Int,
        idempotencyKey: String,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkJobMutationReceipt {
        try Self.requireDurableWork(negotiation)
        guard (1...Self.maximumSafeWorkInteger).contains(expectedVersion) else {
            throw FabricWorkGatewayError.invalidRequest("Work Job version must be a positive safe integer.")
        }
        let requestedID = try Self.requireJobID(jobID)
        try Self.requireIdempotencyKey(idempotencyKey)
        let receipt = try Self.decodeWorkJobMutationReceipt(
            await client.requestObject(
                "job.cancel",
                params: [
                    "session_id": try Self.requireWorkSessionID(sessionID),
                    "job_id": requestedID,
                    "expected_version": expectedVersion,
                    "idempotency_key": idempotencyKey,
                ]
            )
        )
        guard receipt.job.jobID == requestedID else {
            throw FabricWorkGatewayError.invalidResponse("Work cancel receipt did not match job_id.")
        }
        return receipt
    }

    func getWorkAttention(
        sessionID: String,
        attentionID: String,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkAttention {
        try Self.requireDurableWork(negotiation)
        let requestedID = try Self.requireAttentionID(attentionID)
        let result = try await client.requestObject(
            "attention.get",
            params: [
                "session_id": try Self.requireWorkSessionID(sessionID),
                "attention_id": requestedID,
            ]
        )
        let attention = try Self.decodeWorkValue("Attention response") {
            try FabricWorkParser.decodeAttention(result)
        }
        guard attention.attentionID == requestedID else {
            throw FabricWorkGatewayError.invalidResponse("Attention response did not match attention_id.")
        }
        return attention
    }

    func listWorkAttention(
        sessionID: String,
        states: [String]? = nil,
        kinds: [String]? = nil,
        jobID: String? = nil,
        limit: Int? = nil,
        before: String? = nil,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkAttentionListResponse {
        try Self.requireDurableWork(negotiation)
        if let limit, !(1...100).contains(limit) {
            throw FabricWorkGatewayError.invalidRequest("Work Attention limit must be between 1 and 100.")
        }
        var params: [String: Any] = ["session_id": try Self.requireWorkSessionID(sessionID)]
        if let states { params["states"] = try Self.requireWorkStringList(states, field: "states") }
        if let kinds { params["kinds"] = try Self.requireWorkStringList(kinds, field: "kinds") }
        if let jobID { params["job_id"] = try Self.requireJobID(jobID) }
        if let limit { params["limit"] = limit }
        if let before {
            params["before"] = try Self.requireOpaqueString(before, field: "before", maximum: 4_096)
        }
        return try Self.decodeWorkAttentionListResponse(
            await client.requestObject("attention.list", params: params)
        )
    }

    /// Resolve one exact, actionable Attention item. `value` is deliberately
    /// kept in the request envelope only: this wrapper does not log, persist,
    /// or attach it to the returned receipt.
    func respondToWorkAttention(
        sessionID: String,
        attention: FabricWorkAttention,
        action: String,
        idempotencyKey: String,
        reason: String? = nil,
        value: String? = nil,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkAttentionMutationReceipt {
        try Self.requireDurableWork(negotiation)
        guard attention.actionable, attention.allowedActions.contains(action) else {
            throw FabricWorkGatewayError.invalidRequest("That Attention action is no longer available.")
        }
        try Self.requireIdempotencyKey(idempotencyKey)

        if attention.kind == "approval" {
            guard value == nil else {
                throw FabricWorkGatewayError.invalidRequest("Approval responses do not accept a value.")
            }
            if let reason {
                guard action == "deny", reason.unicodeScalars.count <= 1_000 else {
                    throw FabricWorkGatewayError.invalidRequest(
                        "An approval reason is accepted only when denying and must be at most 1000 characters."
                    )
                }
            }
        } else {
            guard reason == nil else {
                throw FabricWorkGatewayError.invalidRequest("A reason is accepted only for approval.")
            }
            if action == "submit" {
                guard value != nil else {
                    throw FabricWorkGatewayError.invalidRequest("This Attention item requires a value to submit.")
                }
            } else if value != nil {
                throw FabricWorkGatewayError.invalidRequest("This Attention action does not accept a value.")
            }
        }

        var params: [String: Any] = [
            "session_id": try Self.requireWorkSessionID(sessionID),
            "attention_id": try Self.requireAttentionID(attention.attentionID),
            "expected_version": attention.version,
            "idempotency_key": idempotencyKey,
            "action": action,
        ]
        if let reason { params["reason"] = reason }
        if let value { params["value"] = value }

        let receipt = try Self.decodeWorkAttentionMutationReceipt(
            await client.requestObject("attention.respond", params: params)
        )
        let expectedState = action == "deny" || action == "cancel" ? "denied" : "resolved"
        guard receipt.attentionID == attention.attentionID,
              receipt.attentionVersion > attention.version,
              receipt.state == expectedState,
              receipt.delivered
        else {
            throw FabricWorkGatewayError.invalidResponse(
                "Attention response did not match the pending durable item."
            )
        }
        return receipt
    }

    // MARK: - Durable Work response decoding

    static func decodeWorkJobMutationReceipt(_ raw: Any?) throws -> FabricWorkJobMutationReceipt {
        let result = try Self.workObject(raw, label: "Job mutation receipt")
        let job = try Self.decodeWorkValue("Job mutation receipt") {
            try FabricWorkParser.decodeJobSummary(
                try Self.workRequired(result, key: "job", label: "Job mutation receipt")
            )
        }
        let mutationID = try Self.decodeWorkValue("Job mutation receipt") {
            try FabricWorkParser.decodeMutationID(
                try Self.workRequiredString(result, key: "mutation_id", label: "Job mutation receipt", maximum: 64)
            )
        }
        return FabricWorkJobMutationReceipt(
            job: job,
            mutationID: mutationID,
            replayed: try Self.workRequiredBoolean(result, key: "replayed", label: "Job mutation receipt"),
            runtimeStarted: try Self.workOptionalBoolean(result, key: "runtime_started", label: "Job mutation receipt"),
            taskID: try Self.workOptionalString(result, key: "task_id", label: "Job mutation receipt", maximum: 512),
            newlyCancelled: try Self.workOptionalBoolean(result, key: "newly_cancelled", label: "Job mutation receipt")
        )
    }

    static func decodeWorkJobDetailResponse(_ raw: Any?) throws -> FabricWorkJobDetail {
        try Self.decodeWorkValue("Job detail response") {
            try FabricWorkParser.decodeJobDetail(
                try Self.workObject(raw, label: "Job detail response")
            )
        }
    }

    static func decodeWorkAttentionMutationReceipt(_ raw: Any?) throws -> FabricWorkAttentionMutationReceipt {
        let result = try Self.workObject(raw, label: "Attention mutation receipt")
        let attentionID = try Self.decodeWorkValue("Attention mutation receipt") {
            try FabricWorkParser.decodeAttentionID(
                try Self.workRequiredString(result, key: "attention_id", label: "Attention mutation receipt", maximum: 64)
            )
        }
        let mutationID = try Self.decodeWorkValue("Attention mutation receipt") {
            try FabricWorkParser.decodeMutationID(
                try Self.workRequiredString(result, key: "mutation_id", label: "Attention mutation receipt", maximum: 64)
            )
        }
        return FabricWorkAttentionMutationReceipt(
            attentionID: attentionID,
            attentionVersion: try Self.workRequiredSafeInteger(
                result,
                key: "attention_version",
                label: "Attention mutation receipt",
                minimum: 1
            ),
            delivered: try Self.workRequiredBoolean(result, key: "delivered", label: "Attention mutation receipt"),
            mutationID: mutationID,
            replayed: try Self.workRequiredBoolean(result, key: "replayed", label: "Attention mutation receipt"),
            state: try Self.workRequiredString(result, key: "state", label: "Attention mutation receipt", maximum: 32)
        )
    }

    static func decodeWorkJobListResponse(_ raw: Any?) throws -> FabricWorkJobListResponse {
        let result = try Self.workObject(raw, label: "Work job list")
        let rows = try Self.workRequiredArray(result, key: "jobs", label: "Work job list")
        let jobs = try rows.enumerated().map { index, row in
            try Self.decodeWorkValue("Work job list item \(index)") {
                try FabricWorkParser.decodeJobSummary(row)
            }
        }
        return FabricWorkJobListResponse(
            workProfileID: try Self.decodeWorkProfileID(result, label: "Work job list"),
            jobs: jobs,
            nextBefore: try Self.workOptionalString(result, key: "next_before", label: "Work job list", maximum: 4_096)
        )
    }

    static func decodeWorkAttentionListResponse(_ raw: Any?) throws -> FabricWorkAttentionListResponse {
        let result = try Self.workObject(raw, label: "Work Attention list")
        let rows = try Self.workRequiredArray(result, key: "attention", label: "Work Attention list")
        let attention = try rows.enumerated().map { index, row in
            try Self.decodeWorkValue("Work Attention list item \(index)") {
                try FabricWorkParser.decodeAttention(row)
            }
        }
        return FabricWorkAttentionListResponse(
            workProfileID: try Self.decodeWorkProfileID(result, label: "Work Attention list"),
            attention: attention,
            nextBefore: try Self.workOptionalString(result, key: "next_before", label: "Work Attention list", maximum: 4_096)
        )
    }

    static func decodeWorkJobEventsResponse(_ raw: Any?) throws -> FabricWorkJobEventsResponse {
        let result = try Self.workObject(raw, label: "Work event list")
        let rows = try Self.workRequiredArray(result, key: "events", label: "Work event list")
        let events = try rows.enumerated().map { index, row in
            try Self.decodeWorkValue("Work event list item \(index)") {
                try FabricWorkParser.decodeEvent(row)
            }
        }
        return FabricWorkJobEventsResponse(
            workProfileID: try Self.decodeWorkProfileID(result, label: "Work event list"),
            cursor: try Self.workRequiredSafeInteger(result, key: "cursor", label: "Work event list"),
            events: events
        )
    }

    // MARK: - Durable Work validation helpers

    private static let maximumSafeWorkInteger = FabricWorkLimits.maximumSafeInteger

    private static func requireDurableWork(_ negotiation: GatewayCapabilityNegotiation) throws {
        guard negotiation.supportsDurableWork else {
            throw FabricWorkGatewayError.unavailableOnGateway
        }
    }

    private static func requireWorkSessionID(_ sessionID: String) throws -> String {
        guard !sessionID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw FabricWorkGatewayError.invalidRequest("session_id must be non-empty.")
        }
        return sessionID
    }

    private static func requireJobID(_ value: String) throws -> String {
        do {
            return try FabricWorkParser.decodeJobID(value)
        } catch {
            throw FabricWorkGatewayError.invalidRequest("job_id must be a valid Work Job identifier.")
        }
    }

    private static func requireAttentionID(_ value: String) throws -> String {
        do {
            return try FabricWorkParser.decodeAttentionID(value)
        } catch {
            throw FabricWorkGatewayError.invalidRequest("attention_id must be a valid Work Attention identifier.")
        }
    }

    private static func requireIdempotencyKey(_ value: String) throws {
        let valid = value.range(
            of: "^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$",
            options: .regularExpression
        ) != nil
        guard valid else {
            throw FabricWorkGatewayError.invalidRequest(
                "idempotency_key must contain 16 to 128 safe characters."
            )
        }
    }

    private static func requireWorkStringList(_ values: [String], field: String) throws -> [String] {
        guard values.count <= 100 else {
            throw FabricWorkGatewayError.invalidRequest("\(field) must contain at most 100 values.")
        }
        return try values.enumerated().map { index, value in
            try requireOpaqueString(value, field: "\(field)[\(index)]", maximum: 128)
        }
    }

    private static func requireOpaqueString(
        _ value: String,
        field: String,
        maximum: Int
    ) throws -> String {
        guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              value.unicodeScalars.count <= maximum
        else {
            throw FabricWorkGatewayError.invalidRequest("\(field) must be a non-empty string of at most \(maximum) characters.")
        }
        return value
    }

    private static func decodeWorkValue<T>(
        _ label: String,
        _ decode: () throws -> T
    ) throws -> T {
        do {
            return try decode()
        } catch let error as FabricWorkGatewayError {
            throw error
        } catch let error as FabricWorkValueParseError {
            switch error {
            case .invalid(let message):
                throw FabricWorkGatewayError.invalidResponse(message)
            }
        } catch {
            throw FabricWorkGatewayError.invalidResponse("\(label) is invalid.")
        }
    }

    private static func workObject(_ raw: Any?, label: String) throws -> [String: Any] {
        guard let result = raw as? [String: Any] else {
            throw FabricWorkGatewayError.invalidResponse("\(label) must be an object.")
        }
        return result
    }

    private static func workRequired(_ result: [String: Any], key: String, label: String) throws -> Any {
        guard result.keys.contains(key) else {
            throw FabricWorkGatewayError.invalidResponse("\(label) is missing \(key).")
        }
        return result[key] as Any
    }

    private static func workRequiredArray(_ result: [String: Any], key: String, label: String) throws -> [Any] {
        guard let values = try workRequired(result, key: key, label: label) as? [Any] else {
            throw FabricWorkGatewayError.invalidResponse("\(label) has an invalid \(key).")
        }
        return values
    }

    private static func workRequiredString(
        _ result: [String: Any],
        key: String,
        label: String,
        maximum: Int
    ) throws -> String {
        guard let value = try workRequired(result, key: key, label: label) as? String,
              !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              value.unicodeScalars.count <= maximum
        else {
            throw FabricWorkGatewayError.invalidResponse("\(label) has an invalid \(key).")
        }
        return value
    }

    private static func workOptionalString(
        _ result: [String: Any],
        key: String,
        label: String,
        maximum: Int
    ) throws -> String? {
        guard let raw = result[key], !(raw is NSNull) else { return nil }
        return try workRequiredString(result, key: key, label: label, maximum: maximum)
    }

    private static func workRequiredBoolean(
        _ result: [String: Any],
        key: String,
        label: String
    ) throws -> Bool {
        guard let number = try workRequired(result, key: key, label: label) as? NSNumber,
              CFGetTypeID(number) == CFBooleanGetTypeID()
        else {
            throw FabricWorkGatewayError.invalidResponse("\(label) has an invalid \(key).")
        }
        return number.boolValue
    }

    private static func workOptionalBoolean(
        _ result: [String: Any],
        key: String,
        label: String
    ) throws -> Bool? {
        guard let raw = result[key], !(raw is NSNull) else { return nil }
        return try workRequiredBoolean(result, key: key, label: label)
    }

    private static func workRequiredSafeInteger(
        _ result: [String: Any],
        key: String,
        label: String,
        minimum: Int = 0
    ) throws -> Int {
        guard let number = try workRequired(result, key: key, label: label) as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID()
        else {
            throw FabricWorkGatewayError.invalidResponse("\(label) has an invalid \(key).")
        }
        let value = number.doubleValue
        guard value.isFinite,
              value.rounded(.towardZero) == value,
              value >= Double(minimum),
              value <= Double(maximumSafeWorkInteger),
              value <= Double(Int.max)
        else {
            throw FabricWorkGatewayError.invalidResponse("\(label) has an invalid \(key).")
        }
        return Int(value)
    }

    private static func decodeWorkProfileID(_ result: [String: Any], label: String) throws -> String {
        try decodeWorkValue(label) {
            try FabricWorkParser.decodeProfileID(
                try workRequired(result, key: "work_profile_id", label: label)
            )
        }
    }

    // MARK: - Sessions

    func listSessions(limit: Int = 100) async throws -> [SessionSummary] {
        let result = try await client.requestObject("session.list", params: ["limit": limit])
        let rows = result["sessions"] as? [[String: Any]] ?? []
        return rows.compactMap { row in
            guard let id = row["id"] as? String else { return nil }
            return SessionSummary(
                id: id,
                title: row["title"] as? String ?? "",
                preview: row["preview"] as? String ?? "",
                startedAt: (row["started_at"] as? NSNumber)?.doubleValue ?? 0,
                messageCount: (row["message_count"] as? NSNumber)?.intValue ?? 0,
                source: row["source"] as? String ?? ""
            )
        }
    }

    func createSession(profile: String? = nil) async throws -> LiveSession {
        var params: [String: Any] = ["cols": 96, "source": "mobile"]
        if let profile, !profile.isEmpty { params["profile"] = profile }
        let result = try await client.requestObject("session.create", params: params)
        let info = result["info"] as? [String: Any]
        return LiveSession(
            sessionId: result["session_id"] as? String ?? "",
            storedSessionId: result["stored_session_id"] as? String,
            workIdentity: info.flatMap(FabricWorkSessionIdentity.from(sessionInfo:)),
            usage: (info?["usage"] as? [String: Any]).flatMap(SessionUsage.from(payload:))
        )
    }

    func resumeSession(storedSessionId: String) async throws -> LiveSession {
        let result = try await client.requestObject(
            "session.resume",
            params: ["session_id": storedSessionId, "cols": 96, "source": "mobile"]
        )
        return LiveSession(resumePayload: result, storedSessionId: storedSessionId)
    }

    /// Rename a live session (its runtime id, not the stored key). The typed
    /// `session.title` RPC is preferred whenever the negotiated contract
    /// advertises it; today's mobile contract instead carries the gateway's
    /// registered `/title` slash command, which persists the same
    /// stored-session title (`_session_title_in_db` and the `/title` handler
    /// share the title write in `tui_gateway/server.py`).
    func setSessionTitle(
        sessionId: String,
        title: String,
        preferTypedMethod: Bool
    ) async throws -> String {
        let title = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else {
            throw GatewayClientError.rpc(message: "A conversation title is required.")
        }
        if preferTypedMethod {
            let result = try await client.requestObject(
                "session.title",
                params: ["session_id": sessionId, "title": title]
            )
            guard let confirmed = result["title"] as? String,
                  !confirmed.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw GatewayClientError.rpc(message: "The gateway did not confirm the new title.")
            }
            return confirmed
        }
        let result = try await client.requestObject(
            "slash.exec",
            params: ["session_id": sessionId, "command": "/title \(title)"]
        )
        // `/title` reports both semantic success and failure as ordinary
        // output text. Require its positive confirmation instead of trying to
        // enumerate every rejection (length, cleanup, uniqueness, missing
        // session, and future validation rules).
        return try Self.confirmedSlashSessionTitle(from: result["output"] as? String)
    }

    static func confirmedSlashSessionTitle(from output: String?) throws -> String {
        let successPrefix = "Session title set:"
        let lines = (output ?? "").split(whereSeparator: \.isNewline)
        guard let confirmation = lines
            .map({ $0.trimmingCharacters(in: .whitespacesAndNewlines) })
            .first(where: { $0.hasPrefix(successPrefix) })
        else {
            throw GatewayClientError.rpc(message: "The gateway did not save this title.")
        }

        let confirmed = confirmation
            .dropFirst(successPrefix.count)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !confirmed.isEmpty else {
            throw GatewayClientError.rpc(message: "The gateway did not confirm the new title.")
        }
        return confirmed
    }

    // MARK: - Prompt attachments (`files` feature)

    /// Queue image bytes for the next prompt (`image.attach_bytes`). PNG,
    /// JPEG, GIF, WebP, and BMP pass through byte-identical — the server
    /// sniffs magic bytes. Returns the server-authored placeholder line for
    /// the queued image.
    func attachImageBytes(
        sessionId: String,
        data: Data,
        filename: String
    ) async throws -> String {
        let result = try await client.requestObject(
            "image.attach_bytes",
            params: [
                "session_id": sessionId,
                "content_base64": data.base64EncodedString(),
                "filename": filename,
            ]
        )
        guard result["attached"] as? Bool == true else {
            throw GatewayClientError.rpc(message: "The image was not attached.")
        }
        return result["text"] as? String ?? "[User attached image: \(filename)]"
    }

    /// Queue a PDF for the next prompt (`pdf.attach`) — the gateway renders
    /// each page for the model's vision pipeline. Returns the placeholder
    /// line naming the attached document.
    func attachPDF(
        sessionId: String,
        data: Data,
        filename: String
    ) async throws -> String {
        let result = try await client.requestObject(
            "pdf.attach",
            params: [
                "session_id": sessionId,
                "content_base64": data.base64EncodedString(),
                "filename": filename,
            ]
        )
        guard result["attached"] as? Bool == true else {
            throw GatewayClientError.rpc(message: "The PDF was not attached.")
        }
        return result["text"] as? String ?? "[User attached PDF: \(filename)]"
    }

    /// Stage a non-image file in the session workspace (`file.attach`).
    /// Returns the server's `@file:` reference, which must appear in the
    /// prompt text so the agent's file tools can find the upload.
    func attachFile(
        sessionId: String,
        data: Data,
        filename: String,
        mimeType: String
    ) async throws -> String {
        let result = try await client.requestObject(
            "file.attach",
            params: [
                "session_id": sessionId,
                "data_url": "data:\(mimeType);base64,\(data.base64EncodedString())",
                "name": filename,
            ]
        )
        guard result["attached"] as? Bool == true,
              let ref = result["ref_text"] as? String,
              !ref.isEmpty else {
            throw GatewayClientError.rpc(message: "The file was not attached.")
        }
        return ref
    }

    // MARK: - Turns

    func submitPrompt(sessionId: String, text: String) async throws {
        _ = try await client.request(
            "prompt.submit",
            params: ["session_id": sessionId, "text": text]
        )
    }

    func interrupt(sessionId: String) async throws {
        _ = try await client.request("session.interrupt", params: ["session_id": sessionId])
    }

    /// Resolve exactly one authoritative approval request. Programmatic
    /// clients never use the legacy FIFO/all-pending compatibility path.
    func respondToApproval(
        sessionId: String,
        requestId: String,
        choice: String
    ) async throws {
        let result = try await client.requestObject(
            "approval.respond",
            params: [
                "session_id": sessionId,
                "request_id": requestId,
                "choice": choice,
            ]
        )
        try Self.requireMatchingInteractionReceipt(result, requestId: requestId, approval: true)
    }

    // MARK: - Remote control / dispatch

    /// Inject a mid-turn note without interrupting (`AIAgent.steer`). Returns
    /// true when the gateway queued it, false when the agent rejected it.
    func steer(sessionId: String, text: String) async throws -> Bool {
        let result = try await client.requestObject(
            "session.steer",
            params: ["session_id": sessionId, "text": text]
        )
        return (result["status"] as? String) == "queued"
    }

    /// Run a prompt as a detached background task. The result arrives later
    /// as a `background.complete` event with `{task_id, text}`.
    func submitBackgroundPrompt(sessionId: String, text: String) async throws -> String? {
        let result = try await client.requestObject(
            "prompt.background",
            params: ["session_id": sessionId, "text": text]
        )
        return result["task_id"] as? String
    }

    /// Dispatch a slash command exactly as the TUI composer does. Some
    /// commands return inline `output`; others act via streamed events.
    func execSlashCommand(sessionId: String, command: String) async throws -> String? {
        let result = try await client.requestObject(
            "slash.exec",
            params: ["session_id": sessionId, "command": command]
        )
        return result["output"] as? String
    }

    /// The registry-backed slash-command catalog, grouped by category.
    func commandCatalog() async throws -> [SlashCommandCategory] {
        let result = try await client.requestObject("commands.catalog")
        let categories = result["categories"] as? [[String: Any]] ?? []
        return categories.compactMap { category in
            guard let name = category["name"] as? String else { return nil }
            let pairs = category["pairs"] as? [[Any]] ?? []
            let commands: [SlashCommand] = pairs.compactMap { pair in
                guard let cmdName = pair.first as? String else { return nil }
                return SlashCommand(
                    name: cmdName,
                    detail: pair.count > 1 ? (pair[1] as? String ?? "") : ""
                )
            }
            return commands.isEmpty ? nil : SlashCommandCategory(name: name, commands: commands)
        }
    }

    /// Live gateway sessions (running turns, waiting prompts, idle agents).
    func activeSessions(currentSessionId: String? = nil) async throws -> [ActiveSession] {
        var params: [String: Any] = [:]
        if let currentSessionId { params["current_session_id"] = currentSessionId }
        let result = try await client.requestObject("session.active_list", params: params)
        let rows = result["sessions"] as? [[String: Any]] ?? []
        return rows.compactMap(ActiveSession.init(payload:))
    }

    /// Background processes owned by a session (preview servers, watchers…).
    func listProcesses(sessionId: String) async throws -> [BackgroundProcess] {
        let result = try await client.requestObject(
            "process.list",
            params: ["session_id": sessionId]
        )
        let rows = result["processes"] as? [[String: Any]] ?? []
        return rows.compactMap { row in
            guard let id = row["session_id"] as? String else { return nil }
            return BackgroundProcess(
                id: id,
                command: row["command"] as? String ?? "",
                pid: (row["pid"] as? NSNumber)?.intValue ?? 0,
                status: row["status"] as? String ?? "running",
                uptimeSeconds: (row["uptime_seconds"] as? NSNumber)?.intValue ?? 0,
                outputTail: row["output_tail"] as? String ?? ""
            )
        }
    }

    func killProcess(sessionId: String, processId: String) async throws -> ProcessKillReceipt {
        let result = try await client.requestObject(
            "process.kill",
            params: ["session_id": sessionId, "process_id": processId]
        )
        return try Self.requireProcessKillReceipt(result)
    }

    // MARK: - Pets (cosmetic companion)
    // Display + adopt only; generation, management, and the global scale knob
    // remain desktop/host surfaces.

    /// The active pet's spritesheet, or nil when pets are disabled — the
    /// server fails open and answers `{enabled: false}` on any problem.
    func petInfo() async throws -> PetSpriteSheet? {
        let result = try await client.requestObject("pet.info")
        return PetSpriteSheet.from(payload: result)
    }

    /// Cheap active-pet metadata used to avoid refetching an unchanged sheet.
    func petInfoMeta() async throws -> PetInfoMeta {
        let result = try await client.requestObject("pet.info.meta")
        return PetInfoMeta(
            enabled: result["enabled"] as? Bool == true,
            slug: result["slug"] as? String,
            displayName: result["displayName"] as? String,
            spritesheetRevision: result["spritesheetRevision"] as? String
        )
    }

    /// Adoptable pets merged with local install state. `localOnly` skips the
    /// remote manifest fetch so installed pets render instantly.
    func petGallery(localOnly: Bool) async throws -> PetGalleryState {
        let result = try await client.requestObject(
            "pet.gallery",
            params: ["localOnly": localOnly]
        )
        let rows = result["pets"] as? [[String: Any]] ?? []
        return PetGalleryState(
            enabled: result["enabled"] as? Bool == true,
            active: result["active"] as? String ?? "",
            pets: rows.compactMap { row in
                guard let slug = row["slug"] as? String, !slug.isEmpty else { return nil }
                return PetGalleryEntry(
                    slug: slug,
                    displayName: row["displayName"] as? String ?? slug,
                    installed: row["installed"] as? Bool ?? false,
                    curated: row["curated"] as? Bool ?? false,
                    generated: row["generated"] as? Bool ?? false,
                    bundled: row["bundled"] as? Bool ?? false,
                    spritesheetUrl: row["spritesheetUrl"] as? String ?? ""
                )
            }
        )
    }

    /// Install (if needed) and activate one pet. The caller re-pulls
    /// `pet.info` to render the adopted sheet.
    func petSelect(slug: String) async throws -> (slug: String, displayName: String) {
        let result = try await client.requestObject("pet.select", params: ["slug": slug])
        guard result["ok"] as? Bool == true,
              let selected = result["slug"] as? String,
              let displayName = result["displayName"] as? String
        else {
            throw GatewayClientError.rpc(message: "The pet couldn't be adopted on this gateway.")
        }
        return (slug: selected, displayName: displayName)
    }

    /// Turn the companion off server-side (`display.pet.enabled = false`).
    func petDisable() async throws {
        let result = try await client.requestObject("pet.disable")
        guard result["ok"] as? Bool == true else {
            throw GatewayClientError.rpc(message: "The pet couldn't be disabled on this gateway.")
        }
    }

    /// Small idle-frame preview as a PNG data URI, or nil when unavailable —
    /// `pet.thumb` fails open with `{ok: false}`.
    func petThumb(slug: String, url: String?) async throws -> String? {
        var params: [String: Any] = ["slug": slug]
        if let url, !url.isEmpty { params["url"] = url }
        let result = try await client.requestObject("pet.thumb", params: params)
        guard result["ok"] as? Bool == true else { return nil }
        return result["dataUri"] as? String
    }

    // MARK: - Computer use (live view)

    /// A read-only screen capture from the gateway host (`computer.screenshot`).
    /// The gateway returns a plain PNG or JPEG (no overlays or accessibility
    /// data); older capture backends commonly use JPEG quality 85.
    func captureScreen() async throws -> ScreenCapture {
        let result = try await client.requestObject("computer.screenshot")
        return try Self.decodeScreenCapture(result)
    }

    /// Validate the encoded payload and ImageIO header without rasterizing it.
    /// `LiveViewModel` can safely hand the returned bounded image to UIImage.
    static func decodeScreenCapture(
        _ result: [String: Any],
        limits: ScreenCaptureValidationLimits = .production
    ) throws -> ScreenCapture {
        guard
            let b64 = result["png_b64"] as? String,
            b64.utf8.count <= limits.maxEncodedBytes,
            let reportedWidth = positiveScreenDimension(result["width"]),
            let reportedHeight = positiveScreenDimension(result["height"]),
            screenDimensionsAreSafe(
                width: reportedWidth,
                height: reportedHeight,
                limits: limits
            ),
            let data = Data(base64Encoded: b64),
            data.count <= limits.maxDecodedBytes,
            let signatureMIME = supportedSignatureMIME(for: data),
            let source = CGImageSourceCreateWithData(
                data as CFData,
                [kCGImageSourceShouldCache: false] as CFDictionary
            ),
            let imageSourceType = CGImageSourceGetType(source) as String?,
            let imageSourceMIME = supportedMIME(forImageSourceType: imageSourceType),
            imageSourceMIME == signatureMIME,
            advertisedMIME(result["mime"], matches: imageSourceMIME),
            CGImageSourceGetCount(source) == 1,
            let properties = CGImageSourceCopyPropertiesAtIndex(
                source,
                0,
                [kCGImageSourceShouldCache: false] as CFDictionary
            ) as? [CFString: Any],
            let actualWidth = positiveScreenDimension(properties[kCGImagePropertyPixelWidth]),
            let actualHeight = positiveScreenDimension(properties[kCGImagePropertyPixelHeight]),
            actualWidth == reportedWidth,
            actualHeight == reportedHeight,
            screenDimensionsAreSafe(width: actualWidth, height: actualHeight, limits: limits)
        else {
            throw invalidScreenCaptureError()
        }
        return ScreenCapture(
            image: data,
            width: actualWidth,
            height: actualHeight
        )
    }

    private static let pngSignature = Data([137, 80, 78, 71, 13, 10, 26, 10])
    private static let jpegSignature = Data([255, 216, 255])

    private static func supportedSignatureMIME(for data: Data) -> String? {
        if data.starts(with: pngSignature) { return "image/png" }
        if data.starts(with: jpegSignature) { return "image/jpeg" }
        return nil
    }

    private static func supportedMIME(forImageSourceType type: String) -> String? {
        switch type {
        case UTType.png.identifier:
            return "image/png"
        case UTType.jpeg.identifier:
            return "image/jpeg"
        default:
            return nil
        }
    }

    /// Older gateways did not publish a MIME field. When present it becomes a
    /// contract assertion and must agree with byte-signature + ImageIO sniffing.
    private static func advertisedMIME(_ value: Any?, matches actual: String) -> Bool {
        guard let value else { return true }
        guard let mime = value as? String else { return false }
        return mime.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == actual
    }

    private static func positiveScreenDimension(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID()
        else { return nil }
        let double = number.doubleValue
        guard double.isFinite,
              double >= 1,
              double.rounded(.towardZero) == double,
              double <= Double(Int.max)
        else { return nil }
        return Int(double)
    }

    private static func screenDimensionsAreSafe(
        width: Int,
        height: Int,
        limits: ScreenCaptureValidationLimits
    ) -> Bool {
        width <= limits.maxDimension
            && height <= limits.maxDimension
            && width <= limits.maxPixelCount / height
    }

    private static func invalidScreenCaptureError() -> GatewayClientError {
        GatewayClientError.rpc(message: "Live view unavailable on this server.")
    }

    // MARK: - Blocking prompt responses (clarify / sudo / secret)
    // These unblock `_block(...)` waits keyed by `request_id`
    // (`_respond` in `tui_gateway/server.py`).

    func respondToClarify(sessionId: String, requestId: String, answer: String) async throws {
        let result = try await client.requestObject(
            "clarify.respond",
            params: ["session_id": sessionId, "request_id": requestId, "answer": answer]
        )
        try Self.requireMatchingInteractionReceipt(result, requestId: requestId)
    }

    func respondToSudo(sessionId: String, requestId: String, password: String) async throws {
        let result = try await client.requestObject(
            "sudo.respond",
            params: ["session_id": sessionId, "request_id": requestId, "password": password]
        )
        try Self.requireMatchingInteractionReceipt(result, requestId: requestId)
    }

    func respondToSecret(sessionId: String, requestId: String, value: String) async throws {
        let result = try await client.requestObject(
            "secret.respond",
            params: ["session_id": sessionId, "request_id": requestId, "value": value]
        )
        try Self.requireMatchingInteractionReceipt(result, requestId: requestId)
    }
}
