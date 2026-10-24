package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.RuleDto
import com.solarquack.sift.data.RuleIn
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.SiftCard
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.relativeTime
import com.solarquack.sift.ui.theme.Ink
import kotlinx.coroutines.launch
import kotlinx.serialization.json.jsonPrimitive

private fun actionTier(type: String?) = when (type) {
    "notify_urgent" -> "urgent"
    "notify_normal", "llm" -> "normal"
    "digest" -> "digest"
    else -> "silent"
}

private fun actionLabel(type: String?) = when (type) {
    "notify_urgent" -> "Notify urgent"
    "notify_normal" -> "Notify normal"
    "silent" -> "Store silently"
    "llm" -> "Send to AI"
    else -> type ?: ""
}

/** Rules list (Phase 1): order, hits and on/off. The editor with preview arrives in Phase 2. */
@Composable
fun RulesScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var rules by remember { mutableStateOf<List<RuleDto>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }

    fun load() = scope.launch {
        try { rules = Api.get(context).rules(); error = null } catch (t: Throwable) { error = t.userMessage() }
    }
    LaunchedEffect(Unit) { load() }

    Column(Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Rules", style = MaterialTheme.typography.headlineMedium, color = Ink.text)
        Text("Checked in order; the first match wins. Sender rules only match mail Gmail authenticated, so spoofed senders never match.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
        error?.let { Banner(it, Ink.urgent, "Retry") { load() } }
        if (rules.isEmpty() && error == null) Text("No rules yet. Everything is classified automatically.", color = Ink.text3, style = MaterialTheme.typography.bodyMedium)
        rules.forEach { r ->
            val type = r.action["type"]?.jsonPrimitive?.content
            SiftCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("${r.position}", color = Ink.text3, style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(end = 10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(r.name, color = Ink.text, style = MaterialTheme.typography.titleSmall)
                        Text(
                            "${r.hitCount} hits" + (r.lastHitAt?.let { " · last ${relativeTime(it)}" } ?: "") + (if (r.exceptions != null) " · with exceptions" else ""),
                            color = Ink.text3, style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    Switch(
                        checked = r.enabled,
                        onCheckedChange = { on ->
                            scope.launch {
                                try {
                                    Api.get(context).updateRule(r.id, RuleIn(r.name, on, r.conditions, r.action, r.exceptions, r.accountScope))
                                    load()
                                } catch (t: Throwable) { error = t.userMessage() }
                            }
                        },
                        colors = SwitchDefaults.colors(checkedTrackColor = Ink.signal, checkedThumbColor = Ink.signalInk, uncheckedTrackColor = Ink.line2),
                    )
                }
                Row(Modifier.padding(top = 8.dp)) { Tag(actionLabel(type), Ink.tier(actionTier(type))) }
            }
        }
    }
}
