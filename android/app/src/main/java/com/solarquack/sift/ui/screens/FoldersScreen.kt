package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.FolderDto
import com.solarquack.sift.data.FolderIn
import com.solarquack.sift.data.FolderPatch
import com.solarquack.sift.data.FolderTree
import com.solarquack.sift.data.FolderView
import com.solarquack.sift.data.MoveIn
import com.solarquack.sift.data.TargetIn
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.Field
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch

/** Folder colors (DESIGN.md: one accent per item, from the token palette). */
val FOLDER_COLORS = listOf("#c8ff3d", "#6ea8ff", "#b79cff", "#ff8a5b", "#4ad6c4", "#f6d365", "#ff6fae")

fun folderColor(hex: String?): Color = hex?.let { runCatching { Color(android.graphics.Color.parseColor(it)) }.getOrNull() } ?: Ink.text3

/** Depth-first list of (folder, depth), children right after their parent. */
fun flatten(folders: List<FolderDto>, depth: Int = 0, open: Set<String>? = null): List<Pair<FolderDto, Int>> =
    folders.flatMap { f ->
        listOf(f to depth) + if (open == null || f.id in open) flatten(f.children, depth + 1, open) else emptyList()
    }

private fun subtreeIds(f: FolderDto): Set<String> = setOf(f.id) + f.children.flatMap { subtreeIds(it) }

private val NOTIFY_LABELS = mapOf("default" to "As usual", "always" to "Always notify", "mute" to "Mute")

@Composable
fun FoldersScreen(onOpen: (String) -> Unit, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var tree by remember { mutableStateOf<FolderTree?>(null) }
    var open by remember { mutableStateOf(setOf<String>()) }
    var error by remember { mutableStateOf<String?>(null) }
    var creatingUnder by remember { mutableStateOf<Pair<Boolean, FolderDto?>>(false to null) }
    var acting by remember { mutableStateOf<FolderDto?>(null) }

    fun load() = scope.launch {
        try { tree = Api.get(context).folders(); error = null } catch (t: Throwable) { error = t.userMessage() }
    }
    fun run(block: suspend () -> Unit) = scope.launch {
        try { block(); tree = Api.get(context).folders(); error = null } catch (t: Throwable) { error = t.userMessage() }
    }
    LaunchedEffect(Unit) { load() }

    Column(Modifier.fillMaxSize().background(Ink.bg)) {
        Row(Modifier.fillMaxWidth().padding(start = 18.dp, end = 14.dp, top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("‹ Back", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(vertical = 6.dp))
            Spacer(Modifier.weight(1f))
            Text("+ New folder", color = Ink.signal, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable { creatingUnder = true to null }.padding(6.dp))
        }
        Text("Folders", style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.padding(start = 18.dp, top = 4.dp))
        Text("Yours, in Sift. Filing never moves or changes mail in Gmail.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 18.dp, vertical = 4.dp))
        error?.let { Box(Modifier.padding(horizontal = 14.dp, vertical = 6.dp)) { Banner(it, Ink.urgent) } }
        val t = tree
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 14.dp, vertical = 8.dp)) {
            if (t != null && t.folders.isEmpty()) item {
                Text("No folders yet. Make one, then file mail into it from any mail, or let a rule do it.", color = Ink.text3,
                    style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 24.dp))
            }
            items(flatten(t?.folders.orEmpty(), open = open), key = { it.first.id }) { (f, depth) ->
                FolderRow(f, depth, expanded = f.id in open,
                    onToggle = { open = if (f.id in open) open - f.id else open + f.id },
                    onOpen = { onOpen(f.id) }, onMore = { acting = f })
            }
        }
    }

    if (creatingUnder.first) NameDialog(
        title = creatingUnder.second?.let { "New folder in ${it.name}" } ?: "New folder", initial = "", initialColor = null,
        onDismiss = { creatingUnder = false to null },
    ) { name, color ->
        val parent = creatingUnder.second
        creatingUnder = false to null
        run { Api.get(context).createFolder(FolderIn(name, parent?.id, color)); parent?.let { open = open + it.id } }
    }
    acting?.let { f ->
        FolderActions(f, tree?.maxDepth ?: 10, all = tree?.folders.orEmpty(), onDismiss = { acting = null },
            onAddChild = { acting = null; creatingUnder = true to f },
            onRun = { block -> acting = null; run(block) })
    }
}

@Composable
private fun FolderRow(f: FolderDto, depth: Int, expanded: Boolean, onToggle: () -> Unit, onOpen: () -> Unit, onMore: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onOpen).padding(start = (depth * 18).dp, top = 4.dp, bottom = 4.dp).heightIn(min = 44.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(if (f.children.isEmpty()) " " else if (expanded) "▾" else "▸", color = Ink.text3, style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.width(26.dp).clickable(enabled = f.children.isNotEmpty(), onClick = onToggle).padding(vertical = 8.dp))
        Box(Modifier.size(10.dp).background(folderColor(f.color), Radius.xs))
        Column(Modifier.weight(1f).padding(start = 10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(f.name, color = Ink.text, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                if (f.pinned) Text("Pinned", color = Ink.text3, style = MaterialTheme.typography.labelSmall)
                if (f.notifyMode != "default") Text(NOTIFY_LABELS.getValue(f.notifyMode), color = if (f.notifyMode == "mute") Ink.text3 else Ink.signal, style = MaterialTheme.typography.labelSmall)
            }
            Text("${f.threads} thread${if (f.threads == 1) "" else "s"}", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
        }
        val unread = if (expanded) f.unread else f.unreadTotal  // collapsed parents show their subfolders' unread too
        if (unread > 0) Text("$unread", color = Ink.signal, style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(horizontal = 8.dp))
        Text("⋯", color = Ink.text2, style = MaterialTheme.typography.titleMedium, modifier = Modifier.clickable(onClick = onMore).padding(horizontal = 10.dp, vertical = 8.dp))
    }
    HorizontalDivider(color = Ink.line)
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun NameDialog(title: String, initial: String, initialColor: String?, onDismiss: () -> Unit, onSave: (String, String?) -> Unit) {
    var name by remember { mutableStateOf(initial) }
    var color by remember { mutableStateOf(initialColor) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Field(name, { name = it }, "Name", placeholder = "e.g. Placements")
                Text("Color", color = Ink.text3, style = MaterialTheme.typography.labelMedium)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    FOLDER_COLORS.forEach { hex ->
                        Box(Modifier.size(28.dp).background(folderColor(hex), Radius.sm)
                            .border(2.dp, if (color == hex) Ink.text else Color.Transparent, Radius.sm).clickable { color = if (color == hex) null else hex })
                    }
                }
            }
        },
        confirmButton = { PrimaryButton("Save", enabled = name.isNotBlank()) { onSave(name.trim(), color) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}

/** Everything you can do to one folder. */
@Composable
private fun FolderActions(
    f: FolderDto, maxDepth: Int, all: List<FolderDto>, onDismiss: () -> Unit, onAddChild: () -> Unit,
    onRun: (suspend () -> Unit) -> Unit,
) {
    val context = LocalContext.current
    var step by remember { mutableStateOf("menu") }
    when (step) {
        "rename" -> NameDialog("Edit folder", f.name, f.color, onDismiss) { name, color ->
            onRun { Api.get(context).editFolder(f.id, FolderPatch(name = name, color = color, clearColor = color == null)) }
        }
        "move" -> FolderPickerDialog("Move ${f.name} to…", all, exclude = subtreeIds(f), allowTop = true, onDismiss = onDismiss) { target ->
            onRun { Api.get(context).moveFolder(f.id, MoveIn(target?.id)) }
        }
        "merge" -> FolderPickerDialog("Merge ${f.name} into…", all, exclude = subtreeIds(f), allowTop = false, onDismiss = onDismiss,
            note = "Its mail and subfolders move into the folder you pick, and rules that filed here file there. Then ${f.name} is removed.") { target ->
            target?.let { onRun { Api.get(context).mergeFolder(f.id, TargetIn(it.id)) } }
        }
        "delete" -> AlertDialog(
            onDismissRequest = onDismiss,
            title = { Text("Delete ${f.name}?") },
            text = {
                Text("Only the folder and its filing go. Mail stays in Gmail and in Sift." +
                    if (f.children.isNotEmpty()) " What should happen to its ${f.children.size} subfolder(s)?" else "",
                    color = Ink.text2, style = MaterialTheme.typography.bodyMedium)
            },
            confirmButton = {
                Column(horizontalAlignment = Alignment.End) {
                    if (f.children.isNotEmpty()) {
                        TextButton(onClick = { onRun { Api.get(context).deleteFolder(f.id, "move_up") } }) { Text("Delete, move subfolders up", color = Ink.text) }
                        TextButton(onClick = { onRun { Api.get(context).deleteFolder(f.id, "delete") } }) { Text("Delete with subfolders", color = Ink.urgent) }
                    } else {
                        TextButton(onClick = { onRun { Api.get(context).deleteFolder(f.id, "move_up") } }) { Text("Delete", color = Ink.urgent) }
                    }
                }
            },
            dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) } },
            containerColor = Ink.surface, shape = Radius.xl,
        )
        else -> AlertDialog(
            onDismissRequest = onDismiss,
            title = { Text(f.name) },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    Text("Notifications for mail filed here", color = Ink.text3, style = MaterialTheme.typography.labelMedium)
                    Row(Modifier.padding(vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        NOTIFY_LABELS.forEach { (mode, label) -> Chip(label, f.notifyMode == mode) { onRun { Api.get(context).editFolder(f.id, FolderPatch(notifyMode = mode)) } } }
                    }
                    Text(
                        when (f.notifyMode) {
                            "always" -> "Digest mail filed here notifies with sound too."
                            "mute" -> "Mail filed here doesn't notify. Urgent mail still does."
                            else -> "Mail notifies by its own priority."
                        }, color = Ink.text3, style = MaterialTheme.typography.bodySmall,
                    )
                    Spacer(Modifier.height(12.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Pin to the top", color = Ink.text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                        Switch(f.pinned, { on -> onRun { Api.get(context).editFolder(f.id, FolderPatch(pinned = on)) } },
                            colors = SwitchDefaults.colors(checkedTrackColor = Ink.signal, checkedThumbColor = Ink.signalInk))
                    }
                    HorizontalDivider(color = Ink.line, modifier = Modifier.padding(vertical = 8.dp))
                    MenuLine("Rename or recolor") { step = "rename" }
                    MenuLine("Add a subfolder") { onAddChild() }
                    MenuLine("Move to…") { step = "move" }
                    MenuLine("Merge into…") { step = "merge" }
                    MenuLine("Delete", Ink.urgent) { step = "delete" }
                    Text("Folders nest up to $maxDepth levels.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
                }
            },
            confirmButton = { TextButton(onClick = onDismiss) { Text("Close", color = Ink.text2) } },
            containerColor = Ink.surface, shape = Radius.xl,
        )
    }
}

@Composable
private fun MenuLine(label: String, color: Color = Ink.text, onClick: () -> Unit) {
    Text(label, color = color, style = MaterialTheme.typography.titleSmall, modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 12.dp))
}

/** Pick a folder from the tree. `allowTop` adds "Top level" (returned as null). */
@Composable
fun FolderPickerDialog(
    title: String, folders: List<FolderDto>?, exclude: Set<String> = emptySet(), allowTop: Boolean = false,
    note: String? = null, onNew: (() -> Unit)? = null, onDismiss: () -> Unit, onPick: (FolderDto?) -> Unit,
) {
    val context = LocalContext.current
    var list by remember { mutableStateOf(folders) }
    LaunchedEffect(Unit) { if (list == null) list = runCatching { Api.get(context).folders().folders }.getOrDefault(emptyList()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                note?.let { Text(it, color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(bottom = 8.dp)) }
                if (allowTop) PickLine("Top level", 0, null) { onPick(null) }
                val rows = flatten(list.orEmpty()).filter { (f, _) -> f.id !in exclude && !f.smart }
                when {
                    list == null -> Text("Loading…", color = Ink.text3)
                    rows.isEmpty() && !allowTop -> Text("No folders yet.", color = Ink.text3, style = MaterialTheme.typography.bodyMedium)
                }
                rows.forEach { (f, depth) -> PickLine(f.name, depth, f.color) { onPick(f) } }
            }
        },
        confirmButton = { if (onNew != null) PrimaryButton("+ New folder", onClick = onNew) },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}

@Composable
private fun PickLine(name: String, depth: Int, color: String?, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(start = (depth * 16).dp, top = 11.dp, bottom = 11.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(10.dp).background(if (color == null && depth == 0 && name == "Top level") Color.Transparent else folderColor(color), Radius.xs))
        Text(name, color = Ink.text, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(start = 10.dp), maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** One folder: its threads (optionally with subfolders), a breadcrumb and a search box. */
@Composable
fun FolderScreen(id: String, onBack: () -> Unit, onOpenMail: (String) -> Unit, onOpenFolder: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var view by remember { mutableStateOf<FolderView?>(null) }
    var includeSub by remember { mutableStateOf(false) }
    var query by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var loadingMore by remember { mutableStateOf(false) }
    val listState = androidx.compose.foundation.lazy.rememberLazyListState()

    fun load() = scope.launch {
        try { view = Api.get(context).folderThreads(id, includeSub, query.trim().ifBlank { null }); error = null } catch (t: Throwable) { error = t.userMessage() }
    }
    fun loadMore() {
        val v = view ?: return
        val cursor = v.nextBefore ?: return
        if (loadingMore) return
        loadingMore = true
        scope.launch {
            try {
                val more = Api.get(context).folderThreads(id, includeSub, query.trim().ifBlank { null }, before = cursor)
                val seen = v.items.map { it.id }.toSet()
                view = v.copy(items = v.items + more.items.filter { it.id !in seen }, nextBefore = more.nextBefore)
            } catch (t: Throwable) { error = t.userMessage() } finally { loadingMore = false }
        }
    }
    LaunchedEffect(id, includeSub) { load() }
    LaunchedEffect(query) { kotlinx.coroutines.delay(350); load() }
    val nearEnd by remember { androidx.compose.runtime.derivedStateOf { listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index?.let { it >= listState.layoutInfo.totalItemsCount - 8 } ?: false } }
    LaunchedEffect(nearEnd, view?.nextBefore) { if (nearEnd) loadMore() }

    Column(Modifier.fillMaxSize().background(Ink.bg)) {
        Text("‹ Back", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(start = 18.dp, top = 12.dp, bottom = 4.dp))
        val v = view
        if (v != null && v.path.size > 1) {
            Row(Modifier.padding(horizontal = 18.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                v.path.dropLast(1).forEach { p ->
                    Text(p.name, color = Ink.text2, style = MaterialTheme.typography.bodySmall, modifier = Modifier.clickable { onOpenFolder(p.id) })
                    Text("/", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        Text(v?.folder?.name ?: "", style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.padding(start = 18.dp, top = 2.dp))
        Column(Modifier.padding(horizontal = 14.dp, vertical = 6.dp)) {
            Field(query, { query = it }, "Search this folder", placeholder = "Sender or subject words")
            Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Include subfolders", color = Ink.text2, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                Switch(includeSub, { includeSub = it }, colors = SwitchDefaults.colors(checkedTrackColor = Ink.signal, checkedThumbColor = Ink.signalInk))
            }
        }
        error?.let { Box(Modifier.padding(horizontal = 14.dp)) { Banner(it, Ink.urgent, "Retry") { load() } } }
        LazyColumn(Modifier.fillMaxSize(), state = listState, contentPadding = PaddingValues(horizontal = 14.dp, vertical = 4.dp)) {
            if (v != null && v.items.isEmpty()) item {
                Text(if (query.isBlank()) "Nothing filed here yet. Open a mail and tap File in folder." else "No mail here matches.",
                    color = Ink.text3, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 24.dp))
            }
            items(v?.items.orEmpty(), key = { it.id }) { row ->
                MailRow(row.asMessage().let { m -> if (row.threadCount > 1) m.copy(senderName = "${m.senderName ?: m.sender} (${row.threadCount})") else m }) { onOpenMail(row.id) }
            }
        }
    }
}

/** "File in folder" for one mail: picker plus "last used" shortcut, and where the thread is filed now. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun FilingSection(messageId: String, buttons: Boolean = true, pickRequest: Int = 0, refreshKey: Int = 0, onRuleDraft: (com.solarquack.sift.data.DraftResponse) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var tree by remember { mutableStateOf<FolderTree?>(null) }
    var inFolders by remember { mutableStateOf<List<FolderDto>>(emptyList()) }
    var picking by remember { mutableStateOf(false) }
    LaunchedEffect(pickRequest) { if (pickRequest > 0) picking = true }
    var creating by remember { mutableStateOf(false) }
    var info by remember { mutableStateOf<String?>(null) }

    fun refresh() = scope.launch {
        runCatching {
            val api = Api.get(context)
            tree = api.folders()
            inFolders = api.foldersForMessage(messageId)
        }.onFailure { info = it.userMessage() }
    }
    fun file(f: FolderDto) = scope.launch {
        try { Api.get(context).fileMail(f.id, com.solarquack.sift.data.FileIn(listOf(messageId))); info = "Filed in ${f.name}" ; refresh() } catch (t: Throwable) { info = t.userMessage() }
    }
    LaunchedEffect(messageId, refreshKey) { refresh() }

    val last = tree?.lastUsedId?.let { lid -> flatten(tree!!.folders).firstOrNull { it.first.id == lid }?.first }
    Column(Modifier.padding(top = 12.dp)) {
        if (buttons) FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            GhostButton("File in folder") { picking = true }
            if (last != null && inFolders.none { it.id == last.id }) GhostButton("Move to ${last.name}") { file(last) }
        }
        if (inFolders.isNotEmpty()) {
            FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("In", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
                inFolders.forEach { f ->
                    Chip("${f.name}  ×", false, dot = folderColor(f.color)) {
                        scope.launch {
                            try { Api.get(context).unfileMail(f.id, com.solarquack.sift.data.FileIn(listOf(messageId))); info = "Removed from ${f.name}"; refresh() } catch (t: Throwable) { info = t.userMessage() }
                        }
                    }
                }
            }
            val target = inFolders.first()
            Text("File mail like this in ${target.name} automatically", color = Ink.signal, style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.padding(top = 8.dp).clickable {
                    scope.launch {
                        try { onRuleDraft(Api.get(context).fileLikeThisHere(target.id, com.solarquack.sift.data.LikeThisHereIn(messageId))) } catch (t: Throwable) { info = t.userMessage() }
                    }
                })
        }
        info?.let { Text(it, color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp)) }
    }

    if (picking) FolderPickerDialog("File in folder", tree?.folders, exclude = inFolders.map { it.id }.toSet(),
        note = "The whole conversation is filed, so replies show up there too.",
        onNew = { picking = false; creating = true }, onDismiss = { picking = false }) { f -> picking = false; f?.let { file(it) } }
    if (creating) NameDialog("New folder", "", null, onDismiss = { creating = false }) { name, color ->
        creating = false
        scope.launch {
            try { file(Api.get(context).createFolder(FolderIn(name, null, color))) } catch (t: Throwable) { info = t.userMessage() }
        }
    }
}
