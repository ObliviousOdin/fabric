import SwiftUI

/// First successful connection handoff. It confirms the endpoint and the
/// gateway-owned execution contract before the user enters Home. This is not a
/// device-enrollment or cryptographic-trust screen; those capabilities remain
/// hidden until the server advertises them.
struct ConnectedGatewayIntroView: View {
    let gateway: SavedGateway
    let negotiation: GatewayCapabilityNegotiation?
    let hasStoredPassword: Bool
    let onContinue: () -> Void
    let onSwitchServer: () -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(
        gateway: SavedGateway,
        negotiation: GatewayCapabilityNegotiation?,
        hasStoredPassword: Bool = false,
        onContinue: @escaping () -> Void,
        onSwitchServer: @escaping () -> Void
    ) {
        self.gateway = gateway
        self.negotiation = negotiation
        self.hasStoredPassword = hasStoredPassword
        self.onContinue = onContinue
        self.onSwitchServer = onSwitchServer
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: dynamicTypeSize.isAccessibilitySize ? 20 : 28) {
                brand

                VStack(alignment: .leading, spacing: 12) {
                    Label("Connected", systemImage: "checkmark.circle.fill")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(FabricTheme.success)
                    Text("Ready on \(gateway.label)")
                        .font(.largeTitle.weight(.semibold))
                        .foregroundStyle(FabricTheme.text)
                        .fixedSize(horizontal: false, vertical: true)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Endpoint")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(FabricTheme.textMuted)
                        GatewayEndpointIdentityText(
                            endpoint: SettingsGatewayIdentity.displayEndpoint(gateway.baseURL),
                            style: .subheadline
                        )
                    }
                    .accessibilityElement(children: .combine)
                }

                VStack(spacing: 0) {
                    ForEach(Array(executionFacts.enumerated()), id: \.offset) { index, fact in
                        if index > 0 {
                            Divider().padding(.leading, 56)
                        }
                        ConnectionFactRow(
                            icon: fact.icon,
                            title: fact.title,
                            detail: fact.detail
                        )
                    }
                    Divider().padding(.leading, 56)
                    let credentialFact = ConnectedGatewayIntroPresentation.credentialFact(
                        for: gateway,
                        hasStoredPassword: hasStoredPassword
                    )
                    ConnectionFactRow(
                        icon: credentialFact.icon,
                        title: credentialFact.title,
                        detail: credentialFact.detail
                    )
                    .accessibilityIdentifier("connected-gateway-credential")
                }
                .background(FabricTheme.surfaceRaised)
                .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
                .overlay {
                    RoundedRectangle(cornerRadius: FabricTheme.radiusLarge)
                        .stroke(FabricTheme.border, lineWidth: 1)
                }

                if case .legacy = negotiation {
                    Label(
                        "Update the gateway for capability-aware controls and verified execution guarantees.",
                        systemImage: "info.circle"
                    )
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
                }

                VStack(spacing: 10) {
                    Button(action: onContinue) {
                        Label("Continue to Fabric", systemImage: "arrow.right")
                            .font(.headline)
                            .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                    }
                    .buttonStyle(.borderedProminent)
                    .accessibilityHint("Opens Fabric Home")

                    Button("Use a different server", action: onSwitchServer)
                        .frame(minHeight: FabricTheme.minTarget)
                }
            }
            .frame(maxWidth: 620, alignment: .leading)
            .padding(.horizontal, 24)
            .padding(.top, 28)
            .padding(.bottom, 32)
        }
        .background(FabricTheme.canvas.ignoresSafeArea())
    }

    private var executionFacts: [ConnectedGatewayFact] {
        ConnectedGatewayIntroPresentation.executionFacts(for: negotiation)
    }

    private var brand: some View {
        HStack(spacing: 12) {
            Image("FabricMark")
                .resizable()
                .scaledToFit()
                .frame(width: 42, height: 42)
                .accessibilityHidden(true)
            Text("Fabric")
                .font(.title2.weight(.semibold))
                .foregroundStyle(FabricTheme.text)
        }
        .accessibilityElement(children: .combine)
    }
}

struct ConnectedGatewayFact: Equatable {
    let icon: String
    let title: String
    let detail: String
}

enum ConnectedGatewayIntroPresentation {
    static func credentialFact(
        for gateway: SavedGateway,
        hasStoredPassword: Bool
    ) -> ConnectedGatewayFact {
        switch gateway.authMode {
        case .token:
            ConnectedGatewayFact(
                icon: "key.fill",
                title: "Token protected in Keychain",
                detail: "This server's token stays in protected storage on this iPhone."
            )
        case .gated where hasStoredPassword:
            ConnectedGatewayFact(
                icon: "person.badge.key.fill",
                title: "Password saved in Keychain",
                detail: "This server's password stays in protected storage on this iPhone."
            )
        case .gated:
            ConnectedGatewayFact(
                icon: "person.badge.key.fill",
                title: "Password is not saved",
                detail: "Fabric keeps only the server address and username on this iPhone."
            )
        }
    }

    static func executionFacts(
        for negotiation: GatewayCapabilityNegotiation?
    ) -> [ConnectedGatewayFact] {
        guard case .verified(let capabilities) = negotiation else {
            return [
                ConnectedGatewayFact(
                    icon: "questionmark.circle",
                    title: "Execution location not verified",
                    detail: "This older gateway cannot verify where conversations and tools run."
                ),
                ConnectedGatewayFact(
                    icon: "iphone.and.arrow.forward",
                    title: "Disconnect behavior not verified",
                    detail: "Keep this iPhone connected while work is active until the gateway is updated."
                ),
                ConnectedGatewayFact(
                    icon: "power",
                    title: "Restart behavior not verified",
                    detail: "Keep the gateway online while work is active."
                ),
            ]
        }

        let execution = capabilities.execution
        return [
            ConnectedGatewayFact(
                icon: "desktopcomputer",
                title: execution.location == "gateway" && execution.toolExecution == "gateway"
                    ? "Fabric runs on this gateway"
                    : "Execution location not verified",
                detail: execution.location == "gateway" && execution.toolExecution == "gateway"
                    ? "Conversations and tools execute on the gateway—not on this iPhone."
                    : "This gateway did not provide a verified execution location."
            ),
            ConnectedGatewayFact(
                icon: "iphone.and.arrow.forward",
                title: execution.survivesClientDisconnect
                    ? "You can leave the app"
                    : "Stay connected while work runs",
                detail: execution.survivesClientDisconnect
                    ? "Active work can continue after this client disconnects."
                    : "The gateway reports that active work may stop when this iPhone disconnects."
            ),
            ConnectedGatewayFact(
                icon: "power",
                title: execution.requiresGatewayHostOnline
                    ? "Keep the gateway online"
                    : "Gateway availability varies",
                detail: execution.survivesGatewayRestart
                    ? "The gateway reports that active work survives a gateway restart."
                    : "A gateway restart interrupts work that is still running."
            ),
        ]
    }
}

private struct ConnectionFactRow: View {
    let icon: String
    let title: String
    let detail: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.body.weight(.semibold))
                .foregroundStyle(FabricTheme.action)
                .frame(width: 32, height: 32)
                .background(FabricTheme.surfaceBrand)
                .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radius))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(FabricTheme.text)
                Text(detail)
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .accessibilityElement(children: .combine)
    }
}
