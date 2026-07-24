import SwiftUI

/// The one watch screen (`WATCH.md` §3 interaction budget: raise wrist → one
/// tap → speak → done). The pet is the identity; the two capture actions and
/// an honest status line are the whole surface. Everything else stays on the
/// phone.
struct WatchHomeView: View {
    @Environment(WatchAppModel.self) private var model

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                petHeader

                if model.pose.isAttention {
                    attentionRow
                }

                TextFieldLink(prompt: Text("Quick note")) {
                    Label("Quick note", systemImage: "square.and.pencil")
                        .frame(maxWidth: .infinity)
                } onSubmit: { text in
                    model.submitNote(text)
                }
                .buttonStyle(.borderedProminent)

                NavigationLink {
                    WatchVoiceNoteView()
                } label: {
                    Label("Voice note", systemImage: "mic.fill")
                        .frame(maxWidth: .infinity)
                }

                if !model.queuedNotes.isEmpty {
                    Label(
                        model.queuedNotes.count == 1
                            ? "1 note queued on watch"
                            : "\(model.queuedNotes.count) notes queued on watch",
                        systemImage: "tray.full"
                    )
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                }

                if let banner = model.banner {
                    Text(banner.text)
                        .font(.footnote)
                        .foregroundStyle(banner.tone == .failure ? .red : .secondary)
                        .multilineTextAlignment(.center)
                        .transition(.opacity)
                }
            }
            .padding(.horizontal, 4)
        }
        .navigationTitle("Fabric")
        .animation(.easeOut(duration: 0.25), value: model.banner)
    }

    private var petHeader: some View {
        VStack(spacing: 2) {
            WatchPetSpriteView(
                atlas: model.sprite,
                stateRaw: model.petStateRaw
            )
            if let name = model.context?.petName {
                Text(name)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Text(model.statusLine)
                .font(.footnote)
                .foregroundStyle(statusColor)
                .multilineTextAlignment(.center)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilitySummary)
    }

    private var attentionRow: some View {
        Label("Fabric needs you — reply on your iPhone.", systemImage: "hand.raised.fill")
            .font(.footnote)
            .foregroundStyle(.orange)
            .multilineTextAlignment(.leading)
    }

    private var statusColor: Color {
        guard let context = model.context, model.phoneReachable else { return .secondary }
        return context.isConnected ? .green : .secondary
    }

    private var accessibilitySummary: String {
        let pose = WatchPetPose.pose(for: model.petStateRaw)
        return "Fabric pet: \(pose.caption). \(model.statusLine)"
    }
}
