package io.github.obliviousodin.fabric.mobile.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Fabric design foundation for Android, generated from the canonical token
 * source `apps/design-system/src/tokens/tokens.json` (Woven Operations
 * contract, `web/DESIGN.md`). Values are the resolved semantic roles for
 * Fabric Light / Fabric Dark — do not hand-tune colors here; change the
 * token source and re-derive.
 *
 * Contract notes that shape this file:
 * - Purple (#4628CC / #5542E3 dark) marks action, focus, and the active
 *   thread — never a page wash. Neutral surfaces ≥ 90% of any screen.
 * - Status colors are semantic and independent from selection.
 * - Default radius 8, previews/dialogs 12, chips 4.
 * - Body 14–16sp, metadata never below 12sp, headings cap at semibold.
 */

// ── Fabric Light ────────────────────────────────────────────────────────────
private val LightCanvas = Color(0xFFFCFAF6)
private val LightSurface = Color(0xFFF6F4F0)
private val LightSurfaceRaised = Color(0xFFF0EEEA)
private val LightSurfaceInset = Color(0xFFEDEBE7)
private val LightSurfaceBrand = Color(0xFFF0EDFB)
private val LightText = Color(0xFF221F1A)
private val LightTextMuted = Color(0xFF5B5852)
private val LightBorder = Color(0xFFD1CFCB)
private val LightBorderStrong = Color(0xFFB6B1A8)
private val LightAction = Color(0xFF4628CC)
private val LightDanger = Color(0xFFBE2323)

// ── Fabric Dark ─────────────────────────────────────────────────────────────
private val DarkCanvas = Color(0xFF0E0C11)
private val DarkSurface = Color(0xFF151318)
private val DarkSurfaceRaised = Color(0xFF1D1A1F)
private val DarkSurfaceInset = Color(0xFF201E23)
private val DarkSurfaceBrand = Color(0xFF25156B)
private val DarkText = Color(0xFFEAE6EE)
private val DarkTextMuted = Color(0xFFADA9B1)
private val DarkBorder = Color(0xFF28252A)
private val DarkBorderStrong = Color(0xFF4B4550)
private val DarkAction = Color(0xFF5542E3)
private val DarkDanger = Color(0xFFFF7266)

/**
 * Semantic roles Material3's ColorScheme has no slot for: status colors and
 * the thread/provenance accents. Reach them via [FabricTheme.extras].
 */
@Immutable
data class FabricExtras(
    val info: Color,
    val success: Color,
    val warning: Color,
    val danger: Color,
    val thread: Color,
    val threadActive: Color,
    val textMuted: Color,
    val surfaceBrand: Color,
) {
    /** Runtime session status → semantic color, per the contract's status language. */
    fun sessionStatusColor(status: String): Color = when (status) {
        "working" -> threadActive
        "waiting" -> warning
        "starting" -> info
        else -> textMuted
    }
}

private val LightExtras = FabricExtras(
    info = Color(0xFF3E63A7),
    success = Color(0xFF137D41),
    warning = Color(0xFF876200),
    danger = LightDanger,
    thread = Color(0xFF8174B0),
    threadActive = LightAction,
    textMuted = LightTextMuted,
    surfaceBrand = LightSurfaceBrand,
)

private val DarkExtras = FabricExtras(
    info = Color(0xFF7BA7E8),
    success = Color(0xFF5EBC7B),
    warning = Color(0xFFCF9B20),
    danger = DarkDanger,
    thread = Color(0xFF9481E6),
    threadActive = Color(0xFF9481E6),
    textMuted = DarkTextMuted,
    surfaceBrand = DarkSurfaceBrand,
)

private val LocalFabricExtras = staticCompositionLocalOf { LightExtras }

private val FabricLightColors = lightColorScheme(
    primary = LightAction,
    onPrimary = Color.White,
    primaryContainer = LightSurfaceBrand,
    onPrimaryContainer = LightText,
    secondary = LightTextMuted,
    onSecondary = Color.White,
    secondaryContainer = LightSurfaceInset,
    onSecondaryContainer = LightText,
    background = LightCanvas,
    onBackground = LightText,
    surface = LightCanvas,
    onSurface = LightText,
    surfaceVariant = LightSurfaceRaised,
    onSurfaceVariant = LightTextMuted,
    surfaceContainer = LightSurface,
    surfaceContainerHigh = LightSurfaceRaised,
    surfaceContainerHighest = LightSurfaceInset,
    outline = LightBorderStrong,
    outlineVariant = LightBorder,
    error = LightDanger,
    onError = Color.White,
)

private val FabricDarkColors = darkColorScheme(
    primary = DarkAction,
    onPrimary = Color.White,
    primaryContainer = DarkSurfaceBrand,
    onPrimaryContainer = DarkText,
    secondary = DarkTextMuted,
    onSecondary = Color.Black,
    secondaryContainer = DarkSurfaceInset,
    onSecondaryContainer = DarkText,
    background = DarkCanvas,
    onBackground = DarkText,
    surface = DarkCanvas,
    onSurface = DarkText,
    surfaceVariant = DarkSurfaceRaised,
    onSurfaceVariant = DarkTextMuted,
    surfaceContainer = DarkSurface,
    surfaceContainerHigh = DarkSurfaceRaised,
    surfaceContainerHighest = DarkSurfaceInset,
    outline = DarkBorderStrong,
    outlineVariant = DarkBorder,
    error = DarkDanger,
    onError = Color.White,
)

/**
 * Type scale from the token source: body 14, emphasis 16, subheading 18,
 * section 20; captions never below 12. System sans (contract font policy);
 * headings cap at semibold.
 */
private val FabricTypography = Typography(
    titleLarge = TextStyle(fontSize = 20.sp, fontWeight = FontWeight.SemiBold, lineHeight = 26.sp),
    titleMedium = TextStyle(fontSize = 18.sp, fontWeight = FontWeight.SemiBold, lineHeight = 24.sp),
    titleSmall = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold, lineHeight = 22.sp),
    bodyLarge = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.Normal, lineHeight = 24.sp),
    bodyMedium = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.Normal, lineHeight = 21.sp),
    bodySmall = TextStyle(fontSize = 13.sp, fontWeight = FontWeight.Normal, lineHeight = 19.sp),
    labelLarge = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.Medium, lineHeight = 20.sp),
    labelMedium = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Medium, lineHeight = 16.sp),
    labelSmall = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Normal, lineHeight = 16.sp),
    headlineLarge = TextStyle(fontSize = 32.sp, fontWeight = FontWeight.SemiBold, lineHeight = 40.sp),
)

/** Radius tokens: 8 default, 12 for dialogs/previews/bubbles, 4 for chips. */
private val FabricShapes = Shapes(
    extraSmall = RoundedCornerShape(4.dp),
    small = RoundedCornerShape(8.dp),
    medium = RoundedCornerShape(8.dp),
    large = RoundedCornerShape(12.dp),
    extraLarge = RoundedCornerShape(16.dp),
)

object FabricTheme {
    val extras: FabricExtras
        @Composable get() = LocalFabricExtras.current
}

@Composable
fun FabricTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    CompositionLocalProvider(LocalFabricExtras provides if (dark) DarkExtras else LightExtras) {
        MaterialTheme(
            colorScheme = if (dark) FabricDarkColors else FabricLightColors,
            typography = FabricTypography,
            shapes = FabricShapes,
            content = content,
        )
    }
}
