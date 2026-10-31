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
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
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
                    Tag("${g.count} mail" + if (g.count == 1) "" else "s")
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

@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
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
    var editing by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    var actionsOpen by remember { mutableStateOf(false) }

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
    LaunchedEffect(Unit) { com.solarquack.sift.data.LiveEvents.changes.collect { load() } }

    val group = g
    com.solarquack.sift.ui.Refreshable({ load().join() }) {
        LazyColumn(Modifier.fillMaxSize().background(Ink.bg), contentPadding = PaddingValues(start = 18.dp, end = 18.dp, top = 18.dp, bottom = 96.dp)) {
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
                    if (group.custom) {
                        Column(Modifier.fillMaxWidth().padding(top = 12.dp).background(Ink.surface, Radius.lg).border(1.dp, Ink.line2, Radius.lg).padding(12.dp)) {
                            Text("New mail joins when it", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                            group.query?.let { Text("matches  $it", color = Ink.text2, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 2.dp)) }
                            group.instruction?.let { Text((if (group.query != null) "and " else "") + "fits “$it” (the AI checks)", color = Ink.text2, style = MaterialTheme.typography.bodySmall) }
                            if (group.query == null && group.instruction == null) Text("Nothing automatic: add mail by hand (a mail's Actions → Add to group).",
                                color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                            FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                GhostButton("Criteria…") { editing = true }
                                if (group.query != null || group.instruction != null) GhostButton("Fill now") {
                                    run(null) {
                                        val r = Api.get(context).fillGroup(id)
                                        info = if (r.status == "done") "Added ${r.changed} mail" else "The AI is adding matching mail. You'll get a notification"
                                    }
                                }
                            }
                        }
                    }
                    Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("Mute this group", color = Ink.text, style = MaterialTheme.typography.bodyMedium)
                            Text("New mail in it won't notify. Urgent mail still does.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                        }
                        com.solarquack.sift.ui.SiftSwitch(group.muted, { on -> run { Api.get(context).editGroup(id, GroupPatch(muted = on)) } })
                    }
                    Row(
                        Modifier.fillMaxWidth().padding(vertical = 12.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        GhostButton("Actions ▾", onClick = { actionsOpen = true })
                        if (selecting) {
                            GhostButton("Cancel split", onClick = { selecting = false; selected = emptySet() })
                        }
                    }

                    if (actionsOpen) {
                        ModalBottomSheet(
                            onDismissRequest = { actionsOpen = false },
                            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
                            containerColor = Ink.surface,
                        ) {
                            val groupActions = buildList {
                                add(SheetItem("File all in folder", "Move all emails in this group to a folder", section = "Organize") {
                                    filing = "file"
                                })
                                add(SheetItem("Split group", "Select emails to split into a new group", section = "Organize") {
                                    selecting = true
                                    selected = emptySet()
                                })
                                add(SheetItem("Merge into…", "Combine with another existing group", section = "Organize") {
                                    merging = true
                                })
                                add(SheetItem("File mail like this…", "Create a rule to file future similar emails automatically", section = "Automation") {
                                    filing = "rule"
                                })
                                add(SheetItem("Silence mail like this", "Create a rule to silence future similar emails", section = "Automation") {
                                    ruleDraft("silent")
                                })
                                group.items.firstOrNull()?.sender?.let { sender ->
                                    add(SheetItem("Never group $sender", "Keep future emails from this sender out of groups", section = "Automation") {
                                        run("Mail from $sender won't be grouped") {
                                            Api.get(context).setGroupPreference(PreferenceIn(sender, "never"))
                                        }
                                    })
                                }
                                add(SheetItem("Delete group", "Remove this group without deleting emails", danger = true, section = "Manage") {
                                    deleting = true
                                })
                            }

                            LazyColumn(Modifier.padding(bottom = 28.dp)) {
                                val sections = groupActions.groupBy { it.section }
                                sections.forEach { (section, entries) ->
                                    item(key = "hdr-$section") {
                                        Text(
                                            section.uppercase(),
                                            color = Ink.text3,
                                            style = MaterialTheme.typography.labelSmall,
                                            modifier = Modifier.padding(start = 22.dp, top = 14.dp, bottom = 6.dp)
                                        )
                                    }
                                    items(entries, key = { it.label }) { entry ->
                                        Column(
                                            Modifier
                                                .fillMaxWidth()
                                                .clickable {
                                                    actionsOpen = false
                                                    entry.onClick()
                                                }
                                                .padding(horizontal = 22.dp, vertical = 12.dp)
                                        ) {
                                            Text(
                                                entry.label,
                                                color = if (entry.danger) Ink.urgent else Ink.text,
                                                style = MaterialTheme.typography.titleSmall
                                            )
                                            entry.hint?.let { hint ->
                                                Text(hint, color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                                            }
                                        }
                                    }
                                }
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
    }

    if (editing) group?.let { gr -> GroupFormDialog(gr, onDismiss = { editing = false }) { editing = false; load() } }
    if (deleting) group?.let { gr ->
        AlertDialog(
            onDismissRequest = { deleting = false },
            title = { Text("Delete ${gr.title}?") },
            text = { Text("The group goes away; every mail in it stays in your feed, folders and timelines.", color = Ink.text2) },
            confirmButton = { TextButton(onClick = { deleting = false; scope.launch { try { Api.get(context).deleteGroup(id); onBack() } catch (t: Throwable) { error = t.userMessage() } } }) {
                Text("Delete", color = Ink.urgent) } },
            dismissButton = { TextButton(onClick = { deleting = false }) { Text("Cancel", color = Ink.text2) } },
            containerColor = Ink.surface, shape = Radius.xl,
        )
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

/** Every group in one place (More > Groups, or "Open its group" in a mail's Actions): grouping
 * on/off, "Collapse all", and each group as a stacked row that opens its own screen. */
@Composable
fun GroupsScreen(onBack: () -> Unit, onOpen: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var status by remember { mutableStateOf<com.solarquack.sift.data.GroupingStatus?>(null) }
    var groups by remember { mutableStateOf<List<GroupDto>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var info by remember { mutableStateOf<String?>(null) }
    var making by remember { mutableStateOf(false) }
    val on = status?.groupingEnabled == "yes"

    fun load() = scope.launch {
        try {
            val api = Api.get(context)
            status = api.grouping()
            groups = api.groups()  // your own groups always; automatic ones while grouping is on
            error = null
        } catch (t: Throwable) { error = t.userMessage() }
    }
    LaunchedEffect(Unit) { load() }
    LaunchedEffect(Unit) { com.solarquack.sift.data.LiveEvents.changes.collect { load() } }
    fun set(answer: String) = scope.launch {
        try {
            Api.get(context).answerGrouping(AnswerIn(answer))
            info = if (answer == "yes") "Grouping on. The last 30 days are being grouped." else "Grouping off."
            load()
        } catch (t: Throwable) { error = t.userMessage() }
    }

    com.solarquack.sift.ui.Refreshable({ load().join() }) {
        LazyColumn(Modifier.fillMaxSize().background(Ink.bg), contentPadding = PaddingValues(start = 14.dp, end = 14.dp, top = 8.dp, bottom = 110.dp)) {
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("‹ Back", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(vertical = 10.dp, horizontal = 4.dp))
                }
                Text("Groups", style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.padding(start = 4.dp, top = 4.dp, bottom = 10.dp))
            }
            error?.let { item { Banner(it, Ink.urgent, "Retry") { load() } } }
            info?.let { item { Banner(it, Ink.signal) } }
            item {
                Row(Modifier.padding(top = 4.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("Your groups", color = Ink.text2, style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                    PrimaryButton("+ New group") { making = true }
                }
            }
            val mine = groups.orEmpty().filter { it.custom }
            if (groups != null && mine.isEmpty()) item {
                Text("None yet. Give a group a search (free) or describe its mail in words (the AI checks each new mail), and new mail joins it on its own, next to its folders and timeline.",
                    color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(vertical = 8.dp, horizontal = 4.dp))
            }
            items(mine, key = { it.id }) { g -> GroupRow(g) { onOpen(g.id) } }
            item { Text("Automatic groups", color = Ink.text2, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 16.dp, bottom = 6.dp)) }
            status?.let {
                item {
                    Column(Modifier.fillMaxWidth().background(Ink.surface, Radius.lg).border(1.dp, Ink.line2, Radius.lg).padding(14.dp)) {
                        Text(if (on) "Automatic grouping is on" else "Automatic grouping is off", color = Ink.text, style = MaterialTheme.typography.titleSmall)
                        Text(if (on) "Similar mail is stacked into one row. Display only: notifications are unaffected."
                            else "Turn it on to stack similar mail (bank alerts, newsletters, one company's drive) into one row. Display only.",
                            color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 2.dp, bottom = 10.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (on) {
                                GhostButton("Turn off") { set("no") }
                                GhostButton("Collapse all") {
                                    scope.launch { runCatching { Api.get(context).collapseAllGroups(com.solarquack.sift.data.CollapseIn(true)) }; info = "Every group folded into one row."; load() }
                                }
                            } else PrimaryButton("Turn on") { set("yes") }
                        }
                    }
                }
            }
            if (on && groups?.none { !it.custom } == true) item {
                Text("No automatic groups yet. A group shows once three similar mails arrive.", color = Ink.text3, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 28.dp, horizontal = 4.dp))
            }
            items(groups.orEmpty().filter { !it.custom }, key = { it.id }) { g -> GroupRow(g) { onOpen(g.id) } }
        }
    }
    if (making) GroupFormDialog(null, onDismiss = { making = false }) { made -> making = false; load(); made?.let { onOpen(it.id) } }
}

/** New group, or a custom group's criteria: a search (free, exact) and/or a description (the AI
 * checks while reading each new mail). A mail can sit in several groups and folders at once. */
@Composable
fun GroupFormDialog(g: GroupDto?, onDismiss: () -> Unit, onSaved: (GroupDto?) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var title by remember { mutableStateOf(g?.title ?: "") }
    var query by remember { mutableStateOf(g?.query ?: "") }
    var instruction by remember { mutableStateOf(g?.instruction ?: "") }
    var fill by remember { mutableStateOf(g == null) }
    var aiOn by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) { runCatching { aiOn = Api.get(context).ai().aiEnabled } }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (g == null) "New group" else "Which mail joins it") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (g == null) Field(title, { title = it.take(200) }, "Name", placeholder = "e.g. Internships")
                Field(query, { query = it.take(500) }, "New mail matching this search (free)", placeholder = "from:nvidia.com")
                Field(instruction, { if (aiOn || it.isEmpty()) instruction = it.take(200) }, "And/or described as (the AI checks)",
                    placeholder = if (aiOn) "e.g. internship offers" else "Add an AI key to describe mail")
                Text("With both, mail must match the search and fit the description. Empty: you add mail by hand.",
                    color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                if (g == null && (query.isNotBlank() || instruction.isNotBlank())) Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Also add matching mail already here" + if (instruction.isNotBlank()) " (AI, last 30 days)" else " (free)",
                        color = Ink.text2, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                    com.solarquack.sift.ui.SiftSwitch(fill, { fill = it })
                }
                error?.let { Text(it, color = Ink.urgent, style = MaterialTheme.typography.bodySmall) }
            }
        },
        confirmButton = {
            PrimaryButton(if (g == null) "Make group" else "Save", enabled = title.isNotBlank()) {
                scope.launch {
                    try {
                        val api = Api.get(context)
                        val out = if (g == null) api.createGroup(com.solarquack.sift.data.NewGroupIn(title.trim(), query.trim().ifEmpty { null },
                            instruction.trim().ifEmpty { null }, fill && (query.isNotBlank() || instruction.isNotBlank())))
                        else api.editGroup(g.id, GroupPatch(query = query.trim(), instruction = instruction.trim()))
                        onSaved(out)
                    } catch (t: Throwable) { error = t.userMessage() }
                }
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}
