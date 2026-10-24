package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.LoginRequest
import com.solarquack.sift.data.Push
import com.solarquack.sift.data.Session
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Field
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch

@Composable
fun Wordmark(size: Int = 22) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size((size * 0.6).dp).rotate(45f).background(Ink.signal, Radius.xs))
        Spacer(Modifier.size(12.dp))
        Text("Sift", style = MaterialTheme.typography.headlineSmall.copy(fontSize = size.sp, letterSpacing = (size * 0.06).sp), color = Ink.text)
    }
}

@Composable
fun LoginScreen(onSignedIn: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var server by remember { mutableStateOf(Session.server(context)) }
    var email by remember { mutableStateOf(Session.email(context) ?: "") }
    var password by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    Column(
        Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).imePadding().padding(horizontal = 24.dp, vertical = 56.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Wordmark()
        Spacer(Modifier.height(24.dp))
        Text(
            buildAnnotatedString {
                append("Your inbox,\n")
                withStyle(SpanStyle(color = Ink.signal)) { append("sifted.") }
            },
            style = MaterialTheme.typography.displaySmall.copy(fontSize = 44.sp, lineHeight = 46.sp), color = Ink.text,
        )
        Text("Sign in to your Sift server. Mail stays read-only and bodies are never logged.", color = Ink.text2, style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(8.dp))
        Field(server, { server = it }, "Server address", keyboard = KeyboardType.Uri)
        Field(email, { email = it }, "Email", keyboard = KeyboardType.Email)
        Field(password, { password = it }, "Password", password = true)
        error?.let { Text(it, color = Ink.urgent, style = MaterialTheme.typography.bodyMedium) }
        PrimaryButton(if (busy) "Signing in…" else "Sign in", Modifier.fillMaxWidth(), enabled = !busy && server.isNotBlank() && email.isNotBlank() && password.isNotBlank()) {
            busy = true
            error = null
            scope.launch {
                try {
                    Session.signOut(context)
                    Session.setServer(context, server)
                    val res = Api.get(context).login(LoginRequest(email.trim(), password))
                    Session.signIn(context, server, res.user.email, res.token)
                    runCatching { Push.registerDevice(context) }
                    onSignedIn()
                } catch (t: Throwable) {
                    error = if (t is retrofit2.HttpException && t.code() == 401) "Wrong email or password." else t.userMessage()
                } finally {
                    busy = false
                }
            }
        }
        Text(
            "On the same Wi-Fi as your laptop use http://<laptop IP>:8000. With Cloudflare Tunnel use https://sift.solarquack.in.",
            color = Ink.text3, style = MaterialTheme.typography.bodySmall,
        )
    }
}
