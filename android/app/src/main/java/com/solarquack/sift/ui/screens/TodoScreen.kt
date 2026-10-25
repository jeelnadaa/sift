package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DatePickerDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberDatePickerState
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
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.TodoDto
import androidx.compose.foundation.verticalScroll
import com.solarquack.sift.data.TodoIn
import com.solarquack.sift.data.TodoPatch
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.Field
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.fullTime
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.ZoneOffset

/** Action-needed mail (from AI) plus your own to-dos, soonest due first. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TodoScreen(onOpenMail: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }
    var state by remember { mutableStateOf("open") }
    var items by remember { mutableStateOf<List<TodoDto>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    var adding by remember { mutableStateOf(false) }
    var editingTodo by remember { mutableStateOf<TodoDto?>(null) }

    fun load() = scope.launch {
        loading = true
        try { items = Api.get(context).todos(state); error = null } catch (t: Throwable) { error = t.userMessage() } finally { loading = false }
    }
    LaunchedEffect(state) { load() }
    LaunchedEffect(Unit) { com.solarquack.sift.data.LiveEvents.changes.collect { load() } }

    fun setDone(t: TodoDto, done: Boolean) = scope.launch {
        try {
            Api.get(context).updateTodo(t.id, TodoPatch(done = done))
            items = items.filterNot { it.id == t.id }
            if (done) {
                val r = snackbar.showSnackbar("Done: ${t.title}", actionLabel = "Undo", withDismissAction = true)
                if (r == SnackbarResult.ActionPerformed) { Api.get(context).updateTodo(t.id, TodoPatch(done = false)); load() }
            }
        } catch (e: Throwable) { error = e.userMessage() }
    }

    Box(Modifier.fillMaxSize().background(Ink.bg)) {
        Column(Modifier.fillMaxSize()) {
            Text("To-do", style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.padding(start = 18.dp, top = 18.dp, bottom = 10.dp))
            Row(Modifier.padding(horizontal = 14.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Chip("open", state == "open") { state = "open" }
                Chip("done", state == "done") { state = "done" }
            }
            PullToRefreshBox(isRefreshing = loading, onRefresh = { load() }, modifier = Modifier.fillMaxSize()) {
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 14.dp, end = 14.dp, top = 8.dp, bottom = 96.dp)) {
                    error?.let { item { Banner(it, Ink.urgent, "Retry") { load() } } }
                    if (!loading && error == null && items.isEmpty()) {
                        item {
                            Text(if (state == "open") "Nothing to do. Mail that needs action shows up here, and you can add your own with +." else "Nothing finished yet.",
                                color = Ink.text3, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 32.dp))
                        }
                    }
                    items(items, key = { it.id }) { t -> TodoRow(t, onToggle = { setDone(t, !t.done) }, onOpen = { t.messageId?.let(onOpenMail) }, onEdit = { editingTodo = t }) }
                }
            }
        }
        com.solarquack.sift.ui.AddButton("Add", Modifier.align(Alignment.BottomEnd)) { adding = true }
        SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).padding(bottom = 80.dp))
    }

    if (adding) EditTodoDialog(null, onDismiss = { adding = false }) { title, notes, due ->
        adding = false
        scope.launch { try { Api.get(context).createTodo(TodoIn(title, due, notes.ifBlank { null })); state = "open"; load() } catch (t: Throwable) { error = t.userMessage() } }
    }
    editingTodo?.let { t ->
        EditTodoDialog(t, onDismiss = { editingTodo = null }, onDelete = {
            editingTodo = null
            scope.launch {
                try { Api.get(context).deleteTodo(t.id); items = items.filterNot { it.id == t.id }; snackbar.showSnackbar("Deleted: ${t.title}", withDismissAction = true) }
                catch (e: Throwable) { error = e.userMessage() }
            }
        }) { title, notes, due ->
            editingTodo = null
            scope.launch {
                try { Api.get(context).updateTodo(t.id, TodoPatch(title = title, notes = notes, dueAt = due, clearDue = due == null)); load() }
                catch (e: Throwable) { error = e.userMessage() }
            }
        }
    }
}

private fun dueLabel(iso: String?): Pair<String, androidx.compose.ui.graphics.Color>? {
    val d = iso?.let { runCatching { OffsetDateTime.parse(it) }.getOrNull() } ?: return null
    val left = Duration.between(OffsetDateTime.now(), d)
    return when {
        left.isNegative -> "Overdue" to Ink.urgent
        left.toHours() < 24 -> "Due ${fullTime(iso).substringAfter(", ")}" to Ink.urgent
        left.toDays() < 3 -> "Due ${fullTime(iso).substringBefore(",")}" to Ink.warn
        else -> "Due ${fullTime(iso).substringBefore(" ·")}" to Ink.text2
    }
}

@Composable
private fun TodoRow(t: TodoDto, onToggle: () -> Unit, onOpen: () -> Unit, onEdit: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(enabled = t.messageId != null, onClick = onOpen).padding(vertical = 12.dp, horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier.size(24.dp).background(if (t.done) Ink.signal else Ink.bg, Radius.sm).border(1.5.dp, if (t.done) Ink.signal else Ink.line2, Radius.sm)
                .clickable(role = Role.Checkbox, onClick = onToggle).semantics { contentDescription = if (t.done) "Mark not done" else "Mark done" },
            contentAlignment = Alignment.Center,
        ) { if (t.done) Text("✓", color = Ink.signalInk, style = MaterialTheme.typography.labelLarge) }
        Column(Modifier.weight(1f).padding(start = 12.dp)) {
            Text(t.title, color = if (t.done) Ink.text3 else Ink.text, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis,
                textDecoration = if (t.done) TextDecoration.LineThrough else null)
            val meta = listOfNotNull(t.company, t.senderName?.takeIf { t.company == null }, if (t.source == "ai") "From mail" else null).joinToString(" · ")
            if (meta.isNotEmpty()) Text(meta, color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            t.notes?.takeIf { it.isNotBlank() }?.let { Text(it, color = Ink.text2, style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis) }
        }
        if (!t.done) dueLabel(t.dueAt)?.let { Tag(it.first, it.second) }
        Text("Edit", color = Ink.signal, style = MaterialTheme.typography.labelMedium, modifier = Modifier.clickable(onClick = onEdit).padding(horizontal = 8.dp, vertical = 10.dp))
    }
    HorizontalDivider(color = Ink.line)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddTodoDialog(initialTitle: String = "", onDismiss: () -> Unit, onAdd: (String, String?) -> Unit) {
    var title by remember { mutableStateOf(initialTitle) }
    var date by remember { mutableStateOf<LocalDate?>(null) }
    var time by remember { mutableStateOf(LocalTime.of(18, 0)) }
    var picking by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("New to-do") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Field(title, { title = it }, "What needs doing")
                Text("Due", color = Ink.text3, style = MaterialTheme.typography.labelSmall)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Chip("no date", date == null) { date = null }
                    Chip("today", date == LocalDate.now()) { date = LocalDate.now() }
                    Chip("tomorrow", date == LocalDate.now().plusDays(1)) { date = LocalDate.now().plusDays(1) }
                    Chip(if (date != null && date!! > LocalDate.now().plusDays(1)) date.toString() else "pick…", date != null && date!! > LocalDate.now().plusDays(1)) { picking = true }
                }
                if (date != null) Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf(LocalTime.of(9, 0) to "9 AM", LocalTime.of(18, 0) to "6 PM", LocalTime.of(23, 59) to "11:59 PM").forEach { (t, label) ->
                        Chip(label, time == t) { time = t }
                    }
                }
                if (date != null) Text("Reminders 24 hours and 2 hours before.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = {
            PrimaryButton("Add", enabled = title.isNotBlank()) {
                val due = date?.atTime(time)?.atZone(ZoneId.systemDefault())?.toOffsetDateTime()?.toString()
                onAdd(title.trim(), due)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
    if (picking) {
        val state = rememberDatePickerState(selectableDates = object : androidx.compose.material3.SelectableDates {
            override fun isSelectableDate(utcTimeMillis: Long) = utcTimeMillis >= LocalDate.now().atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
        })
        DatePickerDialog(
            onDismissRequest = { picking = false },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let { date = Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate() }
                    picking = false
                }) { Text("OK", color = Ink.signal) }
            },
            dismissButton = { TextButton(onClick = { picking = false }) { Text("Cancel", color = Ink.text2) } },
            colors = DatePickerDefaults.colors(containerColor = Ink.surface),
        ) { DatePicker(state = state) }
    }
    Spacer(Modifier.height(0.dp))
}

/** Add a to-do or change one: name, notes, and a deadline at any day and minute. */
@Composable
fun EditTodoDialog(todo: TodoDto?, onDismiss: () -> Unit, onDelete: (() -> Unit)? = null, onSave: (title: String, notes: String, due: String?) -> Unit) {
    var confirmDelete by remember { mutableStateOf(false) }
    var title by remember { mutableStateOf(todo?.title ?: "") }
    var notes by remember { mutableStateOf(todo?.notes ?: "") }
    var due by remember { mutableStateOf(com.solarquack.sift.ui.parseZoned(todo?.dueAt)) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (todo == null) "New to-do" else "Edit to-do") },
        text = {
            Column(Modifier.verticalScroll(androidx.compose.foundation.rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Field(title, { title = it.take(300) }, "What needs doing")
                Text("Due", color = Ink.text3, style = MaterialTheme.typography.labelSmall)
                com.solarquack.sift.ui.DateTimeRow(due, { due = it })
                if (due != null) Text("Reminders 24 hours and 2 hours before.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                Field(notes, { notes = it.take(4000) }, "Notes (optional)", singleLine = false)
            }
        },
        confirmButton = {
            PrimaryButton(if (todo == null) "Add" else "Save", enabled = title.isNotBlank()) {
                onSave(title.trim(), notes.trim(), due?.let { with(com.solarquack.sift.ui.DateTimeIso) { it.isoString() } })
            }
        },
        dismissButton = {
            Row {
                // deleting asks once more: the to-do is gone for good (marking it done keeps it)
                if (onDelete != null) TextButton(onClick = { if (confirmDelete) onDelete() else confirmDelete = true }) {
                    Text(if (confirmDelete) "Delete for good" else "Delete", color = Ink.urgent)
                }
                TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) }
            }
        },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}
