package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.ActionIn
import com.solarquack.sift.data.AiStatus
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.OrderIn
import com.solarquack.sift.data.RuleDto
import com.solarquack.sift.data.RuleIn
import com.solarquack.sift.data.SuggestionDto
import com.solarquack.sift.data.TextIn
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Field
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.SectionLabel
import com.solarquack.sift.ui.SiftCard
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.relativeTime
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
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
    "llm" -> "Ask AI"
    else -> type ?: ""
}

private fun originLabel(origin: String?) = when (origin) {
    "one_tap" -> "One tap"
    "english" -> "Plain English"
    "suggestion" -> "Suggested"
    "scan" -> "First scan"
    "starter" -> "Starter"
    else -> null
}

/** Rules (brief section 8): plain-English entry, repeat-template suggestions, ordered list. */
@Composable
fun RulesScreen(onEdit: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var rules by remember { mutableStateOf<List<RuleDto>>(emptyList()) }
    var suggestions by remember { mutableStateOf<List<SuggestionDto>>(emptyList()) }
    var ai by remember { mutableStateOf<AiStatus?>(null) }
    var sentence by remember { mutableStateOf("") }
    var drafting by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var folderRules by remember { mutableStateOf<List<com.solarquack.sift.data.FolderDto>>(emptyList()) }

    fun load() = scope.launch {
        try {
            val api = Api.get(context)
            rules = api.rules()
            folderRules = runCatching {
                fun flat(fs: List<com.solarquack.sift.data.FolderDto>): List<com.solarquack.sift.data.FolderDto> = fs.flatMap { listOf(it) + flat(it.children) }
                flat(api.folders().folders).filter { it.aiRule != null || it.autoSort != null }
            }.getOrDefault(emptyList())
            suggestions = runCatching { api.suggestions() }.getOrDefault(emptyList())
            ai = runCatching { api.ai() }.getOrNull()
            error = null
        } catch (t: Throwable) { error = t.userMessage() }
    }
    LaunchedEffect(Unit) { load() }

    fun move(index: Int, delta: Int) = scope.launch {
        val ids = rules.map { it.id }.toMutableList()
        val target = index + delta
        if (target !in ids.indices) return@launch
        ids.add(target, ids.removeAt(index))
        try { rules = Api.get(context).reorderRules(OrderIn(ids)) } catch (t: Throwable) { error = t.userMessage() }
    }

    Box(Modifier.fillMaxSize().background(Ink.bg)) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(start = 18.dp, end = 18.dp, top = 18.dp, bottom = 96.dp)) {
            Text("Rules", style = MaterialTheme.typography.headlineMedium, color = Ink.text)
            Text("Checked in order; the first match wins. Sender rules only match mail Gmail verified.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            error?.let { Spacer(Modifier.height(8.dp)); Banner(it, Ink.urgent, "Retry") { load() } }

            // folders that file or sort with the AI are rules too; they're changed on the folder
            if (folderRules.isNotEmpty()) {
                Spacer(Modifier.height(14.dp))
                SiftCard {
                    Text("Folder AI rules", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                    Text("Run after the AI reads a new mail. Change them on the folder (More → Folders → ✦ AI).", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                    folderRules.forEach { f ->
                        val parts = listOfNotNull(
                            f.aiRule?.let { r -> "files " + (r.categories.map { CATEGORY_LABELS[it] ?: it } + if (r.timeline) listOf("timeline mail") else emptyList()).joinToString(", ").lowercase() + " here" },
                            f.autoSort?.let { if (it == "ai") "sorts by “${f.autoSortInstruction}”" else "sorts into subfolders by $it" },
                        )
                        Text(f.name, color = Ink.text, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(top = 10.dp))
                        Text(parts.joinToString("; ").replaceFirstChar { it.uppercase() }, color = Ink.text2, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }

            // plain-English rule (needs the user's own key)
            val aiOn = ai?.aiEnabled == true
            Spacer(Modifier.height(14.dp))
            SiftCard {
                Text("Describe a rule", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                Column(Modifier.alpha(if (aiOn) 1f else 0.5f)) {
                    Spacer(Modifier.height(8.dp))
                    Field(sentence, { if (aiOn) sentence = it }, "Silence Swiggy offers but keep order updates")
                    Spacer(Modifier.height(8.dp))
                    PrimaryButton(if (drafting) "Drafting…" else "Draft rule", enabled = aiOn && !drafting && sentence.length >= 3) {
                        drafting = true
                        scope.launch {
                            try {
                                val r = Api.get(context).ruleFromText(TextIn(sentence.trim()))
                                RuleEditorSeed.clear()
                                RuleEditorSeed.draft = r.draft
                                RuleEditorSeed.origin = "english"
                                sentence = ""
                                onEdit()
                            } catch (t: Throwable) { error = t.userMessage() } finally { drafting = false }
                        }
                    }
                }
                if (!aiOn) Text("Add an API key to enable (Settings → AI provider). The rule editor below works without one.", color = Ink.warn, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
                else Text("Converted once by your AI key; afterwards it runs as a normal rule with no AI cost.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
            }

            if (suggestions.isNotEmpty()) {
                SectionLabel("Suggestions")
                suggestions.forEach { s ->
                    SiftCard(Modifier.padding(bottom = 8.dp), border = Ink.signal.copy(alpha = 0.25f)) {
                        Text("${s.count} similar mails from ${s.domain ?: s.sender}", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                        Text(s.sampleSubject ?: s.template ?: "", color = Ink.text2, style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            PrimaryButton("Silence") { scope.launch { try { Api.get(context).acceptSuggestion(s.id, ActionIn("silent")); load() } catch (t: Throwable) { error = t.userMessage() } } }
                            GhostButton("Digest") { scope.launch { try { Api.get(context).acceptSuggestion(s.id, ActionIn("digest")); load() } catch (t: Throwable) { error = t.userMessage() } } }
                            GhostButton("Keep", color = Ink.text2) { scope.launch { try { Api.get(context).dismissSuggestion(s.id); load() } catch (t: Throwable) { error = t.userMessage() } } }
                        }
                    }
                }
            }

            SectionLabel("Your rules")
            if (rules.isEmpty() && error == null) Text("No rules yet. Everything is classified automatically.", color = Ink.text3, style = MaterialTheme.typography.bodyMedium)
            rules.forEachIndexed { i, r ->
                val type = r.action["type"]?.jsonPrimitive?.content
                SiftCard(Modifier.padding(bottom = 8.dp).clickable { RuleEditorSeed.clear(); RuleEditorSeed.rule = r; onEdit() }) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text("▲", color = if (i > 0) Ink.text2 else Ink.line2, modifier = Modifier.clickable(enabled = i > 0) { move(i, -1) }.padding(4.dp).semantics { contentDescription = "Move up" })
                            Text("${i + 1}", color = Ink.text3, style = MaterialTheme.typography.labelMedium)
                            Text("▼", color = if (i < rules.lastIndex) Ink.text2 else Ink.line2, modifier = Modifier.clickable(enabled = i < rules.lastIndex) { move(i, 1) }.padding(4.dp).semantics { contentDescription = "Move down" })
                        }
                        Column(Modifier.weight(1f).padding(start = 10.dp)) {
                            Text(r.name, color = Ink.text, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            Text("${r.hitCount} hits" + (r.lastHitAt?.let { " · last ${relativeTime(it)}" } ?: "") + (if (r.exceptions != null) " · with exceptions" else ""),
                                color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                            Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                Tag(actionLabel(type), Ink.tier(actionTier(type)))
                                originLabel(r.origin)?.let { Tag(it) }
                            }
                        }
                        com.solarquack.sift.ui.SiftSwitch(
                            checked = r.enabled,
                            onCheckedChange = { on ->
                                scope.launch {
                                    try { Api.get(context).updateRule(r.id, RuleIn(r.name, on, r.conditions, r.action, r.exceptions, r.accountScope)); load() } catch (t: Throwable) { error = t.userMessage() }
                                }
                            }
                        )
                    }
                }
            }
        }
        com.solarquack.sift.ui.AddButton("New rule", Modifier.align(Alignment.BottomEnd)) { RuleEditorSeed.clear(); onEdit() }
    }
}
