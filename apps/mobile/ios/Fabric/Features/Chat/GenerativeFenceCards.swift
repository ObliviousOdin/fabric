import SwiftUI

// SwiftUI cards for the generative chat fences (```work / ```chart). They are
// rendered from a fenced-code block whose language is "work" or "chart" — the
// transcript parser already isolates fenced code, so this adds no parser
// surface. Each card carries the same reduced-motion-aware entrance animation.

/// A reusable entrance: fade + slight scale on first appearance, instant under
/// Reduce Motion. Self-contained (local state + onAppear) so it animates
/// regardless of the surrounding list's animation context.
struct GenerativeCardAppear: ViewModifier {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shown = false

    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .scaleEffect(shown ? 1 : 0.98, anchor: .topLeading)
            .onAppear {
                guard !shown else { return }
                if reduceMotion {
                    shown = true
                } else {
                    withAnimation(.easeOut(duration: 0.22)) { shown = true }
                }
            }
    }
}

extension View {
    func generativeCardAppear() -> some View { modifier(GenerativeCardAppear()) }
}

struct WorkFenceCard: View {
    let spec: WorkFenceSpec

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(spec.title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(FabricTheme.text)
                Spacer(minLength: 8)
                WorkStatusChip(label: statusLabel, tone: statusTone)
            }
            if !spec.steps.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(spec.steps.enumerated()), id: \.offset) { _, step in
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Text(glyph(for: step.state))
                                .font(.caption.monospaced())
                                .foregroundStyle(glyphColor(for: step.state))
                            Text(step.label)
                                .font(.caption)
                                .foregroundStyle(step.state == .done ? FabricTheme.textMuted : FabricTheme.text)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(FabricTheme.surface, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
        .overlay {
            RoundedRectangle(cornerRadius: FabricTheme.radiusLarge).stroke(FabricTheme.border, lineWidth: 1)
        }
        .generativeCardAppear()
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Work: \(spec.title), \(statusLabel)")
    }

    private var statusTone: WorkStatusTone {
        switch spec.status {
        case .queued: return .neutral
        case .running: return .running
        case .done: return .success
        case .failed: return .failure
        case .blocked: return .attention
        }
    }

    private var statusLabel: String {
        spec.status.rawValue.prefix(1).uppercased() + spec.status.rawValue.dropFirst()
    }

    private func glyph(for state: WorkFenceStepState) -> String {
        switch state {
        case .done: return "✓"
        case .running: return "◐"
        case .failed: return "✕"
        case .pending: return "○"
        }
    }

    private func glyphColor(for state: WorkFenceStepState) -> Color {
        switch state {
        case .done: return FabricTheme.success
        case .running: return FabricTheme.action
        case .failed: return FabricTheme.danger
        case .pending: return FabricTheme.textMuted
        }
    }
}

struct ChartFenceCard: View {
    let spec: ChartFenceSpec

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let title = spec.title {
                Text(title)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(FabricTheme.textMuted)
            }
            Canvas { context, size in draw(in: context, size: size) }
                .frame(height: 120)
                .accessibilityHidden(true)
            if spec.data.contains(where: { !$0.label.isEmpty }) {
                HStack(spacing: 0) {
                    ForEach(Array(spec.data.enumerated()), id: \.offset) { _, point in
                        Text(point.label)
                            .font(.caption2)
                            .foregroundStyle(FabricTheme.textMuted)
                            .lineLimit(1)
                            .frame(maxWidth: .infinity)
                    }
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(FabricTheme.surface, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
        .overlay {
            RoundedRectangle(cornerRadius: FabricTheme.radiusLarge).stroke(FabricTheme.border, lineWidth: 1)
        }
        .generativeCardAppear()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(spec.title ?? "Chart") — \(spec.data.count) point chart")
    }

    private func draw(in context: GraphicsContext, size: CGSize) {
        let padX: CGFloat = 6
        let padTop: CGFloat = 4
        let padBottom: CGFloat = 4
        let innerW = max(1, size.width - padX * 2)
        let innerH = max(1, size.height - padTop - padBottom)
        let baseY = padTop + innerH
        let maxValue = max(1, spec.data.map { max(0, $0.value) }.max() ?? 1)
        let count = spec.data.count
        let accent = GraphicsContext.Shading.color(FabricTheme.action)

        switch spec.type {
        case .bar:
            let slot = innerW / CGFloat(count)
            for (index, point) in spec.data.enumerated() {
                let barW = min(28, slot * 0.62)
                let x = padX + slot * (CGFloat(index) + 0.5) - barW / 2
                let height = CGFloat(max(0, point.value) / maxValue) * innerH
                let rect = CGRect(x: x, y: baseY - height, width: barW, height: max(1, height))
                context.fill(Path(roundedRect: rect, cornerRadius: 2), with: accent)
            }
        case .line:
            let stepX = count > 1 ? innerW / CGFloat(count - 1) : 0
            var path = Path()
            for (index, point) in spec.data.enumerated() {
                let x = padX + stepX * CGFloat(index)
                let y = baseY - CGFloat(max(0, point.value) / maxValue) * innerH
                if index == 0 {
                    path.move(to: CGPoint(x: x, y: y))
                } else {
                    path.addLine(to: CGPoint(x: x, y: y))
                }
            }
            context.stroke(path, with: accent, lineWidth: 2)
        }
    }
}
