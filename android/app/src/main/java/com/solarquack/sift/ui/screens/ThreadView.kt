package com.solarquack.sift.ui.screens

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.solarquack.sift.data.AddrDto
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.Session
import com.solarquack.sift.data.ThreadDto
import com.solarquack.sift.data.ThreadMessageDto
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Avatar
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.relativeTime
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius

private fun who(a: AddrDto?) = a?.name?.takeIf { it.isNotBlank() } ?: a?.email ?: "Unknown"

fun fileSize(n: Long): String = when {
    n < 1024 -> "$n B"
    n < 1024 * 1024 -> "${n / 1024} KB"
    else -> String.format(java.util.Locale.US, "%.1f MB", n / 1024.0 / 1024.0)
}

/** The whole conversation, fetched live and never stored. The newest message, the one opened and
 * unread ones start open. Images load through the Sift server (Settings can turn that off; then
 * a banner offers "Load images"). */
@Composable
fun ThreadView(messageId: String?, accountId: String? = null, threadId: String? = null, onWrite: ((mode: String, accountId: String, gmailId: String) -> Unit)? = null) {
    val context = LocalContext.current
    var images by remember { mutableStateOf(false) }
    var thread by remember { mutableStateOf<ThreadDto?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var open by remember { mutableStateOf(setOf<String>()) }

    LaunchedEffect(messageId, images) {
        try {
            val api = Api.get(context)
            val t = if (messageId != null) api.thread(messageId, if (images) true else null)
            else api.accountThread(accountId!!, threadId!!, if (images) true else null)
            thread = t
            open = open + listOfNotNull(t.messages.lastOrNull()?.gmailId, t.messages.firstOrNull { it.id == messageId }?.gmailId) +
                t.messages.filter { it.unread }.map { it.gmailId }
            error = null
        } catch (t: Throwable) { error = t.userMessage() }
    }

    error?.let { Banner(it, Ink.urgent); return }
    val t = thread ?: run { Text("Loading the conversation…", color = Ink.text3, style = MaterialTheme.typography.bodyMedium); return }
    val blocked = t.messages.sumOf { it.imagesBlocked }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (!images && blocked > 0) {
            Banner("$blocked remote image${if (blocked == 1) "" else "s"} blocked. They can tell the sender you opened the mail. Loading goes through your Sift server.", Ink.warn, "Load images") { images = true }
        }
        if (t.messages.size > 1) Text("${t.messages.size} messages in this conversation", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
        t.messages.forEach { m ->
            val acc = t.accountId
            MessageCard(m, expanded = m.gmailId in open, current = m.id == messageId,
                onWrite = if (onWrite != null && acc != null) { mode -> onWrite(mode, acc, m.gmailId) } else null) {
                open = if (m.gmailId in open) open - m.gmailId else open + m.gmailId
            }
        }
    }
}

@Composable
private fun MessageCard(m: ThreadMessageDto, expanded: Boolean, current: Boolean, onWrite: ((String) -> Unit)? = null, onToggle: () -> Unit) {
    val context = LocalContext.current
    val server = Session.server(context).trimEnd('/')
    Column(
        Modifier.fillMaxWidth().background(Ink.surface, Radius.lg).border(1.dp, if (current) Ink.line2 else Ink.line, Radius.lg),
    ) {
        Row(Modifier.fillMaxWidth().clickable(onClick = onToggle).padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Avatar(who(m.from))
            Column(Modifier.weight(1f).padding(start = 10.dp)) {
                Text(who(m.from), color = Ink.text, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    if (expanded) "to " + (m.to.joinToString { who(it) }.ifBlank { "me" }) else m.snippet,
                    color = Ink.text3, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
            }
            if (m.attachments.isNotEmpty()) Text("📎", modifier = Modifier.padding(horizontal = 6.dp))
            Text(relativeTime(m.date), color = Ink.text3, style = MaterialTheme.typography.bodySmall)
        }
        if (expanded) {
            Column(Modifier.padding(start = 12.dp, end = 12.dp, bottom = 12.dp)) {
                val url = m.htmlUrl
                if (url != null) MailWebView(server + url)
                else Text(m.text.ifBlank { m.snippet }, color = Ink.text2, style = MaterialTheme.typography.bodyLarge)
                onWrite?.let { write ->
                    Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        listOf("reply" to "↩ Reply", "reply_all" to "Reply all", "forward" to "↪ Forward").forEach { (mode, label) ->
                            if (mode != "reply_all" || m.to.size + m.cc.size > 1) {
                                Text(label, color = Ink.signal, style = MaterialTheme.typography.labelLarge,
                                    modifier = Modifier.background(Ink.bg2, Radius.md).clickable { write(mode) }.padding(horizontal = 12.dp, vertical = 10.dp))
                            }
                        }
                    }
                }
                m.attachments.forEach { a ->
                    Row(
                        Modifier.fillMaxWidth().padding(top = 8.dp).background(Ink.bg2, Radius.md).border(1.dp, Ink.line2, Radius.md)
                            .clickable { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(server + a.url))) }.padding(10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(if (a.mime.startsWith("image/")) "🖼" else if (a.mime == "application/pdf") "📄" else "📎")
                        Column(Modifier.weight(1f).padding(start = 10.dp)) {
                            Text(a.filename, color = Ink.text, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(fileSize(a.size), color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                        }
                        Text("Download", color = Ink.signal, style = MaterialTheme.typography.labelLarge)
                    }
                }
            }
        }
    }
}

/** Sanitized mail HTML from the server, in a WebView that can't run anything: JavaScript, file and
 * content access, and storage are off; the document's own policy only allows images from the Sift
 * server. Tapping a link opens it in the browser instead of inside the app.
 * The view is drawn in the card colour and stays invisible until the page has loaded, so nothing
 * flashes white while it arrives. Mail is shown in the app's dark colours by default; "Original
 * colours" shows it as the sender styled it. */
@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun MailWebView(url: String) {
    var loaded by remember(url) { mutableStateOf(false) }
    var original by remember(url) { mutableStateOf(false) }
    val target = if (original) "$url?colors=original" else url
    val zoom = (com.solarquack.sift.ui.theme.UiScale.value.takeIf { it > 0f } ?: 1f) * 100
    Column {
        AndroidView(
            modifier = Modifier.fillMaxWidth().heightIn(min = 80.dp).alpha(if (loaded) 1f else 0f),
            factory = { ctx ->
                WebView(ctx).apply {
                    settings.javaScriptEnabled = false
                    settings.allowFileAccess = false
                    settings.allowContentAccess = false
                    settings.domStorageEnabled = false
                    settings.databaseEnabled = false
                    settings.setSupportMultipleWindows(false)
                    settings.javaScriptCanOpenWindowsAutomatically = false
                    settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                    settings.loadWithOverviewMode = true
                    settings.useWideViewPort = true
                    settings.textZoom = zoom.toInt()
                    // offline: show the copy this phone kept when the mail was last opened
                    settings.cacheMode = if (com.solarquack.sift.data.Offline.since.value != null) WebSettings.LOAD_CACHE_ELSE_NETWORK else WebSettings.LOAD_DEFAULT
                    isVerticalScrollBarEnabled = false
                    setBackgroundColor(Ink.surface.toArgb())
                    webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                            val link = request.url
                            if (link.scheme in setOf("http", "https", "mailto", "tel")) {
                                runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, link).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                            }
                            return true  // never navigate inside the mail view
                        }

                        override fun onPageFinished(view: WebView, url: String?) { view.requestLayout(); loaded = true }
                    }
                    tag = target
                    loadUrl(target)
                }
            },
            update = { view ->
                if (view.tag != target) { view.tag = target; loaded = false; view.loadUrl(target) }
            },
        )
        Text(
            if (original) "Dark colours" else "Original colours",
            color = Ink.text3, style = MaterialTheme.typography.labelLarge,
            modifier = Modifier.align(Alignment.End).clickable { original = !original }.padding(horizontal = 6.dp, vertical = 10.dp),
        )
    }
}
