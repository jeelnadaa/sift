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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
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

/** One entry in the Actions sheet. `section` groups entries under a small heading. */
data class SheetItem(val label: String, val hint: String? = null, val danger: Boolean = false, val section: String = "Gmail", val onClick: () -> Unit)

/** Every action for one conversation behind a single "Actions" button (owner, 2026-10-24: the
 * phone screen was crowded with buttons). The sheet scrolls; tapping an entry closes it and runs
 * it. Gmail actions ask once per account for write access ("Allow in Google"), then retry. */
@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
fun MailActionsButton(m: MessageDto, extra: List<SheetItem>, onChanged: () -> Unit, onLeave: () -> Unit, onInfo: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var needAccess by remember { mutableStateOf<Pair<List<WriteAccessAccount>, suspend () -> Unit>?>(null) }
    var snoozing by remember { mutableStateOf(false) }
    var labelling by remember { mutableStateOf(false) }
    var sheetOpen by remember { mutableStateOf(false) }

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

    val gmail = listOf(
        if (m.inInbox) SheetItem("Archive", "Out of the inbox, still searchable") { act("archive", leave = true) }
        else SheetItem("Move to inbox", "Back into Gmail's inbox") { act("unarchive") },
        SheetItem(if (m.unread) "Mark read" else "Mark unread", "For the whole conversation (also in Gmail when the account allows changes)") {
            scope.launch {
                try {
                    val r = Api.get(context).readState(com.solarquack.sift.data.ReadStateIn(listOf(m.id), !m.unread))
                    onInfo((if (m.unread) "Marked read" else "Marked unread") + if (r.siftOnly.isNotEmpty()) " in Sift (Gmail unchanged)" else "")
                    onChanged()
                } catch (t: Throwable) { onInfo(t.userMessage()) }
            }
        },
        SheetItem(if (m.starred) "Remove star" else "Star", null) { act(if (m.starred) "unstar" else "star") },
        SheetItem("Label…", "Add a Gmail label") { labelling = true },
        SheetItem("Snooze…", "Hide it until later; it comes back and notifies you") { snoozing = true },
    )
    val danger = listOf(
        SheetItem("Report spam", "Moves it to Gmail's spam", danger = true, section = "Remove") { act("spam", leave = true) },
        SheetItem("Move to trash", "Gmail keeps it 30 days; Sift never deletes", danger = true, section = "Remove") { act("trash", leave = true) },
    )
    val all = gmail + extra + danger

    GhostButton("Actions…", modifier = Modifier.fillMaxWidth()) { sheetOpen = true }

    if (sheetOpen) {
        ModalBottomSheet(
            onDismissRequest = { sheetOpen = false },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            containerColor = Ink.surface,
            shape = androidx.compose.foundation.shape.RoundedCornerShape(topStart = 14.dp, topEnd = 14.dp),
        ) {
            LazyColumn(Modifier.fillMaxWidth().padding(bottom = 24.dp)) {
                var lastSection = ""
                all.forEach { entry ->
                    if (entry.section != lastSection) {
                        val title = entry.section
                        lastSection = title
                        item(key = "h-$title") {
                            Text(title.uppercase(), color = Ink.text3, style = MaterialTheme.typography.labelSmall,
                                modifier = Modifier.padding(start = 22.dp, top = 14.dp, bottom = 6.dp))
                        }
                    }
                    item(key = entry.label) {
                        Column(
                            Modifier.fillMaxWidth().clickable { sheetOpen = false; entry.onClick() }.padding(horizontal = 22.dp, vertical = 12.dp),
                        ) {
                            Text(entry.label, color = if (entry.danger) Ink.urgent else Ink.text, style = MaterialTheme.typography.titleSmall)
                            entry.hint?.let { Text(it, color = Ink.text3, style = MaterialTheme.typography.bodySmall) }
                        }
                    }
                }
            }
        }
    }

    needAccess?.let { (accounts, retry) ->
        WriteAccessDialog(accounts, onDismiss = { needAccess = null }, onInfo = onInfo) {
            needAccess = null
            scope.launch { try { retry() } catch (t: Throwable) { onInfo(t.userMessage()) } }
        }
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

/** "Allow Sift to change mail?": opens Google's page for each account; "try again" re-runs the
 * action that needed it (mail actions, and writing and sending mail). */
@Composable
fun WriteAccessDialog(accounts: List<WriteAccessAccount>, onDismiss: () -> Unit, onInfo: (String) -> Unit, onRetry: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Allow Sift to change mail?") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Archive, labels, read/unread, star, trash, snooze, and writing and sending mail change things in Gmail, so Google asks once per account. Sift never sends or deletes mail on its own: only when you press Send.",
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
        confirmButton = { PrimaryButton("I've allowed it, try again", onClick = onRetry) },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Not now", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}
