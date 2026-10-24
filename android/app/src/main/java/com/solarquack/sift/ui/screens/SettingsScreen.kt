package com.solarquack.sift.ui.screens

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
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
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.solarquack.sift.data.AiStatus
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.KeyIn
import com.solarquack.sift.data.Push
import com.solarquack.sift.data.Session
import com.solarquack.sift.data.SettingsDto
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Field
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.SectionLabel
import com.solarquack.sift.ui.SiftCard
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.theme.Ink
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

private val AI_FEATURES = "AI classification, deadlines and links, plain-English rules, company matching, summaries, reply drafts"

@SuppressLint("BatteryLife") // a personal mail notifier; the user confirms in a system dialog
@Composable
fun SettingsScreen(onSignedOut: () -> Unit, onSilenced: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var ai by remember { mutableStateOf<AiStatus?>(null) }
    var settings by remember { mutableStateOf<SettingsDto?>(null) }
    var model by remember { mutableStateOf("") }
    var key by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var info by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var tick by remember { mutableIntStateOf(0) }
    var grouping by remember { mutableStateOf<com.solarquack.sift.data.GroupingStatus?>(null) }

    // re-check permissions when returning from system settings
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle) {
        lifecycle.addObserver(LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_RESUME) tick++ })
    }
    val askNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { tick++ }
    val notificationsOk = remember(tick) {
        Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
    }
    val batteryOk = remember(tick) { context.getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(context.packageName) }

    fun load() = scope.launch {
        try {
            val api = Api.get(context)
            ai = api.ai().also { if (model.isBlank()) model = it.model ?: it.suggestedModel ?: "" }
            settings = api.settings()
            grouping = runCatching { api.grouping() }.getOrNull()
            error = null
        } catch (t: Throwable) { error = t.userMessage() }
    }
    LaunchedEffect(Unit) { load() }

    fun patch(name: String, value: Any) = scope.launch {
        try {
            settings = Api.get(context).patchSettings(buildJsonObject {
                put(name, when (value) { is Boolean -> JsonPrimitive(value); is Int -> JsonPrimitive(value); else -> JsonPrimitive(value.toString()) })
            })
        } catch (t: Throwable) { error = t.userMessage() }
    }

    Column(Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).imePadding().padding(18.dp)) {
        Text("Settings", style = MaterialTheme.typography.headlineMedium, color = Ink.text)
        error?.let { Spacer(Modifier.height(8.dp)); Banner(it, Ink.urgent, "Retry") { load() } }

        SectionLabel("This phone")
        var rememberTabs by remember { mutableStateOf(Session.rememberTabs(context)) }
        SiftCard {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Remember where I was in each tab", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                    Text(if (rememberTabs) "Coming back to a tab shows what you had open there." else "A tab always opens at its top, e.g. Feed shows the list.",
                        color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                }
                Switch(checked = rememberTabs, onCheckedChange = { rememberTabs = it; Session.setRememberTabs(context, it) },
                    colors = SwitchDefaults.colors(checkedTrackColor = Ink.signal, checkedThumbColor = Ink.signalInk, uncheckedTrackColor = Ink.line2))
            }
        }
        Spacer(Modifier.height(8.dp))
        StatusRow("Notifications", if (notificationsOk) "Granted" else "Not granted", notificationsOk) {
            if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        Spacer(Modifier.height(8.dp))
        StatusRow("Battery optimization", if (batteryOk) "Exempt" else "Restricted: notifications may be delayed", batteryOk) {
            context.startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${context.packageName}")))
        }
        Session.lastDelay(context)?.let {
            Text("Last push took ${it} ms from server to phone.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
        }

        SectionLabel("AI provider · your own key")
        SiftCard {
            val a = ai
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(if (a?.aiEnabled == true) "AI on" else "AI off", color = Ink.text, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                a?.let {
                    Tag(
                        when (it.status) { "missing" -> "No key"; "quota_exceeded" -> "Quota exceeded"; else -> it.status },
                        when (it.status) { "valid" -> Ink.signal; "missing" -> Ink.text2; "quota_exceeded" -> Ink.warn; else -> Ink.urgent },
                    )
                }
            }
            if (a != null && !a.aiEnabled) {
                Text("Add an API key to enable: $AI_FEATURES. Everything else works without one, and unhandled mail arrives as normal priority.",
                    color = Ink.warn, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
            }
            a?.keyLast4?.let { Text("Gemini · ${a.model} · key ••••$it", color = Ink.text2, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp)) }
            a?.takeIf { it.aiEnabled }?.let { Text("${it.tokensToday} of ${it.dailyTokenCap} tokens used today", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp)) }
            Spacer(Modifier.height(12.dp))
            Field(model, { model = it }, "Model ID", mono = true)
            Spacer(Modifier.height(8.dp))
            Field(key, { key = it }, if (a?.keyLast4 != null) "Replace API key" else "Gemini API key", password = true, mono = true)
            Text("Stored encrypted on your server and never shown again. Get a key at aistudio.google.com.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
            info?.let { Text(it, color = Ink.signal, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp)) }
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PrimaryButton(if (busy) "Checking…" else "Save and test", enabled = !busy && key.length >= 10 && model.isNotBlank()) {
                    busy = true; info = null
                    scope.launch {
                        try {
                            ai = Api.get(context).saveKey(KeyIn("gemini", model.trim(), key.trim()))
                            key = ""
                            info = when (ai?.status) { "valid" -> "Key works. AI is on."; "invalid" -> "The key was rejected."; "quota_exceeded" -> "Key saved, but its quota is used up."; else -> "Saved; could not verify yet." }
                        } catch (t: Throwable) { error = t.userMessage() } finally { busy = false }
                    }
                }
                if (a?.keyLast4 != null) {
                    GhostButton("Test") { scope.launch { try { ai = Api.get(context).testKey() } catch (t: Throwable) { error = t.userMessage() } } }
                    GhostButton("Remove", color = Ink.urgent) { scope.launch { try { Api.get(context).removeKey(); load() } catch (t: Throwable) { error = t.userMessage() } } }
                }
            }
        }

        SectionLabel("Notifications")
        settings?.let { s ->
            SiftCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Re-send urgent until delivered", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                        Text("Every ${s.resendAfterMinutes} min, up to ${s.resendLimit} times", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                    }
                    Switch(checked = s.resendUrgent, onCheckedChange = { patch("resend_urgent", it) },
                        colors = SwitchDefaults.colors(checkedTrackColor = Ink.signal, checkedThumbColor = Ink.signalInk, uncheckedTrackColor = Ink.line2))
                }
                Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(2, 5, 10).forEach { m -> com.solarquack.sift.ui.Chip("$m min", s.resendAfterMinutes == m) { patch("resend_after_minutes", m) } }
                }
            }
        }

        SectionLabel("Mail")
        settings?.let { s ->
            SiftCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Load images in mail automatically", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                        Text("Through your Sift server, so senders never see your address.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                    }
                    Switch(checked = s.loadRemoteImages, onCheckedChange = { patch("load_remote_images", it) },
                        colors = SwitchDefaults.colors(checkedTrackColor = Ink.signal, checkedThumbColor = Ink.signalInk, uncheckedTrackColor = Ink.line2))
                }
            }
            Spacer(Modifier.height(8.dp))
        }
        grouping?.let { g ->
            SiftCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Group similar emails", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                        Text("Only changes how mail is shown. Urgent mail stays on its own row; notifications don't change.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                    }
                    Switch(checked = g.groupingEnabled == "yes", onCheckedChange = { on ->
                        scope.launch {
                            try { grouping = Api.get(context).answerGrouping(com.solarquack.sift.data.AnswerIn(if (on) "yes" else "no")) } catch (t: Throwable) { error = t.userMessage() }
                        }
                    }, colors = SwitchDefaults.colors(checkedTrackColor = Ink.signal, checkedThumbColor = Ink.signalInk, uncheckedTrackColor = Ink.line2))
                }
            }
            Spacer(Modifier.height(8.dp))
        }
        GhostButton("Silenced mail", Modifier.fillMaxWidth(), onClick = onSilenced)

        SectionLabel("Server")
        Text("${Session.email(context) ?: ""} · ${Session.server(context)}", color = Ink.text2, style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            GhostButton("Re-register phone") { scope.launch { try { Push.registerDevice(context); info = "Phone registered." } catch (t: Throwable) { error = t.userMessage() } } }
            GhostButton("Sign out", color = Ink.urgent) { Session.signOut(context); onSignedOut() }
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun StatusRow(label: String, value: String, ok: Boolean, onFix: () -> Unit) {
    SiftCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(label, color = Ink.text, style = MaterialTheme.typography.titleSmall)
                Text(value, color = if (ok) Ink.signal else Ink.urgent, style = MaterialTheme.typography.bodySmall)
            }
            if (!ok) PrimaryButton("Fix", onClick = onFix)
        }
    }
}
