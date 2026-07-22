import SwiftUI
import UIKit

struct SettingsDiagnosticsView: View {
    let presentation: SettingsExperiencePresentation
    let permissions: SettingsPermissionInventory

    @State private var copied = false
    @State private var report: String

    init(
        presentation: SettingsExperiencePresentation,
        permissions: SettingsPermissionInventory
    ) {
        self.presentation = presentation
        self.permissions = permissions
        _report = State(initialValue: SettingsDiagnosticsReport.make(
            presentation: presentation,
            permissions: permissions
        ))
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                redactionNotice
                reportCard
                copyButton
            }
            .padding(.horizontal, 20)
            .padding(.top, 16)
            .padding(.bottom, 40)
        }
        .background(FabricTheme.canvas.ignoresSafeArea())
        .navigationTitle("Diagnostics")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var redactionNotice: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "checkmark.shield")
                .font(.body.weight(.semibold))
                .foregroundStyle(FabricTheme.success)
                .frame(width: 28, height: 28)
                .background(
                    FabricTheme.success.fabricTint(),
                    in: RoundedRectangle(cornerRadius: FabricTheme.radiusChip)
                )
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 5) {
                Text("Safe to review before sharing")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(FabricTheme.text)
                Text("This report excludes the server name and address, credentials, cookies, tickets, raw connection errors, prompts, transcripts, and session identifiers. It is generated on this iPhone and is not sent automatically.")
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            FabricTheme.surface,
            in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge)
        )
        .overlay {
            RoundedRectangle(cornerRadius: FabricTheme.radiusLarge)
                .stroke(FabricTheme.border, lineWidth: 1)
        }
        .accessibilityElement(children: .combine)
    }

    private var reportCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Redacted report")
                .font(.headline.weight(.semibold))
                .foregroundStyle(FabricTheme.text)
                .accessibilityAddTraits(.isHeader)
            ScrollView(.horizontal) {
                Text(report)
                    .font(.caption.monospaced())
                    .foregroundStyle(FabricTheme.text)
                    .textSelection(.enabled)
                    .padding(14)
            }
            .frame(maxWidth: .infinity, minHeight: 300, alignment: .topLeading)
            .background(
                FabricTheme.surfaceInset,
                in: RoundedRectangle(cornerRadius: FabricTheme.radius)
            )
            .overlay {
                RoundedRectangle(cornerRadius: FabricTheme.radius)
                    .stroke(FabricTheme.border, lineWidth: 1)
            }
            .accessibilityLabel("Redacted diagnostic report")
        }
    }

    private var copyButton: some View {
        Button {
            UIPasteboard.general.string = report
            copied = true
            UIAccessibility.post(
                notification: .announcement,
                argument: "Redacted diagnostic report copied"
            )
        } label: {
            Label(
                copied ? "Copied redacted report" : "Copy redacted report",
                systemImage: copied ? "checkmark" : "doc.on.doc"
            )
            .font(.body.weight(.semibold))
            .foregroundStyle(FabricTheme.textOnBrand)
            .frame(maxWidth: .infinity, minHeight: 52)
            .background(
                copied ? FabricTheme.success : FabricTheme.action,
                in: RoundedRectangle(cornerRadius: FabricTheme.radius)
            )
        }
        .buttonStyle(.plain)
        .accessibilityHint("Copies only the redacted text shown above")
    }
}

#if DEBUG
#Preview("Settings diagnostics") {
    NavigationStack {
        SettingsDiagnosticsView(
            presentation: .preview,
            permissions: .preview
        )
    }
    .tint(FabricTheme.action)
}
#endif
