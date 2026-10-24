package com.solarquack.sift.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.BodyDto
import com.solarquack.sift.data.MessageDto
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Avatar
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.SectionLabel
import com.solarquack.sift.ui.SiftCard
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.accountColor
import com.solarquack.sift.ui.fullTime
import com.solarquack.sift.ui.theme.Ink

/** Read-only mail detail (Phase 1). Plain text only; the sandboxed HTML reader is Phase 3. */
@Composable
fun MailScreen(id: String, onBack: () -> Unit) {
    val context = LocalContext.current
    var m by remember { mutableStateOf<MessageDto?>(null) }
    var body by remember { mutableStateOf<BodyDto?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var bodyError by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(id) {
        try {
            m = Api.get(context).message(id)
        } catch (t: Throwable) {
            error = t.userMessage()
            return@LaunchedEffect
        }
        try {
            body = Api.get(context).body(id)
        } catch (t: Throwable) {
            bodyError = t.userMessage()
        }
    }

    Column(Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).padding(18.dp)) {
        Text("‹ Back", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(vertical = 6.dp))
        error?.let { Banner(it, Ink.urgent) }
        val msg = m ?: return@Column
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            msg.priority?.let { Tag(it, Ink.tier(it)) }
            msg.category?.takeIf { it != "other" }?.let { Tag(it) }
            msg.company?.let { Tag(it) }
        }
        Text(msg.subject ?: "(no subject)", style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.padding(vertical = 10.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Avatar(msg.senderName ?: msg.sender ?: "?")
            Column(Modifier.padding(start = 10.dp)) {
                Text(msg.senderName?.takeIf { it.isNotBlank() } ?: msg.sender ?: "", style = MaterialTheme.typography.titleSmall, color = Ink.text)
                Text("${msg.sender ?: ""} · ${fullTime(msg.receivedAt)}", style = MaterialTheme.typography.bodySmall, color = Ink.text3)
                msg.account?.let { Text("To $it", style = MaterialTheme.typography.bodySmall, color = accountColor(msg.accountColor, msg.accountId)) }
            }
        }

        if (msg.summary != null || msg.deadline != null || msg.links.isNotEmpty()) {
            Spacer(Modifier.height(16.dp))
            SiftCard {
                SectionLabel("Extracted")
                msg.summary?.let { Text(it, color = Ink.text, style = MaterialTheme.typography.bodyLarge) }
                msg.deadline?.let { Text("Deadline ${fullTime(it)}", color = Ink.warn, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 6.dp)) }
                msg.platform?.let { Text("Platform: $it", color = Ink.text2, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 4.dp)) }
                msg.links.forEach { link ->
                    Spacer(Modifier.height(10.dp))
                    PrimaryButton(link.label) { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(link.url))) }
                }
            }
        }

        SectionLabel("Message")
        when {
            body != null -> SelectionContainer { Text(body!!.text.ifBlank { msg.snippet ?: "" }, color = Ink.text2, style = MaterialTheme.typography.bodyLarge) }
            bodyError != null -> Text("${msg.snippet ?: ""}\n\n($bodyError)", color = Ink.text2, style = MaterialTheme.typography.bodyLarge)
            else -> Text("Loading…", color = Ink.text3, style = MaterialTheme.typography.bodyMedium)
        }
        body?.attachments?.takeIf { it.isNotEmpty() }?.let { files ->
            SectionLabel("Attachments")
            files.forEach { Text("📎 $it", color = Ink.text2, style = MaterialTheme.typography.bodyMedium) }
        }
        Spacer(Modifier.height(18.dp))
        Text(
            "Decided by ${msg.decidedBy ?: "default"}" + (msg.deliveredAt?.let { " · delivered ${fullTime(it)}" } ?: ""),
            color = Ink.text3, style = MaterialTheme.typography.bodySmall,
        )
        Spacer(Modifier.height(12.dp))
        GhostButton("Open in Gmail") {
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://mail.google.com/mail/u/0/#all")))
        }
    }
}
