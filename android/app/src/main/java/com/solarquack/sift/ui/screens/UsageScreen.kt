package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.UsageDto
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.SectionLabel
import com.solarquack.sift.ui.SiftCard
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import java.text.NumberFormat
import java.time.LocalDate

/** Token usage on the user's own AI key: today against the daily cap, and the last 30 days. */
@Composable
fun UsageScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    var usage by remember { mutableStateOf<UsageDto?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) { try { usage = Api.get(context).usage(30) } catch (t: Throwable) { error = t.userMessage() } }
    val fmt = remember { NumberFormat.getIntegerInstance() }

    Column(Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).padding(18.dp)) {
        Text("‹ More", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(vertical = 6.dp))
        Text("Token usage", style = MaterialTheme.typography.headlineMedium, color = Ink.text)
        Text("Tokens your own AI key spent. Rules, silenced mail and fingerprints cost nothing.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
        error?.let { Spacer(Modifier.height(8.dp)); Banner(it, Ink.urgent) }
        val u = usage ?: return@Column

        Spacer(Modifier.height(14.dp))
        SiftCard {
            Text("Today", color = Ink.text3, style = MaterialTheme.typography.labelSmall)
            Text(fmt.format(u.tokensToday), style = MaterialTheme.typography.displaySmall, color = Ink.text)
            val fraction = if (u.dailyTokenCap > 0) (u.tokensToday.toFloat() / u.dailyTokenCap).coerceIn(0f, 1f) else 0f
            LinearProgressIndicator(progress = { fraction }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp), color = if (fraction > 0.9f) Ink.urgent else Ink.signal, trackColor = Ink.line)
            Text("of ${fmt.format(u.dailyTokenCap)} daily cap. When it's reached, mail is still delivered (as normal priority) without AI.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
        }

        SectionLabel("Last 30 days")
        val byDay = u.days.associateBy { it.day }
        val days = (29 downTo 0).map { LocalDate.now().minusDays(it.toLong()).toString() }
        val max = days.maxOf { (byDay[it]?.let { d -> d.inputTokens + d.outputTokens } ?: 0) }.coerceAtLeast(1)
        Row(Modifier.fillMaxWidth().height(120.dp), horizontalArrangement = Arrangement.spacedBy(3.dp), verticalAlignment = Alignment.Bottom) {
            days.forEach { day ->
                val total = byDay[day]?.let { it.inputTokens + it.outputTokens } ?: 0
                Box(
                    Modifier.weight(1f).fillMaxHeight(fraction = (total.toFloat() / max).coerceAtLeast(0.02f))
                        .background(if (day == days.last()) Ink.signal else Ink.line2, Radius.xs)
                        .semantics { contentDescription = "$day: $total tokens" },
                )
            }
        }
        val calls = u.days.sumOf { it.calls }
        val tokens = u.days.sumOf { it.inputTokens + it.outputTokens }
        Text("${fmt.format(calls)} AI calls · ${fmt.format(tokens)} tokens in 30 days", color = Ink.text2, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 10.dp))
    }
}
