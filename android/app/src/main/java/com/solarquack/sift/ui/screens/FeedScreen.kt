package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
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
import androidx.compose.ui.draw.alpha
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

object FeedSessionCache {
    var items: List<FeedItem> = emptyList()
    var next: String? = null
    var priority: String? = null
    var account: String? = null
    var silenced: Boolean = false
    var grouped: Boolean = false
    var accounts: List<AccountDto> = emptyList()
    var scrollIndex: Int = 0
    var scrollOffset: Int = 0

    fun matches(p: String?, a: String?, s: Boolean): Boolean =
        priority == p && account == a && silenced == s
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FeedScreen(silenced: Boolean = false, onOpen: (String) -> Unit, onAccounts: () -> Unit, onOpenGroup: (String) -> Unit = {}, onSearch: (() -> Unit)? = null, onWrite: (() -> Unit)? = null,
               onAsk: (() -> Unit)? = null) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var priority by remember { mutableStateOf<String?>(null) }
    var account by remember { mutableStateOf<String?>(null) }

    val cachedInitialItems = remember(priority, account, silenced) {
        if (FeedSessionCache.matches(priority, account, silenced) && FeedSessionCache.items.isNotEmpty()) {
            FeedSessionCache.items
        } else if (!silenced && com.solarquack.sift.data.Session.feedGrouped(context)) {
            // grouping on: the feed is the grouped list (group rows + mail rows)
            com.solarquack.sift.data.Offline.getCachedGroupedFeed(context, priority, account)?.let { feedItems(it) } ?: emptyList()
        } else {
            val offlineFeed = com.solarquack.sift.data.Offline.getCachedFeed(context, priority, account, if (silenced) "silenced" else "feed")
            offlineFeed?.items?.map { MailItem(it) } ?: emptyList()
        }
    }

    var items by remember(priority, account, silenced) { mutableStateOf(cachedInitialItems) }
    var askGrouping by remember { mutableStateOf(false) }
    var accounts by remember { mutableStateOf(FeedSessionCache.accounts) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember(priority, account, silenced) { mutableStateOf(cachedInitialItems.isEmpty()) }
    var refreshing by remember { mutableStateOf(false) }
    // a saved list is on screen while the fresh one loads (slow connection): say so, never blank
    var updating by remember { mutableStateOf(false) }
    // infinite scroll: the cursor of the next (older) page, null when there is none
    var next by remember(priority, account, silenced) {
        mutableStateOf(if (FeedSessionCache.matches(priority, account, silenced)) FeedSessionCache.next else null)
    }
    var grouped by remember { mutableStateOf(if (FeedSessionCache.items.isNotEmpty()) FeedSessionCache.grouped else !silenced && com.solarquack.sift.data.Session.feedGrouped(context)) }
    var loadingMore by remember { mutableStateOf(false) }
    var pinnedOnly by remember { mutableStateOf(false) }
    val listState = rememberLazyListState(
        initialFirstVisibleItemIndex = if (FeedSessionCache.matches(priority, account, silenced)) FeedSessionCache.scrollIndex else 0,
        initialFirstVisibleItemScrollOffset = if (FeedSessionCache.matches(priority, account, silenced)) FeedSessionCache.scrollOffset else 0,
    )

    androidx.compose.runtime.DisposableEffect(Unit) {
        onDispose {
            FeedSessionCache.scrollIndex = listState.firstVisibleItemIndex
            FeedSessionCache.scrollOffset = listState.firstVisibleItemScrollOffset
        }
    }

    suspend fun page(before: String?): Pair<List<FeedItem>, String?> {
        val api = Api.get(context)
        return if (grouped) {
            val p = api.groupedFeed(priority = priority, accountId = account, before = before)
            feedItems(p) to p.nextBefore
        } else {
            val p = api.messages(priority = priority, accountId = account, view = if (silenced) "silenced" else "feed", before = before)
            p.items.map { MailItem(it) } to p.nextBefore
        }
    }

    fun syncCache(newItems: List<FeedItem>, newNext: String?) {
        FeedSessionCache.items = newItems
        FeedSessionCache.next = newNext
        FeedSessionCache.priority = priority
        FeedSessionCache.account = account
        FeedSessionCache.silenced = silenced
        FeedSessionCache.grouped = grouped
        FeedSessionCache.accounts = accounts
        // download the newest mails' contents in the background, so they open at once
        com.solarquack.sift.data.Prefetch.mails(context, newItems.mapNotNull { (it as? MailItem)?.m?.id })
    }

    fun load(isPullRefresh: Boolean = false) {
        scope.launch {
            if (isPullRefresh) {
                refreshing = true
            } else if (items.isEmpty()) {
                loading = true
            } else {
                updating = true
            }
            try {
                val api = Api.get(context)
                accounts = api.accounts()
                val grouping = if (silenced) null else runCatching { api.grouping() }.getOrNull()
                if (grouping?.shouldAsk == true && !GroupingPrompt.askedThisOpen && com.solarquack.sift.data.Offline.since.value == null) { GroupingPrompt.askedThisOpen = true; askGrouping = true }
                if (grouping != null) {
                    grouped = grouping.groupingEnabled == "yes"
                    com.solarquack.sift.data.Session.setFeedGrouped(context, grouped)
                }
                val (first, cursor) = page(null)
                items = first
                next = cursor
                if (isPullRefresh) listState.scrollToItem(0)
                error = null
                syncCache(first, cursor)
            } catch (t: Throwable) {
                if (items.isEmpty()) {
                    error = t.userMessage()
                }
            } finally {
                loading = false
                refreshing = false
                updating = false
            }
        }
    }

    fun loadMore() {
        val cursor = next ?: return
        if (loadingMore || loading || refreshing) return
        loadingMore = true
        scope.launch {
            try {
                val (more, nextCursor) = page(cursor)
                val seen = items.map { it.key }.toSet()
                val merged = items + more.filter { it.key !in seen }
                items = merged
                next = nextCursor
                syncCache(merged, nextCursor)
            } catch (t: Throwable) {
                error = t.userMessage()
            } finally {
                loadingMore = false
            }
        }
    }

    // mail that arrived while the list is scrolled down: "↑ N new mails" (tap to go to the top)
    var newCount by remember(priority, account, silenced) { mutableStateOf(0) }
    LaunchedEffect(listState) { androidx.compose.runtime.snapshotFlow { listState.firstVisibleItemIndex }.collect { if (it == 0) newCount = 0 } }

    // live: reload what's loaded, quietly (no spinner, no jump to the top)
    suspend fun refreshQuiet() {
        if (loading || loadingMore) return
        val api = Api.get(context)
        val count = items.size.coerceIn(30, 200)
        val before = items.mapTo(HashSet()) { it.key }
        runCatching {
            if (grouped) {
                val p = api.groupedFeed(priority = priority, accountId = account, limit = count)
                items = feedItems(p)
                next = p.nextBefore
            } else {
                val p = api.messages(priority = priority, accountId = account, view = if (silenced) "silenced" else "feed", limit = count)
                items = p.items.map { MailItem(it) }
                next = p.nextBefore
            }
            accounts = api.accounts()
            syncCache(items, next)  // so coming back from a mail shows this list, not an older one
            val arrived = items.count { it is MailItem && it.key !in before }
            if (before.isNotEmpty() && arrived > 0 && listState.firstVisibleItemIndex > 1) newCount += arrived
        }
    }
    LaunchedEffect(Unit) { com.solarquack.sift.data.LiveEvents.changes.collect { refreshQuiet() } }
    fun toggleRead(m: MessageDto) {
        val unread = !m.unread
        items = items.map { if (it is MailItem && it.m.id == m.id) MailItem(m.copy(unread = unread)) else it }
        scope.launch {
            try {
                val r = Api.get(context).readState(com.solarquack.sift.data.ReadStateIn(listOf(m.id), unread))
                android.widget.Toast.makeText(context, (if (unread) "Marked unread" else "Marked read") +
                    if (r.siftOnly.isNotEmpty()) " in Sift (Gmail unchanged)" else "", android.widget.Toast.LENGTH_SHORT).show()
            } catch (t: Throwable) {
                items = items.map { if (it is MailItem && it.m.id == m.id) MailItem(m) else it }
                error = t.userMessage()
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
            onAsk?.let { go ->
                Text("✦ Ask", color = Ink.signal, style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.padding(end = 8.dp).background(Ink.surface, com.solarquack.sift.ui.theme.Radius.md).clickable(onClick = go).padding(horizontal = 12.dp, vertical = 10.dp))
            }
            onSearch?.let { go ->
                Text("⌕ Search", color = Ink.text2, style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.background(Ink.surface, com.solarquack.sift.ui.theme.Radius.md).clickable(onClick = go).padding(horizontal = 12.dp, vertical = 10.dp))
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
                Chip("All", priority == null && !pinnedOnly) { priority = null; pinnedOnly = false }
                Chip("📌 Pinned", pinnedOnly) { pinnedOnly = !pinnedOnly }
                listOf("urgent", "normal", "digest").forEach { p -> Chip(p, priority == p, dot = Ink.tier(p)) { priority = if (priority == p) null else p } }
            }
        } else {
            Text("Saved and searchable, never notified. Check here if a rule looks too greedy.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 18.dp, vertical = 4.dp))
        }
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = { load(isPullRefresh = true) }, modifier = Modifier.fillMaxSize()) {
            LazyColumn(Modifier.fillMaxSize(), state = listState, contentPadding = androidx.compose.foundation.layout.PaddingValues(start = 14.dp, end = 14.dp, top = 8.dp, bottom = 96.dp)) {
                error?.let { item { Banner(it, Ink.urgent, "Retry") { load() } } }
                if (updating && !refreshing) item(key = "updating") {
                    Text("Updating…", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.fillMaxWidth().padding(bottom = 4.dp))
                }
                if (!loading && error == null && items.isEmpty()) {
                    item {
                        Text(
                            if (silenced) "Nothing silenced yet." else "No mail yet. New mail shows up here within seconds.",
                            color = Ink.text3, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 32.dp),
                        )
                    }
                }
                val displayItems = if (pinnedOnly) items.filter { it is MailItem && it.m.pinned } else items
                items(displayItems, key = { it.key }) { item ->
                    when (item) {
                        is MailItem -> MailRow(item.m, onLongPress = { toggleRead(item.m) }) { FeedSessionCache.scrollIndex = listState.firstVisibleItemIndex; FeedSessionCache.scrollOffset = listState.firstVisibleItemScrollOffset; onOpen(item.m.id) }
                        is GroupItem -> GroupRow(item.g) { onOpenGroup(item.g.id) }
                    }
                }
                if (loadingMore) item {
                    Text("Loading older mail…", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp))
                }
            }
            if (newCount > 0) {
                Text(
                    "↑ $newCount new ${if (newCount == 1) "mail" else "mails"}", color = Ink.bg, style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.align(Alignment.TopCenter).padding(top = 8.dp)
                        .background(Ink.signal, com.solarquack.sift.ui.theme.Radius.md)
                        .clickable { newCount = 0; scope.launch { listState.animateScrollToItem(0) } }
                        .padding(horizontal = 14.dp, vertical = 8.dp),
                )
            }
        }
    }
}

/** One mail in a list. Read mail is greyed out; unread is bright and bold. Long-press switches
 * read / unread (where the screen allows it). */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
fun MailRow(m: MessageDto, onLongPress: (() -> Unit)? = null, onClick: () -> Unit) {
    val urgent = m.priority == "urgent"
    val haptics = androidx.compose.ui.platform.LocalHapticFeedback.current
    Row(
        Modifier.fillMaxWidth()
            .combinedClickable(onClick = onClick, onLongClick = onLongPress?.let { f -> { haptics.performHapticFeedback(androidx.compose.ui.hapticfeedback.HapticFeedbackType.LongPress); f() } },
                onLongClickLabel = if (m.unread) "Mark read" else "Mark unread")
            .alpha(if (m.unread) 1f else 0.62f)
            .padding(vertical = 11.dp, horizontal = 4.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box(Modifier.padding(top = 14.dp, end = 10.dp)) { PriorityDot(m.priority) }
        Avatar(m.senderName ?: m.sender ?: "?", if (urgent) Ink.urgent else null)
        Column(Modifier.weight(1f).padding(start = 10.dp)) {
            Text(
                m.senderName?.takeIf { it.isNotBlank() } ?: m.sender ?: "Unknown", color = if (m.unread) Ink.text else Ink.text2, maxLines = 1, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.titleSmall.copy(fontWeight = if (m.unread) FontWeight.Bold else FontWeight.Medium),
            )
            Text(m.summary ?: m.subject ?: "(no subject)", color = if (m.unread) Ink.text else Ink.text3, style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            // tags sit with the account on the last line, so a long category never squeezes the sender
            Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (m.pinned) Text("📌", style = MaterialTheme.typography.bodySmall)
                if (m.hasNote || m.notesCount > 0) Text("📝", style = MaterialTheme.typography.bodySmall)
                m.category?.takeIf { it != "other" }?.let { Tag(it, Ink.tier(m.priority)) }
                m.company?.let { Tag(it) }
                m.account?.let { Text(it, color = accountColor(m.accountColor, m.accountId), style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis) }
            }
        }
        Text(relativeTime(m.receivedAt), color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(start = 8.dp, top = 2.dp))
    }
    HorizontalDivider(color = Ink.line)
}

/** A grouped feed page (group rows and mail rows) as list items. */
internal fun feedItems(p: com.solarquack.sift.data.GroupedPage): List<FeedItem> = p.items.map { o ->
    if (o["type"]?.jsonPrimitive?.contentOrNull == "group") GroupItem(Api.json.decodeFromJsonElement(GroupDto.serializer(), o))
    else MailItem(Api.json.decodeFromJsonElement(MessageDto.serializer(), o))
}
