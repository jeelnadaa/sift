package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.OpportunityDto
import com.solarquack.sift.data.OpportunityIn
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Avatar
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.Field
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.fullTime
import com.solarquack.sift.ui.relativeTime
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.OffsetDateTime

/** Opportunities: one row per company drive (brief section 10). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DealsScreen(onOpen: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var items by remember { mutableStateOf<List<OpportunityDto>>(emptyList()) }
    var status by remember { mutableStateOf("active") }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    var adding by remember { mutableStateOf(false) }

    fun load() = scope.launch {
        loading = true
        try { items = Api.get(context).opportunities(status); error = null } catch (t: Throwable) { error = t.userMessage() } finally { loading = false }
    }
    LaunchedEffect(status) { load() }
    LaunchedEffect(Unit) { com.solarquack.sift.data.LiveEvents.changes.collect { load() } }

    Box(Modifier.fillMaxSize().background(Ink.bg)) {
        Column(Modifier.fillMaxSize()) {
            Text("Opportunities", style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.padding(start = 18.dp, top = 18.dp, bottom = 10.dp))
            Row(Modifier.padding(horizontal = 14.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Chip("active", status == "active") { status = "active" }
                Chip("closed", status == "closed") { status = "closed" }
            }
            PullToRefreshBox(isRefreshing = loading, onRefresh = { load() }, modifier = Modifier.fillMaxSize()) {
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 14.dp, end = 14.dp, top = 8.dp, bottom = 96.dp)) {
                    error?.let { item { Banner(it, Ink.urgent, "Retry") { load() } } }
                    if (!loading && error == null && items.isEmpty()) {
                        item {
                            Text(
                                if (status == "active") "No company drives yet. Placement mail creates them automatically when AI is on, or add one with +."
                                else "Nothing closed yet.",
                                color = Ink.text3, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 32.dp),
                            )
                        }
                    }
                    items(items, key = { it.id }) { o -> OpportunityRow(o) { onOpen(o.id) } }
                }
            }
        }
        com.solarquack.sift.ui.AddButton("New", Modifier.align(Alignment.BottomEnd)) { adding = true }
    }

    if (adding) NewOpportunityDialog(onDismiss = { adding = false }) { company ->
        scope.launch {
            try {
                val created = Api.get(context).createOpportunity(OpportunityIn(company))
                adding = false
                onOpen(created.id)
            } catch (t: Throwable) { error = t.userMessage(); adding = false }
        }
    }
}

private fun deadlineTag(iso: String?): Pair<String, androidx.compose.ui.graphics.Color>? {
    val d = iso?.let { runCatching { OffsetDateTime.parse(it) }.getOrNull() } ?: return null
    val left = Duration.between(OffsetDateTime.now(), d)
    if (left.isNegative) return null
    return when {
        left.toHours() < 24 -> "Due in ${if (left.toHours() < 1) "${left.toMinutes()}m" else "${left.toHours()}h"}" to Ink.urgent
        left.toDays() < 3 -> "Due in ${left.toDays()}d" to Ink.warn
        else -> "Due ${fullTime(iso).substringBefore(",")}" to Ink.text2
    }
}

@Composable
private fun OpportunityRow(o: OpportunityDto, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 12.dp, horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        val due = deadlineTag(o.deadline)
        Avatar(o.company, if (due?.second == Ink.urgent) Ink.signal else null)
        Column(Modifier.weight(1f).padding(start = 12.dp)) {
            Text(o.company, color = Ink.text, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                listOfNotNull(o.lastKind?.let { com.solarquack.sift.ui.humanize(it) }, "${o.events} event${if (o.events == 1) "" else "s"}", o.updatedAt?.let { "updated ${relativeTime(it)}" }).joinToString(" · "),
                color = Ink.text3, style = MaterialTheme.typography.bodySmall,
            )
        }
        due?.let { Tag(it.first, it.second) }
    }
    HorizontalDivider(color = Ink.line)
}

@Composable
fun NewOpportunityDialog(onDismiss: () -> Unit, onCreate: (String) -> Unit) {
    var company by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("New opportunity") },
        text = {
            Column {
                Text("A company drive you are following. Mail can be attached to it from any account.", color = Ink.text2, style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.height(12.dp))
                Field(company, { company = it }, "Company")
            }
        },
        confirmButton = { PrimaryButton("Create", enabled = company.isNotBlank()) { onCreate(company.trim()) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}
