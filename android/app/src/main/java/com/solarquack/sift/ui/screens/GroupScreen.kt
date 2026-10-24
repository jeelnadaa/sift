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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.AnswerIn
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.FolderIdIn
import com.solarquack.sift.data.GroupDto
import com.solarquack.sift.data.GroupPatch
import com.solarquack.sift.data.GroupRuleIn
import com.solarquack.sift.data.MessageIdIn
import com.solarquack.sift.data.PreferenceIn
import com.solarquack.sift.data.SplitIn
import com.solarquack.sift.data.TargetIn
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Avatar
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Field
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.relativeTime
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch

/** A stacked row for a group in the feed (mobile design: groups). */
@Composable
fun GroupRow(g: GroupDto, onClick: () -> Unit) {
    Box(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 6.dp).clickable(onClick = onClick)) {
        // two offset layers behind the card read as "a stack of mail"
        Box(Modifier.matchParentSize().padding(start = 10.dp, end = 10.dp, top = 8.dp).background(Ink.surface2.copy(alpha = 0.5f), Radius.lg))
        Box(Modifier.matchParentSize().padding(start = 5.dp, end = 5.dp, top = 4.dp).background(Ink.surface2, Radius.lg))
        Row(Modifier.fillMaxWidth().padding(bottom = 8.dp).background(Ink.surface, Radius.lg).border(1.dp, Ink.line2, Radius.lg).padding(12.dp),
            verticalAlignment = Alignment.Top) {
            Avatar(g.title, if (g.urgent > 0) Ink.urgent else null)
            Column(Modifier.weight(1f).padding(start = 10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(g.title, color = Ink.text, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        style = MaterialTheme.typography.titleSmall.copy(fontWeight = if (g.unread > 0) FontWeight.Bold else FontWeight.Medium),
                        modifier = Modifier.weight(1f, fill = false))
                    Tag("${g.count} mails")
                    if (g.muted) Tag("Muted")
                }
                Text(listOfNotNull(g.latestSender, g.latestSubject).joinToString(": "), color = Ink.text2, style = MaterialTheme.typography.bodyMedium,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                val bits = listOfNotNull(g.unread.takeIf { it > 0 }?.let { "$it unread" }, g.urgent.takeIf { it > 0 }?.let { "$it urgent" })
                if (bits.isNotEmpty()) Text(bits.joinToString(" · "), color = if (g.urgent > 0) Ink.urgent else Ink.signal, style = MaterialTheme.typography.bodySmall)
            }
            Text(relativeTime(g.receivedAt), color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(start = 8.dp, top = 2.dp))
        }
    }
}

/** First-open question (brief section 21). Dismissing counts as "not answered": asked again next open, 3 times at most. */
object GroupingPrompt { var askedThisOpen = false }

@Composable
fun GroupingPromptDialog(onAnswered: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    fun answer(a: String) = scope.launch {
        runCatching { Api.get(context).answerGrouping(AnswerIn(a)) }
        onAnswered(a)
    }
    AlertDialog(
        onDismissRequest = { answer("dismissed") },
        title = { Text("Group similar emails together?") },
        text = { Text("Grouping only changes how mail is displayed. Urgent mail still shows on its own and every notification still arrives. You can change this in Settings.", color = Ink.text2, style = MaterialTheme.typography.bodyMedium) },
        confirmButton = { PrimaryButton("Yes, group them") { answer("yes") } },
        dismissButton = { TextButton(onClick = { answer("no") }) { Text("No", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun GroupScreen(id: String, onBack: () -> Unit, onOpenMail: (String) -> Unit, onEditRule: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var g by remember { mutableStateOf<GroupDto?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var info by remember { mutableStateOf<String?>(null) }
    var renaming by remember { mutableStateOf(false) }
    var filing by remember { mutableStateOf<String?>(null) }  // "file" = file group, "rule" = file-like-this rule
    var merging by remember { mutableStateOf(false) }
    var selecting by remember { mutableStateOf(false) }
    var selected by remember { mutableStateOf(setOf<String>()) }

    fun load() = scope.launch {
        try { g = Api.get(context).group(id); error = null } catch (t: Throwable) { error = t.userMessage() }
    }
    fun run(done: String? = null, block: suspend () -> Unit) = scope.launch {
        try { block(); info = done; g = Api.get(context).group(id); error = null } catch (t: Throwable) { error = t.userMessage() }
    }
    fun ruleDraft(action: String, folderId: String? = null) = scope.launch {
        try {
            val r = Api.get(context).ruleFromGroup(id, GroupRuleIn(action, folderId))
            RuleEditorSeed.clear(); RuleEditorSeed.draft = r.draft; RuleEditorSeed.origin = "one_tap"; onEditRule()
        } catch (t: Throwable) { error = t.userMessage() }
    }
    LaunchedEffect(id) { load() }

    val group = g
    LazyColumn(Modifier.fillMaxSize().background(Ink.bg), contentPadding = PaddingValues(18.dp)) {
        item {
            Text("‹ Back", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(vertical = 6.dp))
            error?.let { Banner(it, Ink.urgent) }
        }
        if (group != null) {
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(group.title, style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.weight(1f).padding(vertical = 8.dp))
                    Text("Rename", color = Ink.signal, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable { renaming = true }.padding(6.dp))
                }
                Text("${group.count} mails · ${group.unread} unread" + if (group.urgent > 0) " · ${group.urgent} urgent" else "", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                Text("A group only changes how mail is shown. Nothing changes in Gmail.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Mute this group", color = Ink.text, style = MaterialTheme.typography.bodyMedium)
                        Text("New mail in it won't notify. Urgent mail still does.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                    }
                    Switch(group.muted, { on -> run { Api.get(context).editGroup(id, GroupPatch(muted = on)) } },
                        colors = SwitchDefaults.colors(checkedTrackColor = Ink.signal, checkedThumbColor = Ink.signalInk))
                }
                FlowRow(Modifier.padding(vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    GhostButton("File all in folder") { filing = "file" }
                    GhostButton("File mail like this…") { filing = "rule" }
                    GhostButton("Silence mail like this") { ruleDraft("silent") }
                    GhostButton(if (selecting) "Cancel split" else "Split") { selecting = !selecting; selected = emptySet() }
                    GhostButton("Merge into…") { merging = true }
                    group.items.firstOrNull()?.sender?.let { sender ->
                        GhostButton("Never group $sender") {
                            run("Mail from $sender won't be grouped") { Api.get(context).setGroupPreference(PreferenceIn(sender, "never")) }
                        }
                    }
                }
                if (selecting) Banner(
                    if (selected.isEmpty()) "Tap the mails to move into a new group." else "${selected.size} selected", Ink.signal,
                    if (selected.isNotEmpty()) "Split off" else null,
                ) {
                    run("Split into a new group") { Api.get(context).splitGroup(id, SplitIn(selected.toList())) }
                    selecting = false; selected = emptySet()
                }
                info?.let { Text(it, color = Ink.signal, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(bottom = 6.dp)) }
                HorizontalDivider(color = Ink.line)
            }
            items(group.items, key = { it.id }) { m ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (selecting) Text(if (m.id in selected) "☑" else "☐", color = Ink.signal, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(end = 8.dp))
                    Box(Modifier.weight(1f)) {
                        MailRow(m) { if (selecting) selected = if (m.id in selected) selected - m.id else selected + m.id else onOpenMail(m.id) }
                    }
                    if (!selecting) Text("Take out", color = Ink.text3, style = MaterialTheme.typography.labelMedium,
                        modifier = Modifier.clickable { run("Taken out of the group") { Api.get(context).removeFromGroup(id, MessageIdIn(m.id)) } }.padding(8.dp))
                }
            }
        }
    }

    if (renaming) group?.let { gr ->
        var title by remember { mutableStateOf(gr.title) }
        AlertDialog(
            onDismissRequest = { renaming = false },
            title = { Text("Rename group") },
            text = { Field(title, { title = it }, "Name") },
            confirmButton = { PrimaryButton("Save", enabled = title.isNotBlank()) { renaming = false; run { Api.get(context).editGroup(id, GroupPatch(title = title.trim())) } } },
            dismissButton = { TextButton(onClick = { renaming = false }) { Text("Cancel", color = Ink.text2) } },
            containerColor = Ink.surface, shape = Radius.xl,
        )
    }
    filing?.let { mode ->
        FolderPickerDialog(if (mode == "file") "File the whole group in…" else "File mail like this in…", null,
            note = if (mode == "rule") "Makes a rule: mail like this group's is classified as usual and filed there." else null,
            onDismiss = { filing = null }) { f ->
            filing = null
            if (f != null) {
                if (mode == "file") run("Filed in ${f.name}") { Api.get(context).fileGroup(id, FolderIdIn(f.id)) } else ruleDraft("file", f.id)
            }
        }
    }
    if (merging) {
        var others by remember { mutableStateOf<List<GroupDto>?>(null) }
        LaunchedEffect(Unit) { others = runCatching { Api.get(context).groups().filter { it.id != id } }.getOrDefault(emptyList()) }
        AlertDialog(
            onDismissRequest = { merging = false },
            title = { Text("Merge into…") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    when {
                        others == null -> Text("Loading…", color = Ink.text3)
                        others!!.isEmpty() -> Text("No other groups yet.", color = Ink.text3)
                        else -> others!!.forEach { o ->
                            Text("${o.title} (${o.count})", color = Ink.text, style = MaterialTheme.typography.titleSmall,
                                modifier = Modifier.fillMaxWidth().clickable {
                                    merging = false
                                    scope.launch {
                                        try { Api.get(context).mergeGroup(id, TargetIn(o.id)); onBack() } catch (t: Throwable) { error = t.userMessage() }
                                    }
                                }.padding(vertical = 12.dp))
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { merging = false }) { Text("Cancel", color = Ink.text2) } },
            containerColor = Ink.surface, shape = Radius.xl,
        )
    }
}
