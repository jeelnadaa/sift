package com.solarquack.sift.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.AccountDto
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.SiftCard
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.accountColor
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch

private const val BLOCKED_COPY = "This account may be blocked by its administrator (common for college or work accounts)."

@Composable
fun AccountsScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var accounts by remember { mutableStateOf<List<AccountDto>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var removing by remember { mutableStateOf<AccountDto?>(null) }

    fun load() = scope.launch {
        try {
            accounts = Api.get(context).accounts()
            error = null
        } catch (t: Throwable) {
            error = t.userMessage()
        }
    }
    fun connect() = scope.launch {
        try {
            val url = Api.get(context).connectUrl().authUrl
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (t: Throwable) {
            error = t.userMessage()
        }
    }
    LaunchedEffect(Unit) { load() }

    Column(Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Accounts", style = MaterialTheme.typography.headlineMedium, color = Ink.text)
        error?.let { Banner(it, Ink.urgent, "Retry") { load() } }
        accounts.forEach { a ->
            val border = when (a.status) { "blocked" -> Ink.warn.copy(alpha = 0.4f); "needs_reconnect" -> Ink.urgent.copy(alpha = 0.4f); else -> Ink.line }
            SiftCard(border = border) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(10.dp).background(accountColor(a.color, a.id), Radius.xs))
                    Text(a.email, color = Ink.text, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(start = 10.dp).weight(1f))
                    Tag(if (a.status == "needs_reconnect") "Needs reconnect" else a.status, when (a.status) { "active" -> Ink.signal; "blocked" -> Ink.warn; else -> Ink.urgent })
                }
                when (a.status) {
                    "blocked" -> Text(BLOCKED_COPY, color = Ink.text2, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
                    "needs_reconnect" -> {
                        Text("Google sign-in expired or was revoked. Mail since then is picked up after reconnecting.", color = Ink.text2, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
                        Spacer(Modifier.height(10.dp))
                        PrimaryButton("Reconnect") { connect() }
                    }
                }
                Spacer(Modifier.height(10.dp))
                GhostButton("Remove", color = Ink.urgent) { removing = a }
            }
        }
        if (accounts.isEmpty() && error == null) Text("No Gmail account connected yet.", color = Ink.text3, style = MaterialTheme.typography.bodyMedium)
        PrimaryButton("+ Add Gmail account", Modifier.fillMaxWidth()) { connect() }
        Text(
            "Google sign-in returns to the server's address. While the server runs on your laptop without a tunnel, open the link on the laptop instead (python -m app.cli connect-url).",
            color = Ink.text3, style = MaterialTheme.typography.bodySmall,
        )
    }

    removing?.let { a ->
        AlertDialog(
            onDismissRequest = { removing = null },
            title = { Text("Remove ${a.email}?") },
            text = { Text("Sift stops watching it, deletes its tokens and all of its stored mail. Nothing in Gmail changes.") },
            confirmButton = {
                TextButton(onClick = {
                    removing = null
                    scope.launch {
                        try { Api.get(context).removeAccount(a.id); load() } catch (t: Throwable) { error = t.userMessage() }
                    }
                }) { Text("Remove", color = Ink.urgent) }
            },
            dismissButton = { TextButton(onClick = { removing = null }) { Text("Cancel") } },
            containerColor = Ink.surface, shape = Radius.xl,
        )
    }
}
