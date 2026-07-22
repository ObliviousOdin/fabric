import AVFoundation
import SwiftUI
import UIKit

enum PairingScannerDisposition: Equatable {
    case accepted
    case retry(message: String)
}

struct PairingScannerFeedbackState: Equatable {
    private(set) var message: String?
    private(set) var scanGeneration = 0

    mutating func receive(_ disposition: PairingScannerDisposition) {
        switch disposition {
        case .accepted:
            message = nil
        case .retry(let message):
            self.message = message
        }
    }

    mutating func retry() {
        message = nil
        scanGeneration &+= 1
    }
}

struct PairingScannerDeliveryGate: Equatable {
    private(set) var generation = 0
    private(set) var hasDelivered = false

    mutating func beginDelivery() -> Bool {
        guard !hasDelivered else { return false }
        hasDelivered = true
        return true
    }

    mutating func reset(to generation: Int) {
        guard self.generation != generation else { return }
        self.generation = generation
        hasDelivered = false
    }

    mutating func deactivate() {
        hasDelivered = true
    }
}

/// Complete scanner journey: a rationale appears before iOS can show its
/// camera prompt, and every denied/restricted/unavailable state has a useful
/// escape hatch. No camera authorization is requested by constructing this
/// view; it happens only from the user's explicit Continue action.
struct PairingScannerFlow: View {
    let onScan: (String) -> PairingScannerDisposition
    let onCancel: () -> Void
    let onAdvancedSetup: () -> Void

    @State private var permission: ConnectCameraPermissionState
    @State private var requestingPermission = false
    @State private var torchAvailable = false
    @State private var torchOn = false
    @State private var feedback = PairingScannerFeedbackState()
    private let fixedPermission: ConnectCameraPermissionState?

    init(
        initialPermission: ConnectCameraPermissionState? = nil,
        onScan: @escaping (String) -> PairingScannerDisposition,
        onCancel: @escaping () -> Void,
        onAdvancedSetup: @escaping () -> Void
    ) {
        self.onScan = onScan
        self.onCancel = onCancel
        self.onAdvancedSetup = onAdvancedSetup
        fixedPermission = initialPermission
        _permission = State(
            initialValue: initialPermission
                ?? ConnectCameraPermissionState(AVCaptureDevice.authorizationStatus(for: .video))
        )
    }

    var body: some View {
        NavigationStack {
            Group {
                switch permission {
                case .notDetermined:
                    cameraPrimer
                case .authorized:
                    liveScanner
                case .denied, .restricted, .unavailable:
                    recovery
                }
            }
            .navigationTitle(permission == .authorized ? "Scan pairing code" : "Camera access")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(permission == .authorized ? Color.black : FabricTheme.canvas, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(permission == .authorized ? .dark : nil, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel", action: onCancel)
                        .frame(minHeight: FabricTheme.minTarget)
                }
                if permission == .authorized, torchAvailable {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button {
                            torchOn.toggle()
                        } label: {
                            Label(
                                torchOn ? "Turn flashlight off" : "Turn flashlight on",
                                systemImage: torchOn ? "bolt.fill" : "bolt"
                            )
                        }
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                    }
                }
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)) { _ in
            guard fixedPermission == nil, permission != .authorized else { return }
            permission = ConnectCameraPermissionState(AVCaptureDevice.authorizationStatus(for: .video))
        }
    }

    private var cameraPrimer: some View {
        ZStack {
            FabricTheme.canvas.ignoresSafeArea()
            ScrollView {
                VStack(spacing: 26) {
                    Image(systemName: "camera.viewfinder")
                        .font(.system(size: 74, weight: .light))
                        .foregroundStyle(FabricTheme.action)
                        .frame(width: 126, height: 126)
                        .background(FabricTheme.surfaceBrand, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
                        .accessibilityHidden(true)

                    VStack(spacing: 10) {
                        Text("Allow camera access")
                            .font(.largeTitle.weight(.semibold))
                            .foregroundStyle(FabricTheme.text)
                            .multilineTextAlignment(.center)
                        Text("Fabric uses the camera only to read the pairing code shown on your computer. You can cancel or use Advanced setup instead.")
                            .font(.body)
                            .foregroundStyle(FabricTheme.textMuted)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    VStack(spacing: 12) {
                        Button {
                            requestCameraAccess()
                        } label: {
                            if requestingPermission {
                                ProgressView()
                                    .tint(FabricTheme.textOnBrand)
                                    .frame(maxWidth: .infinity)
                            } else {
                                Text("Continue")
                            }
                        }
                        .buttonStyle(ConnectPrimaryButtonStyle())
                        .disabled(requestingPermission)

                        Button("Use Advanced setup", action: onAdvancedSetup)
                            .buttonStyle(ConnectSecondaryButtonStyle())
                            .disabled(requestingPermission)
                    }
                }
                .frame(maxWidth: 520)
                .padding(.horizontal, 28)
                .padding(.top, 54)
                .padding(.bottom, 30)
                .frame(maxWidth: .infinity)
            }
            .scrollBounceBehavior(.basedOnSize)
        }
    }

    private var liveScanner: some View {
        ZStack {
            QRScannerView(
                isActive: true,
                torchOn: torchOn,
                scanGeneration: feedback.scanGeneration,
                onTorchAvailability: { available in
                    torchAvailable = available
                    if !available { torchOn = false }
                },
                onUnavailable: {
                    permission = .unavailable
                    torchAvailable = false
                    torchOn = false
                },
                onScan: { raw in
                    let disposition = onScan(raw)
                    feedback.receive(disposition)
                    if case .retry(let message) = disposition {
                        UIAccessibility.post(notification: .announcement, argument: message)
                    }
                }
            )
            .ignoresSafeArea()
            .accessibilityHidden(true)

            Color.black.opacity(0.14)
                .ignoresSafeArea()
                .allowsHitTesting(false)

            VStack(spacing: 18) {
                if let message = feedback.message {
                    VStack(spacing: 10) {
                        Text(message)
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(.white)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                        Button("Scan another code") {
                            feedback.retry()
                        }
                        .font(.headline)
                        .foregroundStyle(.black)
                        .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                        .background(.white, in: RoundedRectangle(cornerRadius: FabricTheme.radius))
                    }
                    .padding(14)
                    .background(.black.opacity(0.78), in: RoundedRectangle(cornerRadius: FabricTheme.radius))
                    .padding(.horizontal, 20)
                    .accessibilityElement(children: .contain)
                } else {
                    Text("Point your camera at the code shown by `fabric mobile`.")
                        .font(.headline)
                        .foregroundStyle(.white)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                        .background(.black.opacity(0.62), in: RoundedRectangle(cornerRadius: FabricTheme.radius))
                        .accessibilityLabel("Point your camera at the pairing code shown by fabric mobile")

                    ScannerReticle()
                        .aspectRatio(1, contentMode: .fit)
                        .frame(maxWidth: 290)
                        .padding(.horizontal, 34)
                        .accessibilityHidden(true)
                }

                Spacer(minLength: 8)

                Button("Enter details manually", action: onAdvancedSetup)
                    .font(.headline)
                    .foregroundStyle(.white)
                    .frame(minHeight: FabricTheme.minTarget)
                    .padding(.horizontal, 18)
                    .background(.black.opacity(0.62), in: RoundedRectangle(cornerRadius: FabricTheme.radius))
            }
            .padding(.top, 26)
            .padding(.bottom, 26)
        }
        .background(Color.black)
    }

    private var recovery: some View {
        let copy = ConnectCameraRecoveryCopy.value(for: permission)
        return ZStack {
            FabricTheme.canvas.ignoresSafeArea()
            ScrollView {
                VStack(spacing: 24) {
                    Image(systemName: "camera.fill")
                        .font(.system(size: 66, weight: .light))
                        .foregroundStyle(FabricTheme.textMuted)
                        .frame(width: 124, height: 124)
                        .background(FabricTheme.surfaceRaised, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
                        .accessibilityHidden(true)

                    VStack(spacing: 10) {
                        Text(copy.title)
                            .font(.largeTitle.weight(.semibold))
                            .foregroundStyle(FabricTheme.text)
                            .multilineTextAlignment(.center)
                        Text(copy.message)
                            .font(.body)
                            .foregroundStyle(FabricTheme.textMuted)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    VStack(spacing: 12) {
                        if copy.showsSettingsAction {
                            Button {
                                openAppSettings()
                            } label: {
                                Label("Open Settings", systemImage: "gear")
                            }
                            .buttonStyle(ConnectPrimaryButtonStyle())
                        }

                        if copy.showsSettingsAction {
                            Button("Use Advanced setup", action: onAdvancedSetup)
                                .buttonStyle(ConnectSecondaryButtonStyle())
                        } else {
                            Button("Use Advanced setup", action: onAdvancedSetup)
                                .buttonStyle(ConnectPrimaryButtonStyle())
                        }

                    }
                }
                .frame(maxWidth: 520)
                .padding(.horizontal, 28)
                .padding(.top, 54)
                .padding(.bottom, 30)
                .frame(maxWidth: .infinity)
            }
            .scrollBounceBehavior(.basedOnSize)
        }
    }

    private func requestCameraAccess() {
        guard !requestingPermission else { return }
        requestingPermission = true
        AVCaptureDevice.requestAccess(for: .video) { granted in
            DispatchQueue.main.async {
                requestingPermission = false
                permission = granted
                    ? .authorized
                    : ConnectCameraPermissionState(
                        AVCaptureDevice.authorizationStatus(for: .video)
                    )
            }
        }
    }

    private func openAppSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }
}

private struct ScannerReticle: View {
    var body: some View {
        ScanCornerShape(cornerLength: 54, cornerRadius: 18)
            .stroke(FabricTheme.focus, style: StrokeStyle(lineWidth: 5, lineCap: .round, lineJoin: .round))
            .shadow(color: .black.opacity(0.55), radius: 2, y: 1)
            .background(Color.clear)
    }
}

private struct ScanCornerShape: Shape {
    let cornerLength: CGFloat
    let cornerRadius: CGFloat

    func path(in rect: CGRect) -> Path {
        var path = Path()
        let minX = rect.minX
        let maxX = rect.maxX
        let minY = rect.minY
        let maxY = rect.maxY

        path.move(to: CGPoint(x: minX, y: minY + cornerLength))
        path.addLine(to: CGPoint(x: minX, y: minY + cornerRadius))
        path.addQuadCurve(
            to: CGPoint(x: minX + cornerRadius, y: minY),
            control: CGPoint(x: minX, y: minY)
        )
        path.addLine(to: CGPoint(x: minX + cornerLength, y: minY))

        path.move(to: CGPoint(x: maxX - cornerLength, y: minY))
        path.addLine(to: CGPoint(x: maxX - cornerRadius, y: minY))
        path.addQuadCurve(
            to: CGPoint(x: maxX, y: minY + cornerRadius),
            control: CGPoint(x: maxX, y: minY)
        )
        path.addLine(to: CGPoint(x: maxX, y: minY + cornerLength))

        path.move(to: CGPoint(x: maxX, y: maxY - cornerLength))
        path.addLine(to: CGPoint(x: maxX, y: maxY - cornerRadius))
        path.addQuadCurve(
            to: CGPoint(x: maxX - cornerRadius, y: maxY),
            control: CGPoint(x: maxX, y: maxY)
        )
        path.addLine(to: CGPoint(x: maxX - cornerLength, y: maxY))

        path.move(to: CGPoint(x: minX + cornerLength, y: maxY))
        path.addLine(to: CGPoint(x: minX + cornerRadius, y: maxY))
        path.addQuadCurve(
            to: CGPoint(x: minX, y: maxY - cornerRadius),
            control: CGPoint(x: minX, y: maxY)
        )
        path.addLine(to: CGPoint(x: minX, y: maxY - cornerLength))
        return path
    }
}

/// Camera preview used only after authorization has been granted.
struct QRScannerView: UIViewControllerRepresentable {
    let isActive: Bool
    let torchOn: Bool
    let scanGeneration: Int
    let onTorchAvailability: (Bool) -> Void
    let onUnavailable: () -> Void
    let onScan: (String) -> Void

    func makeUIViewController(context: Context) -> QRScannerViewController {
        let controller = QRScannerViewController()
        controller.onScan = onScan
        controller.onUnavailable = onUnavailable
        controller.onTorchAvailability = onTorchAvailability
        controller.isActive = { isActive }
        controller.setScanGeneration(scanGeneration)
        return controller
    }

    func updateUIViewController(_ controller: QRScannerViewController, context: Context) {
        controller.isActive = { isActive }
        controller.setScanGeneration(scanGeneration)
        controller.setTorchEnabled(torchOn)
    }

    static func dismantleUIViewController(
        _ controller: QRScannerViewController,
        coordinator: Void
    ) {
        controller.deactivate()
    }
}

final class QRScannerViewController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var onScan: ((String) -> Void)?
    var onUnavailable: (() -> Void)?
    var onTorchAvailability: ((Bool) -> Void)?
    var isActive: (() -> Bool)?

    private let session = AVCaptureSession()
    private let sessionQueue = DispatchQueue(label: "io.github.obliviousodin.fabric.mobile.camera")
    private var previewLayer: AVCaptureVideoPreviewLayer?
    private var camera: AVCaptureDevice?
    private var configured = false
    private var deliveryGate = PairingScannerDeliveryGate()

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        configureCaptureSession()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        previewLayer?.frame = view.bounds
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        deactivate()
    }

    func setTorchEnabled(_ enabled: Bool) {
        guard let camera, camera.hasTorch, camera.isTorchAvailable else { return }
        do {
            try camera.lockForConfiguration()
            defer { camera.unlockForConfiguration() }
            if enabled {
                try camera.setTorchModeOn(level: AVCaptureDevice.maxAvailableTorchLevel)
            } else {
                camera.torchMode = .off
            }
        } catch {
            DispatchQueue.main.async { [weak self] in
                self?.onTorchAvailability?(false)
            }
        }
    }

    func setScanGeneration(_ generation: Int) {
        deliveryGate.reset(to: generation)
    }

    func deactivate() {
        deliveryGate.deactivate()
        onScan = nil
        setTorchEnabled(false)
        sessionQueue.async { [session] in
            if session.isRunning { session.stopRunning() }
        }
    }

    func metadataOutput(
        _ output: AVCaptureMetadataOutput,
        didOutput metadataObjects: [AVMetadataObject],
        from connection: AVCaptureConnection
    ) {
        guard
            isActive?() == true,
            let object = metadataObjects.first as? AVMetadataMachineReadableCodeObject,
            let value = object.stringValue,
            !value.isEmpty,
            deliveryGate.beginDelivery()
        else { return }
        onScan?(value)
    }

    private func configureCaptureSession() {
        guard AVCaptureDevice.authorizationStatus(for: .video) == .authorized else {
            reportUnavailable()
            return
        }
        guard
            let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back)
                ?? AVCaptureDevice.default(for: .video),
            let input = try? AVCaptureDeviceInput(device: device),
            session.canAddInput(input)
        else {
            reportUnavailable()
            return
        }

        session.beginConfiguration()
        session.sessionPreset = .high
        session.addInput(input)

        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else {
            session.commitConfiguration()
            reportUnavailable()
            return
        }
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]
        session.commitConfiguration()

        camera = device
        configured = true

        let preview = AVCaptureVideoPreviewLayer(session: session)
        preview.videoGravity = .resizeAspectFill
        view.layer.addSublayer(preview)
        previewLayer = preview

        onTorchAvailability?(device.hasTorch && device.isTorchAvailable)
        sessionQueue.async { [weak self] in
            guard let self, self.configured else { return }
            self.session.startRunning()
        }
    }

    private func reportUnavailable() {
        DispatchQueue.main.async { [weak self] in
            self?.onUnavailable?()
        }
    }
}
