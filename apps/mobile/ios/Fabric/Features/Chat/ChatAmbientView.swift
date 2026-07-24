import SwiftUI

// A subtle reactive ambient behind the chat transcript — the iOS counterpart to
// the concept's cosmos and the desktop thread glow. Two soft radial glows drift
// slowly and brighten while the agent is working, settling when idle. Strictly
// decorative: it sits behind the Fabric canvas base and all content, never
// intercepts touches, and freezes under Reduce Motion.

struct ChatAmbientBackdrop: View {
    let active: Bool

    var body: some View {
        ZStack {
            FabricTheme.canvas
            ChatAmbientView(active: active)
        }
        .ignoresSafeArea()
    }
}

struct ChatAmbientView: View {
    let active: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: reduceMotion || !active)) { timeline in
            Canvas { context, size in
                let time = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
                draw(context: context, size: size, time: time)
            }
        }
        .allowsHitTesting(false)
        .opacity(active ? 1 : 0.55)
        .animation(.easeInOut(duration: 0.8), value: active)
    }

    private func draw(context: GraphicsContext, size: CGSize, time: Double) {
        let energy = active ? 1.0 : 0.4
        let drift = CGFloat(sin(time * 0.3)) * 22
        glow(
            context: context,
            center: CGPoint(x: size.width * 0.22 + drift, y: size.height * 0.16),
            radius: size.width * 0.62,
            color: FabricTheme.action,
            alpha: 0.10 * energy
        )
        glow(
            context: context,
            center: CGPoint(x: size.width * 0.85 - drift, y: size.height * 0.88),
            radius: size.width * 0.62,
            color: Color(red: 1.0, green: 0.43, blue: 0.78),
            alpha: 0.08 * energy
        )
    }

    private func glow(
        context: GraphicsContext,
        center: CGPoint,
        radius: CGFloat,
        color: Color,
        alpha: Double
    ) {
        let rect = CGRect(
            x: center.x - radius,
            y: center.y - radius,
            width: radius * 2,
            height: radius * 2
        )
        let shading = GraphicsContext.Shading.radialGradient(
            Gradient(colors: [color.opacity(alpha), color.opacity(0)]),
            center: center,
            startRadius: 0,
            endRadius: radius
        )
        context.fill(Path(ellipseIn: rect), with: shading)
    }
}
