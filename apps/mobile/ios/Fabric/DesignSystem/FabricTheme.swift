import SwiftUI
import UIKit

/// Fabric design foundation for iOS, generated from the canonical token
/// source `apps/design-system/src/tokens/tokens.json` (Woven Operations
/// contract, `web/DESIGN.md`). Values are the resolved semantic roles for
/// Fabric Light / Fabric Dark — do not hand-tune colors here; change the
/// token source and re-derive.
///
/// Contract notes that shape this file:
/// - Purple (#4628CC / #5542E3 dark) marks action, focus, and the active
///   thread — never a page wash. Neutral surfaces ≥ 90% of any screen.
/// - Status colors are semantic and independent from selection.
/// - Default radius 8, previews/dialogs 12, chips 4.
/// - Body 14–16pt, metadata never below 12pt, headings cap at semibold.
enum FabricTheme {
    // MARK: - Semantic colors (light / dark)

    static let canvas = dynamic(light: 0xFCFAF6, dark: 0x0E0C11)
    static let surface = dynamic(light: 0xF6F4F0, dark: 0x151318)
    static let surfaceRaised = dynamic(light: 0xF0EEEA, dark: 0x1D1A1F)
    static let surfaceInset = dynamic(light: 0xEDEBE7, dark: 0x201E23)
    static let surfaceBrand = dynamic(light: 0xF0EDFB, dark: 0x25156B)

    static let text = dynamic(light: 0x221F1A, dark: 0xEAE6EE)
    static let textMuted = dynamic(light: 0x5B5852, dark: 0xADA9B1)
    static let textDisabled = dynamic(light: 0x8F8A82, dark: 0x77717D)
    static let textOnBrand = dynamic(light: 0xFFFFFF, dark: 0xFFFFFF)

    static let border = dynamic(light: 0xD1CFCB, dark: 0x28252A)
    static let borderStrong = dynamic(light: 0xB6B1A8, dark: 0x4B4550)

    static let action = dynamic(light: 0x4628CC, dark: 0x5542E3)
    static let focus = dynamic(light: 0x4628CC, dark: 0x9481E6)

    static let info = dynamic(light: 0x3E63A7, dark: 0x7BA7E8)
    static let success = dynamic(light: 0x137D41, dark: 0x5EBC7B)
    static let warning = dynamic(light: 0x876200, dark: 0xCF9B20)
    static let danger = dynamic(light: 0xBE2323, dark: 0xFF7266)

    /// Provenance/relationship accent; `threadActive` marks the live turn.
    static let thread = dynamic(light: 0x8174B0, dark: 0x9481E6)
    static let threadActive = dynamic(light: 0x4628CC, dark: 0x9481E6)

    // MARK: - Shape and rhythm

    /// Default control/container radius.
    static let radius: CGFloat = 8
    /// Object previews, dialogs, message bubbles.
    static let radiusLarge: CGFloat = 12
    /// Chips and compact controls.
    static let radiusChip: CGFloat = 4
    /// Minimum interactive target (contract: 44×44 including icon controls).
    static let minTarget: CGFloat = 44

    // MARK: - Status mapping

    /// Runtime session status → semantic color + label, per the contract's
    /// status language (running = active thread, waiting = amber, etc.).
    static func sessionStatusColor(_ status: String) -> Color {
        switch status {
        case "working": return threadActive
        case "waiting": return warning
        case "starting": return info
        default: return textMuted
        }
    }

    // MARK: - Helpers

    private static func dynamic(light: UInt32, dark: UInt32) -> Color {
        Color(UIColor { traits in
            traits.userInterfaceStyle == .dark ? uiColor(dark) : uiColor(light)
        })
    }

    private static func uiColor(_ hex: UInt32) -> UIColor {
        UIColor(
            red: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: 1
        )
    }
}

/// A status tint at the contract's 8–12% panel budget: status color marks a
/// dot/line/tint, never a fully saturated panel.
extension Color {
    func fabricTint() -> Color { opacity(0.1) }
}
