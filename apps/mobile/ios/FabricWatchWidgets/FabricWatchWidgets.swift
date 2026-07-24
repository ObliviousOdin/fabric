import SwiftUI
import WidgetKit

/// Pet-forward complications and Smart Stack card (`WATCH.md` §1–2): one
/// glance contract — pose symbol + attention badge — on whichever face the
/// user already runs. Data arrives from the watch app through the shared
/// app-group snapshot; the widget never talks to the phone or the gateway.
/// v1 renders the shared pose vocabulary, not sprite bitmaps.
struct PetGlanceEntry: TimelineEntry {
    let date: Date
    let petStateRaw: String
    let petName: String?
    let connected: Bool
    let attention: Bool

    static let placeholder = PetGlanceEntry(
        date: .now,
        petStateRaw: "idle",
        petName: nil,
        connected: false,
        attention: false
    )
}

struct PetGlanceProvider: TimelineProvider {
    func placeholder(in context: Context) -> PetGlanceEntry {
        .placeholder
    }

    func getSnapshot(in context: Context, completion: @escaping (PetGlanceEntry) -> Void) {
        completion(currentEntry())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<PetGlanceEntry>) -> Void) {
        // The watch app reloads timelines whenever the relayed state changes;
        // between reloads the snapshot is the freshest truth available.
        completion(Timeline(entries: [currentEntry()], policy: .never))
    }

    private func currentEntry() -> PetGlanceEntry {
        guard let groupID = Bundle.main.object(
            forInfoDictionaryKey: WatchWidgetSnapshot.appGroupInfoKey
        ) as? String,
              let defaults = UserDefaults(suiteName: groupID),
              let decoded = WatchWidgetSnapshot.decode(
                  defaults.dictionary(forKey: WatchWidgetSnapshot.defaultsKey)
              )
        else { return .placeholder }
        return PetGlanceEntry(
            date: Date(timeIntervalSince1970: decoded.updatedAt),
            petStateRaw: decoded.petStateRaw,
            petName: decoded.petName,
            connected: decoded.connected,
            attention: decoded.attention
        )
    }
}

struct PetGlanceWidgetView: View {
    let entry: PetGlanceEntry
    @Environment(\.widgetFamily) private var family

    private var pose: WatchPetPose { WatchPetPose.pose(for: entry.petStateRaw) }

    var body: some View {
        Group {
            switch family {
            case .accessoryCircular:
                circular
            case .accessoryCorner:
                corner
            case .accessoryInline:
                inline
            default:
                rectangular
            }
        }
        .containerBackground(for: .widget) { Color.clear }
    }

    private var circular: some View {
        ZStack {
            AccessoryWidgetBackground()
            poseSymbol
                .font(.title2)
        }
        .accessibilityLabel(summary)
    }

    private var corner: some View {
        poseSymbol
            .font(.title2)
            .widgetLabel {
                Text(statusText)
            }
            .accessibilityLabel(summary)
    }

    private var inline: some View {
        // Inline renders a single line; lead with the state, not the name.
        Label(statusText, systemImage: pose.symbolName)
            .accessibilityLabel(summary)
    }

    private var rectangular: some View {
        HStack(spacing: 6) {
            poseSymbol
                .font(.title3)
            VStack(alignment: .leading, spacing: 1) {
                Text(entry.petName ?? "Fabric")
                    .font(.headline)
                    .lineLimit(1)
                Text(statusText)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(summary)
    }

    private var poseSymbol: some View {
        Image(systemName: pose.symbolName)
            .foregroundStyle(pose.isAttention ? Color.orange : Color.accentColor)
    }

    private var statusText: String {
        guard entry.connected else { return "Offline" }
        return pose.caption
    }

    private var summary: String {
        "Fabric pet: \(pose.caption). \(entry.connected ? "Connected." : "Offline.")"
    }
}

struct PetGlanceWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(
            kind: "FabricPetGlance",
            provider: PetGlanceProvider()
        ) { entry in
            PetGlanceWidgetView(entry: entry)
        }
        .configurationDisplayName("Fabric Pet")
        .description("Your Fabric pet's state at a glance.")
        .supportedFamilies([
            .accessoryCircular,
            .accessoryCorner,
            .accessoryInline,
            .accessoryRectangular,
        ])
    }
}

@main
struct FabricWatchWidgetsBundle: WidgetBundle {
    var body: some Widget {
        PetGlanceWidget()
    }
}
