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
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
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
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject

private val AI_FEATURES = "AI classification, deadlines and links, plain-English rules, company matching, summaries, reply drafts"

@SuppressLint("BatteryLife") // a personal mail notifier; the user confirms in a system dialog
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun SettingsScreen(onSignedOut: () -> Unit, onSilenced: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var ai by remember { mutableStateOf<AiStatus?>(null) }
    var settings by remember { mutableStateOf<SettingsDto?>(null) }
    var provider by remember { mutableStateOf("gemini") }
    var model by remember { mutableStateOf("") }
    var baseUrl by remember { mutableStateOf("") }
    var key by remember { mutableStateOf("") }
    var enableFallback by remember { mutableStateOf(false) }
    var fallbackProvider by remember { mutableStateOf("ollama") }
    var fallbackModel by remember { mutableStateOf("") }
    var fallbackBaseUrl by remember { mutableStateOf("") }
    var fallbackKey by remember { mutableStateOf("") }
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
            ai = api.ai().also {
                if (model.isBlank()) model = it.model ?: it.suggestedModel ?: ""
                if (it.provider != null) provider = it.provider
                if (it.baseUrl != null) baseUrl = it.baseUrl
                if (it.fallbackProvider != null) {
                    enableFallback = true
                    fallbackProvider = it.fallbackProvider
                    if (it.fallbackModel != null) fallbackModel = it.fallbackModel
                    if (it.fallbackBaseUrl != null) fallbackBaseUrl = it.fallbackBaseUrl
                }
            }
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
        SiftCard {
            Text("App size", color = Ink.text, style = MaterialTheme.typography.titleSmall)
            Text("Text, buttons and spacing, on top of your phone's own font size.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            androidx.compose.foundation.layout.FlowRow(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                com.solarquack.sift.ui.theme.UiScale.CHOICES.forEach { (name, scale) ->
                    com.solarquack.sift.ui.Chip(name, kotlin.math.abs(com.solarquack.sift.ui.theme.UiScale.value - scale) < 0.001f) {
                        com.solarquack.sift.ui.theme.UiScale.value = scale; Session.setUiScale(context, scale)
                    }
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        var rememberTabs by remember { mutableStateOf(Session.rememberTabs(context)) }
        SiftCard {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Remember where I was in each tab", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                    Text(if (rememberTabs) "Coming back to a tab shows what you had open there." else "A tab always opens at its top, e.g. Feed shows the list.",
                        color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                }
                com.solarquack.sift.ui.SiftSwitch(checked = rememberTabs, onCheckedChange = { rememberTabs = it; Session.setRememberTabs(context, it) })
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
            a?.keyLast4?.let {
                val p = a.provider ?: "Gemini"
                val b = if (a.baseUrl != null) " · ${a.baseUrl}" else ""
                val fb = if (a.fallbackProvider != null) " · Fallback: ${a.fallbackProvider}" else ""
                Text("$p · ${a.model} · key ••••$it$b$fb", color = Ink.text2, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp))
            }
            a?.takeIf { it.aiEnabled }?.let { Text("${it.tokensToday} of ${it.dailyTokenCap} tokens used today", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp)) }
            settings?.let { s ->
                var cap by remember(s.dailyTokenCap) { mutableStateOf(s.dailyTokenCap.toString()) }
                Spacer(Modifier.height(12.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.weight(1f)) { Field(cap, { cap = it.filter(Char::isDigit).take(8) }, "Daily token limit", keyboard = androidx.compose.ui.text.input.KeyboardType.Number) }
                    val n = cap.toIntOrNull()
                    if (n != null && n != s.dailyTokenCap) {
                        Spacer(Modifier.width(8.dp))
                        PrimaryButton("Save") { patch("daily_token_cap", n) }
                    }
                }
                Text("AI stops for the day at this many tokens; mail still arrives as normal priority.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
            }
            Spacer(Modifier.height(12.dp))
            Text("AI Provider", color = Ink.text2, style = MaterialTheme.typography.labelSmall)
            Spacer(Modifier.height(4.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("gemini" to "Gemini", "ollama" to "Ollama", "openai_compatible" to "OpenAI-compat").forEach { (id, label) ->
                    com.solarquack.sift.ui.Chip(label, provider == id) {
                        provider = id
                        if (model.isBlank()) {
                            model = if (id == "ollama") "llama3.2" else if (id == "openai_compatible") "gpt-4o-mini" else "gemini-2.5-flash"
                        }
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            Field(model, { model = it }, "Model ID", mono = true)
            if (provider == "ollama" || provider == "openai_compatible") {
                Spacer(Modifier.height(8.dp))
                Field(baseUrl, { baseUrl = it }, if (provider == "ollama") "Base URL (default: http://localhost:11434/v1)" else "Base URL (e.g. https://api.openai.com/v1)", mono = true)
            }
            Spacer(Modifier.height(8.dp))
            Field(key, { key = it }, if (a?.keyLast4 != null) "Replace API key" else if (provider == "ollama") "Ollama API key (optional)" else "API key", password = true, mono = true)
            Text(if (provider == "ollama") "Local Ollama requires no key. Base URL defaults to http://localhost:11434/v1." else "Stored encrypted on your server and never shown again.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))

            Spacer(Modifier.height(14.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Fallback LLM Provider", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                    Text("Failover on rate limits (429) or transient errors", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                }
                com.solarquack.sift.ui.SiftSwitch(checked = enableFallback, onCheckedChange = { enableFallback = it })
            }
            if (enableFallback) {
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("ollama" to "Ollama", "openai_compatible" to "OpenAI-compat", "gemini" to "Gemini").forEach { (id, label) ->
                        com.solarquack.sift.ui.Chip(label, fallbackProvider == id) { fallbackProvider = id }
                    }
                }
                Spacer(Modifier.height(6.dp))
                Field(fallbackModel, { fallbackModel = it }, "Fallback Model ID (e.g. llama3.2)", mono = true)
                if (fallbackProvider == "ollama" || fallbackProvider == "openai_compatible") {
                    Spacer(Modifier.height(6.dp))
                    Field(fallbackBaseUrl, { fallbackBaseUrl = it }, "Fallback Base URL", mono = true)
                }
                Spacer(Modifier.height(6.dp))
                Field(fallbackKey, { fallbackKey = it }, if (a?.fallbackKeyLast4 != null) "Replace Fallback API key" else "Fallback API key (optional for Ollama)", password = true, mono = true)
            }

            info?.let { Text(it, color = Ink.signal, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp)) }
            Spacer(Modifier.height(10.dp))
            val canSave = !busy && (provider == "ollama" || key.length >= 10 || a?.keyLast4 != null) && (model.isNotBlank() || a?.model != null)
            androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                PrimaryButton(if (busy) "Checking…" else "Save and test", enabled = canSave) {
                    busy = true; info = null
                    scope.launch {
                        try {
                            val effModel = model.trim().ifBlank { if (provider == "ollama") "llama3.2" else if (provider == "openai_compatible") "gpt-4o-mini" else "gemini-2.5-flash" }
                            val apiKey = key.trim().ifBlank { if (provider == "ollama") "ollama-local" else null }
                            val fModel = if (enableFallback) fallbackModel.trim().ifBlank { if (fallbackProvider == "ollama") "llama3.2" else if (fallbackProvider == "openai_compatible") "gpt-4o-mini" else "gemini-2.5-flash" } else null
                            val fKey = if (enableFallback) fallbackKey.trim().ifBlank { if (fallbackProvider == "ollama") "ollama-local" else null } else null
                            ai = Api.get(context).saveKey(KeyIn(
                                provider = provider,
                                model = effModel,
                                apiKey = apiKey,
                                baseUrl = baseUrl.trim().ifBlank { null },
                                fallbackProvider = if (enableFallback) fallbackProvider else null,
                                fallbackModel = fModel,
                                fallbackBaseUrl = if (enableFallback) fallbackBaseUrl.trim().ifBlank { null } else null,
                                fallbackApiKey = fKey,
                            ))
                            key = ""
                            fallbackKey = ""
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
                    com.solarquack.sift.ui.SiftSwitch(checked = s.resendUrgent, onCheckedChange = { patch("resend_urgent", it) })
                }
                Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(2, 5, 10).forEach { m -> com.solarquack.sift.ui.Chip("$m min", s.resendAfterMinutes == m) { patch("resend_after_minutes", m) } }
                }

                Spacer(Modifier.height(14.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Quiet hours", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                        Text("Silence non-urgent notifications during scheduled hours", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                    }
                    com.solarquack.sift.ui.SiftSwitch(checked = s.quietHoursEnabled, onCheckedChange = { patch("quiet_hours_enabled", it) })
                }
                if (s.quietHoursEnabled) {
                    Spacer(Modifier.height(8.dp))
                    var startVal by remember(s.quietHoursStart) { mutableStateOf(s.quietHoursStart) }
                    var endVal by remember(s.quietHoursEnd) { mutableStateOf(s.quietHoursEnd) }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.weight(1f)) {
                            Field(startVal, { startVal = it; if (it.matches(Regex("^\\d{2}:\\d{2}$"))) patch("quiet_hours_start", it) }, "Start (HH:MM)")
                        }
                        Text("to", color = Ink.text3, style = MaterialTheme.typography.bodyMedium)
                        Box(Modifier.weight(1f)) {
                            Field(endVal, { endVal = it; if (it.matches(Regex("^\\d{2}:\\d{2}$"))) patch("quiet_hours_end", it) }, "End (HH:MM)")
                        }
                    }
                }

                Spacer(Modifier.height(14.dp))
                Text("Mute notification categories", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                Text("Silence non-urgent notifications for selected categories", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                androidx.compose.foundation.layout.FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    val allCats = listOf("fyi" to "FYI", "placement_announcement" to "Placement drive", "registration" to "Registration", "assessment_link" to "Online test", "interview" to "Interview", "result" to "Result", "recruiter" to "Recruiter", "action_needed" to "Needs action")
                    allCats.forEach { (catKey, label) ->
                        val muted = s.mutedCategories.contains(catKey)
                        com.solarquack.sift.ui.Chip(label, muted) {
                            val next = if (muted) s.mutedCategories - catKey else s.mutedCategories + catKey
                            scope.launch {
                                try {
                                    val arr = buildJsonArray { next.forEach { add(JsonPrimitive(it)) } }
                                    settings = Api.get(context).patchSettings(buildJsonObject { put("muted_categories", arr) })
                                } catch (t: Throwable) { error = t.userMessage() }
                            }
                        }
                    }
                }
            }
        }

        settings?.let { s ->
            SectionLabel("Writing mail")
            SiftCard {
                var selectedAccountId by remember { mutableStateOf<String?>(null) }
                var accountSettings by remember { mutableStateOf<SettingsDto?>(null) }
                var accountsList by remember { mutableStateOf<List<com.solarquack.sift.data.AccountDto>>(emptyList()) }

                LaunchedEffect(Unit) {
                    runCatching { accountsList = Api.get(context).accounts() }
                }
                LaunchedEffect(selectedAccountId) {
                    if (selectedAccountId != null) {
                        runCatching { accountSettings = Api.get(context).settings(selectedAccountId) }
                    } else {
                        accountSettings = null
                    }
                }

                val activeSettings = accountSettings ?: s
                var name by remember(activeSettings.senderName, selectedAccountId) { mutableStateOf(activeSettings.senderName) }
                var sig by remember(activeSettings.signature, selectedAccountId) { mutableStateOf(activeSettings.signature) }

                if (accountsList.isNotEmpty()) {
                    Text("Profile for", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                    Text("Customize name and signature per account, or default for all", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                    androidx.compose.foundation.layout.FlowRow(Modifier.padding(top = 6.dp, bottom = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        com.solarquack.sift.ui.Chip("All accounts (default)", selectedAccountId == null) { selectedAccountId = null }
                        accountsList.forEach { a ->
                            com.solarquack.sift.ui.Chip(a.email, selectedAccountId == a.id) { selectedAccountId = a.id }
                        }
                    }
                }

                com.solarquack.sift.ui.Field(name, { name = it.take(100) }, "Your name", placeholder = if (selectedAccountId != null && s.senderName.isNotBlank()) s.senderName else "Shown next to your address")
                Spacer(Modifier.height(8.dp))
                androidx.compose.material3.OutlinedTextField(
                    value = sig, onValueChange = { sig = it.take(2000) }, label = { Text("Signature") }, minLines = 3, maxLines = 8,
                    placeholder = { if (selectedAccountId != null && s.signature.isNotBlank()) Text(s.signature) },
                    modifier = Modifier.fillMaxWidth(), shape = com.solarquack.sift.ui.theme.Radius.md,
                    colors = androidx.compose.material3.OutlinedTextFieldDefaults.colors(focusedBorderColor = Ink.signal, unfocusedBorderColor = Ink.line2,
                        focusedLabelColor = Ink.signal, unfocusedLabelColor = Ink.text3, cursorColor = Ink.signal, focusedContainerColor = Ink.bg2, unfocusedContainerColor = Ink.bg2),
                )
                if (name.trim() != activeSettings.senderName || sig != activeSettings.signature) {
                    Spacer(Modifier.height(8.dp))
                    PrimaryButton("Save") {
                        scope.launch {
                            try {
                                val patchBody = buildJsonObject { put("sender_name", JsonPrimitive(name.trim())); put("signature", JsonPrimitive(sig)) }
                                val updated = Api.get(context).patchSettings(patchBody, accountId = selectedAccountId)
                                if (selectedAccountId != null) accountSettings = updated else settings = updated
                            } catch (t: Throwable) { error = t.userMessage() }
                        }
                    }
                }
                Text("Undo send", color = Ink.text, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 14.dp))
                Text("How long you can take a mail back after pressing Send", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                androidx.compose.foundation.layout.FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(0, 5, 10, 20, 30).forEach { n -> com.solarquack.sift.ui.Chip(if (n == 0) "Off" else "$n s", s.undoSendSeconds == n) { patch("undo_send_seconds", n) } }
                }
            }
            Spacer(Modifier.height(8.dp))
        }

        SectionLabel("Mail")
        settings?.let { s ->
            SiftCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Load images in mail automatically", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                        Text("Through your Sift server, so senders never see your address.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                    }
                    com.solarquack.sift.ui.SiftSwitch(checked = s.loadRemoteImages, onCheckedChange = { patch("load_remote_images", it) })
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
                    com.solarquack.sift.ui.SiftSwitch(checked = g.groupingEnabled == "yes", onCheckedChange = { on ->
                        scope.launch {
                            try { grouping = Api.get(context).answerGrouping(com.solarquack.sift.data.AnswerIn(if (on) "yes" else "no")) } catch (t: Throwable) { error = t.userMessage() }
                        }
                    })
                }
            }
            Spacer(Modifier.height(8.dp))
        }
        GhostButton("Silenced mail", Modifier.fillMaxWidth(), onClick = onSilenced)

        SectionLabel("Saved on this device")
        SiftCard {
            // what the phone kept so Sift still opens while the server is off (data/Offline.kt)
            var saved by remember { mutableStateOf(com.solarquack.sift.data.Offline.size(context)) }
            val mb = saved.first / 1048576.0
            Text(if (mb < 0.1) "${maxOf(1, (saved.first / 1024).toInt())} KB · ${saved.second} items" else String.format(java.util.Locale.US, "%.1f MB · %d items", mb, saved.second),
                color = Ink.text, style = MaterialTheme.typography.titleSmall)
            Text("Mail and pages you already opened, so Sift still opens when the server is off. Clearing changes nothing in Gmail or on the server.",
                color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(10.dp))
            GhostButton("Clear saved data", enabled = saved.second > 0) {
                com.solarquack.sift.data.Offline.clear(context)
                android.webkit.WebView(context).clearCache(true)
                saved = com.solarquack.sift.data.Offline.size(context)
                info = "Cleared what this phone saved."
            }
        }

        SectionLabel("Server")
        Text("${Session.email(context) ?: ""} · ${Session.server(context)}", color = Ink.text2, style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            GhostButton("Re-register phone") { scope.launch { try { Push.registerDevice(context); info = "Phone registered." } catch (t: Throwable) { error = t.userMessage() } } }
            GhostButton("Sign out", color = Ink.urgent) {
                // signing out leaves no mail behind on the phone
                com.solarquack.sift.data.Offline.clear(context); android.webkit.WebView(context).clearCache(true)
                Session.signOut(context); onSignedOut()
            }
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
