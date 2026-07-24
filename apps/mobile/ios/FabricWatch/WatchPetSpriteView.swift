import SwiftUI

/// Wrist renderer for the relayed Petdex atlas — the same crop-and-step
/// technique as the phone's `PetSpriteView`, with two watch-specific rules:
/// the always-on dimmed state freezes on the row's first frame (per the
/// platform update budget), and a missing atlas falls back to the shared
/// pose-symbol vocabulary so the pet identity never disappears.
struct WatchPetSpriteView: View {
    let atlas: WatchSpriteAtlas?
    let stateRaw: String
    var height: CGFloat = 68

    @Environment(\.isLuminanceReduced) private var isLuminanceReduced

    var body: some View {
        if let atlas,
           let cgAtlas = atlas.image.cgImage,
           let layout = WatchSpriteFrameLayout.resolve(
               stateRaw: stateRaw,
               manifest: atlas.manifest,
               atlasWidth: cgAtlas.width,
               atlasHeight: cgAtlas.height
           ) {
            if isLuminanceReduced {
                frameImage(cgAtlas: cgAtlas, layout: layout, column: 0)
            } else {
                TimelineView(.animation(minimumInterval: Double(layout.stepMilliseconds) / 1_000)) { context in
                    let elapsed = Int(context.date.timeIntervalSinceReferenceDate * 1_000)
                    frameImage(
                        cgAtlas: cgAtlas,
                        layout: layout,
                        column: layout.column(atMillisecond: elapsed)
                    )
                }
            }
        } else {
            posePlaceholder
        }
    }

    @ViewBuilder
    private func frameImage(cgAtlas: CGImage, layout: WatchSpriteFrameLayout, column: Int) -> some View {
        if let manifest = atlas?.manifest,
           let frame = cgAtlas.cropping(to: CGRect(
               x: CGFloat(column * manifest.frameW),
               y: CGFloat(layout.rowIndex * manifest.frameH),
               width: CGFloat(manifest.frameW),
               height: CGFloat(manifest.frameH)
           )) {
            Image(decorative: frame, scale: 1)
                .interpolation(.none)
                .resizable()
                .scaledToFit()
                .frame(height: height)
        } else {
            posePlaceholder
        }
    }

    private var posePlaceholder: some View {
        let pose = WatchPetPose.pose(for: stateRaw)
        return Image(systemName: pose.symbolName)
            .font(.system(size: height * 0.6))
            .foregroundStyle(pose.isAttention ? Color.orange : Color.accentColor)
            .frame(height: height)
            .accessibilityHidden(true)
    }
}
