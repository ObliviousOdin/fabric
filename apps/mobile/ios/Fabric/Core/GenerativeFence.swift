import Foundation

// Pure parsers for the generative chat fences an agent can emit — ```work and
// ```chart — mirroring the desktop renderers (work-embed.tsx / chart-embed.tsx)
// so both clients accept the same specs. These never throw: an invalid spec
// returns nil and the transcript falls back to the ordinary fenced-code block.

enum WorkFenceStatus: String, Equatable {
    case queued
    case running
    case done
    case failed
    case blocked
}

enum WorkFenceStepState: String, Equatable {
    case pending
    case running
    case done
    case failed
}

struct WorkFenceStep: Equatable {
    let label: String
    let state: WorkFenceStepState
}

struct WorkFenceSpec: Equatable {
    let title: String
    let status: WorkFenceStatus
    let steps: [WorkFenceStep]

    static func parse(_ code: String) -> WorkFenceSpec? {
        guard let object = jsonObject(code) else { return nil }
        guard let title = trimmedString(object["title"]), !title.isEmpty else { return nil }
        let status = WorkFenceStatus(rawValue: (object["status"] as? String) ?? "") ?? .queued

        var steps: [WorkFenceStep] = []
        if let rawSteps = object["steps"] as? [Any] {
            for entry in rawSteps.prefix(24) {
                guard let step = entry as? [String: Any],
                      let label = trimmedString(step["label"]), !label.isEmpty else { continue }
                let state = WorkFenceStepState(rawValue: (step["state"] as? String) ?? "") ?? .pending
                steps.append(WorkFenceStep(label: label, state: state))
            }
        }
        return WorkFenceSpec(title: title, status: status, steps: steps)
    }
}

enum ChartFenceKind: String, Equatable {
    case bar
    case line
}

struct ChartFencePoint: Equatable {
    let label: String
    let value: Double
}

struct ChartFenceSpec: Equatable {
    let type: ChartFenceKind
    let title: String?
    let data: [ChartFencePoint]

    static func parse(_ code: String) -> ChartFenceSpec? {
        guard let object = jsonObject(code),
              let rawData = object["data"] as? [Any] else { return nil }
        let type = ChartFenceKind(rawValue: (object["type"] as? String) ?? "") ?? .bar
        let title = trimmedString(object["title"]).flatMap { $0.isEmpty ? nil : $0 }

        var points: [ChartFencePoint] = []
        for entry in rawData.prefix(16) {
            guard let point = entry as? [String: Any] else { continue }
            let value: Double
            if let number = point["value"] as? NSNumber {
                value = number.doubleValue
            } else if let string = point["value"] as? String, let parsed = Double(string) {
                value = parsed
            } else {
                continue
            }
            guard value.isFinite else { continue }
            let label = (point["label"] as? String) ?? ""
            points.append(ChartFencePoint(label: label, value: value))
        }
        guard !points.isEmpty else { return nil }
        return ChartFenceSpec(type: type, title: title, data: points)
    }
}

private func jsonObject(_ code: String) -> [String: Any]? {
    let trimmed = code.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty, let data = trimmed.data(using: .utf8) else { return nil }
    return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
}

private func trimmedString(_ value: Any?) -> String? {
    guard let string = value as? String else { return nil }
    return string.trimmingCharacters(in: .whitespacesAndNewlines)
}
