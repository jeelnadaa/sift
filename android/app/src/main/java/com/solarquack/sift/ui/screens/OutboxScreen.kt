package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.DraftList
import com.solarquack.sift.data.FollowUpList
import com.solarquack.sift.data.OutboxList
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.fullTime
import com.solarquack.sift.ui.relativeTime
import com.solarquack.sift.ui.theme.Ink
import kotlinx.coroutines.launch

/** Outbox (Phase 4): Gmail drafts of every account, mail scheduled to send later, follow-up
 * reminders, and what Sift sent lately (or couldn't send). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun OutboxScreen(onBack: () -> Unit, onCompose: () -> Unit, onOpenDraft: (String, String) -> Unit, onOpenThread: (String, String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var tab by remember { mutableStateOf("drafts") }
    var drafts by remember { mutableStateOf<DraftList?>(null) }
    var box by remember { mutableStateOf<OutboxList?>(null) }
    var follows by remember { mutableStateOf<FollowUpList?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    fun load() = scope.launch {
        try {
            val api = Api.get(context)
            box = api.outbox(); follows = api.followUps(); drafts = api.drafts(); error = null
        } catch (t: Throwable) { error = t.userMessage() }
    }
    fun act(done: String, block: suspend () -> Unit) = scope.launch {
        try { block(); android.widget.Toast.makeText(context, done, android.widget.Toast.LENGTH_SHORT).show(); load() } catch (t: Throwable) { error = t.userMessage() }
    }
    LaunchedEffect(Unit) { load() }
    LaunchedEffect(Unit) { com.solarquack.sift.data.LiveEvents.changes.collect { load() } }

    com.solarquack.sift.ui.Refreshable({ load().join() }) {
        LazyColumn(Modifier.fillMaxSize().background(Ink.bg), contentPadding = PaddingValues(start = 18.dp, end = 18.dp, top = 18.dp, bottom = 96.dp)) {
            item {
                Text("‹ Back", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(vertical = 6.dp))
                Text("Outbox", style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.padding(vertical = 8.dp))
                PrimaryButton("New mail", Modifier.fillMaxWidth(), onClick = onCompose)
                FlowRow(Modifier.padding(vertical = 14.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    val waiting = follows?.followUps?.count { it.status == "waiting" } ?: 0
                    listOf(
                        "drafts" to "Drafts${drafts?.drafts?.size?.takeIf { it > 0 }?.let { " · $it" } ?: ""}",
                        "scheduled" to "Scheduled${box?.scheduled?.size?.takeIf { it > 0 }?.let { " · $it" } ?: ""}",
                        "follow" to "Follow-ups${if (waiting > 0) " · $waiting" else ""}",
                        "recent" to "Sent by Sift",
                    ).forEach { (k, label) -> Chip(label, tab == k) { tab = k } }
                }
                error?.let { Banner(it, Ink.urgent, "Retry") { load() } }
            }
            when (tab) {
                "drafts" -> {
                    val list = drafts
                    if (list == null) item { Text("Loading drafts from Gmail…", color = Ink.text3) }
                    else {
                        if (list.failedAccounts.isNotEmpty()) item { Banner("Couldn't load drafts of ${list.failedAccounts.joinToString()}.", Ink.warn) }
                        if (list.drafts.isEmpty()) item { Text("No drafts.", color = Ink.text3, modifier = Modifier.padding(vertical = 24.dp)) }
                        items(list.drafts, key = { it.accountId + it.draftId }) { d ->
                            Line(d.subject.ifBlank { "(no subject)" }, listOf(d.to.ifBlank { "No recipient" }, d.accountEmail).joinToString(" · "), d.snippet,
                                onClick = { onOpenDraft(d.accountId, d.draftId) }) {
                                d.outbox?.let { Tag("Sends ${fullTime(it.sendAt)}", Ink.normal) }
                            }
                        }
                    }
                }
                "scheduled" -> {
                    val list = box?.scheduled
                    if (list == null) item { Text("Loading…", color = Ink.text3) }
                    else {
                        if (list.isEmpty()) item { Text("Nothing scheduled. In a draft, use \"Send later…\".", color = Ink.text3, modifier = Modifier.padding(vertical = 24.dp)) }
                        items(list, key = { it.id }) { r ->
                            Line(r.subject ?: "(no subject)", "${r.recipients ?: ""} · ${r.accountEmail ?: ""}",
                                if (r.status == "sending") "Sending…" else "Sends ${fullTime(r.sendAt)}", onClick = { onOpenDraft(r.accountId, r.draftId) }) {
                                r.error?.let { Text(it, color = Ink.urgent, style = MaterialTheme.typography.bodySmall) }
                                if (r.status == "scheduled") Row {
                                    LinkText("Send now") { act("Sending now") { Api.get(context).sendNow(r.id) } }
                                    LinkText("Unschedule") { act("Unscheduled. It stays a draft") { Api.get(context).cancelSend(r.id) } }
                                }
                            }
                        }
                    }
                }
                "follow" -> {
                    val list = follows?.followUps
                    if (list == null) item { Text("Loading…", color = Ink.text3) }
                    else {
                        if (list.isEmpty()) item { Text("No follow-ups. When sending, pick \"Remind me if no reply\".", color = Ink.text3, modifier = Modifier.padding(vertical = 24.dp)) }
                        items(list, key = { it.id }) { f ->
                            Line(f.subject ?: "(no subject)", "${f.recipients ?: ""} · sent ${relativeTime(f.sentAt)} ago", null, onClick = { onOpenThread(f.accountId, f.threadId) }) {
                                when (f.status) {
                                    "waiting" -> Row {
                                        Tag("Reminds ${fullTime(f.dueAt)}")
                                        LinkText("Cancel") { act("Reminder cancelled") { Api.get(context).cancelFollowUp(f.id) } }
                                    }
                                    "replied" -> Tag("Replied", Ink.signal)
                                    "reminded" -> Tag("No reply, reminded", Ink.warn)
                                    else -> Tag("Cancelled")
                                }
                            }
                        }
                    }
                }
                else -> {
                    val list = box?.recent
                    if (list == null) item { Text("Loading…", color = Ink.text3) }
                    else {
                        if (list.isEmpty()) item { Text("Nothing sent through Sift yet.", color = Ink.text3, modifier = Modifier.padding(vertical = 24.dp)) }
                        items(list, key = { it.id }) { r ->
                            Line(r.subject ?: "(no subject)", "${r.recipients ?: ""} · ${relativeTime(r.sentAt ?: r.sendAt)}", r.error?.takeIf { r.status == "failed" },
                                onClick = { if (r.status == "sent") r.threadId?.let { onOpenThread(r.accountId, it) } else onOpenDraft(r.accountId, r.draftId) }) {
                                when (r.status) { "sent" -> Tag("Sent", Ink.signal); "failed" -> Tag("Not sent", Ink.urgent); else -> Tag("Undone") }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Line(title: String, sub: String, extra: String?, onClick: () -> Unit, trailing: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 12.dp)) {
        Text(title, color = Ink.text, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(sub, color = Ink.text3, style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
        extra?.takeIf { it.isNotBlank() }?.let { Text(it, color = Ink.text2, style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis) }
        Row(Modifier.padding(top = 6.dp)) { trailing() }
    }
    HorizontalDivider(color = Ink.line)
}

@Composable
private fun LinkText(text: String, onClick: () -> Unit) {
    Text(text, color = Ink.signal, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onClick).padding(horizontal = 10.dp, vertical = 4.dp))
}
