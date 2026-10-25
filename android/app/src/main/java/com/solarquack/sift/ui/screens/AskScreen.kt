package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.AskIn
import com.solarquack.sift.data.AskLinkDto
import com.solarquack.sift.data.AskResultDto
import com.solarquack.sift.data.AskRunDto
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.fullTime
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch

private val EXAMPLES = listOf(
    "Make a group Internships for internship offers and add old ones too",
    "New mail from Nvidia goes to the Nvidia folder and a group Nvidia updates",
    "What's due this week?",
    "Draft a reply to Riya saying Thursday 4 pm works",
)

/** Ask Sift (backend app/assistant.py): anything the app can do, in plain words. Each request is
 * one small AI call that plans steps over the app's own actions. Plans that only look things up
 * run at once; plans that change anything wait for Run (steps that change Gmail say so). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun AskScreen(onBack: () -> Unit, onOpenMail: (String) -> Unit, onOpenLink: (AskLinkDto) -> Unit, onRuleDraft: (com.solarquack.sift.data.RuleDraft) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var runs by remember { mutableStateOf<List<AskRunDto>>(emptyList()) }
    var text by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf<String?>(null) }  // "ask" or a run id
    var error by remember { mutableStateOf<String?>(null) }
    val list = rememberLazyListState()

    LaunchedEffect(Unit) { runCatching { runs = Api.get(context).askRuns().take(8).reversed() } }
    LaunchedEffect(runs.size, busy) { if (runs.isNotEmpty()) list.animateScrollToItem(runs.size) }

    fun replace(r: AskRunDto) { runs = runs.map { if (it.id == r.id) r else it } }
    fun ask(words: String = text) {
        val t = words.trim()
        if (t.isEmpty() || busy != null) return
        busy = "ask"; error = null
        scope.launch {
            try { runs = (runs + Api.get(context).ask(AskIn(t))).takeLast(8); text = "" } catch (e: Throwable) { error = e.userMessage() } finally { busy = null }
        }
    }

    Column(Modifier.fillMaxSize().background(Ink.bg).imePadding()) {
        Row(Modifier.fillMaxWidth().padding(start = 8.dp, end = 14.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("‹ Back", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(10.dp))
        }
        Row(Modifier.padding(start = 18.dp, end = 18.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("✦", color = Ink.signal, style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(end = 8.dp))
            Text("Ask Sift", style = MaterialTheme.typography.headlineMedium, color = Ink.text)
        }
        Text("Anything the app can do, in plain words. You see what it touches and the tokens first; changes wait for your OK.", color = Ink.text3, style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(horizontal = 18.dp))

        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = list, contentPadding = PaddingValues(start = 14.dp, end = 14.dp, top = 14.dp, bottom = 14.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)) {
            if (runs.isEmpty() && busy == null) item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Tell Sift what to do, like you'd tell a person. Each request is one small AI call with your own key.",
                        color = Ink.text2, style = MaterialTheme.typography.bodyMedium)
                    EXAMPLES.forEach { x ->
                        Text(x, color = Ink.text, style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.fillMaxWidth().border(1.dp, Ink.line2, Radius.md).clickable { ask(x) }.padding(horizontal = 12.dp, vertical = 10.dp))
                    }
                }
            }
            items(runs, key = { it.id }) { r ->
                RunCard(r, busy == r.id,
                    onRun = { busy = r.id; scope.launch { try { replace(Api.get(context).runPlan(r.id)); com.solarquack.sift.data.LiveEvents.changed() } catch (e: Throwable) { error = e.userMessage() } finally { busy = null } } },
                    onCancel = { scope.launch { try { replace(Api.get(context).cancelPlan(r.id)) } catch (e: Throwable) { error = e.userMessage() } } },
                    onOpenMail = onOpenMail, onOpenLink = onOpenLink, onRuleDraft = onRuleDraft)
            }
            if (busy == "ask") item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(8.dp).background(Ink.signal, Radius.xs))
                    Text("  Planning…", color = Ink.text3, style = MaterialTheme.typography.bodyMedium)
                }
            }
            error?.let { item { Banner(it, Ink.urgent) } }
        }

        Row(Modifier.fillMaxWidth().background(Ink.bg).padding(start = 14.dp, end = 14.dp, top = 8.dp, bottom = 12.dp), verticalAlignment = Alignment.Bottom) {
            OutlinedTextField(
                value = text, onValueChange = { text = it.take(600) }, placeholder = { Text("e.g. make timelines from Placements → Nvidia", color = Ink.text3) },
                modifier = Modifier.weight(1f), shape = Radius.md, maxLines = 4,
                colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Ink.signal, unfocusedBorderColor = Ink.line2, cursorColor = Ink.signal,
                    focusedContainerColor = Ink.bg2, unfocusedContainerColor = Ink.bg2, focusedTextColor = Ink.text, unfocusedTextColor = Ink.text),
            )
            PrimaryButton("Ask", Modifier.padding(start = 8.dp), enabled = text.isNotBlank() && busy == null) { ask() }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RunCard(r: AskRunDto, busy: Boolean, onRun: () -> Unit, onCancel: () -> Unit, onOpenMail: (String) -> Unit,
                    onOpenLink: (AskLinkDto) -> Unit, onRuleDraft: (com.solarquack.sift.data.RuleDraft) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
            Text(r.text, color = Ink.text, style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.background(Ink.surface2, Radius.lg).border(1.dp, Ink.line2, Radius.lg).padding(horizontal = 14.dp, vertical = 10.dp))
        }
        Column(Modifier.fillMaxWidth().background(Ink.surface, Radius.lg).border(1.dp, Ink.line2, Radius.lg).padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            r.reply?.takeIf { it.isNotBlank() }?.let { Text(it, color = Ink.text, style = MaterialTheme.typography.bodyMedium) }
            r.steps.forEachIndexed { i, s ->
                val res = r.results.getOrNull(i)
                val edge = when { s.error != null || res?.ok == false -> Ink.urgent.copy(alpha = 0.45f); res?.ok == true -> Ink.signal.copy(alpha = 0.4f); else -> Ink.line }
                Column(Modifier.fillMaxWidth().background(Ink.bg, Radius.md).border(1.dp, edge, Radius.md).padding(10.dp)) {
                    Row(verticalAlignment = Alignment.Top) {
                        Text("${i + 1}", color = Ink.text2, style = MaterialTheme.typography.labelMedium,
                            modifier = Modifier.background(Ink.surface2, Radius.xs).padding(horizontal = 7.dp, vertical = 2.dp))
                        Text(s.preview ?: s.action, color = Ink.text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f).padding(start = 10.dp))
                        if (s.kind == "gmail") Tag("Gmail", Ink.warn)
                    }
                    if (s.error == null && s.tokens > 0) Text("~${"%,d".format(s.tokens)} tokens when run", color = Ink.warn,
                        style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(start = 30.dp, top = 4.dp))
                    if (s.error == null) s.targets.forEach { t ->
                        Text("→ $t", color = Ink.text3, style = MaterialTheme.typography.bodySmall, maxLines = 1,
                            overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis, modifier = Modifier.padding(start = 30.dp, top = 2.dp))
                    }
                    s.error?.let { Text("Can't do this step: $it", color = Ink.urgent, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(start = 30.dp, top = 4.dp)) }
                    res?.let { ResultBlock(it, onOpenMail, onOpenLink, onRuleDraft) }
                }
            }
            if (r.needsConfirm && r.estimate > 0) Text("Running may use about ${"%,d".format(r.estimate)} more tokens", color = Ink.warn,
                style = MaterialTheme.typography.bodySmall)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (r.needsConfirm) {
                    PrimaryButton(if (busy) "Running…" else if (r.changesGmail) "Run, with Gmail changes" else "Run", enabled = !busy, onClick = onRun)
                    GhostButton("Cancel", enabled = !busy, onClick = onCancel)
                }
                if (r.status == "cancelled") Text("Cancelled. Nothing changed.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            }
            Text("%,d tokens used".format(r.tokens), color = Ink.text3, style = MaterialTheme.typography.labelSmall, modifier = Modifier.align(Alignment.End))
        }
    }
}

@Composable
private fun ResultBlock(res: AskResultDto, onOpenMail: (String) -> Unit, onOpenLink: (AskLinkDto) -> Unit, onRuleDraft: (com.solarquack.sift.data.RuleDraft) -> Unit) {
    Column(Modifier.padding(start = 30.dp, top = 6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text((if (res.ok) "✓ " else "✕ ") + res.text, color = Ink.text2, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
            val link = res.link
            if (link != null && (link.page != "rule_draft" || res.ruleDraft != null)) {
                Text(when (link.page) { "rule_draft" -> "Review rule"; "draft" -> "Open draft"; else -> "Open" }, color = Ink.signal, style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.clickable { if (link.page == "rule_draft") res.ruleDraft?.let(onRuleDraft) else onOpenLink(link) }.padding(horizontal = 6.dp, vertical = 6.dp))
            }
        }
        res.mail?.take(12)?.forEach { m ->
            Column(Modifier.fillMaxWidth().clickable { onOpenMail(m.id) }.padding(vertical = 6.dp)) {
                Text(m.senderName ?: m.sender ?: "", color = Ink.text, style = MaterialTheme.typography.labelLarge.copy(fontWeight = if (m.unread) FontWeight.Bold else FontWeight.Medium))
                Text(m.summary ?: m.subject ?: "", color = Ink.text2, style = MaterialTheme.typography.bodySmall, maxLines = 2)
            }
        }
        res.items?.forEach { x ->
            Text("• ${x.name}" + (x.detail?.let { " · $it" } ?: ""), color = Ink.signal, style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.clickable { onOpenLink(AskLinkDto(x.page, x.id)) }.padding(vertical = 3.dp))
        }
        res.todos?.forEach { t -> Text("• ${t.title}" + (t.dueAt?.let { " · due ${fullTime(it)}" } ?: ""), color = Ink.text2, style = MaterialTheme.typography.bodySmall) }
        res.timelines?.forEach { o ->
            Text("• ${o.company}" + (o.last?.let { " · $it" } ?: ""), color = Ink.signal, style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.clickable { onOpenLink(AskLinkDto("opportunity", o.id)) }.padding(vertical = 3.dp))
        }
        res.timeline?.forEach { e -> Text("• ${e.kind}: ${e.title ?: e.summary ?: ""}" + (e.occurredAt?.let { " · ${fullTime(it)}" } ?: ""), color = Ink.text2, style = MaterialTheme.typography.bodySmall) }
    }
}
