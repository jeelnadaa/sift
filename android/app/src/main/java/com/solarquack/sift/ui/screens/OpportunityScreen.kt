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
            Text("No mail on this timeline yet. Open a mail and choose this company to add it.", color = Ink.text3, style = MaterialTheme.typography.bodyMedium)
        }
        d.timeline.forEachIndexed { i, e -> TimelineItem(e, last = i == d.timeline.lastIndex, onOpenMail = onOpenMail) }

        Spacer(Modifier.height(20.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            GhostButton("Edit") { editing = true }
            GhostButton(if (d.status == "active") "Close" else "Reopen") { patch(OpportunityPatch(status = if (d.status == "active") "closed" else "active")) }
            GhostButton("Delete", color = Ink.urgent) { deleting = true }
        }
        Spacer(Modifier.height(24.dp))
    }

    o?.let { d ->
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
private fun TimelineItem(e: TimelineEventDto, last: Boolean, onOpenMail: (String) -> Unit) {
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
                Tag(e.kind, kindColor(e.kind))
                e.platform?.let { Tag(it) }
                Text(fullTime(e.occurredAt), color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            }
            Text(e.summary ?: e.subject ?: "Mail", color = Ink.text, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 4.dp))
            Text(listOfNotNull(e.senderName, e.account).joinToString(" · "), color = Ink.text3, style = MaterialTheme.typography.bodySmall)
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
