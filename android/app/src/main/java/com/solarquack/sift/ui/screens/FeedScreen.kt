package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
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
import com.solarquack.sift.data.AccountDto
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.FeedItem
import com.solarquack.sift.data.GroupDto
import com.solarquack.sift.data.GroupItem
import com.solarquack.sift.data.MailItem
import com.solarquack.sift.data.MessageDto
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Avatar
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.PriorityDot
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.accountColor
import com.solarquack.sift.ui.relativeTime
import com.solarquack.sift.ui.theme.Ink
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FeedScreen(silenced: Boolean = false, onOpen: (String) -> Unit, onAccounts: () -> Unit, onOpenGroup: (String) -> Unit = {}, onSearch: (() -> Unit)? = null) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var items by remember { mutableStateOf<List<FeedItem>>(emptyList()) }
    var askGrouping by remember { mutableStateOf(false) }
    var accounts by remember { mutableStateOf<List<AccountDto>>(emptyList()) }
    var priority by remember { mutableStateOf<String?>(null) }
    var account by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    // infinite scroll: the cursor of the next (older) page, null when there is none
    var next by remember { mutableStateOf<String?>(null) }
    var grouped by remember { mutableStateOf(false) }
    var loadingMore by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()

    suspend fun page(before: String?): Pair<List<FeedItem>, String?> {
        val api = Api.get(context)
        return if (grouped) {
            val p = api.groupedFeed(priority = priority, accountId = account, before = before)
            p.items.map { o ->
                if (o["type"]?.jsonPrimitive?.contentOrNull == "group") GroupItem(Api.json.decodeFromJsonElement(GroupDto.serializer(), o))
                else MailItem(Api.json.decodeFromJsonElement(MessageDto.serializer(), o))
            } to p.nextBefore
        } else {
            val p = api.messages(priority = priority, accountId = account, view = if (silenced) "silenced" else "feed", before = before)
            p.items.map { MailItem(it) } to p.nextBefore
        }
    }

    fun load() {
        scope.launch {
            loading = true
            try {
                val api = Api.get(context)
                accounts = api.accounts()
                val grouping = if (silenced) null else runCatching { api.grouping() }.getOrNull()
                if (grouping?.shouldAsk == true && !GroupingPrompt.askedThisOpen) { GroupingPrompt.askedThisOpen = true; askGrouping = true }
                grouped = grouping?.groupingEnabled == "yes"
                val (first, cursor) = page(null)
                items = first
                next = cursor
                listState.scrollToItem(0)
                error = null
            } catch (t: Throwable) {
                error = t.userMessage()
            } finally {
                loading = false
            }
        }
    }

    fun loadMore() {
        val cursor = next ?: return
        if (loadingMore || loading) return
        loadingMore = true
        scope.launch {
            try {
                val (more, nextCursor) = page(cursor)
                val seen = items.map { it.key }.toSet()
                items = items + more.filter { it.key !in seen }
                next = nextCursor
            } catch (t: Throwable) {
                error = t.userMessage()
            } finally {
                loadingMore = false
            }
        }
    }

    // fetch the next page when the list gets within 8 rows of its end
    val nearEnd by remember { derivedStateOf { listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index?.let { it >= listState.layoutInfo.totalItemsCount - 8 } ?: false } }
    LaunchedEffect(nearEnd, next) { if (nearEnd && next != null) loadMore() }
    LaunchedEffect(priority, account, silenced) { load() }
    if (askGrouping) GroupingPromptDialog { answer -> askGrouping = false; if (answer == "yes") load() }

    Column(Modifier.fillMaxSize().background(Ink.bg)) {
        Row(Modifier.fillMaxWidth().padding(start = 18.dp, end = 14.dp, top = 18.dp, bottom = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(if (silenced) "Silenced" else "Feed", style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.weight(1f))
            onSearch?.let { go ->
                Text("⌕ Search", color = Ink.text2, style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.background(Ink.surface, com.solarquack.sift.ui.theme.Radius.md).clickable(onClick = go).padding(horizontal = 12.dp, vertical = 8.dp))
            }
        }
        accounts.filter { it.status == "active" && it.stalled }.forEach { a ->
            Box(Modifier.padding(horizontal = 14.dp, vertical = 4.dp)) {
                val since = (a.checkFailingSince ?: a.lastCheckOkAt)?.let { com.solarquack.sift.ui.fullTime(it) }
                Banner("Sift can't check ${a.email}${since?.let { " since $it" } ?: ""}${a.lastCheckError?.let { " ($it)" } ?: ""}. It keeps retrying and catches up on its own.",
                    Ink.urgent, "Open", onAccounts)
            }
        }
        val trouble = accounts.filter { it.status != "active" }
        if (trouble.isNotEmpty()) {
            Box(Modifier.padding(horizontal = 14.dp, vertical = 4.dp)) {
                val a = trouble.first()
                Banner(
                    if (a.status == "blocked") "${a.email} may be blocked by its administrator." else "${a.email} needs to reconnect. Other accounts are fine.",
                    if (a.status == "blocked") Ink.warn else Ink.urgent, "Open", onAccounts,
                )
            }
        }
        Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 14.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Chip("All accounts", account == null) { account = null }
            accounts.forEach { a -> Chip(a.label ?: a.email, account == a.id, dot = accountColor(a.color, a.id)) { account = if (account == a.id) null else a.id } }
        }
        if (!silenced) {
            Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 14.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Chip("All", priority == null) { priority = null }
                listOf("urgent", "normal", "digest").forEach { p -> Chip(p, priority == p, dot = Ink.tier(p)) { priority = if (priority == p) null else p } }
            }
        } else {
            Text("Saved and searchable, never notified. Check here if a rule looks too greedy.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 18.dp, vertical = 4.dp))
        }
        PullToRefreshBox(isRefreshing = loading, onRefresh = { load() }, modifier = Modifier.fillMaxSize()) {
            LazyColumn(Modifier.fillMaxSize(), state = listState, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 14.dp, vertical = 8.dp)) {
                error?.let { item { Banner(it, Ink.urgent, "Retry") { load() } } }
                if (!loading && error == null && items.isEmpty()) {
                    item {
                        Text(
                            if (silenced) "Nothing silenced yet." else "No mail yet. New mail shows up here within seconds.",
                            color = Ink.text3, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 32.dp),
                        )
                    }
                }
                items(items, key = { it.key }) { item ->
                    when (item) {
                        is MailItem -> MailRow(item.m) { onOpen(item.m.id) }
                        is GroupItem -> GroupRow(item.g) { onOpenGroup(item.g.id) }
                    }
                }
                if (loadingMore) item {
                    Text("Loading older mail…", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp))
                }
            }
        }
    }
}

@Composable
fun MailRow(m: MessageDto, onClick: () -> Unit) {
    val urgent = m.priority == "urgent"
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 11.dp, horizontal = 4.dp), verticalAlignment = Alignment.Top) {
        Box(Modifier.padding(top = 14.dp, end = 10.dp)) { PriorityDot(m.priority) }
        Avatar(m.senderName ?: m.sender ?: "?", if (urgent) Ink.urgent else null)
        Column(Modifier.weight(1f).padding(start = 10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    m.senderName?.takeIf { it.isNotBlank() } ?: m.sender ?: "Unknown", color = Ink.text, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.titleSmall.copy(fontWeight = if (m.unread) FontWeight.Bold else FontWeight.Medium), modifier = Modifier.weight(1f, fill = false),
                )
                m.category?.takeIf { it != "other" }?.let { Tag(it, Ink.tier(m.priority)) }
                m.company?.let { Tag(it) }
            }
            Text(m.summary ?: m.subject ?: "(no subject)", color = if (m.unread) Ink.text else Ink.text2, style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            m.account?.let { Text(it, color = accountColor(m.accountColor, m.accountId), style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 2.dp)) }
        }
        Text(relativeTime(m.receivedAt), color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(start = 8.dp, top = 2.dp))
    }
    HorizontalDivider(color = Ink.line)
}
