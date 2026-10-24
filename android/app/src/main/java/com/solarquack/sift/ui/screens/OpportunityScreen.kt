package com.solarquack.sift.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.CalendarIntent
import com.solarquack.sift.data.OpportunityDetail
import com.solarquack.sift.data.OpportunityPatch
import com.solarquack.sift.data.TimelineEventDto
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Field
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.SectionLabel
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.fullTime
import com.solarquack.sift.ui.humanize
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch
import java.time.OffsetDateTime

private val STAGES = listOf("announcement", "registration", "assessment", "interview", "result")

private fun kindColor(kind: String): Color = when (kind) {
    "assessment", "interview" -> Ink.urgent
    "result" -> Ink.signal
    "registration" -> Ink.warn
    else -> Ink.normal
}

private fun isFuture(iso: String?) = iso?.let { runCatching { OffsetDateTime.parse(it).isAfter(OffsetDateTime.now()) }.getOrNull() } == true

/** Company timeline: every mail about one drive, from any account, in order. */
@Composable
fun OpportunityScreen(id: String, onBack: () -> Unit, onOpenMail: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var o by remember { mutableStateOf<OpportunityDetail?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var editing by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    // a section to add ("new") or change; for a mail only its stage
    var section by remember { mutableStateOf<Any?>(null) }
    var removing by remember { mutableStateOf<TimelineEventDto?>(null) }

    fun load() = scope.launch { try { o = Api.get(context).opportunity(id); error = null } catch (t: Throwable) { error = t.userMessage() } }
    fun patch(p: OpportunityPatch) = scope.launch { try { Api.get(context).updateOpportunity(id, p); load() } catch (t: Throwable) { error = t.userMessage() } }
    LaunchedEffect(id) { load() }

    Column(Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).padding(18.dp)) {
        Text("‹ Back", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(vertical = 6.dp))
        error?.let { Banner(it, Ink.urgent, "Retry") { load() } }
        val d = o ?: return@Column
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(d.company, style = MaterialTheme.typography.displaySmall, color = Ink.text, modifier = Modifier.weight(1f))
            Tag(d.status, if (d.status == "active") Ink.signal else Ink.text2)
        }
        if (d.aliases.isNotEmpty() || d.domains.isNotEmpty()) {
            Text(
                listOfNotNull(d.aliases.takeIf { it.isNotEmpty() }?.let { "Also: ${it.joinToString()}" }, d.domains.takeIf { it.isNotEmpty() }?.let { "Senders: ${it.joinToString()}" }).joinToString(" · "),
                color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp),
            )
        }

        // stage strip: which steps of the drive have happened
        val seen = d.timeline.map { it.kind }.toSet()
        Row(Modifier.padding(top = 14.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            STAGES.forEach { s ->
                val on = s in seen
                Box(
                    Modifier.weight(1f).background(if (on) kindColor(s).copy(alpha = 0.16f) else Ink.surface, Radius.sm)
                        .border(1.dp, if (on) kindColor(s).copy(alpha = 0.5f) else Ink.line, Radius.sm).padding(vertical = 6.dp),
                    contentAlignment = Alignment.Center,
                ) { Text(humanize(s).take(6), color = if (on) kindColor(s) else Ink.text3, style = MaterialTheme.typography.labelSmall) }
            }
        }

        if (isFuture(d.deadline)) {
            Spacer(Modifier.height(14.dp))
            Banner("Next deadline ${fullTime(d.deadline)}", Ink.warn, "Add to calendar") {
                CalendarIntent.open(context, "${d.company} deadline", d.deadline!!, "From your ${d.company} timeline in Sift")
            }
        }

        SectionLabel("Timeline")
        if (d.timeline.isEmpty()) {
            Text("Nothing on this timeline yet. Mail about ${d.company} lands here, or add a section.", color = Ink.text3, style = MaterialTheme.typography.bodyMedium)
        }
        d.timeline.forEachIndexed { i, e ->
            TimelineItem(e, last = i == d.timeline.lastIndex, onOpenMail = onOpenMail, onEdit = { section = e }, onRemove = { removing = e })
        }

        Spacer(Modifier.height(12.dp))
        PrimaryButton("+ Add section", Modifier.fillMaxWidth()) { section = "new" }
        Text("A test, interview, result… with its date and time. It takes its place on the timeline by that time.",
            color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
        Spacer(Modifier.height(16.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            GhostButton("Edit") { editing = true }
            GhostButton(if (d.status == "active") "Close" else "Reopen") { patch(OpportunityPatch(status = if (d.status == "active") "closed" else "active")) }
            GhostButton("Delete", color = Ink.urgent) { deleting = true }
        }
        Spacer(Modifier.height(24.dp))
    }

    o?.let { d ->
        section?.let { s ->
            SectionDialog(d.company, s as? TimelineEventDto, onDismiss = { section = null }) { body, patchBody ->
                section = null
                scope.launch {
                    try {
                        val api = Api.get(context)
                        o = if (s is TimelineEventDto) api.editEvent(id, s.id, patchBody!!) else api.addSection(id, body!!)
                    } catch (t: Throwable) { error = t.userMessage() }
                }
            }
        }
        removing?.let { e ->
            AlertDialog(
                onDismissRequest = { removing = null },
                title = { Text(if (e.manual) "Remove this section?" else "Take this mail off the timeline?") },
                text = { Text(if (e.manual) "“${e.title}” is removed." else "The mail itself stays in your inbox and feed.") },
                confirmButton = { TextButton(onClick = { removing = null; scope.launch { try { o = Api.get(context).removeEvent(id, e.id) } catch (t: Throwable) { error = t.userMessage() } } }) { Text("Remove", color = Ink.urgent) } },
                dismissButton = { TextButton(onClick = { removing = null }) { Text("Cancel", color = Ink.text2) } },
                containerColor = Ink.surface, shape = Radius.xl,
            )
        }
        if (editing) EditOpportunityDialog(d, onDismiss = { editing = false }) { company, aliases ->
            editing = false
            patch(OpportunityPatch(company = company, aliases = aliases))
        }
        if (deleting) AlertDialog(
            onDismissRequest = { deleting = false },
            title = { Text("Delete ${d.company}?") },
            text = { Text("Only the timeline is deleted. The mail stays in your inbox and feed.") },
            confirmButton = { TextButton(onClick = { deleting = false; scope.launch { try { Api.get(context).deleteOpportunity(id); onBack() } catch (t: Throwable) { error = t.userMessage() } } }) { Text("Delete", color = Ink.urgent) } },
            dismissButton = { TextButton(onClick = { deleting = false }) { Text("Cancel", color = Ink.text2) } },
            containerColor = Ink.surface, shape = Radius.xl,
        )
    }
}

@Composable
private fun TimelineItem(e: TimelineEventDto, last: Boolean, onOpenMail: (String) -> Unit, onEdit: () -> Unit, onRemove: () -> Unit) {
    val context = LocalContext.current
    Row {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.width(22.dp)) {
            Box(Modifier.padding(top = 4.dp).size(12.dp).background(kindColor(e.kind), CircleShape))
            if (!last) Box(Modifier.width(2.dp).height(86.dp).background(Ink.line2))
        }
        Column(
            Modifier.weight(1f).padding(start = 10.dp, bottom = 16.dp).clickable(enabled = e.messageId != null) { e.messageId?.let(onOpenMail) },
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                Tag(STAGE_LABELS[e.kind] ?: e.kind, kindColor(e.kind))
                e.platform?.let { Tag(it) }
                Text(fullTime(e.occurredAt), color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                Text("Edit", color = Ink.signal, style = MaterialTheme.typography.labelMedium, modifier = Modifier.clickable(onClick = onEdit).padding(6.dp))
                Text("✕", color = Ink.text3, style = MaterialTheme.typography.labelMedium, modifier = Modifier.clickable(onClick = onRemove).padding(6.dp))
            }
            Text((if (e.manual) e.title else null) ?: e.summary ?: e.subject ?: "Mail", color = Ink.text, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 4.dp))
            if (e.manual) {
                e.note?.let { Text(it, color = Ink.text2, style = MaterialTheme.typography.bodySmall) }
                Text("Added by you" + if (e.remind) " · reminds you" else "", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            } else Text(listOfNotNull(e.senderName, e.account).joinToString(" · "), color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            if (isFuture(e.deadline)) Text("Deadline ${fullTime(e.deadline)}", color = Ink.warn, style = MaterialTheme.typography.bodySmall)
            e.links.firstOrNull()?.let { link ->
                Text("${link.label} ↗", color = Ink.signal, style = MaterialTheme.typography.labelMedium,
                    modifier = Modifier.padding(top = 4.dp).clickable { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(link.url))) })
            }
        }
    }
}

@Composable
private fun EditOpportunityDialog(d: OpportunityDetail, onDismiss: () -> Unit, onSave: (String, List<String>) -> Unit) {
    var company by remember { mutableStateOf(d.company) }
    var aliases by remember { mutableStateOf(d.aliases.joinToString(", ")) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Edit opportunity") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Field(company, { company = it }, "Company")
                Field(aliases, { aliases = it }, "Other names (comma separated)")
                Text("Mail naming any of these lands on this timeline.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = {
            PrimaryButton("Save", enabled = company.isNotBlank()) {
                onSave(company.trim(), aliases.split(",").map { it.trim() }.filter { it.isNotEmpty() })
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}

private val STAGE_LABELS = linkedMapOf(
    "announcement" to "Announcement", "registration" to "Registration", "assessment" to "Test",
    "interview" to "Interview", "result" to "Result", "update" to "Update",
)

/** Add a section (stage, title, note, date and time, reminder) or change one. For a mail on the
 * timeline only its stage can change; it keeps its own subject and time. */
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun SectionDialog(company: String, event: TimelineEventDto?, onDismiss: () -> Unit,
                          onSave: (com.solarquack.sift.data.SectionIn?, com.solarquack.sift.data.SectionPatch?) -> Unit) {
    val mail = event != null && !event.manual
    var kind by remember { mutableStateOf(event?.kind ?: "interview") }
    var title by remember { mutableStateOf(event?.title ?: "") }
    var note by remember { mutableStateOf(event?.note ?: "") }
    var at by remember { mutableStateOf(com.solarquack.sift.ui.parseZoned(event?.occurredAt) ?: java.time.ZonedDateTime.now().plusDays(1).withHour(10).withMinute(0).withSecond(0).withNano(0)) }
    var remind by remember { mutableStateOf(event?.remind ?: false) }
    val future = at?.isAfter(java.time.ZonedDateTime.now()) == true
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (event == null) "Add a section to $company" else if (mail) "Change the stage" else "Edit section") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Stage", color = Ink.text3, style = MaterialTheme.typography.labelSmall)
                androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    STAGE_LABELS.forEach { (k, label) -> com.solarquack.sift.ui.Chip(label, kind == k) { kind = k } }
                }
                if (mail) Text("A mail keeps its own subject and time.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                else {
                    Field(title, { title = it.take(200) }, "Title", placeholder = "e.g. Technical interview, round 2")
                    Text("Date and time", color = Ink.text3, style = MaterialTheme.typography.labelSmall)
                    com.solarquack.sift.ui.DateTimeRow(at, { at = it }, allowNone = false)
                    Text("The section takes its place on the timeline by this date and time.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                    Field(note, { note = it.take(2000) }, "Note (optional)", singleLine = false, placeholder = "Venue, link, what to prepare…")
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(if (future) "Remind me before it" else "Remind me (only for a future time)", color = if (future) Ink.text else Ink.text3,
                            style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                        com.solarquack.sift.ui.SiftSwitch(remind && future, { if (future) remind = it }, enabled = future)
                    }
                }
            }
        },
        confirmButton = {
            PrimaryButton(if (event == null) "Add" else "Save", enabled = mail || (title.isNotBlank() && at != null)) {
                val a = at ?: return@PrimaryButton
                when {
                    mail -> onSave(null, com.solarquack.sift.data.SectionPatch(kind = kind))
                    event != null -> onSave(null, com.solarquack.sift.data.SectionPatch(kind, title.trim(), note.trim(), with(com.solarquack.sift.ui.DateTimeIso) { a.isoString() }, remind && future))
                    else -> onSave(com.solarquack.sift.data.SectionIn(kind, title.trim(), note.trim().ifEmpty { null }, with(com.solarquack.sift.ui.DateTimeIso) { a.isoString() }, remind && future), null)
                }
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}
