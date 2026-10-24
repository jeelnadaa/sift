package com.solarquack.sift.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.LabelDto
import com.solarquack.sift.data.MailActionIn
import com.solarquack.sift.data.MessageDto
import com.solarquack.sift.data.SnoozeIn
import com.solarquack.sift.data.WriteAccessAccount
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.data.writeAccessNeeded
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.Field
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch
import java.time.DayOfWeek
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.time.temporal.TemporalAdjusters

/** Archive, read/unread, star, label, snooze, spam and trash for one conversation (Phase 3c).
 * An account without write access asks once ("Allow in Google"), then the action is retried. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MailActionsRow(m: MessageDto, onChanged: () -> Unit, onLeave: () -> Unit, onInfo: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var needAccess by remember { mutableStateOf<Pair<List<WriteAccessAccount>, suspend () -> Unit>?>(null) }
    var snoozing by remember { mutableStateOf(false) }
    var labelling by remember { mutableStateOf(false) }

    fun act(action: String, leave: Boolean = false, label: String? = null) {
        val run: suspend () -> Unit = {
            val r = Api.get(context).mailAction(MailActionIn(messageIds = listOf(m.id), action = action, label = label))
            if (r.failedAccounts.isNotEmpty()) onInfo("Couldn't change mail in ${r.failedAccounts.joinToString()}.")
            else { onInfo(DONE[action] ?: "Done"); if (leave) onLeave() else onChanged() }
        }
        scope.launch {
            try { run() } catch (t: Throwable) {
                val accounts = t.writeAccessNeeded()
                if (accounts != null) needAccess = accounts to run else onInfo(t.userMessage())
            }
        }
    }

    FlowRow(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (m.inInbox) GhostButton("Archive") { act("archive", leave = true) } else GhostButton("Move to inbox") { act("unarchive") }
        GhostButton(if (m.unread) "Mark read" else "Mark unread") { act(if (m.unread) "read" else "unread") }
        GhostButton(if (m.starred) "★ Starred" else "☆ Star") { act(if (m.starred) "unstar" else "star") }
        GhostButton("Label…") { labelling = true }
        GhostButton("Snooze…") { snoozing = true }
        GhostButton("Spam") { act("spam", leave = true) }
        GhostButton("Trash", color = Ink.urgent) { act("trash", leave = true) }
    }

    needAccess?.let { (accounts, retry) ->
        AlertDialog(
            onDismissRequest = { needAccess = null },
            title = { Text("Allow Sift to change mail?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Archive, labels, read/unread, star, trash and snooze change mail in Gmail, so Google asks once per account. Sift never sends or deletes mail on its own.",
                        color = Ink.text2, style = MaterialTheme.typography.bodyMedium)
                    accounts.forEach { a ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(a.email, color = Ink.text, style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                            Text("Allow in Google", color = Ink.signal, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable {
                                scope.launch {
                                    try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(Api.get(context).writeAccessUrl(a.id).authUrl))) }
                                    catch (t: Throwable) { onInfo(t.userMessage()) }
                                }
                            }.padding(6.dp))
                        }
                    }
                }
            },
            confirmButton = {
                PrimaryButton("I've allowed it, try again") {
                    val r = retry
                    needAccess = null
                    scope.launch { try { r() } catch (t: Throwable) { onInfo(t.userMessage()) } }
                }
            },
            dismissButton = { TextButton(onClick = { needAccess = null }) { Text("Not now", color = Ink.text2) } },
            containerColor = Ink.surface, shape = Radius.xl,
        )
    }

    if (snoozing) SnoozeDialog(onDismiss = { snoozing = false }) { until ->
        snoozing = false
        scope.launch {
            try {
                val r = Api.get(context).snooze(SnoozeIn(listOf(m.id), until.format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)))
                onInfo("Snoozed until ${until.format(DateTimeFormatter.ofPattern("EEE d MMM, h:mm a"))}" + if (r.any { !it.inGmail }) " (hidden in Sift; Gmail unchanged)" else "")
                onLeave()
            } catch (t: Throwable) { onInfo(t.userMessage()) }
        }
    }

    if (labelling) {
        var labels by remember { mutableStateOf<List<LabelDto>?>(null) }
        var name by remember { mutableStateOf("") }
        LaunchedEffect(Unit) { labels = runCatching { Api.get(context).labels(m.accountId) }.getOrDefault(emptyList()) }
        AlertDialog(
            onDismissRequest = { labelling = false },
            title = { Text("Add a Gmail label") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Field(name, { name = it }, "Label", placeholder = "New or existing label")
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        labels?.forEach { l -> Chip(l.name, false) { labelling = false; act("label", label = l.name) } }
                    }
                }
            },
            confirmButton = { PrimaryButton("Add label", enabled = name.isNotBlank()) { labelling = false; act("label", label = name.trim()) } },
            dismissButton = { TextButton(onClick = { labelling = false }) { Text("Cancel", color = Ink.text2) } },
            containerColor = Ink.surface, shape = Radius.xl,
        )
    }
}

private val DONE = mapOf(
    "archive" to "Archived", "unarchive" to "Back in the inbox", "read" to "Marked read", "unread" to "Marked unread",
    "star" to "Starred", "unstar" to "Star removed", "label" to "Label added", "spam" to "Reported as spam", "trash" to "Moved to Gmail's trash",
)

fun snoozeChoices(now: ZonedDateTime = ZonedDateTime.now()): List<Pair<String, ZonedDateTime>> {
    val out = mutableListOf<Pair<String, ZonedDateTime>>()
    val later = now.plusHours(3).truncatedTo(ChronoUnit.HOURS)
    if (later.toLocalDate() == now.toLocalDate()) out += "Later today" to later
    val tomorrow = now.plusDays(1).toLocalDate()
    out += "Tomorrow morning" to tomorrow.atTime(9, 0).atZone(now.zone)
    out += "Tomorrow evening" to tomorrow.atTime(18, 0).atZone(now.zone)
    val saturday = now.toLocalDate().with(TemporalAdjusters.next(DayOfWeek.SATURDAY))
    if (saturday != tomorrow) out += "This weekend" to saturday.atTime(9, 0).atZone(now.zone)
    out += "Next week" to now.toLocalDate().with(TemporalAdjusters.next(DayOfWeek.MONDAY)).atTime(9, 0).atZone(now.zone)
    return out
}

@Composable
private fun SnoozeDialog(onDismiss: () -> Unit, onPick: (ZonedDateTime) -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Snooze until…") },
        text = {
            Column {
                snoozeChoices().forEach { (label, at) ->
                    Row(Modifier.fillMaxWidth().clickable { onPick(at) }.padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(label, color = Ink.text, style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                        Text(at.format(DateTimeFormatter.ofPattern("EEE h:mm a")), color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                    }
                }
                Text("It comes back to your feed and notifies you. With write access it's also archived in Gmail and returns to the inbox. A reply brings it back early.",
                    color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}
