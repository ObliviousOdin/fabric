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

/// Capability negotiation is a real third state, not evidence that capture is
/// unsupported. Reconnects pass through `.negotiating`, so keeping it explicit
/// prevents a temporary socket transition from erasing the last verified
/// frame or presenting a false unsupported state.
enum LiveViewCaptureCapability: Equatable {
    case negotiating
    case supported
    case unsupported

    init(negotiation: GatewayCapabilityNegotiation?) {
        guard let negotiation else {
            self = .negotiating
            return
        }

        switch negotiation {
        case .negotiating:
            self = .negotiating
        case .verified(let capabilities):
            self = capabilities.methods.contains("computer.screenshot")
                ? .supported
                : .unsupported
        case .legacy:
            self = legacyMobileMethods.contains("computer.screenshot")
                ? .supported
                : .unsupported
        case .incompatible, .invalid:
            self = .unsupported
        }
    }

    var isSupported: Bool { self == .supported }

    var verifiedSupport: Bool? {
        switch self {
        case .negotiating: nil
        case .supported: true
        case .unsupported: false
        }
    }
}

enum LiveViewStatusTone: Equatable {
    case danger
    case muted
    case warning
    case info
    case live
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
    private(set) var isCaptureInFlight = false
    private(set) var isPaused = false
    private(set) var captureCapability: LiveViewCaptureCapability
    private(set) var lastVerifiedSupportsCapture: Bool?
    private(set) var isConnectionReady: Bool

    @ObservationIgnored private let interval: Duration
    @ObservationIgnored private let capture: () async throws -> ScreenCapture
    @ObservationIgnored private let wait: (Duration) async throws -> Void

    private var isVisible = false
    private var isSceneActive = false
    @ObservationIgnored private var pollTask: Task<Void, Never>?
    @ObservationIgnored private var activePollToken: UUID?
    @ObservationIgnored private var restartAfterCurrent = false

    init(
        captureCapability: LiveViewCaptureCapability,
        connectionReady: Bool = true,
        interval: Duration = .milliseconds(1500),
        capture: @escaping () async throws -> ScreenCapture,
        wait: @escaping (Duration) async throws -> Void = { duration in
            try await Task.sleep(for: duration)
        }
    ) {
        self.captureCapability = captureCapability
        lastVerifiedSupportsCapture = captureCapability.verifiedSupport
        isConnectionReady = connectionReady
        self.interval = interval
        self.capture = capture
        self.wait = wait
        isLoading = captureCapability.isSupported && connectionReady
    }

    convenience init(
        supportsCapture: Bool,
        connectionReady: Bool = true,
        interval: Duration = .milliseconds(1500),
        capture: @escaping () async throws -> ScreenCapture,
        wait: @escaping (Duration) async throws -> Void = { duration in
            try await Task.sleep(for: duration)
        }
    ) {
        self.init(
            captureCapability: supportsCapture ? .supported : .unsupported,
            connectionReady: connectionReady,
            interval: interval,
            capture: capture,
            wait: wait
        )
    }

    var isUnsupported: Bool { captureCapability == .unsupported }
    var isCaptureCapabilityNegotiating: Bool { captureCapability == .negotiating }
    var isPolling: Bool { pollTask != nil }
    var shouldObscureContent: Bool { !isVisible || !isSceneActive }
    var statusTone: LiveViewStatusTone {
        if isUnsupported || retryRequired { return .danger }
        if isPaused { return .muted }
        if isFrameStale { return .warning }
        if !isConnectionReady
            || isCaptureCapabilityNegotiating
            || isLoading
            || isCaptureInFlight {
            return .info
        }
        return .live
    }
    var statusText: String {
        if isUnsupported { return "Unavailable" }
        if isPaused {
            return isFrameStale ? "Paused · stale frame" : "Paused"
        }
        if retryRequired {
            return frame == nil ? "Unavailable" : "Stale · retry needed"
        }
        if !isConnectionReady {
            return frame == nil ? "Waiting for connection" : "Stale · reconnecting"
        }
        if isCaptureCapabilityNegotiating {
            return frame == nil ? "Checking availability" : "Stale · checking availability"
        }
        if isFrameStale {
            return errorText == nil ? "Stale · refreshing" : "Stale · retrying"
        }
        if isCaptureInFlight {
            return frame == nil ? "Connecting" : "Refreshing · last frame"
        }
        if isLoading { return "Connecting" }
        return "Live"
    }
    var frameAccessibilityLabel: String {
        isFrameStale || isCaptureInFlight
            ? "Last available screen frame"
            : "Live screen frame"
    }
    var staleNoticeText: String? {
        guard frame != nil, isFrameStale, let errorText else { return nil }
        if retryRequired {
            return "Last frame shown. \(errorText) Tap Retry to reconnect."
        }
        if isPaused {
            return "Last frame shown. \(errorText) Live view is paused."
        }
        if !isConnectionReady {
            return "Last frame shown. \(errorText) Waiting for Fabric to reconnect."
        }
        return "Last frame shown. \(errorText) Retrying…"
    }

    /// Capability negotiation is connection-scoped and may change after a
    /// reconnect. A verified revocation drops retained pixels; the normal
    /// negotiating bridge preserves the last verified result and frame while
    /// holding capture closed until the next contract arrives.
    func setCaptureCapability(_ capability: LiveViewCaptureCapability) {
        guard captureCapability != capability else { return }
        captureCapability = capability

        switch capability {
        case .negotiating:
            isLoading = false
            stopPolling()
        case .supported:
            lastVerifiedSupportsCapture = true
            if frame == nil, isConnectionReady { isLoading = true }
            requestImmediateRefresh()
        case .unsupported:
            lastVerifiedSupportsCapture = false
            isLoading = false
            frame = nil
            isFrameStale = false
            errorText = nil
            retryRequired = false
            stopPolling()
        }
    }

    /// The chat session owns reconnect readiness. Holding this gate closed
    /// keeps a foreground transition from converting a temporary socket gap
    /// into a hard, user-driven Retry state.
    func setConnectionReady(_ ready: Bool) {
        guard isConnectionReady != ready else { return }
        isConnectionReady = ready
        if ready {
            if frame == nil { isLoading = true }
            requestImmediateRefresh()
        } else {
            isLoading = false
            // A raw URLSession/POSIX send failure can arrive before the app's
            // authoritative connection transition. Do not let that transient
            // error latch a manual Retry across the next successful reconnect.
            retryRequired = false
            stopPolling()
        }
    }

    func appear(sceneIsActive: Bool) {
        isVisible = true
        isSceneActive = sceneIsActive
        guard captureCapability.isSupported else {
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
        guard captureCapability.isSupported else { return }
        retryRequired = false
        errorText = nil
        isPaused = false
        if frame == nil { isLoading = true }
        requestImmediateRefresh()
    }

    private var canPoll: Bool {
        captureCapability.isSupported
            && isConnectionReady
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
        isCaptureInFlight = true
        defer { isCaptureInFlight = false }
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
        // RPC descriptions and transport diagnostics are server-controlled
        // and may contain response bodies, paths, or credentials. Keep those
        // outside observable UI state and render only fixed recovery copy.
        errorText = Self.userVisibleFailure(for: error)

        guard frame != nil else {
            if Self.isConnectionFailure(error) {
                // The app-level reconnect is already in progress. Keep this
                // bounded sequential loop eligible so it recovers without a
                // misleading hard Retry screen when the socket returns.
                isLoading = true
                retryRequired = false
                isFrameStale = false
                return true
            }

            // With no trustworthy image to show, continuing would be an
            // indefinite spinner. Stop and give the user an explicit retry.
            isLoading = false
            retryRequired = true
            isFrameStale = false
            return false
        }

        isLoading = false
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

    private static func userVisibleFailure(for error: Error) -> String {
        if let frameError = error as? LiveViewFrameError {
            return frameError.localizedDescription
        }
        if isConnectionFailure(error) {
            return "Live view is waiting for the Fabric connection."
        }
        if let gatewayError = error as? GatewayClientError {
            switch gatewayError {
            case .requestTimedOut:
                return "Live view refresh timed out."
            case .rpc:
                return "Live view stopped on the Fabric computer."
            case .notConnected, .connectFailed, .socketClosed:
                return "Live view is waiting for the Fabric connection."
            }
        }
        return "Live view couldn't refresh."
    }

    private static func isHardFailure(_ error: Error) -> Bool {
        if error is LiveViewFrameError { return true }
        guard let gatewayError = error as? GatewayClientError else { return false }
        switch gatewayError {
        case .requestTimedOut, .notConnected, .connectFailed, .socketClosed:
            return false
        case .rpc:
            return true
        }
    }

    private static func isConnectionFailure(_ error: Error) -> Bool {
        if let gatewayError = error as? GatewayClientError {
            switch gatewayError {
            case .notConnected, .connectFailed, .socketClosed:
                return true
            case .requestTimedOut, .rpc:
                return false
            }
        }
        if let urlError = error as? URLError {
            switch urlError.code {
            case .timedOut,
                 .cannotFindHost,
                 .cannotConnectToHost,
                 .networkConnectionLost,
                 .dnsLookupFailed,
                 .notConnectedToInternet,
                 .secureConnectionFailed,
                 .cannotLoadFromNetwork:
                return true
            default:
                return false
            }
        }
        return false
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
    @Bindable var model: LiveViewModel

    init(model: LiveViewModel) {
        self.model = model
    }

    var body: some View {
        NavigationStack {
            ZStack {
                FabricTheme.canvas.ignoresSafeArea()
                content
                staleNotice
                statusBar
                privacyCover
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
                    .privacySensitive()
                    .accessibilityLabel(model.frameAccessibilityLabel)
            }
        } else if model.retryRequired {
            ContentUnavailableView {
                Label("Live view unavailable", systemImage: "display.trianglebadge.exclamationmark")
            } description: {
                Text(model.errorText ?? "The screen could not be loaded.")
            } actions: {
                Button("Retry") { model.retry() }
                    .buttonStyle(.borderedProminent)
                    .frame(
                        minWidth: FabricTheme.minTarget,
                        minHeight: FabricTheme.minTarget
                    )
            }
        } else if model.isPaused {
            ContentUnavailableView {
                Label("Live view paused", systemImage: "pause.circle")
            } description: {
                Text("Resume to request a screen frame.")
            }
        } else if !model.isConnectionReady {
            ContentUnavailableView {
                Label("Waiting for Fabric", systemImage: "wifi.exclamationmark")
            } description: {
                Text("Live view will resume automatically when the gateway reconnects.")
            }
        } else if model.isCaptureCapabilityNegotiating {
            ProgressView("Checking live view availability…")
                .tint(FabricTheme.action)
        } else {
            ProgressView("Connecting to the screen…")
                .tint(FabricTheme.action)
        }
    }

    @ViewBuilder
    private var staleNotice: some View {
        if let notice = model.staleNoticeText {
            VStack {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "clock.badge.exclamationmark")
                        .foregroundStyle(FabricTheme.warning)
                        .accessibilityHidden(true)
                    Text(notice)
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

    @ViewBuilder
    private var privacyCover: some View {
        if scenePhase != .active || model.shouldObscureContent {
            ZStack {
                FabricTheme.canvas.ignoresSafeArea()
                ContentUnavailableView {
                    Label("Live view hidden", systemImage: "eye.slash")
                } description: {
                    Text("Return to Fabric to show the remote screen.")
                }
            }
            .accessibilityElement(children: .combine)
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
                Text(model.statusText)
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
                .frame(
                    minWidth: FabricTheme.minTarget,
                    minHeight: FabricTheme.minTarget
                )
        } else if !model.isUnsupported {
            Button(model.isPaused ? "Resume" : "Pause") {
                model.setPaused(!model.isPaused)
            }
            .disabled(model.retryRequired)
        }
    }

    private var statusColor: Color {
        switch model.statusTone {
        case .danger: FabricTheme.danger
        case .muted: FabricTheme.textMuted
        case .warning: FabricTheme.warning
        case .info: FabricTheme.info
        case .live: FabricTheme.threadActive
        }
    }
}
