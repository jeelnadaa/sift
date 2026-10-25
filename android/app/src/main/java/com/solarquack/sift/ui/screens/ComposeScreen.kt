package com.solarquack.sift.ui.screens

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DatePickerDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.AccountDto
import com.solarquack.sift.data.AiDraftIn
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.DraftCreateIn
import com.solarquack.sift.data.DraftDto
import com.solarquack.sift.data.DraftFieldsIn
import com.solarquack.sift.data.OutboxDto
import com.solarquack.sift.data.SendIn
import com.solarquack.sift.data.WriteAccessAccount
import com.solarquack.sift.data.draftChanged
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.data.writeAccessNeeded
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.SectionLabel
import com.solarquack.sift.ui.fullTime
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.RequestBody.Companion.toRequestBody
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

/** What opens the composer: a new mail, a reply / reply all / forward of a message (stored by
 * Sift: messageId; or Gmail-only: accountId + gmailId), or an existing draft ("account:draft"). */
data class ComposeArgs(val mode: String = "new", val messageId: String? = null, val accountId: String? = null, val gmailId: String? = null, val draft: String? = null)

private val EMAIL = Regex("^[^\\s@<>]+@[^\\s@<>]+\\.[^\\s@<>]+$")
private fun bare(a: String) = (Regex("<([^>]+)>").find(a)?.groupValues?.get(1) ?: a).trim()
private fun parseList(s: String) = s.split(',', ';', '\n').map { it.trim() }.filter { it.isNotEmpty() }

/** Write mail (Phase 4). The mail is a Gmail draft from the first change on and autosaves 1.5 s
 * after typing stops (saves run one at a time). Send waits for the undo window with an Undo
 * button; Send later schedules it; "Remind me" sets a follow-up. AI only fills the text box. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ComposeScreen(args: ComposeArgs, onDone: (String?) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val replying = args.mode == "reply" || args.mode == "reply_all"
    var ready by remember { mutableStateOf(false) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var accounts by remember { mutableStateOf<List<AccountDto>>(emptyList()) }
    var accountId by remember { mutableStateOf("") }
    var to by remember { mutableStateOf("") }
    var cc by remember { mutableStateOf("") }
    var bcc by remember { mutableStateOf("") }
    var showCc by remember { mutableStateOf(false) }
    var subject by remember { mutableStateOf("") }
    var body by remember { mutableStateOf("") }
    var draft by remember { mutableStateOf<DraftDto?>(null) }
    var threadId by remember { mutableStateOf<String?>(null) }
    var inReplyTo by remember { mutableStateOf<String?>(null) }
    var references by remember { mutableStateOf<String?>(null) }
    var forwardGmailId by remember { mutableStateOf<String?>(null) }
    var scheduled by remember { mutableStateOf<OutboxDto?>(null) }
    var dirty by remember { mutableStateOf(false) }
    var saveText by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var followUp by remember { mutableIntStateOf(0) }
    var undoSeconds by remember { mutableIntStateOf(10) }
    var aiOn by remember { mutableStateOf(false) }
    var aiOpen by remember { mutableStateOf(false) }
    var laterOpen by remember { mutableStateOf(false) }
    var sending by remember { mutableStateOf<OutboxDto?>(null) }
    var needAccess by remember { mutableStateOf<Pair<List<WriteAccessAccount>, suspend () -> Unit>?>(null) }
    var info by remember { mutableStateOf<String?>(null) }
    // set when another device (or Gmail) saved this draft since it was loaded here: autosave
    // pauses until the user loads that version or keeps this one
    var conflict by remember { mutableStateOf<DraftDto?>(null) }
    val lock = remember { Mutex() }

    fun toast(s: String) = android.widget.Toast.makeText(context, s, android.widget.Toast.LENGTH_SHORT).show()

    LaunchedEffect(Unit) {
        try {
            val api = Api.get(context)
            accounts = api.accounts()
            var targetAcc = ""
            var replyBody = ""
            if (args.draft != null) {
                val (acc, did) = args.draft.split(":", limit = 2)
                targetAcc = acc
                val d = api.draft(acc, did)
                draft = d; accountId = d.accountId; to = d.to.joinToString(", "); cc = d.cc.joinToString(", "); bcc = d.bcc.joinToString(", ")
                showCc = d.cc.isNotEmpty() || d.bcc.isNotEmpty(); subject = d.subject; body = d.body; threadId = d.threadId
                inReplyTo = d.inReplyTo; references = d.references; scheduled = d.outbox
            } else if (args.mode != "new") {
                val c = api.replyContext(args.mode, args.messageId, args.accountId, args.gmailId)
                targetAcc = c.accountId
                replyBody = c.body
                accountId = c.accountId; to = c.to.joinToString(", "); cc = c.cc.joinToString(", "); showCc = c.cc.isNotEmpty()
                subject = c.subject; threadId = c.threadId; inReplyTo = c.inReplyTo; references = c.references
                forwardGmailId = c.forwardGmailId
                if (args.mode == "forward") dirty = true  // save at once so the original's attachments come along
            } else {
                targetAcc = accounts.firstOrNull { it.status == "active" && !it.email.endsWith("@demo.sift.local") }?.id ?: ""
                accountId = targetAcc
            }
            val s = api.settings(targetAcc.takeIf { it.isNotBlank() })
            undoSeconds = s.undoSendSeconds
            aiOn = runCatching { api.ai().aiEnabled }.getOrDefault(false)
            val sig = if (s.signature.isNotBlank()) "\n\n-- \n${s.signature}" else ""
            if (args.draft == null) {
                body = if (args.mode != "new") sig + replyBody else sig
            }
            ready = true
        } catch (t: Throwable) { loadError = t.userMessage() }
    }

    /** Run a write; when the account needs write access, ask once and retry. */
    suspend fun <T> withAccess(block: suspend () -> T): T? = try { block() } catch (t: Throwable) {
        val theirs = t.draftChanged()
        val need = t.writeAccessNeeded()
        when {
            theirs != null -> { conflict = theirs; saveText = "" }
            need != null -> needAccess = need to { block() }
            else -> info = t.userMessage()
        }
        null
    }

    suspend fun save(overwrite: Boolean = false): DraftDto? = lock.withLock {
        if (conflict != null && !overwrite) return@withLock null
        saveText = "Saving to Gmail drafts…"
        val current = draft
        val fields = DraftFieldsIn(parseList(to), parseList(cc), parseList(bcc), subject, body, if (overwrite) null else current?.version)
        val r = try {
            withAccess {
                val api = Api.get(context)
                if (current != null) api.saveDraft(current.accountId, current.draftId, fields)
                else api.createDraft(DraftCreateIn(accountId, fields.to, fields.cc, fields.bcc, fields.subject, fields.body, threadId, inReplyTo, references, forwardGmailId))
            }
        } catch (t: Throwable) { if (t is kotlinx.coroutines.CancellationException) throw t; null }
        if (r != null) { draft = r; saveText = "Saved in Gmail drafts" } else if (conflict == null) saveText = "Couldn't save"
        r
    }

    // Autosave 1.5 s after the last change. The save itself runs in the screen's scope, not in
    // this effect, so a keystroke during a save can't cancel it halfway.
    LaunchedEffect(to, cc, bcc, subject, body, dirty, ready) {
        if (!ready || !dirty || accountId.isEmpty()) return@LaunchedEffect
        delay(1500)
        dirty = false
        scope.launch { save() }
    }

    // leaving: keep what was typed (saved in the background, the screen may be gone by then)
    fun leave(message: String? = null) {
        if (dirty && ready && accountId.isNotEmpty()) {
            dirty = false
            CoroutineScope(Dispatchers.Main).launch { runCatching { save() } }
        }
        onDone(message)
    }
    BackHandler(enabled = sending == null) { leave() }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris: List<Uri> ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        scope.launch {
            dirty = false
            val d = save() ?: return@launch
            for (uri in uris) {
                val (name, size) = withContext(Dispatchers.IO) {
                    context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
                        if (c.moveToFirst()) (c.getString(0) ?: "attachment") to c.getLong(1) else "attachment" to 0L
                    } ?: ("attachment" to 0L)
                }
                val cur = draft ?: d
                if (cur.attachmentsSize + size > cur.attachmentsLimit) { info = "$name is too big: attachments are limited to 25 MB in total"; continue }
                val mime = context.contentResolver.getType(uri) ?: "application/octet-stream"
                val bytes = withContext(Dispatchers.IO) { context.contentResolver.openInputStream(uri)?.use { it.readBytes() } } ?: continue
                saveText = "Attaching $name…"
                val r = lock.withLock { withAccess { Api.get(context).addAttachment(cur.accountId, cur.draftId, name, bytes.toRequestBody(mime.toMediaTypeOrNull())) } }
                if (r != null) { draft = r; saveText = "Saved in Gmail drafts" }
            }
        }
    }

    fun send(at: ZonedDateTime? = null) {
        val all = parseList(to) + parseList(cc) + parseList(bcc)
        if (all.isEmpty()) { info = "Add at least one recipient"; return }
        all.firstOrNull { !EMAIL.matches(bare(it)) }?.let { info = "Check $it: not an email address"; return }
        busy = true
        scope.launch {
            try {
                dirty = false
                val d = save() ?: return@launch
                val r = withAccess {
                    Api.get(context).send(d.accountId, d.draftId, SendIn(at?.format(DateTimeFormatter.ISO_OFFSET_DATE_TIME), followUp.takeIf { it > 0 }))
                } ?: return@launch
                when {
                    r.status == "sent" -> onDone("Sent")
                    r.later -> onDone("Scheduled for ${fullTime(r.sendAt)}")
                    else -> sending = r
                }
            } finally { busy = false }
        }
    }

    // ---- the undo window: a countdown with Undo, then back to where the user came from ----
    sending?.let { r ->
        var left by remember(r.id) { mutableIntStateOf(r.undoSeconds) }
        LaunchedEffect(r.id) {
            while (left > 0) { delay(1000); left-- }
            onDone("Sent")
        }
        Column(Modifier.fillMaxSize().background(Ink.bg).padding(24.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
            Text("Sending in $left s…", color = Ink.text, style = MaterialTheme.typography.headlineSmall)
            Text(r.recipients ?: "", color = Ink.text3, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp))
            Spacer(Modifier.height(20.dp))
            PrimaryButton("Undo", Modifier.fillMaxWidth()) {
                scope.launch {
                    try { Api.get(context).cancelSend(r.id); sending = null; toast("Not sent. It's back in your drafts") }
                    catch (t: Throwable) { sending = null; onDone(t.userMessage()) }
                }
            }
            Spacer(Modifier.height(8.dp))
            GhostButton("Send now", Modifier.fillMaxWidth()) {
                scope.launch {
                    try { Api.get(context).sendNow(r.id); onDone("Sending now") } catch (t: Throwable) { onDone(t.userMessage()) }
                }
            }
        }
        return
    }

    Column(Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).imePadding().padding(18.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("‹ Back", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable { leave() }.padding(vertical = 6.dp))
            Spacer(Modifier.weight(1f))
            Text(saveText, color = Ink.text3, style = MaterialTheme.typography.bodySmall)
        }
        Text(
            when { args.draft != null -> "Draft"; args.mode == "reply" -> "Reply"; args.mode == "reply_all" -> "Reply all"; args.mode == "forward" -> "Forward"; else -> "New mail" },
            style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.padding(vertical = 8.dp),
        )
        loadError?.let { Banner(it, Ink.urgent, "Back") { onDone(null) }; return@Column }
        if (!ready) { Text("Loading…", color = Ink.text3); return@Column }
        val usable = accounts.filter { it.status == "active" && !it.email.endsWith("@demo.sift.local") }
        if (usable.isEmpty()) { Banner("Connect a Gmail account to write mail. The demo account can't send.", Ink.warn); return@Column }
        scheduled?.let { s ->
            Banner("Scheduled to send ${fullTime(s.sendAt)}. Changes you make here are sent too.", Ink.signal, "Unschedule") {
                scope.launch { try { Api.get(context).cancelSend(s.id); scheduled = null; toast("Unscheduled. It stays a draft") } catch (t: Throwable) { info = t.userMessage() } }
            }
            Spacer(Modifier.height(10.dp))
        }
        info?.let { Banner(it, Ink.urgent, "OK") { info = null }; Spacer(Modifier.height(10.dp)) }
        conflict?.let { theirs ->
            Banner("This draft was changed on another device or in Gmail. Saving is paused so neither version is lost.", Ink.warn)
            Row(Modifier.padding(vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                GhostButton("Load that version", Modifier.weight(1f)) {
                    conflict = null; dirty = false; draft = theirs
                    to = theirs.to.joinToString(", "); cc = theirs.cc.joinToString(", "); bcc = theirs.bcc.joinToString(", ")
                    subject = theirs.subject; body = theirs.body; saveText = "Saved in Gmail drafts"
                }
                GhostButton("Keep mine", Modifier.weight(1f)) { conflict = null; dirty = false; scope.launch { save(overwrite = true) } }
            }
        }

        // From: fixed for replies, forwards and drafts already saved in an account
        SectionLabel("From")
        if (replying || args.mode == "forward" || draft != null) {
            Text(accounts.firstOrNull { it.id == accountId }?.email ?: "", color = Ink.text, style = MaterialTheme.typography.bodyLarge)
        } else {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                usable.forEach { a ->
                    Chip(a.email, a.id == accountId) {
                        if (a.id != accountId) {
                            val oldAcc = accountId
                            accountId = a.id
                            dirty = true
                            scope.launch {
                                runCatching {
                                    val api = Api.get(context)
                                    val oldS = api.settings(oldAcc.takeIf { it.isNotBlank() })
                                    val newS = api.settings(a.id)
                                    val prevSig = if (oldS.signature.isNotBlank()) "\n\n-- \n${oldS.signature}" else ""
                                    val newSig = if (newS.signature.isNotBlank()) "\n\n-- \n${newS.signature}" else ""
                                    if (prevSig.isNotEmpty() && body.endsWith(prevSig)) {
                                        body = body.removeSuffix(prevSig) + newSig
                                    } else if (body.isEmpty() || body == prevSig) {
                                        body = newSig
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        AddressField(to, { to = it; dirty = true }, "To")
        if (!showCc) Text("Add Cc / Bcc", color = Ink.signal, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable { showCc = true }.padding(vertical = 8.dp))
        else {
            Spacer(Modifier.height(8.dp)); AddressField(cc, { cc = it; dirty = true }, "Cc")
            Spacer(Modifier.height(8.dp)); AddressField(bcc, { bcc = it; dirty = true }, "Bcc (hidden from others)")
        }
        Spacer(Modifier.height(8.dp))
        com.solarquack.sift.ui.Field(subject, { subject = it; dirty = true }, "Subject")
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = body, onValueChange = { body = it; dirty = true }, label = { Text("Message") },
            modifier = Modifier.fillMaxWidth().heightIn(min = 240.dp), shape = Radius.md, minLines = 10,
            textStyle = MaterialTheme.typography.bodyLarge,
            colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Ink.signal, unfocusedBorderColor = Ink.line2, focusedLabelColor = Ink.signal,
                unfocusedLabelColor = Ink.text3, cursorColor = Ink.signal, focusedContainerColor = Ink.bg2, unfocusedContainerColor = Ink.bg2),
        )
        draft?.attachments?.takeIf { it.isNotEmpty() }?.let { atts ->
            Spacer(Modifier.height(10.dp))
            atts.forEach { a ->
                Row(Modifier.fillMaxWidth().padding(vertical = 3.dp).background(Ink.bg2, Radius.md).border(1.dp, Ink.line2, Radius.md).padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Text("📎", modifier = Modifier.padding(end = 8.dp))
                    Column(Modifier.weight(1f)) {
                        Text(a.filename, color = Ink.text, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(fileSize(a.size), color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                    }
                    Text("Remove", color = Ink.urgent, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable {
                        scope.launch {
                            val cur = draft ?: return@launch
                            lock.withLock { withAccess { Api.get(context).removeAttachment(cur.accountId, cur.draftId, a.index) } }?.let { draft = it }
                        }
                    }.padding(6.dp))
                }
            }
            Text("${fileSize(atts.sumOf { it.size })} of 25 MB", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
        }

        SectionLabel("Remind me if no reply")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf(0 to "Off", 1 to "1 day", 2 to "2 days", 3 to "3 days", 7 to "A week").forEach { (d, label) -> Chip(label, followUp == d) { followUp = d } }
        }
        Spacer(Modifier.height(16.dp))
        PrimaryButton(if (busy) "Sending…" else "Send", Modifier.fillMaxWidth(), enabled = !busy) { send() }
        Spacer(Modifier.height(8.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            GhostButton("Send later…") { laterOpen = true }
            GhostButton("Attach…") { picker.launch(arrayOf("*/*")) }
            if (replying) GhostButton(if (aiOn) "✦ Draft with AI" else "✦ AI (add a key)", color = if (aiOn) Ink.text else Ink.text3) {
                if (aiOn) aiOpen = true else info = "Add an API key to draft replies with AI (Settings → AI provider)"
            }
            GhostButton("Discard", color = Ink.urgent) {
                scope.launch {
                    dirty = false
                    lock.withLock {
                        val d = draft
                        if (d != null && withAccess { Api.get(context).discardDraft(d.accountId, d.draftId) } == null) return@launch
                    }
                    onDone("Draft discarded")
                }
            }
        }
        Text("Undo is available for $undoSeconds s after Send (Settings → Writing mail).", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 10.dp))
    }

    if (aiOpen) AiDialog(onDismiss = { aiOpen = false }) { instructions ->
        aiOpen = false
        scope.launch {
            saveText = "Writing with AI…"
            try {
                val r = Api.get(context).aiDraft(AiDraftIn(args.messageId, args.accountId, args.gmailId, instructions))
                body = r.body + "\n" + body.replace(Regex("^\\s*"), "\n")
                dirty = true
                toast("Draft written. Read it and change anything before sending")
            } catch (t: Throwable) { info = t.userMessage(); saveText = "" }
        }
    }
    if (laterOpen) SendLaterDialog(onDismiss = { laterOpen = false }) { at -> laterOpen = false; send(at) }
    needAccess?.let { (accts, retry) ->
        WriteAccessDialog(accts, onDismiss = { needAccess = null }, onInfo = { info = it }) {
            needAccess = null
            scope.launch { try { retry() } catch (t: Throwable) { info = t.userMessage() } }
        }
    }
}

@Composable
private fun AddressField(value: String, onChange: (String) -> Unit, label: String) {
    // addresses wrap onto more lines instead of scrolling sideways; separate them with commas
    OutlinedTextField(
        value = value, onValueChange = { onChange(it.replace(Regex("\r?\n"), ", ")) }, label = { Text(label) },
        placeholder = { Text("name@example.com, …", color = Ink.text3) }, maxLines = 4, shape = Radius.md, modifier = Modifier.fillMaxWidth(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
        isError = parseList(value).any { !EMAIL.matches(bare(it)) },
        textStyle = MaterialTheme.typography.bodyLarge,
        colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Ink.signal, unfocusedBorderColor = Ink.line2, focusedLabelColor = Ink.signal,
            unfocusedLabelColor = Ink.text3, cursorColor = Ink.signal, focusedContainerColor = Ink.bg2, unfocusedContainerColor = Ink.bg2),
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AiDialog(onDismiss: () -> Unit, onWrite: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Draft the reply with AI") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("Accept and confirm", "Decline politely", "Ask for more details", "Say thanks").forEach { q -> Chip(q, false) { onWrite(q) } }
                }
                com.solarquack.sift.ui.Field(text, { text = it }, "Or say what to write", placeholder = "e.g. yes to Friday 3 PM")
                Text("Uses your own AI key. Phone numbers and IDs are hidden from it. It only fills the text box; you read it and press Send.",
                    color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = { PrimaryButton("Write it") { onWrite(text) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}

/** Presets (this evening, tomorrow morning, Monday morning) or a picked day and hour. */
@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
private fun SendLaterDialog(onDismiss: () -> Unit, onPick: (ZonedDateTime) -> Unit) {
    val now = ZonedDateTime.now()
    val day = { plus: Long, hour: Int -> now.toLocalDate().plusDays(plus).atTime(hour, 0).atZone(ZoneId.systemDefault()) }
    val presets = buildList {
        if (now.hour < 17) add("This evening, 18:00" to day(0, 18))
        add("Tomorrow morning, 09:00" to day(1, 9))
        val toMonday = ((8 - now.dayOfWeek.value % 7) % 7).let { if (it == 0) 7 else it }.toLong()
        add("Monday, 09:00" to day(toMonday, 9))
    }
    var date by remember { mutableStateOf<LocalDate?>(null) }
    var hour by remember { mutableIntStateOf(9) }
    var picking by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Send later") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                presets.forEach { (label, at) ->
                    Box(Modifier.fillMaxWidth().background(Ink.bg2, Radius.md).border(1.dp, Ink.line2, Radius.md).clickable { onPick(at) }.padding(14.dp)) {
                        Text(label, color = Ink.text, style = MaterialTheme.typography.titleSmall)
                    }
                }
                SectionLabel("Or pick a day and time")
                GhostButton(date?.format(DateTimeFormatter.ofPattern("EEE d MMM yyyy")) ?: "Pick a day…") { picking = true }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf(7, 8, 9, 10, 12, 14, 16, 18, 20, 22).forEach { h -> Chip("%02d:00".format(h), hour == h) { hour = h } }
                }
            }
        },
        confirmButton = {
            val at = date?.atTime(LocalTime.of(hour, 0))?.atZone(ZoneId.systemDefault())
            PrimaryButton("Schedule", enabled = at != null && at.isAfter(ZonedDateTime.now().plusMinutes(1))) { at?.let(onPick) }
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
}
