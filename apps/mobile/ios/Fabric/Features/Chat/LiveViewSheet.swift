import SwiftUI

/// Read-only live view of the gateway host's screen — a picture-in-picture
/// window onto what a `computer_use` turn is doing. Polls
/// `computer.screenshot` on a fixed cadence; no input is ever sent back.
/// When the host can't capture (unsupported OS, cua-driver missing), the
/// sheet says so and stops rather than spinning.
struct LiveViewSheet: View {
    let api: GatewayAPI

    @Environment(\.dismiss) private var dismiss
    @State private var frame: UIImage?
    @State private var dimensions: String = ""
    @State private var errorText: String?
    @State private var paused = false
    @State private var pollTask: Task<Void, Never>?

    private let interval: Duration = .milliseconds(1500)

    var body: some View {
        NavigationStack {
            ZStack {
                FabricTheme.canvas.ignoresSafeArea()

                if let errorText {
                    ContentUnavailableView {
                        Label("Live view unavailable", systemImage: "display.trianglebadge.exclamationmark")
                    } description: {
                        Text(errorText)
                    }
                } else if let frame {
                    ScrollView([.horizontal, .vertical]) {
                        Image(uiImage: frame)
                            .resizable()
                            .aspectRatio(contentMode: .fit)
                            .frame(maxWidth: .infinity)
                    }
                } else {
                    ProgressView("Connecting to the screen…")
                }

                VStack {
                    Spacer()
                    HStack(spacing: 8) {
                        Circle()
                            .fill(paused ? FabricTheme.textMuted : FabricTheme.threadActive)
                            .frame(width: 8, height: 8)
                        Text(paused ? "Paused" : "Live")
                            .font(.caption)
                        if !dimensions.isEmpty {
                            Text(dimensions)
                                .font(.caption.monospaced())
                                .foregroundStyle(FabricTheme.textMuted)
                        }
                        Spacer()
                        Text("Read-only")
                            .font(.caption)
                            .foregroundStyle(FabricTheme.textMuted)
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .background(.ultraThinMaterial, in: Capsule())
                    .padding(.bottom, 12)
                    .padding(.horizontal, 16)
                }
            }
            .navigationTitle("Live view")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Done") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(paused ? "Resume" : "Pause") { paused.toggle() }
                        .disabled(errorText != nil)
                }
            }
            .task { startPolling() }
            .onDisappear { pollTask?.cancel() }
        }
    }

    private func startPolling() {
        pollTask?.cancel()
        pollTask = Task {
            while !Task.isCancelled {
                if !paused {
                    do {
                        let capture = try await api.captureScreen()
                        if let image = UIImage(data: capture.image) {
                            frame = image
                            dimensions = "\(capture.width)×\(capture.height)"
                            errorText = nil
                        }
                    } catch {
                        // A one-off failure while a turn churns is normal;
                        // only surface a hard stop when we have no frame yet.
                        if frame == nil {
                            errorText = error.localizedDescription
                            return
                        }
                    }
                }
                try? await Task.sleep(for: interval)
            }
        }
    }
}
