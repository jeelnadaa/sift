package com.solarquack.sift.ui.screens

import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Popup
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.BulkIn
import com.solarquack.sift.data.BulkJobDto
import com.solarquack.sift.data.BulkPicked
import com.solarquack.sift.data.BulkUndo
import com.solarquack.sift.data.WriteAccessAccount
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.data.writeAccessNeeded
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.format.DateTimeFormatter

/** Rows picked on one list (owner, 2026-10-31): long-press starts, taps toggle, Back clears.
 * `all` means "everything this list shows", not only what is loaded. */
@Stable
class Picks {
    var keys by mutableStateOf(setOf<String>())
        private set
    var all by mutableStateOf(false)
    val active get() = keys.isNotEmpty() || all
    val size get() = keys.size
    fun has(key: String) = all || key in keys
    fun toggle(key: String) {
        if (all) { all = false }
        keys = if (key in keys) keys - key else keys + key
    }
    fun pick(keys: Collection<String>) { all = false; this.keys = keys.toSet() }
    fun clear() { keys = emptySet(); all = false }
}

/** A selection that starts empty again when any of `reset` changes (filters, account, tab). */
@Composable
fun rememberPicks(vararg reset: Any?): Picks {
    val picks = remember(*reset) { Picks() }
    BackHandler(enabled = picks.active) { picks.clear() }
    return picks
}

private const val ASK_OVER = 50  // more conversations than this are confirmed first

private val DONE = mapOf(
    "read" to "Marked read", "unread" to "Marked unread", "archive" to "Archived", "unarchive" to "Moved to the inbox",
    "trash" to "Moved to Gmail's trash", "untrash" to "Restored from trash", "spam" to "Reported as spam", "notspam" to "Not spam",
    "star" to "Starred", "unstar" to "Star removed", "important" to "Marked important", "unimportant" to "Marked not important",
    "label" to "Label added", "unlabel" to "Label removed", "pin" to "Pinned", "unpin" to "Unpinned", "file" to "Filed",
    "unfile" to "Taken out of the folder", "group_add" to "Added to the group", "group_remove" to "Taken out of the group",
    "mute" to "Muted", "unmute" to "Unmuted", "timeline" to "Added to the timeline", "untimeline" to "Taken off the timeline",
    "snooze" to "Snoozed",
)

// for "Archive 12 conversations?"
private val VERB = mapOf(
    "read" to "Mark read", "unread" to "Mark unread", "archive" to "Archive", "unarchive" to "Move to the inbox",
    "trash" to "Move to Gmail's trash", "spam" to "Report as spam", "star" to "Star", "unstar" to "Remove the star from",
    "important" to "Mark important", "unimportant" to "Mark not important", "pin" to "Pin", "unpin" to "Unpin",
    "file" to "File", "group_add" to "Add to the group", "group_remove" to "Take out of the group", "mute" to "Mute",
    "unmute" to "Unmute", "timeline" to "Add to the timeline", "snooze" to "Snooze",
)

private fun plural(n: Int, one: String, many: String = one + "s") = "$n ${if (n == 1) one else many}"

data class Notice(val text: String, val undo: BulkUndo? = null, val at: Long = System.nanoTime())

/** Runs one action over many conversations, like the web: confirm when it's big, risky or reaches
 * into groups; ask for Gmail write access when needed; follow a background job; offer Undo. */
@Stable
class BulkRunner internal constructor(private val context: Context, private val scope: CoroutineScope, private val onChanged: () -> Unit) {
    internal var ask by mutableStateOf<Triple<String, Boolean, () -> Unit>?>(null)  // question, risky, go
    internal var needAccess by mutableStateOf<Pair<List<WriteAccessAccount>, () -> Unit>?>(null)
    internal var busy by mutableStateOf<String?>(null)
    internal var notice by mutableStateOf<Notice?>(null)

    fun say(text: String) { notice = Notice(text) }

    /** Ask before something that can't be undone (deleting to-dos, timelines, groups). */
    fun confirm(question: String, go: () -> Unit) { ask = Triple(question, true) { ask = null; go() } }

    /** `fn` for each id, two at a time, then one line saying how it went. */
    fun many(ids: Collection<String>, done: String, fn: suspend (String) -> Unit, after: () -> Unit) {
        scope.launch {
            val ok = runMany(ids, fn)
            say(if (ok == ids.size) "$done: $ok" else "$done: $ok of ${ids.size}. Try the rest again.")
            onChanged()
            after()
        }
    }

    /** `after(true)` once it's done. */
    fun run(body: BulkIn, confirmed: Boolean = false, quiet: Boolean = false, after: (Boolean) -> Unit = {}) {
        scope.launch {
            try {
                if (!confirmed) {
                    val p = Api.get(context).bulk(body.copy(preview = true)).picked
                    if (p.conversations == 0) { say("Nothing to change"); after(false); return@launch }
                    val risky = body.action == "trash" || body.action == "spam"
                    if (risky || p.conversations > ASK_OVER || p.groups > 0) {
                        ask = Triple(question(body.action, p), risky) { ask = null; go(body, quiet, after) }
                        return@launch
                    }
                }
                go(body, quiet, after)
            } catch (t: Throwable) { say(t.userMessage()); after(false) }
        }
    }

    private fun question(action: String, p: BulkPicked): String {
        val parts = mutableListOf(plural(p.conversations, "conversation"))
        if (p.groups > 0) parts += "including ${plural(p.groupMails, "mail")} in ${plural(p.groups, "group")}"
        if (p.urgentInGroups > 0) parts += "(${plural(p.urgentInGroups, "urgent mail")} among them)"
        return "${VERB[action] ?: action} ${parts.joinToString(" ")}?"
    }

    private fun go(body: BulkIn, quiet: Boolean, after: (Boolean) -> Unit) {
        scope.launch {
            try {
                val r = Api.get(context).bulk(body)
                val job = r.job
                if (job != null) after(follow(job, body.action, quiet))
                else { finish(body.action, r.changed, r.failedAccounts, r.siftOnly, r.undo, quiet); after(true) }
            } catch (t: Throwable) {
                val accounts = t.writeAccessNeeded()
                if (accounts != null) needAccess = accounts to { needAccess = null; go(body, quiet, after) }
                else { say(t.userMessage()); after(false) }
            }
        }
    }

    private suspend fun follow(job: BulkJobDto, action: String, quiet: Boolean): Boolean {
        var j = job
        var waited = 0
        while ((j.status == "queued" || j.status == "running") && waited < 1800) {
            busy = "${DONE[action] ?: "Working"}… ${j.done} of ${j.total}"
            delay(1000)
            waited++
            j = runCatching { Api.get(context).bulkJob(j.id) }.getOrDefault(j)  // the job carries on in the worker
        }
        busy = null
        if (j.status != "done") { say("Stopped after ${j.done} of ${j.total}. Try again for the rest."); onChanged(); return false }
        finish(action, j.changed, j.failedAccounts, emptyList(), j.undo, quiet)
        return true
    }

    private fun finish(action: String, changed: Int, failed: List<String>, siftOnly: List<String>, undo: BulkUndo?, quiet: Boolean) {
        onChanged()
        if (failed.isNotEmpty()) { say("Couldn't change mail in ${failed.joinToString()}. The rest is done."); return }
        if (quiet) return
        val text = if (changed == 0) "Already done" else "${DONE[action] ?: "Done"}: ${plural(changed, "conversation")}" +
            if (siftOnly.isNotEmpty()) " (in Sift only for ${siftOnly.joinToString()})" else ""
        notice = Notice(text, undo)
    }

    fun undo(u: BulkUndo) {
        notice = null
        run(BulkIn(u.action, messageIds = u.messageIds, label = u.params["label"], folderId = u.params["folder_id"],
            groupId = u.params["group_id"], opportunityId = u.params["opportunity_id"]), confirmed = true, quiet = true) { ok -> if (ok) say("Undone") }
    }
}

@Composable
fun rememberBulkRunner(onChanged: () -> Unit): BulkRunner {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val latest by rememberUpdatedState(onChanged)
    return remember { BulkRunner(context.applicationContext, scope) { latest() } }
}

/** The runner's dialogs and its progress / Undo bar (floats above the bottom of the screen). */
@Composable
fun BulkRunnerUi(r: BulkRunner) {
    r.ask?.let { (question, risky, go) ->
        AlertDialog(
            onDismissRequest = { r.ask = null },
            title = { Text(question) },
            text = when {
                question.startsWith("Move to Gmail's trash") -> { { Text("Gmail keeps trash for 30 days; Undo restores it.", color = Ink.text2) } }
                question.startsWith("Report as spam") -> { { Text("Gmail moves them to Spam and learns from it.", color = Ink.text2) } }
                else -> null
            },
            confirmButton = { TextButton(onClick = go) { Text("Go ahead", color = if (risky) Ink.urgent else Ink.signal) } },
            dismissButton = { TextButton(onClick = { r.ask = null }) { Text("Cancel", color = Ink.text2) } },
            containerColor = Ink.surface, shape = Radius.xl,
        )
    }
    r.needAccess?.let { (accounts, retry) ->
        WriteAccessDialog(accounts, onDismiss = { r.needAccess = null }, onInfo = { r.say(it) }, onRetry = retry)
    }
    val n = r.notice
    LaunchedEffect(n) {
        if (n != null) {
            delay(if (n.undo != null) 8000 else 3500)
            if (r.notice == n) r.notice = null
        }
    }
    val text = r.busy ?: n?.text ?: return
    val lift = with(LocalDensity.current) { 150.dp.roundToPx() }
    Popup(alignment = Alignment.BottomCenter, offset = IntOffset(0, -lift)) {
        Row(
            Modifier.padding(horizontal = 16.dp).background(Ink.surface2, Radius.lg).border(1.dp, Ink.line2, Radius.lg)
                .padding(start = 14.dp, end = 6.dp, top = 6.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(text, color = Ink.text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f, fill = false).padding(vertical = 8.dp))
            val undo = n?.undo
            if (r.busy == null && undo != null) {
                Text("Undo", color = Ink.signal, style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.padding(start = 8.dp).clickable { r.undo(undo) }.padding(horizontal = 10.dp, vertical = 8.dp))
            }
        }
    }
}

/** Replaces a list's title row while picking: ✕, the count, and "Select all". `onAllMatching`
 * picks everything the list shows (server side), past what is loaded. */
@Composable
fun SelectionTopBar(picks: Picks, loaded: List<String>, noun: String = "selected", onAllMatching: (() -> Unit)? = null) {
    Row(Modifier.fillMaxWidth().padding(start = 8.dp, end = 10.dp, top = 12.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("✕", color = Ink.text, style = MaterialTheme.typography.titleLarge,
            modifier = Modifier.clickable(onClickLabel = "Clear the selection") { picks.clear() }.padding(horizontal = 12.dp, vertical = 8.dp))
        Text(if (picks.all) "All $noun" else "${picks.size} $noun", color = Ink.text, style = MaterialTheme.typography.titleLarge,
            modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
        val everyLoaded = loaded.isNotEmpty() && loaded.all { it in picks.keys }
        when {
            !everyLoaded && !picks.all -> SmallAction("Select all") { picks.pick(loaded) }
            onAllMatching != null && !picks.all -> SmallAction("All matching") { onAllMatching() }
        }
    }
}

@Composable
private fun SmallAction(label: String, onClick: () -> Unit) {
    Text(label, color = Ink.signal, style = MaterialTheme.typography.labelLarge,
        modifier = Modifier.background(Ink.surface, Radius.md).clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp))
}

/** A small square check mark for picked rows (squares, not circles: DESIGN.md shape rules). */
@Composable
fun PickMark(picked: Boolean, modifier: Modifier = Modifier) {
    Box(
        modifier.size(20.dp).background(if (picked) Ink.signal else Color.Transparent, Radius.xs).border(1.5.dp, if (picked) Ink.signal else Ink.text3, Radius.xs),
        contentAlignment = Alignment.Center,
    ) { if (picked) Text("✓", color = Ink.bg, style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.Bold)) }
}

/** A list row that swipes: right = `onRight` (read / unread), left = `onLeft` (archive). The row
 * springs back; the action runs. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SwipeRow(rightLabel: String, onRight: (() -> Unit)?, onLeft: (() -> Unit)?, leftLabel: String = "Archive", content: @Composable () -> Unit) {
    if (onRight == null && onLeft == null) { content(); return }
    val right by rememberUpdatedState(onRight)
    val left by rememberUpdatedState(onLeft)
    val state = rememberSwipeToDismissBoxState(confirmValueChange = { v ->
        when (v) {
            SwipeToDismissBoxValue.StartToEnd -> right?.invoke()
            SwipeToDismissBoxValue.EndToStart -> left?.invoke()
            SwipeToDismissBoxValue.Settled -> Unit
        }
        false  // never dismissed: the list refreshes itself
    })
    SwipeToDismissBox(
        state = state,
        enableDismissFromStartToEnd = onRight != null,
        enableDismissFromEndToStart = onLeft != null,
        backgroundContent = {
            val toRight = state.dismissDirection == SwipeToDismissBoxValue.StartToEnd
            Box(Modifier.fillMaxSize().background(if (toRight) Ink.signal.copy(alpha = 0.16f) else Ink.surface2, Radius.md).padding(horizontal = 18.dp),
                contentAlignment = if (toRight) Alignment.CenterStart else Alignment.CenterEnd) {
                Text(if (toRight) rightLabel else leftLabel, color = if (toRight) Ink.signal else Ink.text, style = MaterialTheme.typography.labelLarge)
            }
        },
    ) { Box(Modifier.background(Ink.bg)) { content() } }
}

/** The bottom bar while mail is picked: Read, Unread, Archive, Delete and More (every other
 * action, Sift's own included). `body(action)` builds the request for what is picked; `onlyGroups`
 * hides mail-only choices. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MailBulkBar(runner: BulkRunner, body: (String) -> BulkIn, extra: List<SheetItem> = emptyList(), onAsk: (() -> Unit)? = null, onDone: () -> Unit) {
    val context = LocalContext.current
    var more by remember { mutableStateOf(false) }
    var picker by remember { mutableStateOf<String?>(null) }  // folder, group, timeline, snooze
    fun go(action: String, edit: (BulkIn) -> BulkIn = { it }) = runner.run(edit(body(action))) { ok -> if (ok) onDone() }

    Column(Modifier.fillMaxWidth().background(Ink.surface).navigationBarsPadding()) {
        HorizontalDivider(color = Ink.line2)
        Row(Modifier.fillMaxWidth().padding(horizontal = 6.dp, vertical = 4.dp), horizontalArrangement = Arrangement.SpaceEvenly) {
            BarButton("Read") { go("read") }
            BarButton("Unread") { go("unread") }
            BarButton("Archive") { go("archive") }
            BarButton("Delete", Ink.urgent) { go("trash") }
            BarButton("More") { more = true }
        }
    }

    if (more) {
        val items = listOf(
            SheetItem("Move to inbox", "Back into Gmail's inbox") { go("unarchive") },
            SheetItem("Star", null) { go("star") },
            SheetItem("Remove star", null) { go("unstar") },
            SheetItem("Mark important", null) { go("important") },
            SheetItem("Mark not important", null) { go("unimportant") },
            SheetItem("Snooze…", "Hide them until later; they come back and notify you") { picker = "snooze" },
            SheetItem("Pin", "Keep them at the top of the feed", section = "Sift") { go("pin") },
            SheetItem("Unpin", null, section = "Sift") { go("unpin") },
            SheetItem("File in a folder…", "Filing never changes Gmail", section = "Sift") { picker = "folder" },
            SheetItem("Add to a group…", null, section = "Sift") { picker = "group" },
            SheetItem("Add to a timeline…", null, section = "Sift") { picker = "timeline" },
            SheetItem("Mute the conversations", "No more notifications from them", section = "Sift") { go("mute") },
            SheetItem("Unmute", null, section = "Sift") { go("unmute") },
        ) + extra + listOfNotNull(
            onAsk?.let { ask -> SheetItem("✦ Ask Sift about these…", "In your own words; you see the steps and tokens first", section = "Sift AI") { ask() } },
            SheetItem("Report spam", "Moves them to Gmail's spam", danger = true, section = "Remove") { go("spam") },
        )
        ModalBottomSheet(
            onDismissRequest = { more = false },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            containerColor = Ink.surface,
            shape = androidx.compose.foundation.shape.RoundedCornerShape(topStart = 14.dp, topEnd = 14.dp),
        ) {
            LazyColumn(Modifier.fillMaxWidth().padding(bottom = 24.dp)) {
                var lastSection = ""
                items.forEach { entry ->
                    if (entry.section != lastSection) {
                        val title = entry.section
                        lastSection = title
                        item(key = "h-$title") {
                            Text(title.uppercase(), color = Ink.text3, style = MaterialTheme.typography.labelSmall,
                                modifier = Modifier.padding(start = 22.dp, top = 14.dp, bottom = 6.dp))
                        }
                    }
                    item(key = entry.label) {
                        Column(Modifier.fillMaxWidth().clickable { more = false; entry.onClick() }.padding(horizontal = 22.dp, vertical = 12.dp)) {
                            Text(entry.label, color = if (entry.danger) Ink.urgent else Ink.text, style = MaterialTheme.typography.titleSmall)
                            entry.hint?.let { Text(it, color = Ink.text3, style = MaterialTheme.typography.bodySmall) }
                        }
                    }
                }
            }
        }
    }

    when (picker) {
        "snooze" -> SnoozeDialog(onDismiss = { picker = null }) { until ->
            picker = null
            go("snooze") { it.copy(until = until.format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)) }
        }
        "folder" -> FolderPickerDialog("File in…", null, onDismiss = { picker = null }) { f ->
            picker = null
            if (f != null) go("file") { it.copy(folderId = f.id) }
        }
        "group" -> PickListDialog("Add to a group", load = { Api.get(context).groups().map { it.id to it.title } }, onDismiss = { picker = null }) { id ->
            picker = null
            go("group_add") { it.copy(groupId = id) }
        }
        "timeline" -> PickListDialog("Add to a timeline", load = { Api.get(context).opportunities().map { it.id to it.company } }, onDismiss = { picker = null }) { id ->
            picker = null
            go("timeline") { it.copy(opportunityId = id) }
        }
    }
}

@Composable
fun BarButton(label: String, color: Color = Ink.text, onClick: () -> Unit) {
    Text(label, color = color, style = MaterialTheme.typography.labelLarge, textAlign = androidx.compose.ui.text.style.TextAlign.Center,
        modifier = Modifier.clickable(onClick = onClick).padding(horizontal = 10.dp, vertical = 14.dp))
}

/** Pick one of a loaded list of (id, name). */
@Composable
fun PickListDialog(title: String, load: suspend () -> List<Pair<String, String>>, onDismiss: () -> Unit, onPick: (String) -> Unit) {
    var list by remember { mutableStateOf<List<Pair<String, String>>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) { try { list = load() } catch (t: Throwable) { error = t.userMessage() } }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                when {
                    error != null -> Text(error!!, color = Ink.urgent)
                    list == null -> Text("Loading…", color = Ink.text3)
                    list!!.isEmpty() -> Text("Nothing here yet.", color = Ink.text3)
                }
                list?.forEach { (id, name) ->
                    Text(name, color = Ink.text, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.fillMaxWidth().clickable { onPick(id) }.padding(vertical = 12.dp))
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}

/** A bottom bar of plain buttons for lists that aren't mail (to-dos, timelines, groups). */
@Composable
fun ThingBulkBar(buttons: List<Pair<String, () -> Unit>>, danger: Pair<String, () -> Unit>? = null) {
    Column(Modifier.fillMaxWidth().background(Ink.surface).navigationBarsPadding()) {
        HorizontalDivider(color = Ink.line2)
        Row(Modifier.fillMaxWidth().padding(horizontal = 6.dp, vertical = 4.dp), horizontalArrangement = Arrangement.SpaceEvenly) {
            buttons.forEach { (label, go) -> BarButton(label, onClick = go) }
            danger?.let { (label, go) -> BarButton(label, Ink.urgent, go) }
        }
    }
}

/** Many simple calls (to-dos, timelines, groups), two at a time; returns how many worked. */
suspend fun runMany(ids: Collection<String>, fn: suspend (String) -> Unit): Int {
    val queue = ArrayDeque(ids)
    var ok = 0
    kotlinx.coroutines.coroutineScope {
        repeat(2) {
            launch {
                while (true) {
                    val id = queue.removeFirstOrNull() ?: break
                    if (runCatching { fn(id) }.isSuccess) ok++
                }
            }
        }
    }
    return ok
}
