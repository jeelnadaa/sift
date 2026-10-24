package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.QueryChip
import com.solarquack.sift.data.QueryIn
import com.solarquack.sift.data.SavedSearchDto
import com.solarquack.sift.data.SavedSearchIn
import com.solarquack.sift.data.SearchHit
import com.solarquack.sift.data.SemanticStatus
import com.solarquack.sift.data.TextIn
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.Field
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch

private val QUICK = listOf("is:unread" to "Unread", "has:attachment" to "Attachment", "newer_than:7d" to "Last 7 days",
    "newer_than:30d" to "Last 30 days", "is:silenced" to "Silenced", "priority:urgent" to "Urgent")

/** Search (brief section 19) on the phone: Gmail syntax plus Sift filters across accounts, or by
 * meaning with the user's key. Results keep loading as you scroll. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SearchScreen(onOpenMail: (String) -> Unit, onOpenThread: (String, String) -> Unit, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var draft by rememberSaveable { mutableStateOf("") }
    var query by rememberSaveable { mutableStateOf("") }
    var meaning by rememberSaveable { mutableStateOf(false) }
    var chips by remember { mutableStateOf<List<QueryChip>>(emptyList()) }
    var hits by remember { mutableStateOf<List<SearchHit>>(emptyList()) }
    var next by remember { mutableStateOf<String?>(null) }
    var total by remember { mutableStateOf(0) }
    var estimated by remember { mutableStateOf(false) }
    var failed by remember { mutableStateOf<List<String>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var saved by remember { mutableStateOf<List<SavedSearchDto>>(emptyList()) }
    var sem by remember { mutableStateOf<SemanticStatus?>(null) }
    var english by remember { mutableStateOf("") }
    var saving by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()

    LaunchedEffect(Unit) {
        runCatching { saved = Api.get(context).savedSearches() }
        runCatching { sem = Api.get(context).semanticStatus() }
    }

    suspend fun page(cursor: String?): Pair<List<SearchHit>, String?> {
        val api = Api.get(context)
        return if (meaning) {
            val r = api.semantic(query, cursor?.toInt() ?: 0)
            total = r.total
            r.items to r.nextOffset?.toString()
        } else {
            val r = api.search(query, cursor)
            total = r.total; estimated = r.estimated; failed = r.failedAccounts
            if (cursor == null) chips = r.chips
            r.items to r.nextCursor
        }
    }

    LaunchedEffect(query, meaning) {
        hits = emptyList(); next = null; error = null
        if (query.isBlank()) { chips = emptyList(); return@LaunchedEffect }
        loading = true
        try {
            if (meaning) chips = Api.get(context).parseQuery(QueryIn(query)).chips
            val (first, cursor) = page(null)
            hits = first; next = cursor
            listState.scrollToItem(0)
        } catch (t: Throwable) { error = t.userMessage() } finally { loading = false }
    }
    fun loadMore() {
        val cursor = next ?: return
        if (loading) return
        loading = true
        scope.launch {
            try {
                val (more, n) = page(cursor)
                val seen = hits.map { it.accountId + it.threadId + it.id }.toSet()
                hits = hits + more.filter { (it.accountId + it.threadId + it.id) !in seen }
                next = n
            } catch (t: Throwable) { error = t.userMessage() } finally { loading = false }
        }
    }
    val nearEnd by remember { derivedStateOf { listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index?.let { it >= listState.layoutInfo.totalItemsCount - 6 } ?: false } }
    LaunchedEffect(nearEnd, next) { if (nearEnd && next != null) loadMore() }

    fun run(q: String) { draft = q.trim(); query = q.trim() }
    fun add(token: String) = run((query.split(" ").filter { it.isNotBlank() && it != token } + token).joinToString(" "))
    val aiOn = sem?.aiEnabled == true

    LazyColumn(Modifier.fillMaxSize().background(Ink.bg), state = listState, contentPadding = PaddingValues(horizontal = 14.dp, vertical = 12.dp)) {
        item {
            Text("‹ Back", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(vertical = 6.dp))
            Text("Search", style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.padding(bottom = 8.dp))
            Field(draft, { draft = it }, "Search all accounts", placeholder = "from:kotak has:attachment · folder:Work")
            Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                PrimaryButton("Search", enabled = draft.isNotBlank()) { run(draft) }
                Chip("Keywords", !meaning) { meaning = false }
                Chip(if (aiOn) "By meaning" else "By meaning (needs key)", meaning) { if (aiOn) meaning = true }
            }
            if (chips.isNotEmpty()) {
                FlowRow(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    chips.forEach { c ->
                        Chip((if (c.kind == "sift") "◆ " else "") + c.label + "  ×", true) {
                            run(chips.filter { it != c }.joinToString(" ") { it.text })
                        }
                    }
                }
            }
            Row(Modifier.horizontalScroll(rememberScrollState()).padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                QUICK.forEach { (tok, label) -> Chip(label, false) { add(tok) } }
            }
            Text(
                "◆ Sift filters (folder, tag, priority, company, silenced…) only see mail Sift has seen, from when you connected the account. " +
                    "Gmail syntax (from:, subject:, has:attachment, newer_than:…) searches all your mail in Gmail.",
                color = Ink.text3, style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(top = 10.dp).fillMaxWidth().background(Ink.bg2, Radius.sm).padding(10.dp),
            )
            if (saved.isNotEmpty()) {
                Row(Modifier.horizontalScroll(rememberScrollState()).padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("Saved", color = Ink.text3, style = MaterialTheme.typography.labelMedium)
                    saved.forEach { s -> Chip((if (s.pinned) "📌 " else "") + s.name + if (s.notify) " 🔔" else "", query == s.query) { run(s.query) } }
                }
            }
            Column(Modifier.padding(top = 12.dp)) {
                if (aiOn) {
                    Field(english, { english = it }, "Or describe it", placeholder = "mails from Walmart last week")
                    Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        GhostButton("Turn into search") {
                            scope.launch {
                                try { val r = Api.get(context).searchFromText(TextIn(english.trim())); run(r.query) } catch (t: Throwable) { error = t.userMessage() }
                            }
                        }
                        if (query.isNotBlank()) GhostButton("Save search") { saving = true }
                    }
                } else {
                    Text("Describing a search in plain English and searching by meaning need your AI key (Settings). Gmail syntax works without it.",
                        color = Ink.warn, style = MaterialTheme.typography.bodySmall)
                    if (query.isNotBlank()) Box(Modifier.padding(top = 6.dp)) { GhostButton("Save search") { saving = true } }
                }
            }
            error?.let { Box(Modifier.padding(top = 10.dp)) { Banner(it, Ink.urgent) } }
            if (failed.isNotEmpty()) Box(Modifier.padding(top = 10.dp)) { Banner("Couldn't search ${failed.joinToString()} right now.", Ink.warn) }
            if (query.isNotBlank() && !loading && error == null) {
                Text(
                    when {
                        hits.isEmpty() -> if (meaning) "Nothing close enough in meaning." else "No mail matches."
                        meaning -> "$total matches by meaning"
                        estimated -> "${hits.size} conversations${if (next != null) " so far, more as you scroll" else ""}"  // Gmail's own counts are only estimates
                        else -> "$total conversation${if (total == 1) "" else "s"}"
                    },
                    color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 14.dp, bottom = 4.dp),
                )
            }
        }
        items(hits, key = { it.id ?: (it.accountId + ":" + it.threadId) }) { h ->
            Box {
                MailRow(h.asMessage()) { if (h.id != null) onOpenMail(h.id) else onOpenThread(h.accountId, h.threadId) }
                Row(Modifier.align(Alignment.BottomEnd).padding(bottom = 8.dp, end = 4.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    h.score?.let { Tag("${(it * 100).toInt()}%", Ink.signal) }
                    if (h.id == null) Tag("Gmail only")
                }
            }
        }
        if (loading) item { Text("Searching…", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(vertical = 16.dp)) }
    }

    if (saving) {
        var name by remember { mutableStateOf("") }
        var notify by remember { mutableStateOf(false) }
        var smart by remember { mutableStateOf(false) }
        AlertDialog(
            onDismissRequest = { saving = false },
            title = { Text("Save this search") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Field(name, { name = it }, "Name", placeholder = "e.g. Unreplied recruiters")
                    Text(query, color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Notify me of new matches", color = Ink.text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                        Switch(notify, { notify = it }, colors = SwitchDefaults.colors(checkedTrackColor = Ink.signal, checkedThumbColor = Ink.signalInk))
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Show as a smart folder", color = Ink.text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                        Switch(smart, { smart = it }, colors = SwitchDefaults.colors(checkedTrackColor = Ink.signal, checkedThumbColor = Ink.signalInk))
                    }
                }
            },
            confirmButton = {
                PrimaryButton("Save", enabled = name.isNotBlank()) {
                    saving = false
                    scope.launch {
                        try {
                            Api.get(context).saveSearch(SavedSearchIn(name.trim(), query, notify = notify, smartFolder = smart))
                            saved = Api.get(context).savedSearches()
                        } catch (t: Throwable) { error = t.userMessage() }
                    }
                }
            },
            dismissButton = { TextButton(onClick = { saving = false }) { Text("Cancel", color = Ink.text2) } },
            containerColor = Ink.surface, shape = Radius.xl,
        )
    }
}

/** A conversation Sift never stored (older mail found by search), read straight from Gmail. */
@Composable
fun ReadThreadScreen(accountId: String, threadId: String, onBack: () -> Unit) {
    androidx.compose.foundation.lazy.LazyColumn(Modifier.fillMaxSize().background(Ink.bg), contentPadding = PaddingValues(18.dp)) {
        item {
            Text("‹ Back", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(vertical = 6.dp))
            Text("Older mail Sift never processed, read straight from Gmail.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(vertical = 8.dp))
            ThreadView(null, accountId, threadId)
        }
    }
}
