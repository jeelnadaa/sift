package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
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
import androidx.compose.ui.unit.sp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.SenderItemDto
import com.solarquack.sift.ui.Avatar
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch

@Composable
fun SendersScreen(
    onBack: () -> Unit,
    onSearchSender: (String) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var items by remember { mutableStateOf<List<SenderItemDto>>(emptyList()) }
    var total by remember { mutableStateOf(0) }
    var loading by remember { mutableStateOf(true) }
    var query by remember { mutableStateOf("") }
    var sortBy by remember { mutableStateOf("count") }
    var offset by remember { mutableStateOf(0) }

    fun refresh(q: String, sort: String, off: Int) =
        scope.launch {
            loading = true
            try {
                val api = Api.get(context)
                val res = api.senders(
                    q = q.ifBlank { null },
                    sortBy = sort,
                    limit = 40,
                    offset = off,
                )
                items = res.items
                total = res.total
            } catch (_: Exception) {
                // keep what is on screen; a failed reload must not blank the list
            } finally {
                loading = false
            }
        }

    LaunchedEffect(Unit) {
        refresh(query, sortBy, offset)
    }
    LaunchedEffect(Unit) { com.solarquack.sift.data.LiveEvents.changes.collect { refresh(query, sortBy, offset) } }

    val sortTabs = listOf(
        "count" to "Volume",
        "recent" to "Recent",
        "unread" to "Unread",
        "urgent" to "Urgent",
        "name" to "Name",
    )

    Column(
        Modifier
            .fillMaxSize()
            .background(Ink.bg)
    ) {
        // Top Bar
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                "‹ Back",
                color = Ink.normal,
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.clickable(onClick = onBack)
            )
            Spacer(Modifier.width(16.dp))
            Column(Modifier.weight(1f)) {
                Text("Senders", style = MaterialTheme.typography.titleLarge, color = Ink.text, fontWeight = FontWeight.SemiBold)
                Text(
                    "$total senders across accounts",
                    style = MaterialTheme.typography.bodySmall,
                    color = Ink.text3
                )
            }
        }

        HorizontalDivider(color = Ink.line)

        // Sort Chips
        Row(
            Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            sortTabs.forEach { (sortKey, label) ->
                Chip(
                    text = label,
                    on = sortBy == sortKey,
                    onClick = {
                        sortBy = sortKey
                        offset = 0
                        refresh(query, sortKey, 0)
                    }
                )
            }
        }

        // Search Input
        OutlinedTextField(
            value = query,
            onValueChange = {
                query = it
                offset = 0
                refresh(it, sortBy, 0)
            },
            placeholder = { Text("Search sender name, email, domain…", color = Ink.text3, fontSize = 14.sp) },
            singleLine = true,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 4.dp),
            shape = Radius.sm,
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = Ink.normal,
                unfocusedBorderColor = Ink.line,
                focusedTextColor = Ink.text,
                unfocusedTextColor = Ink.text,
            )
        )

        Spacer(Modifier.height(8.dp))

        // Content
        if (loading && items.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = Ink.normal)
            }
        } else if (items.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("👥", fontSize = 42.sp)
                    Spacer(Modifier.height(8.dp))
                    Text("No senders found", color = Ink.text, style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    Text(
                        if (query.isNotBlank()) "Try clearing your search keyword"
                        else "Senders will appear as emails arrive in your accounts",
                        color = Ink.text3,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
        } else {
            com.solarquack.sift.ui.Refreshable({ refresh(query, sortBy, offset).join() }) {
                LazyColumn(
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxSize()
                ) {
                    items(items, key = { it.email }) { s ->
                        SenderRow(
                            item = s,
                            onSearch = { onSearchSender(s.email) }
                        )
                    }

                    if (total > 40) {
                        item {
                            Row(
                                Modifier.fillMaxWidth().padding(16.dp),
                                horizontalArrangement = Arrangement.Center,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                GhostButton(
                                    label = "‹ Previous",
                                    enabled = offset > 0,
                                    onClick = {
                                        val newOff = maxOf(0, offset - 40)
                                        offset = newOff
                                        refresh(query, sortBy, newOff)
                                    }
                                )
                                Spacer(Modifier.width(16.dp))
                                Text(
                                    "${offset + 1}–${minOf(offset + 40, total)} of $total",
                                    color = Ink.text3,
                                    style = MaterialTheme.typography.bodySmall
                                )
                                Spacer(Modifier.width(16.dp))
                                GhostButton(
                                    label = "Next ›",
                                    enabled = offset + 40 < total,
                                    onClick = {
                                        val newOff = offset + 40
                                        offset = newOff
                                        refresh(query, sortBy, newOff)
                                    }
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SenderRow(
    item: SenderItemDto,
    onSearch: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var isVip by remember(item.email, item.isVip) { mutableStateOf(item.isVip ?: false) }
    var updatingVip by remember { mutableStateOf(false) }

    Row(
        Modifier
            .fillMaxWidth()
            .background(Ink.surface, Radius.sm)
            .clickable(onClick = onSearch)
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Avatar(item.name ?: item.email)

        Spacer(Modifier.width(12.dp))

        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    item.name ?: item.email,
                    color = Ink.text,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Medium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                if (isVip) {
                    Spacer(Modifier.width(6.dp))
                    Text(
                        "★ VIP",
                        color = Ink.warn,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold
                    )
                }
                item.domain?.let { dom ->
                    Spacer(Modifier.width(6.dp))
                    Text(
                        dom,
                        color = Ink.text3,
                        fontSize = 11.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }

            if (item.name != null) {
                Text(
                    item.email,
                    color = Ink.text3,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }

            item.sampleSubject?.let { subj ->
                Text(
                    "Latest: \"$subj\"",
                    color = Ink.text3,
                    fontSize = 12.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }

        Spacer(Modifier.width(8.dp))

        // Stats
        Column(horizontalAlignment = Alignment.End) {
            Text(
                "${item.totalCount} mail",
                color = Ink.text,
                fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold
            )
            if (item.unreadCount > 0) {
                Text(
                    "${item.unreadCount} unread",
                    color = Ink.normal,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Medium
                )
            }
            if (item.urgentCount > 0) {
                Text(
                    "${item.urgentCount} urgent",
                    color = Ink.urgent,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Medium
                )
            }
        }

        Spacer(Modifier.width(8.dp))

        GhostButton(
            label = if (isVip) "★ VIP" else "☆ VIP",
            enabled = !updatingVip,
            onClick = {
                scope.launch {
                    updatingVip = true
                    try {
                        val api = Api.get(context)
                        if (isVip) {
                            api.unsetSenderVip(item.email)
                            isVip = false
                        } else {
                            api.setSenderVip(item.email)
                            isVip = true
                        }
                    } catch (_: Exception) {}
                    finally { updatingVip = false }
                }
            }
        )

        Spacer(Modifier.width(4.dp))

        GhostButton("Search", onClick = onSearch)
    }
}
