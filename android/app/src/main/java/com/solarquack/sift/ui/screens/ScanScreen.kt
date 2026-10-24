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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
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
import com.solarquack.sift.data.ApplyIn
import com.solarquack.sift.data.ScanDto
import com.solarquack.sift.data.ScanSender
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private val SCAN_ACTIONS = listOf("keep" to "Keep", "silent" to "Silent", "digest" to "Digest", "notify_normal" to "Normal", "notify_urgent" to "Urgent")

/** First look at a new account: last 30 days, headers only, assign actions to senders in bulk. */
@Composable
fun ScanScreen(accountId: String, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var scan by remember { mutableStateOf<ScanDto?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var info by remember { mutableStateOf<String?>(null) }
    var applying by remember { mutableStateOf(false) }
    val choice = remember { mutableStateMapOf<String, String>() }

    LaunchedEffect(accountId) {
        while (true) {
            scan = runCatching { Api.get(context).latestScan(accountId) }.getOrNull()
            val s = scan
            if (s != null && s.status == "done") { s.senders.forEach { choice.putIfAbsent(it.key, it.suggested) }; break }
            if (s != null && s.status == "failed") break
            if (s == null) break
            delay(3000)
        }
    }

    Column(Modifier.fillMaxSize().background(Ink.bg)) {
        Column(Modifier.padding(18.dp)) {
            Text("‹ Back", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(vertical = 6.dp))
            Text("First scan", style = MaterialTheme.typography.headlineMedium, color = Ink.text)
            Text("Your last 30 days, headers only: no mail bodies, no AI. Choose what Sift should do with each sender from now on.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            error?.let { Spacer(Modifier.height(8.dp)); Banner(it, Ink.urgent) }
            info?.let { Spacer(Modifier.height(8.dp)); Banner(it, Ink.signal) }
        }
        val s = scan
        when {
            s == null -> Column(Modifier.padding(horizontal = 18.dp)) {
                Text("No scan yet for this account.", color = Ink.text2, style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(10.dp))
                PrimaryButton("Scan last 30 days") {
                    scope.launch { try { scan = Api.get(context).startScan(accountId) } catch (t: Throwable) { error = t.userMessage() } }
                }
            }
            s.status in setOf("queued", "running") -> Column(Modifier.padding(horizontal = 18.dp)) {
                Text("Reading headers… ${s.scanned} mails so far", color = Ink.text2, style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(10.dp))
                LinearProgressIndicator(Modifier.fillMaxWidth(), color = Ink.signal, trackColor = Ink.line)
                Text("Paced to stay well inside Gmail's limits; a large mailbox takes a few minutes. You can leave this screen.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
            }
            s.status == "failed" -> Column(Modifier.padding(horizontal = 18.dp)) {
                Banner("The scan stopped: ${s.error ?: "unknown error"}.", Ink.urgent, "Try again") {
                    scope.launch { try { scan = Api.get(context).startScan(accountId) } catch (t: Throwable) { error = t.userMessage() } }
                }
            }
            else -> Box(Modifier.fillMaxSize()) {
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 14.dp, end = 14.dp, bottom = 96.dp)) {
                    item {
                        Text("${s.scanned} mails from ${s.senders.size} senders" + (s.appliedAt?.let { " · applied" } ?: ""), color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 4.dp, vertical = 6.dp))
                    }
                    items(s.senders, key = { it.key }) { sender -> SenderRow(sender, choice[sender.key] ?: sender.suggested) { choice[sender.key] = it } }
                }
                val count = choice.count { it.value != "keep" }
                Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().background(Ink.bg2).padding(14.dp)) {
                    PrimaryButton(if (applying) "Applying…" else "Apply to $count sender${if (count == 1) "" else "s"}", Modifier.fillMaxWidth(), enabled = !applying && count > 0) {
                        applying = true
                        scope.launch {
                            try {
                                val r = Api.get(context).applyScan(s.id, ApplyIn(choice.toMap()))
                                info = "Created ${r.rules.size} rule${if (r.rules.size == 1) "" else "s"}. Security mail (fraud, OTP, sign-in alerts) from these senders still gets through."
                                scan = Api.get(context).latestScan(accountId)
                            } catch (t: Throwable) { error = t.userMessage() } finally { applying = false }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SenderRow(s: ScanSender, chosen: String, onChoose: (String) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(vertical = 10.dp, horizontal = 4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(s.name ?: s.key, color = Ink.text, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(s.key + (s.sampleSubject?.let { " · $it" } ?: ""), color = Ink.text3, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Box(Modifier.background(Ink.surface2, Radius.sm).padding(horizontal = 8.dp, vertical = 4.dp)) { Text("${s.count}", color = Ink.text, style = MaterialTheme.typography.labelLarge) }
        }
        if (s.hints.isNotEmpty() || s.kind == "unverified") Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            s.hints.forEach { Tag(it.replace("_", " ")) }
            if (s.kind == "unverified") Tag("Unverified sender", Ink.warn)
        }
        if (s.kind != "unverified") Row(Modifier.padding(top = 8.dp).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            SCAN_ACTIONS.forEach { (key, label) -> Chip(label, chosen == key) { onChoose(key) } }
        } else Text("Gmail couldn't verify this sender, so no rule can safely match it.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
    }
    HorizontalDivider(color = Ink.line)
}
