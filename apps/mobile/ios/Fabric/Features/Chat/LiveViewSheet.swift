import Observation
import SwiftUI

/// The single decoded image retained by Live View. Replacing this value drops
/// the previous frame; captures are never logged, recorded, or persisted.
struct LiveViewFrame {
    let image: UIImage
    let width: Int
    let height: Int

    var dimensions: String { "\(width)×\(height)" }
}

private enum LiveViewFrameError: LocalizedError {
    case invalidImage

    var errorDescription: String? {
        "The gateway returned an unreadable screen image."
    }
}

/// Owns the read-only capture lifecycle independently from the sheet chrome.
/// A single task performs capture then delay in sequence, so even cancellation
/// races during sleep/wake cannot create concurrent screenshot requests.
@Observable
@MainActor
final class LiveViewModel {
    private(set) var frame: LiveViewFrame?
    private(set) var isFrameStale = false
    private(set) var errorText: String?
    private(set) var retryRequired = false
    private(set) var isLoading: Bool
    private(set) var isPaused = false

    @ObservationIgnored private let supportsCapture: Bool
    @ObservationIgnored private let interval: Duration
    @ObservationIgnored private let capture: () async throws -> ScreenCapture
    @ObservationIgnored private let wait: (Duration) async throws -> Void

    @ObservationIgnored private var isVisible = false
    @ObservationIgnored private var isSceneActive = false
    @ObservationIgnored private var pollTask: Task<Void, Never>?
    @ObservationIgnored private var activePollToken: UUID?
    @ObservationIgnored private var restartAfterCurrent = false

    init(
        supportsCapture: Bool,
        interval: Duration = .milliseconds(1500),
        capture: @escaping () async throws -> ScreenCapture,
        wait: @escaping (Duration) async throws -> Void = { duration in
            try await Task.sleep(for: duration)
        }
    ) {
        self.supportsCapture = supportsCapture
        self.interval = interval
        self.capture = capture
        self.wait = wait
        isLoading = supportsCapture
    }

    var isUnsupported: Bool { !supportsCapture }
    var isPolling: Bool { pollTask != nil }

    func appear(sceneIsActive: Bool) {
        isVisible = true
        isSceneActive = sceneIsActive
        guard supportsCapture else {
            isLoading = false
            return
        }
        requestImmediateRefresh()
    }

    func disappear() {
        isVisible = false
        isLoading = false
        stopPolling()
    }

    func setSceneActive(_ active: Bool) {
        guard isSceneActive != active else { return }
        isSceneActive = active
        if active {
            requestImmediateRefresh()
        } else {
            isLoading = false
            stopPolling()
        }
    }

    func setPaused(_ paused: Bool) {
        guard isPaused != paused else { return }
        isPaused = paused
        if paused {
            isLoading = false
            stopPolling()
        } else {
            requestImmediateRefresh()
        }
    }

    /// Clears a stopped failure and refreshes immediately. If a cancelled
    /// request has not returned yet, the refresh waits for it instead of
    /// overlapping it.
    func retry() {
        guard supportsCapture else { return }
        retryRequired = false
        errorText = nil
        isPaused = false
        if frame == nil { isLoading = true }
        requestImmediateRefresh()
    }

    private var canPoll: Bool {
        supportsCapture
            && isVisible
            && isSceneActive
            && !isPaused
            && !retryRequired
    }

    private func requestImmediateRefresh() {
        guard canPoll else { return }
        if let pollTask {
            // Cancellation wakes an interval sleep immediately. A transport
            // that ignores cancellation still owns the sole in-flight slot;
            // the replacement starts only from finishPolling(token:).
            restartAfterCurrent = true
            pollTask.cancel()
            return
        }
        startPolling()
    }

    private func stopPolling() {
        restartAfterCurrent = false
        if frame != nil { isFrameStale = true }
        pollTask?.cancel()
    }

    private func startPolling() {
        guard canPoll, pollTask == nil else { return }
        restartAfterCurrent = false
        let token = UUID()
        activePollToken = token
        pollTask = Task { [weak self] in
            guard let self else { return }
            await self.poll(token: token)
        }
    }

    private func poll(token: UUID) async {
        while canPoll, !Task.isCancelled {
            let shouldContinue = await captureOnce()
            guard shouldContinue, canPoll, !Task.isCancelled else { break }
            do {
                try await wait(interval)
            } catch {
                break
            }
        }
        finishPolling(token: token)
    }

    private func captureOnce() async -> Bool {
        if frame == nil { isLoading = true }

        do {
            let captured = try await capture()
            guard !Task.isCancelled, canPoll else { return false }
            guard let image = UIImage(data: captured.image) else {
                return handleFailure(LiveViewFrameError.invalidImage)
            }

            let pixelWidth = captured.width > 0
                ? captured.width
                : Int(image.size.width * image.scale)
            let pixelHeight = captured.height > 0
                ? captured.height
                : Int(image.size.height * image.scale)
            frame = LiveViewFrame(
                image: image,
                width: pixelWidth,
                height: pixelHeight
            )
            isFrameStale = false
            errorText = nil
            retryRequired = false
            isLoading = false
            return true
        } catch is CancellationError {
            return false
        } catch {
            guard !Task.isCancelled, canPoll else { return false }
            return handleFailure(error)
        }
    }

    private func handleFailure(_ error: Error) -> Bool {
        isLoading = false
        errorText = error.localizedDescription

        guard frame != nil else {
            // With no trustworthy image to show, continuing would be an
            // indefinite spinner. Stop and give the user an explicit retry.
            retryRequired = true
            isFrameStale = false
            return false
        }

        isFrameStale = true
        if Self.isHardFailure(error) {
            retryRequired = true
            return false
        }

        // Network churn is recoverable. Retain exactly the last decoded frame,
        // mark it stale, and let the same sequential loop try again.
        retryRequired = false
        return true
    }

    private static func isHardFailure(_ error: Error) -> Bool {
        if error is LiveViewFrameError { return true }
        guard let gatewayError = error as? GatewayClientError else { return false }
        switch gatewayError {
        case .requestTimedOut:
            return false
        case .notConnected, .connectFailed, .socketClosed, .rpc:
            return true
        }
    }

    private func finishPolling(token: UUID) {
        guard activePollToken == token else { return }
        activePollToken = nil
        pollTask = nil

        let shouldRestart = restartAfterCurrent
        restartAfterCurrent = false
        if shouldRestart, canPoll {
            startPolling()
        }
    }
}

/// Read-only live view of the gateway host's screen — a picture-in-picture
/// window onto what a `computer_use` turn is doing. Polling is sequential,
/// visible-only, and pause-aware; no input is ever sent back.
struct LiveViewSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @State private var model: LiveViewModel

    init(api: GatewayAPI, supportsMethod: @escaping (String) -> Bool) {
        _model = State(initialValue: LiveViewModel(
            supportsCapture: supportsMethod("computer.screenshot"),
            capture: { try await api.captureScreen() }
        ))
    }

    var body: some View {
        NavigationStack {
            ZStack {
                FabricTheme.canvas.ignoresSafeArea()
                content
                staleNotice
                statusBar
            }
            .navigationTitle("Live view")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Done") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    trailingAction
                }
            }
            .onAppear {
                model.appear(sceneIsActive: scenePhase == .active)
            }
            .onDisappear {
                model.disappear()
            }
            .onChange(of: scenePhase) { _, phase in
                model.setSceneActive(phase == .active)
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if model.isUnsupported {
            ContentUnavailableView {
                Label("Live view unavailable", systemImage: "display.trianglebadge.exclamationmark")
            } description: {
                Text("This gateway does not support read-only screen capture.")
            }
        } else if let frame = model.frame {
            ScrollView([.horizontal, .vertical]) {
                Image(uiImage: frame.image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(maxWidth: .infinity)
                    .accessibilityLabel(model.isFrameStale ? "Last available screen frame" : "Live screen frame")
            }
        } else if model.retryRequired {
            ContentUnavailableView {
                Label("Live view unavailable", systemImage: "display.trianglebadge.exclamationmark")
            } description: {
                Text(model.errorText ?? "The screen could not be loaded.")
            } actions: {
                Button("Retry") { model.retry() }
                    .buttonStyle(.borderedProminent)
            }
        } else if model.isPaused {
            ContentUnavailableView {
                Label("Live view paused", systemImage: "pause.circle")
            } description: {
                Text("Resume to request a screen frame.")
            }
        } else {
            ProgressView("Connecting to the screen…")
                .tint(FabricTheme.action)
        }
    }

    @ViewBuilder
    private var staleNotice: some View {
        if model.frame != nil, model.isFrameStale, let errorText = model.errorText {
            VStack {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "clock.badge.exclamationmark")
                        .foregroundStyle(FabricTheme.warning)
                        .accessibilityHidden(true)
                    Text(model.retryRequired
                        ? "Last frame shown. \(errorText) Tap Retry to reconnect."
                        : "Last frame shown. \(errorText) Retrying…")
                        .font(.subheadline)
                        .foregroundStyle(FabricTheme.text)
                    Spacer(minLength: 0)
                }
                .padding(12)
                .background(FabricTheme.surfaceRaised, in: RoundedRectangle(cornerRadius: FabricTheme.radius))
                .overlay {
                    RoundedRectangle(cornerRadius: FabricTheme.radius)
                        .stroke(FabricTheme.warning, lineWidth: 1)
                }
                .padding(.horizontal, 16)
                .padding(.top, 12)
                Spacer()
            }
        }
    }

    private var statusBar: some View {
        VStack {
            Spacer()
            HStack(spacing: 8) {
                Circle()
                    .fill(statusColor)
                    .frame(width: 8, height: 8)
                    .accessibilityHidden(true)
                Text(statusText)
                    .font(.caption.weight(.medium))
                if let dimensions = model.frame?.dimensions {
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
            .accessibilityElement(children: .combine)
        }
    }

    @ViewBuilder
    private var trailingAction: some View {
        if model.retryRequired, model.frame != nil {
            Button("Retry") { model.retry() }
        } else if !model.isUnsupported {
            Button(model.isPaused ? "Resume" : "Pause") {
                model.setPaused(!model.isPaused)
            }
            .disabled(model.retryRequired)
        }
    }

    private var statusText: String {
        if model.isUnsupported { return "Unavailable" }
        if model.isPaused {
            return model.isFrameStale ? "Paused · stale frame" : "Paused"
        }
        if model.retryRequired {
            return model.frame == nil ? "Unavailable" : "Stale · retry needed"
        }
        if model.isFrameStale {
            return model.errorText == nil ? "Stale · refreshing" : "Stale · retrying"
        }
        if model.isLoading { return "Connecting" }
        return "Live"
    }

    private var statusColor: Color {
        if model.isUnsupported || model.retryRequired { return FabricTheme.danger }
        if model.isPaused { return FabricTheme.textMuted }
        if model.isFrameStale { return FabricTheme.warning }
        if model.isLoading { return FabricTheme.info }
        return FabricTheme.threadActive
    }
}
