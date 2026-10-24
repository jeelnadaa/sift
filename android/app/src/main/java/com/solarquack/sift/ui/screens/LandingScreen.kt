package com.solarquack.sift.ui.screens

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius

private val FEATURES = listOf(
    Triple("◉", "Only what matters buzzes", "Your rules run first. Bank noise is kept and searchable, never notified. Fraud alerts still get through."),
    Triple("◈", "One timeline per company", "Announcement, registration, test link, interview, result: from any account, in order. Add your own steps with a date and time."),
    Triple("▤", "Folders that sort themselves", "Placement mail files itself, one subfolder per company. Ask the AI to build timelines or to-dos from any folder."),
    Triple("⌕", "Read, search and write", "Whole conversations, Gmail search plus Sift's filters, reply, attach, undo send, send later, reminders when nobody answers."),
    Triple("✦", "Your own AI key", "No shared key. Add yours and AI switches on; skip it and everything else still works. See where every token went."),
)

/** First screen before signing in: what Sift is, then Get started (sign up) or I have an account. */
@Composable
fun LandingScreen(onGetStarted: () -> Unit, onSignIn: () -> Unit, animate: Boolean = true) {
    // a short fade-in; skipped when the phone's animations are turned off
    val reduced = android.provider.Settings.Global.getFloat(
        androidx.compose.ui.platform.LocalContext.current.contentResolver, android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 1f,
    ) == 0f || !animate || androidx.compose.ui.platform.LocalInspectionMode.current  // previews and screenshot tests: no animation
    val shown = remember { Animatable(if (reduced) 1f else 0f) }
    LaunchedEffect(Unit) { if (!reduced) shown.animateTo(1f, tween(700)) }

    Column(
        Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 40.dp),
    ) {
        Wordmark()
        Column(Modifier.alpha(shown.value).graphicsLayer { translationY = (1f - shown.value) * 40f }) {
            Spacer(Modifier.height(40.dp))
            Text(
                buildAnnotatedString {
                    append("Your inbox,\n")
                    withStyle(SpanStyle(color = Ink.signal)) { append("sifted.") }
                },
                style = MaterialTheme.typography.displaySmall.copy(fontSize = 54.sp, lineHeight = 54.sp), color = Ink.text,
            )
            Text(
                "Sift watches every Gmail account you own, runs your rules first, and buzzes your phone the second something matters.",
                color = Ink.text2, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(top = 18.dp),
            )
            Spacer(Modifier.height(24.dp))
            PrimaryButton("Get started", Modifier.fillMaxWidth().height(52.dp), onClick = onGetStarted)
            Spacer(Modifier.height(10.dp))
            GhostButton("I have an account", Modifier.fillMaxWidth().height(52.dp), onClick = onSignIn)

            Row(Modifier.fillMaxWidth().padding(top = 32.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                listOf("2 s" to "mail to buzz", "0" to "tokens on bank alerts", "100%" to "your own key").forEach { (n, label) ->
                    Column {
                        Text(n, style = MaterialTheme.typography.headlineMedium, color = Ink.text)
                        Text(label, color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }

            Text("WHAT YOU GET", color = Ink.signal, style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(top = 40.dp, bottom = 12.dp))
            FEATURES.forEach { (icon, title, text) ->
                Row(
                    Modifier.fillMaxWidth().padding(vertical = 5.dp).background(Ink.surface, Radius.lg).border(1.dp, Ink.line, Radius.lg).padding(16.dp),
                    verticalAlignment = Alignment.Top,
                ) {
                    Box(Modifier.size(40.dp).background(Ink.signal.copy(alpha = 0.14f), Radius.md), contentAlignment = Alignment.Center) {
                        Text(icon, color = Ink.signal, fontSize = 20.sp)
                    }
                    Column(Modifier.padding(start = 14.dp)) {
                        Text(title, color = Ink.text, style = MaterialTheme.typography.titleMedium)
                        Text(text, color = Ink.text2, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 4.dp))
                    }
                }
            }

            Text(
                buildAnnotatedString {
                    append("Stop digging.\n")
                    withStyle(SpanStyle(color = Ink.signal)) { append("Start sifting.") }
                },
                style = MaterialTheme.typography.headlineLarge.copy(fontSize = 38.sp, lineHeight = 40.sp), color = Ink.text,
                modifier = Modifier.padding(top = 40.dp),
            )
            Spacer(Modifier.height(20.dp))
            PrimaryButton("Get started", Modifier.fillMaxWidth().height(52.dp), onClick = onGetStarted)
            Text("Read-only until you ask. Never logs email bodies.", color = Ink.text3, style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(top = 14.dp))
        }
    }
}
