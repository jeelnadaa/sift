package com.solarquack.sift.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.solarquack.sift.R

/** Tokens from DESIGN.md. */
object Ink {
    val bg = Color(0xFF0A0A0B)
    val bg2 = Color(0xFF101012)
    val surface = Color(0xFF151518)
    val surface2 = Color(0xFF1C1C20)
    val line = Color(0xFF26262B)
    val line2 = Color(0xFF34343B)
    val text = Color(0xFFF4F3EE)
    val text2 = Color(0xFFA9A9B1)
    val text3 = Color(0xFF6E6E78)
    val signal = Color(0xFFC8FF3D)
    val signalInk = Color(0xFF10150A)
    val urgent = Color(0xFFFF5A3C)
    val normal = Color(0xFF6EA8FF)
    val digest = Color(0xFFB79CFF)
    val silent = Color(0xFF5B5B64)
    val warn = Color(0xFFFFB938)
    val accounts = listOf(Color(0xFFFF8A5B), Color(0xFF4AD6C4), Color(0xFFF6D365), Color(0xFFFF6FAE))

    fun tier(priority: String?): Color = when (priority) {
        "urgent" -> urgent
        "normal" -> normal
        "digest" -> digest
        else -> silent
    }
}

object Radius {
    val xs = RoundedCornerShape(4.dp)
    val sm = RoundedCornerShape(6.dp)
    val md = RoundedCornerShape(8.dp)
    val lg = RoundedCornerShape(10.dp)
    val xl = RoundedCornerShape(14.dp)
}

val Satoshi = FontFamily(
    Font(R.font.satoshi_400, FontWeight.Normal),
    Font(R.font.satoshi_500, FontWeight.Medium),
    Font(R.font.satoshi_700, FontWeight.Bold),
)

val ClashDisplay = FontFamily(
    Font(R.font.clash_display_500, FontWeight.Medium),
    Font(R.font.clash_display_600, FontWeight.SemiBold),
    Font(R.font.clash_display_700, FontWeight.Bold),
)

private val typography = Typography(
    displaySmall = TextStyle(fontFamily = ClashDisplay, fontWeight = FontWeight.SemiBold, fontSize = 34.sp, lineHeight = 38.sp),
    headlineMedium = TextStyle(fontFamily = ClashDisplay, fontWeight = FontWeight.SemiBold, fontSize = 26.sp, lineHeight = 30.sp),
    headlineSmall = TextStyle(fontFamily = ClashDisplay, fontWeight = FontWeight.SemiBold, fontSize = 22.sp, lineHeight = 26.sp),
    titleMedium = TextStyle(fontFamily = Satoshi, fontWeight = FontWeight.Bold, fontSize = 15.sp, lineHeight = 20.sp),
    titleSmall = TextStyle(fontFamily = Satoshi, fontWeight = FontWeight.Bold, fontSize = 13.5.sp, lineHeight = 18.sp),
    bodyLarge = TextStyle(fontFamily = Satoshi, fontSize = 15.sp, lineHeight = 22.sp),
    bodyMedium = TextStyle(fontFamily = Satoshi, fontSize = 13.5.sp, lineHeight = 19.sp),
    bodySmall = TextStyle(fontFamily = Satoshi, fontSize = 12.sp, lineHeight = 16.sp),
    labelLarge = TextStyle(fontFamily = Satoshi, fontWeight = FontWeight.Bold, fontSize = 14.sp),
    labelMedium = TextStyle(fontFamily = Satoshi, fontWeight = FontWeight.Bold, fontSize = 12.sp),
    labelSmall = TextStyle(fontFamily = Satoshi, fontWeight = FontWeight.Bold, fontSize = 10.5.sp, letterSpacing = 1.4.sp),
)

/** Everything in the app (text, spacing, touch targets) is drawn 8% larger than the system's
 * base size, on top of the user's own font-size setting (owner, 2026-10-24: "scale a bit bigger"). */
const val UI_SCALE = 1.08f

@Composable
fun SiftTheme(content: @Composable () -> Unit) {
    val base = androidx.compose.ui.platform.LocalDensity.current
    androidx.compose.runtime.CompositionLocalProvider(
        androidx.compose.ui.platform.LocalDensity provides androidx.compose.ui.unit.Density(base.density * UI_SCALE, base.fontScale),
    ) { SiftMaterial(content) }
}

@Composable
private fun SiftMaterial(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Ink.signal, onPrimary = Ink.signalInk, background = Ink.bg, onBackground = Ink.text,
            surface = Ink.surface, onSurface = Ink.text, surfaceVariant = Ink.surface2, onSurfaceVariant = Ink.text2,
            outline = Ink.line2, error = Ink.urgent,
        ),
        typography = typography,
        shapes = Shapes(extraSmall = Radius.xs, small = Radius.sm, medium = Radius.md, large = Radius.lg, extraLarge = Radius.xl),
        content = content,
    )
}
