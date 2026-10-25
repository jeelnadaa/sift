package com.solarquack.sift.ui.screens

import android.content.Intent
import android.net.Uri
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
import com.solarquack.sift.data.AttachmentItemDto
import com.solarquack.sift.data.AttachmentStatsDto
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch

private fun formatBytes(bytes: Long): String {
    if (bytes == 0L) return "0 B"
    if (bytes < 1024L) return "$bytes B"
    if (bytes < 1024L * 1024L) return "${bytes / 1024L} KB"
    if (bytes < 1024L * 1024L * 1024L) return "%.1f MB".format(bytes.toDouble() / (1024L * 1024L))
    return "%.2f GB".format(bytes.toDouble() / (1024L * 1024L * 1024L))
}

private fun getCategoryEmoji(mime: String, filename: String): String {
    val m = mime.lowercase()
    val f = filename.lowercase()
    return when {
        m.contains("pdf") || f.endsWith(".pdf") -> "📄"
        m.startsWith("image/") || f.endsWith(".png") || f.endsWith(".jpg") || f.endsWith(".jpeg") -> "🖼️"
        m.contains("spreadsheet") || m.contains("excel") || f.endsWith(".xlsx") || f.endsWith(".csv") -> "📊"
        m.contains("word") || m.contains("document") || f.endsWith(".docx") || f.endsWith(".txt") -> "📝"
        m.contains("zip") || m.contains("tar") || m.contains("compressed") || f.endsWith(".zip") -> "📦"
        else -> "📎"
    }
}

@Composable
fun AttachmentsScreen(
    onBack: () -> Unit,
    onOpenMail: (String) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var items by remember { mutableStateOf<List<AttachmentItemDto>>(emptyList()) }
    var stats by remember { mutableStateOf<AttachmentStatsDto?>(null) }
    var selectedType by remember { mutableStateOf<String?>(null) }
    var query by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(true) }
    var nextBefore by remember { mutableStateOf<String?>(null) }
    var total by remember { mutableStateOf(0) }

    fun refresh(type: String?, q: String) {
        scope.launch {
            loading = true
            try {
                val api = Api.get(context)
                val res = api.attachments(
                    type = type,
                    q = q.ifBlank { null },
                    limit = 30,
                )
                items = res.items
                nextBefore = res.nextBefore
                total = res.total
            } catch (_: Exception) {
                items = emptyList()
            } finally {
                loading = false
            }
        }
    }

    LaunchedEffect(Unit) {
        try {
            stats = Api.get(context).attachmentStats()
        } catch (_: Exception) {}
        refresh(selectedType, query)
    }

    val typeFilters = listOf(
        null to "All",
        "pdf" to "📄 PDFs",
        "image" to "🖼️ Images",
        "sheet" to "📊 Sheets",
        "doc" to "📝 Docs",
        "archive" to "📦 Archives",
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
                Text("Attachments", style = MaterialTheme.typography.titleLarge, color = Ink.text, fontWeight = FontWeight.SemiBold)
                stats?.let { s ->
                    Text(
                        "${s.totalCount} files · ${formatBytes(s.totalSize)} stored",
                        style = MaterialTheme.typography.bodySmall,
                        color = Ink.text3
                    )
                }
            }
        }

        HorizontalDivider(color = Ink.line)

        // Filter Chips Row
        Row(
            Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            typeFilters.forEach { (typeKey, label) ->
                Chip(
                    text = label,
                    on = selectedType == typeKey,
                    onClick = {
                        selectedType = typeKey
                        refresh(typeKey, query)
                    }
                )
            }
        }

        // Search Input
        OutlinedTextField(
            value = query,
            onValueChange = {
                query = it
                refresh(selectedType, it)
            },
            placeholder = { Text("Search filename, sender, subject…", color = Ink.text3, fontSize = 14.sp) },
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
                    Text("📎", fontSize = 42.sp)
                    Spacer(Modifier.height(8.dp))
                    Text("No attachments found", color = Ink.text, style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    Text(
                        if (query.isNotBlank() || selectedType != null) "Try changing your search or filter"
                        else "Attachments in your incoming mail appear here",
                        color = Ink.text3,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
        } else {
            LazyColumn(
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxSize()
            ) {
                items(items, key = { it.id }) { att ->
                    AttachmentRow(
                        item = att,
                        onOpenMail = { onOpenMail(att.messageId) },
                        onDownload = {
                            try {
                                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(att.downloadUrl))
                                context.startActivity(intent)
                            } catch (_: Exception) {}
                        }
                    )
                }

                if (nextBefore != null) {
                    item {
                        Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) {
                            GhostButton(
                                label = if (loading) "Loading…" else "Load more (${total - items.size} remaining)",
                                onClick = {
                                    if (!loading) {
                                        scope.launch {
                                            loading = true
                                            try {
                                                val res = Api.get(context).attachments(
                                                    type = selectedType,
                                                    q = query.ifBlank { null },
                                                    before = nextBefore,
                                                    limit = 30,
                                                )
                                                items = items + res.items
                                                nextBefore = res.nextBefore
                                                total = res.total
                                            } catch (_: Exception) {}
                                            finally {
                                                loading = false
                                            }
                                        }
                                    }
                                }
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AttachmentRow(
    item: AttachmentItemDto,
    onOpenMail: () -> Unit,
    onDownload: () -> Unit,
) {
    val emoji = getCategoryEmoji(item.mime, item.filename)

    Row(
        Modifier
            .fillMaxWidth()
            .background(Ink.surface, Radius.sm)
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        // Icon
        Box(
            Modifier
                .size(40.dp)
                .background(Ink.bg, Radius.sm),
            contentAlignment = Alignment.Center
        ) {
            Text(emoji, fontSize = 20.sp)
        }

        Spacer(Modifier.width(12.dp))

        // Info
        Column(Modifier.weight(1f)) {
            Text(
                item.filename,
                color = Ink.text,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Medium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    formatBytes(item.size),
                    color = Ink.text3,
                    style = MaterialTheme.typography.bodySmall
                )
                item.sender?.let { s ->
                    Text(" · From $s", color = Ink.text3, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            item.subject?.let { sub ->
                Text(
                    "✉️ $sub",
                    color = Ink.normal,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.clickable(onClick = onOpenMail)
                )
            }
        }

        Spacer(Modifier.width(8.dp))

        // Actions
        GhostButton("Download", onClick = onDownload)
    }
}
