import Foundation

/// The native client implementation of the versioned `fabric.work` v1 wire
/// contract. This deliberately mirrors `apps/shared/src/work-contract.ts`:
/// pages are parsed before they are projected, required nullable fields are
/// still required, and a compatible future enum is retained for display but
/// never treated as an action the phone understands.
let fabricWorkClientContractVersion = 1

enum FabricWorkLimits {
    static let maximumSafeInteger = 9_007_199_254_740_991
    static let syncPageBytes = 1_024 * 1_024
    static let syncPageItems = 500
    static let subjectBytes = 32 * 1_024
    static let resultPreviewBytes = 4 * 1_024
    static let errorPreviewBytes = 8 * 1_024
    static let jobDetailBodyBytes = 256 * 1_024
}

struct FabricWorkUnknownEnum: Equatable {
    let field: String
    let raw: String
}

struct FabricWorkContractDescriptor: Equatable {
    let name: String
    let version: Int
    let minimumCompatibleVersion: Int
}

/// A recursively normalized JSON value. Keeping public payloads in this
/// narrow type prevents an `Any` payload from escaping the parser into a
/// projection or UI state.
indirect enum FabricWorkJSONValue: Equatable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([FabricWorkJSONValue])
    case object([String: FabricWorkJSONValue])

    var foundationValue: Any {
        switch self {
        case .null:
            return NSNull()
        case .bool(let value):
            return value
        case .number(let value):
            return value
        case .string(let value):
            return value
        case .array(let values):
            return values.map(\.foundationValue)
        case .object(let values):
            return values.mapValues(\.foundationValue)
        }
    }
}

typealias FabricWorkJSONObject = [String: FabricWorkJSONValue]

struct FabricWorkRunSummary: Equatable {
    let runID: String
    let attempt: Int
    let version: Int
    let status: String
    let runtimeKind: String
    let ownerState: String
    let restartBehavior: String
    let claimedAt: Int?
    let startedAt: Int?
    let updatedAt: Int
    let finishedAt: Int?
    let actionable: Bool
    let unknownEnums: [FabricWorkUnknownEnum]
}

struct FabricWorkJobSummary: Equatable {
    let jobID: String
    let version: Int
    let kind: String
    let status: String
    let title: String
    let summary: String?
    let source: String
    let sourceSessionKey: String?
    let runtimeSessionID: String?
    let attemptCount: Int
    let openAttentionCount: Int
    let createdAt: Int
    let startedAt: Int?
    let updatedAt: Int
    let finishedAt: Int?
    let cancelRequestedAt: Int?
    let runtime: FabricWorkJSONObject
    let currentRun: FabricWorkRunSummary?
    let resultPreview: FabricWorkJSONValue
    let resultReference: String?
    let resultOmittedReason: String?
    let error: FabricWorkJSONValue
    let actionable: Bool
    let unknownEnums: [FabricWorkUnknownEnum]
}

/// `job.get` may append bounded bodies to the normal public Job after-state.
/// The summary is still parsed through the same strict, projection-safe
/// decoder; detail fields never enter sync state and remain value-typed.
struct FabricWorkJobDetail: Equatable {
    let job: FabricWorkJobSummary
    let promptPreview: String?
    let result: FabricWorkJSONValue?
    let errorDetail: FabricWorkJSONValue?
}

struct FabricWorkAttention: Equatable {
    let attentionID: String
    let version: Int
    let jobID: String?
    let runID: String?
    let sourceSessionKey: String?
    let runtimeSessionID: String?
    let requestID: String
    let kind: String
    let state: String
    let blocking: Bool
    let sensitive: Bool
    let title: String
    let publicPayload: FabricWorkJSONObject
    let allowedActions: [String]
    let createdAt: Int
    let updatedAt: Int
    let expiresAt: Int?
    let resolvedAt: Int?
    let terminalReason: String?
    let actionable: Bool
    let unknownEnums: [FabricWorkUnknownEnum]
}

struct FabricWorkUnknownSubject: Equatable {
    let raw: FabricWorkJSONObject
    let unknownEnums: [FabricWorkUnknownEnum]

    let actionable = false
}

enum FabricWorkEventSubject: Equatable {
    case job(FabricWorkJobSummary)
    case attention(FabricWorkAttention)
    case unknown(FabricWorkUnknownSubject)

    var actionable: Bool {
        switch self {
        case .job(let job): return job.actionable
        case .attention(let attention): return attention.actionable
        case .unknown: return false
        }
    }

    var identifier: String? {
        switch self {
        case .job(let job): return job.jobID
        case .attention(let attention): return attention.attentionID
        case .unknown: return nil
        }
    }

    var version: Int? {
        switch self {
        case .job(let job): return job.version
        case .attention(let attention): return attention.version
        case .unknown: return nil
        }
    }

    var unknownEnums: [FabricWorkUnknownEnum] {
        switch self {
        case .job(let job): return job.unknownEnums
        case .attention(let attention): return attention.unknownEnums
        case .unknown(let subject): return subject.unknownEnums
        }
    }
}

struct FabricWorkEvent: Equatable {
    let eventID: Int
    let eventType: String
    let subjectType: String
    let subjectID: String
    let jobID: String?
    let runID: String?
    let subjectVersion: Int
    let subject: FabricWorkEventSubject?
    let tombstone: Bool
    let createdAt: Int
    let actionable: Bool
    let unknownEnums: [FabricWorkUnknownEnum]
}

struct FabricWorkSyncPage: Equatable {
    let contract: FabricWorkContractDescriptor
    let ledgerID: String
    let workProfileID: String
    let mode: String
    let watermark: Int
    let cursor: Int
    let hasMore: Bool
    let nextPageToken: String?
    let jobs: [FabricWorkJobSummary]
    let attention: [FabricWorkAttention]
    let events: [FabricWorkEvent]
    let encodedBytes: Int
    let actionable: Bool
    let unknownEnums: [FabricWorkUnknownEnum]
}

enum FabricWorkSyncParseResult: Equatable {
    case verified(FabricWorkSyncPage)
    case incompatible(minimumCompatibleVersion: Int)
    case invalid(message: String)
}

struct FabricWorkCursorReset: Equatable {
    struct Data: Equatable {
        let reason: String?
        let ledgerID: String?
        let eventFloor: Int?
        let highWater: Int?
    }

    let message: String
    let data: Data
}

enum FabricWorkCursorResetParseResult: Equatable {
    case verified(FabricWorkCursorReset)
    case invalid(message: String)
}

/// Typed error used by non-sync Work RPC wrappers (`job.get`, list responses,
/// and mutation receipts). The raw server payload is intentionally never
/// retained on failure.
enum FabricWorkValueParseError: LocalizedError, Equatable {
    case invalid(String)

    var errorDescription: String? {
        switch self {
        case .invalid(let message): return message
        }
    }
}

/// Strict, additive-aware decoder for pages returned by `job.sync` and the
/// sanitized `cursor_expired` JSON-RPC error body. It intentionally does not
/// infer a legacy Work mode: callers must negotiate and gate Work separately.
enum FabricWorkParser {
    static func parseSyncPage(
        _ value: Any,
        encodedBytes: Int? = nil
    ) -> FabricWorkSyncParseResult {
        do {
            let measuredBytes = try jsonByteLength(value)
            let pageBytes = encodedBytes ?? measuredBytes
            guard pageBytes >= 0,
                  pageBytes <= FabricWorkLimits.syncPageBytes,
                  measuredBytes <= FabricWorkLimits.syncPageBytes
            else {
                throw DecodeError("work sync page exceeds its \(FabricWorkLimits.syncPageBytes)-byte wire limit.")
            }

            let raw = try object(value, path: "work")
            switch try parseContract(raw) {
            case .incompatible(let minimum):
                return .incompatible(minimumCompatibleVersion: minimum)
            case .verified(let contract):
                return .verified(try parsePage(
                    raw,
                    contract: contract,
                    encodedBytes: pageBytes
                ))
            }
        } catch let error as DecodeError {
            return .invalid(message: error.message)
        } catch {
            return .invalid(message: "Work sync page is malformed.")
        }
    }

    /// Parse the only reset error that may cause a client to discard its
    /// projection. Other RPC failures are not reset signals and must remain
    /// visible to the caller.
    static func parseCursorReset(_ value: Any) -> FabricWorkCursorResetParseResult {
        do {
            let raw = try object(value, path: "work reset")
            let resetCode = try signedSafeInteger(
                try required(raw, "code", path: "work reset"),
                path: "work reset.code"
            )
            guard resetCode == -32_047 else {
                throw DecodeError("work reset.code must be -32047.")
            }
            let data = try object(
                try required(raw, "data", path: "work reset"),
                path: "work reset.data"
            )
            guard try required(data, "code", path: "work reset.data") as? String == "cursor_expired" else {
                throw DecodeError("work reset.data.code must be cursor_expired.")
            }
            guard try strictBoolean(
                try required(data, "bootstrap", path: "work reset.data"),
                path: "work reset.data.bootstrap"
            ) else {
                throw DecodeError("work reset.data.bootstrap must be true.")
            }

            let ledgerID: String?
            if let value = data["ledger_id"], !isNull(value) {
                ledgerID = try workIdentifier(value, kind: .ledger, path: "work reset.data.ledger_id")
            } else {
                ledgerID = nil
            }
            let eventFloor = try optionalInteger(data, key: "event_floor", path: "work reset.data")
            let highWater = try optionalInteger(data, key: "high_water", path: "work reset.data")
            if let eventFloor, let highWater, eventFloor > highWater + 1 {
                throw DecodeError("work reset event_floor cannot exceed high_water + 1.")
            }
            let reason = try optionalString(data, key: "reason", path: "work reset.data", max: 128)

            return .verified(FabricWorkCursorReset(
                message: try string(
                    try required(raw, "message", path: "work reset"),
                    path: "work reset.message",
                    max: 512
                ),
                data: .init(
                    reason: reason,
                    ledgerID: ledgerID,
                    eventFloor: eventFloor,
                    highWater: highWater
                )
            ))
        } catch let error as DecodeError {
            return .invalid(message: error.message)
        } catch {
            return .invalid(message: "Work cursor reset is malformed.")
        }
    }

    /// Decode one public Job after-state returned by a read or mutation RPC.
    /// Unknown additive fields are omitted and compatible future enum values
    /// remain visible but non-actionable, exactly as they do in sync pages.
    static func decodeJobSummary(_ value: Any) throws -> FabricWorkJobSummary {
        try decodeValue("Work Job response") {
            try parseJob(value, path: "work.job")
        }
    }

    /// Decode `job.get` without letting its optional 256 KiB bodies weaken
    /// the smaller sync/list subject boundary. Unknown detail keys are
    /// additive and ignored; the known bodies stay in typed, non-projection
    /// memory only.
    static func decodeJobDetail(_ value: Any) throws -> FabricWorkJobDetail {
        try decodeValue("Work Job detail response") {
            let raw = try object(value, path: "work.job_detail")
            var summary: [String: Any] = [:]
            for key in jobSummaryFields {
                summary[key] = try required(raw, key, path: "work.job_detail")
            }
            let job = try parseJob(summary, path: "work.job_detail")

            let promptPreview: String?
            if let rawPrompt = raw["prompt_preview"], !isNull(rawPrompt) {
                promptPreview = try string(
                    rawPrompt,
                    path: "work.job_detail.prompt_preview",
                    max: 1_000,
                    nonempty: false
                )
            } else {
                promptPreview = nil
            }

            let result = try optionalDetailJSON(raw, key: "result", path: "work.job_detail")
            let errorDetail = try optionalDetailJSON(raw, key: "error_detail", path: "work.job_detail")
            guard job.resultOmittedReason == nil || result == nil else {
                throw DecodeError("work.job_detail.result must be null when a result is omitted.")
            }
            return FabricWorkJobDetail(
                job: job,
                promptPreview: promptPreview,
                result: result,
                errorDetail: errorDetail
            )
        }
    }

    /// Decode one public Attention after-state without accepting any response
    /// value or transport-local state into the DTO.
    static func decodeAttention(_ value: Any) throws -> FabricWorkAttention {
        try decodeValue("Work Attention response") {
            try parseAttention(value, path: "work.attention")
        }
    }

    /// Decode a public Work event for `job.events` list responses.
    static func decodeEvent(_ value: Any) throws -> FabricWorkEvent {
        try decodeValue("Work event response") {
            try parseEvent(value, path: "work.event")
        }
    }

    static func decodeProfileID(_ value: Any) throws -> String {
        try decodeValue("Work profile identity") {
            try workIdentifier(value, kind: .profile, path: "work.work_profile_id")
        }
    }

    static func decodeJobID(_ value: Any) throws -> String {
        try decodeValue("Work Job identity") {
            try workIdentifier(value, kind: .job, path: "work.job_id")
        }
    }

    static func decodeAttentionID(_ value: Any) throws -> String {
        try decodeValue("Work Attention identity") {
            try workIdentifier(value, kind: .attention, path: "work.attention_id")
        }
    }

    static func decodeLedgerID(_ value: Any) throws -> String {
        try decodeValue("Work ledger identity") {
            try workIdentifier(value, kind: .ledger, path: "work.ledger_id")
        }
    }

    static func decodeMutationID(_ value: Any) throws -> String {
        try decodeValue("Work mutation identity") {
            try workIdentifier(value, kind: .mutation, path: "work.mutation_id")
        }
    }

    private enum ParsedContract {
        case verified(FabricWorkContractDescriptor)
        case incompatible(Int)
    }

    private enum IdentifierKind: String {
        case attention = "attn_"
        case job = "job_"
        case ledger = "ledger_"
        case mutation = "mut_"
        case profile = "profile_"
        case run = "run_"
    }

    private struct DecodeError: Error {
        let message: String

        init(_ message: String) {
            self.message = message
        }
    }

    private static func decodeValue<T>(_ label: String, _ body: () throws -> T) throws -> T {
        do {
            return try body()
        } catch let error as DecodeError {
            throw FabricWorkValueParseError.invalid("\(label) is invalid: \(error.message)")
        } catch {
            throw FabricWorkValueParseError.invalid("\(label) is invalid.")
        }
    }

    private static let knownJobKinds: Set<String> = ["background_prompt"]
    private static let knownJobStatuses: Set<String> = [
        "queued", "claimed", "running", "waiting_attention", "cancel_requested",
        "succeeded", "failed", "cancelled", "interrupted",
    ]
    private static let knownAttentionKinds: Set<String> = ["approval", "clarify", "sudo", "secret"]
    private static let knownAttentionStates: Set<String> = [
        "pending", "resolving", "resolved", "denied", "expired", "cancelled", "orphaned",
    ]
    private static let knownAttentionActions: Set<String> = [
        "once", "session", "always", "deny", "submit", "cancel",
    ]
    private static let knownRuntimeKinds: Set<String> = ["in_process_agent"]
    private static let knownOwnerStates: Set<String> = ["creator_bound"]
    private static let knownRestartBehaviors: Set<String> = ["interrupt"]
    private static let knownResultOmittedReasons: Set<String> = ["sensitive_input"]
    private static let knownModes: Set<String> = ["bootstrap", "delta"]
    private static let knownSubjectTypes: Set<String> = ["job", "attention"]
    private static let jobSummaryFields = [
        "job_id",
        "version",
        "kind",
        "status",
        "title",
        "summary",
        "source",
        "source_session_key",
        "runtime_session_id",
        "attempt_count",
        "open_attention_count",
        "created_at",
        "started_at",
        "updated_at",
        "finished_at",
        "cancel_requested_at",
        "runtime",
        "current_run",
        "result_preview",
        "result_ref",
        "result_omitted_reason",
        "error",
    ]

    private static func parsePage(
        _ raw: [String: Any],
        contract: FabricWorkContractDescriptor,
        encodedBytes: Int
    ) throws -> FabricWorkSyncPage {
        var unknown: [FabricWorkUnknownEnum] = []
        let mode = try enumValue(
            try required(raw, "mode", path: "work"),
            known: knownModes,
            path: "work.mode",
            unknown: &unknown
        )
        let watermark = try safeInteger(
            try required(raw, "watermark", path: "work"),
            path: "work.watermark"
        )
        let cursor = try safeInteger(
            try required(raw, "cursor", path: "work"),
            path: "work.cursor"
        )
        guard cursor <= watermark else {
            throw DecodeError("work.cursor cannot exceed work.watermark.")
        }
        let hasMore = try strictBoolean(
            try required(raw, "has_more", path: "work"),
            path: "work.has_more"
        )
        let nextPageToken = try nullableString(
            try required(raw, "next_page_token", path: "work"),
            path: "work.next_page_token",
            max: 4_096,
            nonempty: true
        )
        let jobs = try array(
            try required(raw, "jobs", path: "work"),
            path: "work.jobs"
        ).enumerated().map { index, item in
            try parseJob(item, path: "work.jobs[\(index)]")
        }
        let attention = try array(
            try required(raw, "attention", path: "work"),
            path: "work.attention"
        ).enumerated().map { index, item in
            try parseAttention(item, path: "work.attention[\(index)]")
        }
        let events = try array(
            try required(raw, "events", path: "work"),
            path: "work.events"
        ).enumerated().map { index, item in
            try parseEvent(item, path: "work.events[\(index)]")
        }

        if mode == "bootstrap" {
            guard events.isEmpty else {
                throw DecodeError("bootstrap pages cannot contain events.")
            }
            guard jobs.count + attention.count <= FabricWorkLimits.syncPageItems else {
                throw DecodeError("bootstrap pages cannot exceed \(FabricWorkLimits.syncPageItems) subjects.")
            }
            guard cursor == watermark else {
                throw DecodeError("bootstrap page cursor must equal its fixed watermark.")
            }
            guard hasMore == (nextPageToken != nil) else {
                throw DecodeError("bootstrap has_more must match next_page_token presence.")
            }
        } else if mode == "delta" {
            guard jobs.isEmpty && attention.isEmpty else {
                throw DecodeError("delta pages carry subjects only inside events.")
            }
            guard events.count <= FabricWorkLimits.syncPageItems else {
                throw DecodeError("delta pages cannot exceed \(FabricWorkLimits.syncPageItems) events.")
            }
            guard nextPageToken == nil else {
                throw DecodeError("delta next_page_token must be null.")
            }
            guard !hasMore || !events.isEmpty else {
                throw DecodeError("a truncated delta page must advance with at least one event.")
            }
            guard hasMore || cursor == watermark else {
                throw DecodeError("a complete delta page cursor must equal its watermark.")
            }
            var priorEventID = 0
            for event in events {
                guard event.eventID > priorEventID else {
                    throw DecodeError("delta event_id values must be strictly increasing.")
                }
                guard event.eventID <= cursor else {
                    throw DecodeError("delta events cannot exceed the returned cursor.")
                }
                priorEventID = event.eventID
            }
            if let finalEvent = events.last, finalEvent.eventID != cursor {
                throw DecodeError("a delta cursor must equal its final event_id.")
            }
        }

        guard Set(jobs.map(\.jobID)).count == jobs.count else {
            throw DecodeError("work.jobs contains a duplicate job_id.")
        }
        guard Set(attention.map(\.attentionID)).count == attention.count else {
            throw DecodeError("work.attention contains a duplicate attention_id.")
        }

        return FabricWorkSyncPage(
            contract: contract,
            ledgerID: try workIdentifier(
                try required(raw, "ledger_id", path: "work"),
                kind: .ledger,
                path: "work.ledger_id"
            ),
            workProfileID: try workIdentifier(
                try required(raw, "work_profile_id", path: "work"),
                kind: .profile,
                path: "work.work_profile_id"
            ),
            mode: mode,
            watermark: watermark,
            cursor: cursor,
            hasMore: hasMore,
            nextPageToken: nextPageToken,
            jobs: jobs,
            attention: attention,
            events: events,
            encodedBytes: encodedBytes,
            actionable: unknown.isEmpty,
            unknownEnums: unknown
        )
    }

    private static func parseContract(_ raw: [String: Any]) throws -> ParsedContract {
        let contract = try object(
            try required(raw, "contract", path: "work"),
            path: "work.contract"
        )
        guard try required(contract, "name", path: "work.contract") as? String == "fabric.work" else {
            throw DecodeError("work.contract.name must be fabric.work.")
        }
        let version = try safeInteger(
            try required(contract, "version", path: "work.contract"),
            path: "work.contract.version",
            minimum: 1
        )
        let minimum = try safeInteger(
            try required(contract, "min_compatible", path: "work.contract"),
            path: "work.contract.min_compatible",
            minimum: 1
        )
        guard minimum <= version else {
            throw DecodeError("work.contract.min_compatible cannot exceed contract.version.")
        }
        if minimum > fabricWorkClientContractVersion {
            return .incompatible(minimum)
        }
        return .verified(FabricWorkContractDescriptor(
            name: "fabric.work",
            version: version,
            minimumCompatibleVersion: minimum
        ))
    }

    private static func parseRun(_ value: Any, path: String) throws -> FabricWorkRunSummary {
        let raw = try object(value, path: path)
        var unknown: [FabricWorkUnknownEnum] = []
        let result = FabricWorkRunSummary(
            runID: try workIdentifier(
                try required(raw, "run_id", path: path),
                kind: .run,
                path: "\(path).run_id"
            ),
            attempt: try safeInteger(
                try required(raw, "attempt", path: path),
                path: "\(path).attempt",
                minimum: 1
            ),
            version: try safeInteger(
                try required(raw, "version", path: path),
                path: "\(path).version",
                minimum: 1
            ),
            status: try enumValue(
                try required(raw, "status", path: path),
                known: knownJobStatuses,
                path: "\(path).status",
                unknown: &unknown
            ),
            runtimeKind: try enumValue(
                try required(raw, "runtime_kind", path: path),
                known: knownRuntimeKinds,
                path: "\(path).runtime_kind",
                unknown: &unknown
            ),
            ownerState: try enumValue(
                try required(raw, "owner_state", path: path),
                known: knownOwnerStates,
                path: "\(path).owner_state",
                unknown: &unknown
            ),
            restartBehavior: try enumValue(
                try required(raw, "restart_behavior", path: path),
                known: knownRestartBehaviors,
                path: "\(path).restart_behavior",
                unknown: &unknown
            ),
            claimedAt: try nullableTimestamp(
                try required(raw, "claimed_at", path: path),
                path: "\(path).claimed_at"
            ),
            startedAt: try nullableTimestamp(
                try required(raw, "started_at", path: path),
                path: "\(path).started_at"
            ),
            updatedAt: try safeInteger(
                try required(raw, "updated_at", path: path),
                path: "\(path).updated_at"
            ),
            finishedAt: try nullableTimestamp(
                try required(raw, "finished_at", path: path),
                path: "\(path).finished_at"
            ),
            actionable: unknown.isEmpty,
            unknownEnums: unknown
        )
        return result
    }

    private static func parseJob(_ value: Any, path: String) throws -> FabricWorkJobSummary {
        let raw = try object(value, path: path)
        try enforceByteLimit(raw, maximum: FabricWorkLimits.subjectBytes, path: path)
        var unknown: [FabricWorkUnknownEnum] = []
        let currentRunRaw = try required(raw, "current_run", path: path)
        let resultPreview = try jsonValue(
            try required(raw, "result_preview", path: path),
            path: "\(path).result_preview"
        )
        let error = try jsonValue(
            try required(raw, "error", path: path),
            path: "\(path).error"
        )
        try enforceByteLimit(
            resultPreview.foundationValue,
            maximum: FabricWorkLimits.resultPreviewBytes,
            path: "\(path).result_preview"
        )
        try enforceByteLimit(
            error.foundationValue,
            maximum: FabricWorkLimits.errorPreviewBytes,
            path: "\(path).error"
        )
        let omittedRaw = try required(raw, "result_omitted_reason", path: path)
        let omittedReason: String?
        if isNull(omittedRaw) {
            omittedReason = nil
        } else {
            omittedReason = try enumValue(
                omittedRaw,
                known: knownResultOmittedReasons,
                path: "\(path).result_omitted_reason",
                unknown: &unknown
            )
        }
        guard omittedReason == nil || resultPreview == .null else {
            throw DecodeError("\(path).result_preview must be null when a result is omitted.")
        }
        let runtime = try jsonObject(
            try required(raw, "runtime", path: path),
            path: "\(path).runtime"
        )
        try enforceByteLimit(
            runtime.foundationValue,
            maximum: FabricWorkLimits.subjectBytes,
            path: "\(path).runtime"
        )
        let currentRun: FabricWorkRunSummary?
        if isNull(currentRunRaw) {
            currentRun = nil
        } else {
            currentRun = try parseRun(currentRunRaw, path: "\(path).current_run")
            if let currentRun {
                unknown.append(contentsOf: currentRun.unknownEnums)
            }
        }

        let result = FabricWorkJobSummary(
            jobID: try workIdentifier(
                try required(raw, "job_id", path: path),
                kind: .job,
                path: "\(path).job_id"
            ),
            version: try safeInteger(
                try required(raw, "version", path: path),
                path: "\(path).version",
                minimum: 1
            ),
            kind: try enumValue(
                try required(raw, "kind", path: path),
                known: knownJobKinds,
                path: "\(path).kind",
                unknown: &unknown
            ),
            status: try enumValue(
                try required(raw, "status", path: path),
                known: knownJobStatuses,
                path: "\(path).status",
                unknown: &unknown
            ),
            title: try string(
                try required(raw, "title", path: path),
                path: "\(path).title",
                max: 200
            ),
            summary: try nullableString(
                try required(raw, "summary", path: path),
                path: "\(path).summary"
            ),
            source: try string(
                try required(raw, "source", path: path),
                path: "\(path).source",
                max: 128
            ),
            sourceSessionKey: try nullableString(
                try required(raw, "source_session_key", path: path),
                path: "\(path).source_session_key",
                max: 512
            ),
            runtimeSessionID: try nullableString(
                try required(raw, "runtime_session_id", path: path),
                path: "\(path).runtime_session_id",
                max: 512
            ),
            attemptCount: try safeInteger(
                try required(raw, "attempt_count", path: path),
                path: "\(path).attempt_count"
            ),
            openAttentionCount: try safeInteger(
                try required(raw, "open_attention_count", path: path),
                path: "\(path).open_attention_count"
            ),
            createdAt: try safeInteger(
                try required(raw, "created_at", path: path),
                path: "\(path).created_at"
            ),
            startedAt: try nullableTimestamp(
                try required(raw, "started_at", path: path),
                path: "\(path).started_at"
            ),
            updatedAt: try safeInteger(
                try required(raw, "updated_at", path: path),
                path: "\(path).updated_at"
            ),
            finishedAt: try nullableTimestamp(
                try required(raw, "finished_at", path: path),
                path: "\(path).finished_at"
            ),
            cancelRequestedAt: try nullableTimestamp(
                try required(raw, "cancel_requested_at", path: path),
                path: "\(path).cancel_requested_at"
            ),
            runtime: runtime,
            currentRun: currentRun,
            resultPreview: resultPreview,
            resultReference: try nullableString(
                try required(raw, "result_ref", path: path),
                path: "\(path).result_ref",
                max: 2_048
            ),
            resultOmittedReason: omittedReason,
            error: error,
            actionable: unknown.isEmpty,
            unknownEnums: unknown
        )
        if let currentRun, currentRun.attempt > result.attemptCount {
            throw DecodeError("\(path).current_run.attempt cannot exceed attempt_count.")
        }
        return result
    }

    private static func parseAttention(_ value: Any, path: String) throws -> FabricWorkAttention {
        let raw = try object(value, path: path)
        try enforceByteLimit(raw, maximum: FabricWorkLimits.subjectBytes, path: path)
        var unknown: [FabricWorkUnknownEnum] = []
        let kind = try enumValue(
            try required(raw, "kind", path: path),
            known: knownAttentionKinds,
            path: "\(path).kind",
            unknown: &unknown
        )
        let state = try enumValue(
            try required(raw, "state", path: path),
            known: knownAttentionStates,
            path: "\(path).state",
            unknown: &unknown
        )
        let actions = try array(
            try required(raw, "allowed_actions", path: path),
            path: "\(path).allowed_actions"
        ).enumerated().map { index, item in
            try enumValue(
                item,
                known: knownAttentionActions,
                path: "\(path).allowed_actions[\(index)]",
                unknown: &unknown
            )
        }
        guard Set(actions).count == actions.count else {
            throw DecodeError("\(path).allowed_actions must not contain duplicates.")
        }
        if unknown.isEmpty {
            let validActions = validActions(for: kind)
            if !validActions.isEmpty && actions.contains(where: { !validActions.contains($0) }) {
                throw DecodeError("\(path).allowed_actions contains an action invalid for \(kind).")
            }
            if state == "pending" && !validActions.isEmpty && actions.isEmpty {
                throw DecodeError("\(path).allowed_actions cannot be empty while Attention is pending.")
            }
            if state != "pending" && !actions.isEmpty {
                throw DecodeError("\(path).allowed_actions must be empty when Attention is not pending.")
            }
        }
        let publicPayload = try jsonObject(
            try required(raw, "public_payload", path: path),
            path: "\(path).public_payload"
        )
        try enforceByteLimit(
            publicPayload.foundationValue,
            maximum: FabricWorkLimits.subjectBytes,
            path: "\(path).public_payload"
        )
        return FabricWorkAttention(
            attentionID: try workIdentifier(
                try required(raw, "attention_id", path: path),
                kind: .attention,
                path: "\(path).attention_id"
            ),
            version: try safeInteger(
                try required(raw, "version", path: path),
                path: "\(path).version",
                minimum: 1
            ),
            jobID: try nullableWorkIdentifier(
                try required(raw, "job_id", path: path),
                kind: .job,
                path: "\(path).job_id"
            ),
            runID: try nullableWorkIdentifier(
                try required(raw, "run_id", path: path),
                kind: .run,
                path: "\(path).run_id"
            ),
            sourceSessionKey: try nullableString(
                try required(raw, "source_session_key", path: path),
                path: "\(path).source_session_key",
                max: 512
            ),
            runtimeSessionID: try nullableString(
                try required(raw, "runtime_session_id", path: path),
                path: "\(path).runtime_session_id",
                max: 512
            ),
            requestID: try string(
                try required(raw, "request_id", path: path),
                path: "\(path).request_id",
                max: 128
            ),
            kind: kind,
            state: state,
            blocking: try strictBoolean(
                try required(raw, "blocking", path: path),
                path: "\(path).blocking"
            ),
            sensitive: try strictBoolean(
                try required(raw, "sensitive", path: path),
                path: "\(path).sensitive"
            ),
            title: try string(
                try required(raw, "title", path: path),
                path: "\(path).title",
                max: 200
            ),
            publicPayload: publicPayload,
            allowedActions: actions,
            createdAt: try safeInteger(
                try required(raw, "created_at", path: path),
                path: "\(path).created_at"
            ),
            updatedAt: try safeInteger(
                try required(raw, "updated_at", path: path),
                path: "\(path).updated_at"
            ),
            expiresAt: try nullableTimestamp(
                try required(raw, "expires_at", path: path),
                path: "\(path).expires_at"
            ),
            resolvedAt: try nullableTimestamp(
                try required(raw, "resolved_at", path: path),
                path: "\(path).resolved_at"
            ),
            terminalReason: try nullableString(
                try required(raw, "terminal_reason", path: path),
                path: "\(path).terminal_reason",
                max: 256
            ),
            actionable: unknown.isEmpty && state == "pending",
            unknownEnums: unknown
        )
    }

    private static func parseEvent(_ value: Any, path: String) throws -> FabricWorkEvent {
        let raw = try object(value, path: path)
        try enforceByteLimit(raw, maximum: FabricWorkLimits.subjectBytes, path: path)
        var unknown: [FabricWorkUnknownEnum] = []
        let subjectType = try enumValue(
            try required(raw, "subject_type", path: path),
            known: knownSubjectTypes,
            path: "\(path).subject_type",
            unknown: &unknown
        )
        let subjectID = try string(
            try required(raw, "subject_id", path: path),
            path: "\(path).subject_id",
            max: 128
        )
        if subjectType == "job" {
            _ = try workIdentifier(subjectID, kind: .job, path: "\(path).subject_id")
        } else if subjectType == "attention" {
            _ = try workIdentifier(subjectID, kind: .attention, path: "\(path).subject_id")
        }
        let subjectVersion = try safeInteger(
            try required(raw, "subject_version", path: path),
            path: "\(path).subject_version",
            minimum: 1
        )
        let tombstone = try strictBoolean(
            try required(raw, "tombstone", path: path),
            path: "\(path).tombstone"
        )
        let subjectRaw = try required(raw, "subject", path: path)
        let subject: FabricWorkEventSubject?
        if tombstone {
            guard isNull(subjectRaw) else {
                throw DecodeError("\(path).subject must be null for a tombstone.")
            }
            subject = nil
        } else {
            guard !isNull(subjectRaw) else {
                throw DecodeError("\(path).subject is required for a live event.")
            }
            if subjectType == "job" {
                subject = .job(try parseJob(subjectRaw, path: "\(path).subject"))
            } else if subjectType == "attention" {
                subject = .attention(try parseAttention(subjectRaw, path: "\(path).subject"))
            } else {
                subject = .unknown(FabricWorkUnknownSubject(
                    raw: try jsonObject(subjectRaw, path: "\(path).subject"),
                    unknownEnums: [FabricWorkUnknownEnum(
                        field: "\(path).subject_type",
                        raw: subjectType
                    )]
                ))
            }
            guard let subject else {
                throw DecodeError("\(path).subject is required for a live event.")
            }
            if let identifier = subject.identifier, identifier != subjectID {
                throw DecodeError("\(path).subject must match subject_id and subject_version.")
            }
            if let version = subject.version, version != subjectVersion {
                throw DecodeError("\(path).subject must match subject_id and subject_version.")
            }
            unknown.append(contentsOf: subject.unknownEnums)
        }
        return FabricWorkEvent(
            eventID: try safeInteger(
                try required(raw, "event_id", path: path),
                path: "\(path).event_id",
                minimum: 1
            ),
            eventType: try string(
                try required(raw, "event_type", path: path),
                path: "\(path).event_type",
                max: 128
            ),
            subjectType: subjectType,
            subjectID: subjectID,
            jobID: try nullableWorkIdentifier(
                try required(raw, "job_id", path: path),
                kind: .job,
                path: "\(path).job_id"
            ),
            runID: try nullableWorkIdentifier(
                try required(raw, "run_id", path: path),
                kind: .run,
                path: "\(path).run_id"
            ),
            subjectVersion: subjectVersion,
            subject: subject,
            tombstone: tombstone,
            createdAt: try safeInteger(
                try required(raw, "created_at", path: path),
                path: "\(path).created_at"
            ),
            actionable: unknown.isEmpty && (tombstone || (subject?.actionable ?? false)),
            unknownEnums: unknown
        )
    }

    private static func validActions(for kind: String) -> Set<String> {
        switch kind {
        case "approval": return ["once", "session", "always", "deny"]
        case "clarify", "sudo", "secret": return ["submit", "cancel"]
        default: return []
        }
    }

    private static func object(_ value: Any, path: String) throws -> [String: Any] {
        guard let object = value as? [String: Any] else {
            throw DecodeError("\(path) must be an object.")
        }
        return object
    }

    private static func required(_ object: [String: Any], _ key: String, path: String) throws -> Any {
        guard object.keys.contains(key) else {
            throw DecodeError("\(path).\(key) is required, including when its value is null.")
        }
        return object[key] as Any
    }

    private static func isNull(_ value: Any) -> Bool {
        value is NSNull
    }

    private static func string(
        _ value: Any,
        path: String,
        max: Int? = nil,
        nonempty: Bool = true
    ) throws -> String {
        guard let string = value as? String else {
            throw DecodeError("\(path) must be a string.")
        }
        if nonempty && string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw DecodeError("\(path) must be a non-empty string.")
        }
        if let max, string.unicodeScalars.count > max {
            throw DecodeError("\(path) must contain at most \(max) characters.")
        }
        return string
    }

    private static func nullableString(
        _ value: Any,
        path: String,
        max: Int? = nil,
        nonempty: Bool = false
    ) throws -> String? {
        if isNull(value) { return nil }
        return try string(value, path: path, max: max, nonempty: nonempty)
    }

    private static func optionalString(
        _ object: [String: Any],
        key: String,
        path: String,
        max: Int
    ) throws -> String? {
        guard let value = object[key], !isNull(value) else { return nil }
        return try string(value, path: "\(path).\(key)", max: max)
    }

    private static func strictBoolean(_ value: Any, path: String) throws -> Bool {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) == CFBooleanGetTypeID()
        else {
            throw DecodeError("\(path) must be a boolean.")
        }
        return number.boolValue
    }

    private static func safeInteger(
        _ value: Any,
        path: String,
        minimum: Int = 0
    ) throws -> Int {
        let parsed = try signedSafeInteger(value, path: path)
        guard parsed >= minimum else {
            throw DecodeError("\(path) must be a safe integer greater than or equal to \(minimum).")
        }
        return parsed
    }

    private static func signedSafeInteger(_ value: Any, path: String) throws -> Int {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID()
        else {
            throw DecodeError("\(path) must be a safe integer.")
        }
        let decimal = number.doubleValue
        let maximumSafeInteger = Double(FabricWorkLimits.maximumSafeInteger)
        guard decimal.isFinite,
              decimal.rounded(.towardZero) == decimal,
              decimal >= -maximumSafeInteger,
              decimal <= maximumSafeInteger,
              decimal >= Double(Int.min),
              decimal <= Double(Int.max)
        else {
            throw DecodeError("\(path) must be a safe integer.")
        }
        return Int(decimal)
    }

    private static func optionalInteger(
        _ object: [String: Any],
        key: String,
        path: String
    ) throws -> Int? {
        guard let value = object[key], !isNull(value) else { return nil }
        return try safeInteger(value, path: "\(path).\(key)")
    }

    private static func nullableTimestamp(_ value: Any, path: String) throws -> Int? {
        if isNull(value) { return nil }
        return try safeInteger(value, path: path)
    }

    private static func array(_ value: Any, path: String) throws -> [Any] {
        guard let array = value as? [Any] else {
            throw DecodeError("\(path) must be an array.")
        }
        return array
    }

    private static func workIdentifier(_ value: Any, kind: IdentifierKind, path: String) throws -> String {
        let identifier = try string(value, path: path)
        let suffix = String(identifier.dropFirst(kind.rawValue.count))
        let isLowerHex = suffix.unicodeScalars.allSatisfy { scalar in
            (scalar.value >= 48 && scalar.value <= 57)
                || (scalar.value >= 97 && scalar.value <= 102)
        }
        guard identifier.hasPrefix(kind.rawValue),
              suffix.unicodeScalars.count == 32,
              isLowerHex
        else {
            throw DecodeError("\(path) must be a 128-bit \(kind) identifier.")
        }
        return identifier
    }

    private static func nullableWorkIdentifier(
        _ value: Any,
        kind: IdentifierKind,
        path: String
    ) throws -> String? {
        if isNull(value) { return nil }
        return try workIdentifier(value, kind: kind, path: path)
    }

    private static func enumValue(
        _ value: Any,
        known: Set<String>,
        path: String,
        unknown: inout [FabricWorkUnknownEnum]
    ) throws -> String {
        let parsed = try string(value, path: path, max: 128)
        if !known.contains(parsed) {
            unknown.append(FabricWorkUnknownEnum(field: path, raw: parsed))
        }
        return parsed
    }

    private static func jsonValue(_ value: Any, path: String) throws -> FabricWorkJSONValue {
        if isNull(value) { return .null }
        if let string = value as? String { return .string(string) }
        if let number = value as? NSNumber {
            if CFGetTypeID(number) == CFBooleanGetTypeID() {
                return .bool(number.boolValue)
            }
            guard number.doubleValue.isFinite else {
                throw DecodeError("\(path) contains a non-finite number.")
            }
            return .number(number.doubleValue)
        }
        if let values = value as? [Any] {
            return .array(try values.enumerated().map { index, item in
                try jsonValue(item, path: "\(path)[\(index)]")
            })
        }
        if let object = value as? [String: Any] {
            var result: FabricWorkJSONObject = [:]
            for (key, child) in object {
                result[key] = try jsonValue(child, path: "\(path).\(key)")
            }
            return .object(result)
        }
        throw DecodeError("\(path) must contain only JSON values.")
    }

    private static func optionalDetailJSON(
        _ raw: [String: Any],
        key: String,
        path: String
    ) throws -> FabricWorkJSONValue? {
        guard let value = raw[key], !isNull(value) else { return nil }
        let parsed = try jsonValue(value, path: "\(path).\(key)")
        try enforceByteLimit(
            parsed.foundationValue,
            maximum: FabricWorkLimits.jobDetailBodyBytes,
            path: "\(path).\(key)"
        )
        return parsed
    }

    private static func jsonObject(_ value: Any, path: String) throws -> FabricWorkJSONObject {
        guard case .object(let object) = try jsonValue(value, path: path) else {
            throw DecodeError("\(path) must be an object.")
        }
        return object
    }

    private static func jsonByteLength(_ value: Any) throws -> Int {
        do {
            let data = try JSONSerialization.data(
                withJSONObject: value,
                options: [.fragmentsAllowed, .sortedKeys]
            )
            return data.count
        } catch {
            throw DecodeError("Work payload must be JSON serializable.")
        }
    }

    private static func enforceByteLimit(_ value: Any, maximum: Int, path: String) throws {
        if try jsonByteLength(value) > maximum {
            throw DecodeError("\(path) exceeds its \(maximum)-byte wire limit.")
        }
    }
}

private extension Dictionary where Key == String, Value == FabricWorkJSONValue {
    var foundationValue: Any {
        mapValues(\.foundationValue)
    }
}
