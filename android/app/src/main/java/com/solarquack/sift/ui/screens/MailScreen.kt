package com.solarquack.sift.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.TextButton
import androidx.compose.runtime.rememberCoroutineScope
import com.solarquack.sift.data.CalendarIntent
import com.solarquack.sift.data.CompanyAnswer
import com.solarquack.sift.data.DraftResponse
import com.solarquack.sift.data.LikeThisIn
import com.solarquack.sift.data.OpportunityDto
import com.solarquack.sift.data.TodoIn
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.MessageDto
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Avatar
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.SectionLabel
import com.solarquack.sift.ui.SiftCard
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.accountColor
import com.solarquack.sift.ui.fullTime
import com.solarquack.sift.ui.theme.Ink

/** Mail detail: Sift's view of the mail, then the whole conversation (Phase 3a reader). */
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun MailScreen(id: String, onBack: () -> Unit, onOpenOpportunity: (String) -> Unit = {}, onEditRule: () -> Unit = {}, onWrite: (mode: String, messageId: String) -> Unit = { _, _ -> },
               onOpenGroup: (String) -> Unit = {}) {
    val context = LocalContext.current
    var m by remember { mutableStateOf<MessageDto?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var addingTodo by remember { mutableStateOf(false) }
    var likeThis by remember { mutableStateOf<DraftResponse?>(null) }
    var silencedByRule by remember { mutableStateOf<String?>(null) }
    var folderPick by remember { mutableStateOf(0) }
    var groupPick by remember { mutableStateOf(false) }
    var companyPick by remember { mutableStateOf(0) }
    var filingRefresh by remember { mutableStateOf(0) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(id) {
        try {
            val loaded = Api.get(context).message(id)
            m = loaded
            // opening a mail reads it: the whole conversation is marked read (in Gmail when the
            // account allows changes) and other devices update live
            if (loaded.unread) {
                m = loaded.copy(unread = false)
                runCatching { Api.get(context).readState(com.solarquack.sift.data.ReadStateIn(listOf(id), false)) }
            }
        } catch (t: Throwable) {
            error = t.userMessage()
            return@LaunchedEffect
        }
    }
    LaunchedEffect(id) {
        com.solarquack.sift.data.LiveEvents.changes.collect { runCatching { Api.get(context).message(id) }.onSuccess { m = it } }
    }

    Column(Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).padding(18.dp)) {
        Text("‹ Back", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(vertical = 6.dp))
        error?.let { Banner(it, Ink.urgent) }
        val msg = m ?: return@Column
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            msg.priority?.let { Tag(it, Ink.tier(it)) }
            msg.category?.takeIf { it != "other" }?.let { Tag(it) }
            msg.company?.let { Tag(it) }
        }
        Text(msg.subject ?: "(no subject)", style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.padding(vertical = 10.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Avatar(msg.senderName ?: msg.sender ?: "?")
            Column(Modifier.padding(start = 10.dp)) {
                Text(msg.senderName?.takeIf { it.isNotBlank() } ?: msg.sender ?: "", style = MaterialTheme.typography.titleSmall, color = Ink.text)
                Text("${msg.sender ?: ""} · ${fullTime(msg.receivedAt)}", style = MaterialTheme.typography.bodySmall, color = Ink.text3)
                msg.account?.let { Text("To $it", style = MaterialTheme.typography.bodySmall, color = accountColor(msg.accountColor, msg.accountId)) }
            }
        }

        if (msg.summary != null || msg.deadline != null || msg.links.isNotEmpty()) {
            Spacer(Modifier.height(16.dp))
            SiftCard {
                SectionLabel("Extracted")
                msg.summary?.let { Text(it, color = Ink.text, style = MaterialTheme.typography.bodyLarge) }
                msg.deadline?.let { Text("Deadline ${fullTime(it)}", color = Ink.warn, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 6.dp)) }
                msg.platform?.let { Text("Platform: $it", color = Ink.text2, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 4.dp)) }
                msg.links.forEach { link ->
                    Spacer(Modifier.height(10.dp))
                    PrimaryButton(link.label) { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(link.url))) }
                }
            }
        }

        val info: (String) -> Unit = { android.widget.Toast.makeText(context, it, android.widget.Toast.LENGTH_SHORT).show() }
        val reload: () -> Unit = { scope.launch { m = Api.get(context).message(id); filingRefresh++ } }
        val silenced = msg.status == "silenced" || msg.status == "ignored"
        val deadlineAhead = msg.deadline != null && runCatching { java.time.OffsetDateTime.parse(msg.deadline).isAfter(java.time.OffsetDateTime.now()) }.getOrDefault(false)
        val extra = buildList {
            add(SheetItem("File in folder…", "The whole conversation; replies follow it", section = "Organize") { folderPick++ })
            add(SheetItem("Move to last used folder", "One tap, same folder as last time", section = "Organize") {
                scope.launch {
                    try { Api.get(context).fileLastUsed(com.solarquack.sift.data.FileIn(listOf(msg.id))); info("Filed"); filingRefresh++ } catch (t: Throwable) { info(t.userMessage()) }
                }
            })
            if (msg.opportunityId == null && msg.companyQuestion == null) add(SheetItem("Add to a company…", "Put it on a company timeline", section = "Organize") { companyPick++ })
            if (msg.todoId == null) add(SheetItem("Add to to-do…", "With an optional deadline and reminders", section = "Organize") { addingTodo = true })
            add(SheetItem("Add to group…", "One of your groups, or a new one; a mail can be in several", section = "Organize") { groupPick = true })
            msg.groups.forEach { g -> add(SheetItem("Open group: ${g.title}", "Every mail in it", section = "Organize") { onOpenGroup(g.id) }) }
            if (msg.groups.isEmpty()) msg.groupId?.let { g -> add(SheetItem("Open its group", "Every mail grouped with this one", section = "Organize") { onOpenGroup(g) }) }
            if (deadlineAhead) add(SheetItem("Add to calendar", "Opens your calendar with the deadline", section = "Organize") {
                CalendarIntent.open(context, listOfNotNull(msg.company, msg.summary ?: msg.subject).joinToString(": "), msg.deadline)
            })
            if (silenced) add(SheetItem("Not like this", "Back to the feed, and stop silencing mail like it", section = "Sift") {
                scope.launch {
                    try { val r = Api.get(context).unsilence(msg.id); m = Api.get(context).message(id); silencedByRule = r.ruleId } catch (t: Throwable) { error = t.userMessage() }
                }
            }) else add(SheetItem("Ignore mails like this…", "Silence future mail from this sender with this kind of subject", section = "Sift") {
                scope.launch { try { likeThis = Api.get(context).likeThis(msg.id, LikeThisIn(save = false)) } catch (t: Throwable) { error = t.userMessage() } }
            })
            add(SheetItem("Open in Gmail", "In the Gmail app or browser", section = "Sift") {
                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://mail.google.com/mail/u/0/#all")))
            })
        }
        Spacer(Modifier.height(14.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PrimaryButton("↩ Reply", Modifier.weight(1f)) { onWrite("reply", msg.id) }
            GhostButton("↪ Forward", Modifier.weight(1f)) { onWrite("forward", msg.id) }
        }
        Spacer(Modifier.height(8.dp))
        MailActionsButton(msg, listOf(SheetItem("Reply all", "To everyone on this mail", section = "Write") { onWrite("reply_all", msg.id) }) + extra,
            onChanged = reload, onLeave = onBack, onInfo = info)

        CompanySection(msg, onOpenOpportunity, onChanged = reload, pickRequest = companyPick)
        if (msg.todoId != null) Box(Modifier.padding(top = 10.dp)) { Tag("On your to-do list", Ink.signal) }
        if (msg.groups.isNotEmpty()) androidx.compose.foundation.layout.FlowRow(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("In group", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp))
            msg.groups.forEach { g -> com.solarquack.sift.ui.Chip(g.title, false) { onOpenGroup(g.id) } }
        }

        FilingSection(msg.id, buttons = false, pickRequest = folderPick, refreshKey = filingRefresh) { r -> RuleEditorSeed.clear(); RuleEditorSeed.draft = r.draft; RuleEditorSeed.origin = "one_tap"; onEditRule() }

        SectionLabel("Conversation")
        ThreadView(id)
        Spacer(Modifier.height(18.dp))
        Text(
            "Decided by ${msg.decidedBy ?: "default"}" + (msg.deliveredAt?.let { " · delivered ${fullTime(it)}" } ?: ""),
            color = Ink.text3, style = MaterialTheme.typography.bodySmall,
        )
        silencedByRule?.let { ruleId ->
            Spacer(Modifier.height(8.dp))
            Banner("Back in your feed. A rule silenced it; edit the rule so it doesn't happen again.", Ink.warn, "Edit rule") {
                scope.launch {
                    Api.get(context).rules().firstOrNull { it.id == ruleId }?.let { RuleEditorSeed.clear(); RuleEditorSeed.rule = it; onEditRule() }
                }
            }
        }
    }

    likeThis?.let { r ->
        AlertDialog(
            onDismissRequest = { likeThis = null },
            title = { Text("Silence mails like this?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("New mail from the same verified sender with the same kind of subject will be stored silently: searchable, never notified.", color = Ink.text2, style = MaterialTheme.typography.bodyMedium)
                    Text("${r.preview.matches} of your last ${r.preview.checked} mails match.", color = Ink.signal, style = MaterialTheme.typography.titleSmall)
                    r.preview.samples.take(3).forEach { s -> Text("· ${s.subject ?: ""}", color = Ink.text3, style = MaterialTheme.typography.bodySmall, maxLines = 1) }
                }
            },
            confirmButton = {
                PrimaryButton("Silence") {
                    likeThis = null
                    scope.launch {
                        try { Api.get(context).likeThis(id, LikeThisIn("silent", save = true)); m = Api.get(context).message(id) } catch (t: Throwable) { error = t.userMessage() }
                    }
                }
            },
            dismissButton = {
                Row {
                    TextButton(onClick = { RuleEditorSeed.clear(); RuleEditorSeed.draft = r.draft; RuleEditorSeed.origin = "one_tap"; likeThis = null; onEditRule() }) { Text("Adjust…", color = Ink.text2) }
                    TextButton(onClick = { likeThis = null }) { Text("Cancel", color = Ink.text2) }
                }
            },
            containerColor = Ink.surface, shape = Radius.xl,
        )
    }

    if (groupPick) m?.let { msg ->
        GroupPickerDialog(msg.id, msg.groups.map { it.id }.toSet(), onDismiss = { groupPick = false }) { title ->
            groupPick = false
            android.widget.Toast.makeText(context, "Added to $title", android.widget.Toast.LENGTH_SHORT).show()
            scope.launch { m = runCatching { Api.get(context).message(id) }.getOrNull() ?: m }
        }
    }
    if (addingTodo) m?.let { msg ->
        AddTodoDialog(initialTitle = msg.summary ?: msg.subject ?: "", onDismiss = { addingTodo = false }) { title, due ->
            addingTodo = false
            scope.launch {
                try {
                    Api.get(context).createTodo(TodoIn(title, due ?: msg.deadline, messageId = msg.id, opportunityId = msg.opportunityId))
                    m = Api.get(context).message(id).let { it.copy(todoId = it.todoId ?: "manual") }
                } catch (t: Throwable) { error = t.userMessage() }
            }
        }
    }
}

/** Which company drive this mail belongs to: link, "which company?" question, or a manual picker. */
@Composable
private fun CompanySection(msg: MessageDto, onOpenOpportunity: (String) -> Unit, onChanged: () -> Unit, pickRequest: Int = 0) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var picking by remember { mutableStateOf(false) }
    var naming by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(pickRequest) { if (pickRequest > 0) picking = true }

    fun answer(body: CompanyAnswer) = scope.launch {
        try { Api.get(context).answerCompany(msg.id, body); onChanged() } catch (t: Throwable) { error = t.userMessage() }
    }

    Spacer(Modifier.height(14.dp))
    when {
        msg.opportunityId != null -> Banner("On the ${msg.company ?: "company"} timeline", Ink.signal, "Open") { onOpenOpportunity(msg.opportunityId) }
        msg.companyQuestion != null -> SiftCard(border = Ink.warn.copy(alpha = 0.4f)) {
            Text("Which company is this?", color = Ink.text, style = MaterialTheme.typography.titleSmall)
            Text("Your answer teaches Sift, so the next mail like this is sorted by itself.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                msg.companyQuestion.take(3).forEach { c -> Chip(c.name, false) { answer(CompanyAnswer(opportunityId = c.id)) } }
                Chip("other…", false) { picking = true }
            }
        }
        else -> {}  // "Add to a company" is in the Actions sheet
    }
    error?.let { Text(it, color = Ink.urgent, style = MaterialTheme.typography.bodySmall) }

    if (picking) CompanyPicker(onDismiss = { picking = false }, onNew = { picking = false; naming = true }) { id ->
        picking = false
        answer(CompanyAnswer(opportunityId = id))
    }
    if (naming) NewOpportunityDialog(onDismiss = { naming = false }) { name ->
        naming = false
        answer(CompanyAnswer(newCompany = name))
    }
}

@Composable
private fun CompanyPicker(onDismiss: () -> Unit, onNew: () -> Unit, onPick: (String) -> Unit) {
    val context = LocalContext.current
    var opps by remember { mutableStateOf<List<OpportunityDto>?>(null) }
    LaunchedEffect(Unit) { opps = runCatching { Api.get(context).opportunities() }.getOrDefault(emptyList()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add to a company") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                when {
                    opps == null -> Text("Loading…", color = Ink.text3)
                    opps!!.isEmpty() -> Text("No company drives yet.", color = Ink.text3, style = MaterialTheme.typography.bodyMedium)
                    else -> opps!!.forEach { o ->
                        Text(o.company, color = Ink.text, style = MaterialTheme.typography.titleSmall,
                            modifier = Modifier.fillMaxWidth().clickable { onPick(o.id) }.padding(vertical = 12.dp))
                    }
                }
            }
        },
        confirmButton = { PrimaryButton("+ New company", onClick = onNew) },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}


/** Your groups to put this mail in, or a new one by name. */
@Composable
fun GroupPickerDialog(messageId: String, exclude: Set<String>, onDismiss: () -> Unit, onAdded: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var groups by remember { mutableStateOf<List<com.solarquack.sift.data.GroupDto>?>(null) }
    var name by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) { groups = runCatching { Api.get(context).groups().filter { it.custom && it.id !in exclude } }.getOrDefault(emptyList()) }
    fun add(id: String, title: String) = scope.launch {
        try { Api.get(context).addToGroup(id, com.solarquack.sift.data.GroupIdsIn(listOf(messageId))); onAdded(title) } catch (t: Throwable) { error = t.userMessage() }
    }
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add to group") },
        text = {
            Column(Modifier.verticalScroll(androidx.compose.foundation.rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                when {
                    groups == null -> Text("Loading…", color = Ink.text3)
                    groups!!.isEmpty() -> Text("No groups of your own yet. Make one here, or in More → Groups with rules for new mail.", color = Ink.text3,
                        style = MaterialTheme.typography.bodySmall)
                    else -> groups!!.forEach { g ->
                        Text("${g.title}  ·  ${g.count} mails", color = Ink.text, style = MaterialTheme.typography.titleSmall,
                            modifier = Modifier.fillMaxWidth().clickable { add(g.id, g.title) }.padding(vertical = 10.dp))
                    }
                }
                com.solarquack.sift.ui.Field(name, { name = it.take(200) }, "New group", placeholder = "Name")
                error?.let { Text(it, color = Ink.urgent, style = MaterialTheme.typography.bodySmall) }
            }
        },
        confirmButton = {
            com.solarquack.sift.ui.PrimaryButton("Make and add", enabled = name.isNotBlank()) {
                scope.launch {
                    try { val g = Api.get(context).createGroup(com.solarquack.sift.data.NewGroupIn(name.trim())); add(g.id, g.title) }
                    catch (t: Throwable) { error = t.userMessage() }
                }
            }
        },
        dismissButton = { androidx.compose.material3.TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) } },
        containerColor = Ink.surface, shape = com.solarquack.sift.ui.theme.Radius.xl,
    )
}
