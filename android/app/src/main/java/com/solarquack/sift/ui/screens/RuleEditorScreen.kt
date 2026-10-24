package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.PreviewIn
import com.solarquack.sift.data.PreviewResult
import com.solarquack.sift.data.RuleDto
import com.solarquack.sift.data.RuleDraft
import com.solarquack.sift.data.RuleIn
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.Field
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.SectionLabel
import com.solarquack.sift.ui.SiftCard
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/** What the editor opens with: an existing rule, a draft (plain English / one tap), or nothing. */
object RuleEditorSeed {
    var rule: RuleDto? = null
    var draft: RuleDraft? = null
    var origin: String = "editor"
    fun clear() { rule = null; draft = null; origin = "editor" }
}

/** One editable condition row. `kind` maps to a field/op pair of the rule engine. */
enum class CondKind(val label: String, val field: String, val op: String, val inputLabel: String, val hint: String, val list: Boolean) {
    SENDER_DOMAIN("Sender domain is", "sender_domain", "in", "Domains, comma separated", "kotak.com, slice.bank.in", true),
    SENDER("Sender address is", "sender", "in", "Addresses, comma separated", "alerts@kotak.com", true),
    SUBJECT_ANY("Subject contains any of", "subject", "contains_any", "Words or phrases, comma separated", "debited, credited, UPI", true),
    SUBJECT_REGEX("Subject matches (regex)", "subject", "matches", "Regular expression", "\\b(debited|credited)\\b", false),
    BODY_ANY("Body contains any of", "body", "contains_any", "Words or phrases, comma separated", "fraud, blocked", true),
    AMOUNT_ABOVE("Amount above ₹", "amount", "gt", "Rupees", "2000", false),
    AMOUNT_BELOW("Amount below ₹", "amount", "lt", "Rupees", "500", false),
    LABEL("Gmail label is", "label", "has", "Gmail label", "CATEGORY_PROMOTIONS", false),
    HEADER("Header is present", "header", "present", "Header name", "List-Unsubscribe", false),
    ATTACHMENT("Has an attachment", "has_attachment", "is", "", "", false),
}

class CondRow(kind: CondKind, text: String) {
    var kind by mutableStateOf(kind)
    var text by mutableStateOf(text)
}

private fun values(text: String) = text.split(",").map { it.trim() }.filter { it.isNotEmpty() }

private fun CondRow.toJson(): JsonObject? = buildJsonObject {
    put("field", kind.field)
    when (kind) {
        CondKind.ATTACHMENT -> { put("op", "is"); put("value", true) }
        CondKind.AMOUNT_ABOVE, CondKind.AMOUNT_BELOW -> {
            val n = text.replace(",", "").replace("₹", "").trim().toDoubleOrNull() ?: return null
            put("op", kind.op); put("value", if (n % 1.0 == 0.0) JsonPrimitive(n.toLong()) else JsonPrimitive(n))
        }
        CondKind.SUBJECT_REGEX, CondKind.LABEL, CondKind.HEADER -> {
            if (text.isBlank()) return null
            put("op", kind.op); put("value", text.trim())
        }
        else -> {
            val v = values(text)
            if (v.isEmpty()) return null
            put("op", kind.op); put("value", JsonArray(v.map { JsonPrimitive(it) }))
        }
    }
}

private fun leafToRow(o: JsonObject): CondRow? {
    val field = o["field"]?.jsonPrimitive?.contentOrNull ?: return null
    val op = o["op"]?.jsonPrimitive?.contentOrNull ?: return null
    val v = o["value"]
    val text = when (v) {
        is JsonArray -> v.joinToString(", ") { it.jsonPrimitive.content }
        is JsonPrimitive -> v.doubleOrNull?.takeIf { field == "amount" }?.let { if (it % 1.0 == 0.0) it.toLong().toString() else it.toString() } ?: v.contentOrNull ?: ""
        else -> ""
    }
    val kind = when {
        field == "sender_domain" -> CondKind.SENDER_DOMAIN
        field == "sender" && op in setOf("is", "in") -> CondKind.SENDER
        field == "subject" && op == "matches" -> CondKind.SUBJECT_REGEX
        field == "subject" -> CondKind.SUBJECT_ANY
        field == "body" -> CondKind.BODY_ANY
        field == "amount" && op in setOf("gt", "gte") -> CondKind.AMOUNT_ABOVE
        field == "amount" && op in setOf("lt", "lte") -> CondKind.AMOUNT_BELOW
        field == "label" -> CondKind.LABEL
        field == "header" -> CondKind.HEADER
        field == "has_attachment" && (v as? JsonPrimitive)?.booleanOrNull != false -> CondKind.ATTACHMENT
        else -> return null
    }
    return CondRow(kind, text)
}

/** Flat {all|any: [leaves]} or a single leaf -> rows. Null when the shape is not editable here. */
private fun treeToRows(tree: JsonElement?): Pair<Boolean, List<CondRow>>? {
    if (tree == null || tree !is JsonObject) return true to emptyList()
    val (all, items) = when {
        "all" in tree -> true to tree["all"]!!.jsonArray
        "any" in tree -> false to tree["any"]!!.jsonArray
        "field" in tree -> return leafToRow(tree)?.let { true to listOf(it) }
        else -> return null
    }
    return all to items.map { (it as? JsonObject)?.let(::leafToRow) ?: return null }
}

/** Exceptions: {any: [leaf | {all: [leaves]}]} -> groups (each group: all of its rows). */
private fun exceptionGroups(tree: JsonElement?): List<List<CondRow>>? {
    if (tree == null || tree !is JsonObject) return emptyList()
    val items = when {
        "any" in tree -> tree["any"]!!.jsonArray
        "field" in tree || "all" in tree -> JsonArray(listOf(tree))
        else -> return null
    }
    return items.map { item ->
        val o = item as? JsonObject ?: return null
        if ("all" in o) o["all"]!!.jsonArray.map { (it as? JsonObject)?.let(::leafToRow) ?: return null }
        else listOf(leafToRow(o) ?: return null)
    }
}

/** Plain-language summary for shapes the form can't edit. */
private fun describe(tree: JsonElement?): String = when {
    tree !is JsonObject -> ""
    "all" in tree -> tree["all"]!!.jsonArray.joinToString(" and ") { describe(it) }.let { "($it)" }
    "any" in tree -> tree["any"]!!.jsonArray.joinToString(" or ") { describe(it) }.let { "($it)" }
    "not" in tree -> "not ${describe(tree["not"])}"
    else -> leafToRow(tree)?.let { "${it.kind.label.lowercase()} ${it.text}".trim() } ?: tree.toString()
}

private val ACTIONS = listOf("notify_urgent" to "Notify urgent", "notify_normal" to "Notify normal", "digest" to "Digest", "silent" to "Store silently", "ignore" to "Ignore", "llm" to "Classify as usual")
private val QUIETING = setOf("silent", "ignore", "digest")

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun RuleEditorScreen(onDone: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val seed = remember { Triple(RuleEditorSeed.rule, RuleEditorSeed.draft, RuleEditorSeed.origin) }
    val (existing, draft, origin) = seed
    val source = existing?.let { RuleDraft(it.name, it.conditions, it.action, it.exceptions, it.accountScope) } ?: draft

    val parsed = remember { treeToRows(source?.conditions) }
    val parsedExc = remember { exceptionGroups(source?.exceptions) }
    val editable = source == null || (parsed != null && parsedExc != null)

    var name by remember { mutableStateOf(source?.name?.replace('_', ' ')?.replaceFirstChar { it.uppercase() } ?: "") }
    var matchAll by remember { mutableStateOf(parsed?.first ?: true) }
    val conds: SnapshotStateList<CondRow> = remember { mutableStateListOf<CondRow>().apply { addAll(parsed?.second?.ifEmpty { null } ?: listOf(CondRow(CondKind.SENDER_DOMAIN, ""))) } }
    val groups: SnapshotStateList<SnapshotStateList<CondRow>> = remember {
        mutableStateListOf<SnapshotStateList<CondRow>>().apply { parsedExc?.forEach { g -> add(mutableStateListOf<CondRow>().apply { addAll(g) }) } }
    }
    var action by remember { mutableStateOf(source?.action?.get("type")?.jsonPrimitive?.contentOrNull ?: "silent") }
    var folderId by remember { mutableStateOf(source?.action?.get("folder_id")?.jsonPrimitive?.contentOrNull) }
    var folderName by remember { mutableStateOf<String?>(null) }
    var pickingFolder by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        folderId?.let { fid -> folderName = runCatching { flatten(Api.get(context).folders().folders).firstOrNull { it.first.id == fid }?.first?.name }.getOrNull() ?: "a deleted folder" }
    }
    var preview by remember { mutableStateOf<PreviewResult?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var saving by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    var confirmImportant by remember { mutableStateOf(false) }

    fun conditionsJson(): JsonElement? {
        if (!editable) return source?.conditions
        val leaves = conds.mapNotNull { it.toJson() }
        if (leaves.isEmpty()) return null
        return buildJsonObject { put(if (matchAll) "all" else "any", JsonArray(leaves)) }
    }
    fun exceptionsJson(): JsonElement? {
        if (!editable) return source?.exceptions
        val items = groups.mapNotNull { g ->
            val leaves = g.mapNotNull { it.toJson() }
            when (leaves.size) { 0 -> null; 1 -> leaves[0]; else -> buildJsonObject { put("all", JsonArray(leaves)) } }
        }
        return if (items.isEmpty()) null else buildJsonObject { put("any", JsonArray(items)) }
    }

    // live preview, debounced; keyed on everything that changes the match
    val previewKey = conds.joinToString { "${it.kind}:${it.text}" } + matchAll + groups.joinToString("|") { g -> g.joinToString { "${it.kind}:${it.text}" } }
    LaunchedEffect(previewKey) {
        delay(600)
        val c = conditionsJson() ?: run { preview = null; return@LaunchedEffect }
        preview = runCatching { Api.get(context).previewRule(PreviewIn(c, exceptionsJson())) }.getOrNull()
    }

    fun save() {
        saving = true
        scope.launch {
            try {
                // keep extras this form doesn't edit (category, tag); folder comes from the picker
                val actionJson = buildJsonObject {
                    source?.action?.forEach { (k, v) -> if (k != "type" && k != "folder_id") put(k, v) }
                    put("type", action)
                    folderId?.let { put("folder_id", it) }
                }
                val body = RuleIn(name.trim(), existing?.enabled ?: true, conditionsJson()!!, actionJson, exceptionsJson(), existing?.accountScope, origin = origin)
                if (existing != null) Api.get(context).updateRule(existing.id, body) else Api.get(context).createRule(body)
                RuleEditorSeed.clear()
                onDone()
            } catch (t: Throwable) { error = t.userMessage() } finally { saving = false }
        }
    }

    if (pickingFolder) FolderPickerDialog("File matching mail in…", null, note = "Filing never changes the mail in Gmail.",
        onDismiss = { pickingFolder = false }) { f -> pickingFolder = false; f?.let { folderId = it.id; folderName = it.name } }

    Column(Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).imePadding().padding(18.dp)) {
        Text("‹ Rules", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable { RuleEditorSeed.clear(); onDone() }.padding(vertical = 6.dp))
        Text(if (existing != null) "Edit rule" else "New rule", style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.padding(vertical = 8.dp))
        if (origin == "english" && existing == null) Banner("Drafted from your sentence. Check it, then save.", Ink.signal)
        draft?.notes?.takeIf { it.isNotEmpty() && existing == null }?.let { notes ->
            Spacer(Modifier.height(8.dp))
            Banner(notes.joinToString("\n"), Ink.warn)
        }
        error?.let { Spacer(Modifier.height(8.dp)); Banner(it, Ink.urgent) }

        SectionLabel("Name")
        Field(name, { name = it }, "e.g. Bank alerts: silent")

        if (editable) {
            SectionLabel("When")
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Chip("all of these", matchAll) { matchAll = true }
                Chip("any of these", !matchAll) { matchAll = false }
            }
            conds.forEachIndexed { i, row -> ConditionRow(row, canRemove = conds.size > 1) { conds.removeAt(i) } }
            Text("+ condition", color = Ink.signal, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable { conds.add(CondRow(CondKind.SUBJECT_ANY, "")) }.padding(vertical = 10.dp))

            SectionLabel("Unless (any of these groups)")
            groups.forEachIndexed { gi, group ->
                Column(Modifier.fillMaxWidth().padding(top = 8.dp).border(1.dp, Ink.line2, Radius.lg).padding(10.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(if (group.size > 1) "Exception ${gi + 1}: all of" else "Exception ${gi + 1}", color = Ink.text3, style = MaterialTheme.typography.labelMedium, modifier = Modifier.weight(1f))
                        Text("Remove", color = Ink.text3, style = MaterialTheme.typography.labelMedium, modifier = Modifier.clickable { groups.removeAt(gi) }.padding(4.dp))
                    }
                    group.forEachIndexed { i, row -> ConditionRow(row, canRemove = group.size > 1) { group.removeAt(i) } }
                    Text("+ and…", color = Ink.signal, style = MaterialTheme.typography.labelMedium, modifier = Modifier.clickable { group.add(CondRow(CondKind.AMOUNT_ABOVE, "")) }.padding(top = 8.dp))
                }
            }
            Text("+ exception", color = Ink.signal, style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.clickable { groups.add(mutableStateListOf(CondRow(CondKind.SUBJECT_ANY, ""))) }.padding(vertical = 10.dp))
            Text("Sender conditions only match mail Gmail verified, so spoofed senders never match. Amounts are read from the subject or preview text.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
        } else {
            SectionLabel("When")
            Text(describe(source?.conditions), color = Ink.text, style = MaterialTheme.typography.bodyMedium)
            source?.exceptions?.let { SectionLabel("Unless"); Text(describe(it), color = Ink.text, style = MaterialTheme.typography.bodyMedium) }
            Text("This rule's shape can't be edited in this form, but you can rename it, change its action, save or delete it.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
        }

        SectionLabel("Then")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            ACTIONS.forEach { (key, label) -> Chip(label, action == key, dot = Ink.tier(when (key) { "notify_urgent" -> "urgent"; "notify_normal", "llm" -> "normal"; "digest" -> "digest"; else -> null })) { action = key } }
        }
        Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(if (folderId == null) "Also file in a folder" else "Also file in ${folderName ?: "…"}", color = Ink.text2,
                style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            Text(if (folderId == null) "Pick" else "Change", color = Ink.signal, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable { pickingFolder = true }.padding(6.dp))
            if (folderId != null) Text("Remove", color = Ink.text3, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable { folderId = null; folderName = null }.padding(6.dp))
        }

        val p = preview
        val hidesImportant = p != null && action in QUIETING && p.importantMatches > 0
        Spacer(Modifier.height(16.dp))
        SiftCard(border = if (hidesImportant) Ink.urgent.copy(alpha = 0.5f) else Ink.line2) {
            if (p == null) Text("Add a condition to see which of your recent mail it matches.", color = Ink.text3, style = MaterialTheme.typography.bodyMedium)
            else {
                val verb = when (action) {
                    "silent" -> "stored silently"; "ignore" -> "ignored"; "digest" -> "sent to the digest"
                    "notify_normal" -> "notified as normal"; "notify_urgent" -> "notified as urgent"; else -> "sent to the AI"
                }
                Text("Of the ${p.checked} mails Sift has stored:", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
                Row(verticalAlignment = Alignment.Bottom) {
                    Text("${p.matches}", style = MaterialTheme.typography.displaySmall, color = if (hidesImportant) Ink.urgent else Ink.signal)
                    Text("  would be $verb", color = Ink.text2, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(bottom = 6.dp))
                }
                if (hidesImportant) Text("${p.importantMatches} of them look important (urgent, needs action, or on a company timeline). This rule would quiet them.",
                    color = Ink.urgent, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 4.dp))
                p.samples.take(6).forEach { s ->
                    Text((if (s.important) "⚠ " else "· ") + "${s.sender ?: ""} · ${s.subject ?: ""}", color = if (s.important && action in QUIETING) Ink.urgent else Ink.text2,
                        style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 4.dp))
                }
                if (p.keptByExceptions > 0) {
                    Text("${p.keptByExceptions} kept by your exceptions (this rule leaves them alone):", color = Ink.signal,
                        style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 12.dp))
                    p.keptSamples.take(6).forEach { s ->
                        Text("✓ ${s.sender ?: ""} · ${s.subject ?: ""}", color = Ink.text2, style = MaterialTheme.typography.bodySmall,
                            maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 4.dp))
                    }
                }
                if (p.bodyNotPreviewed) Text("Body conditions can't be previewed (mail bodies are never stored); they apply to new mail.", color = Ink.warn, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
                Text("Sift stores mail from the time you connected an account, so this count grows over time.", color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
            }
        }

        Spacer(Modifier.height(18.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PrimaryButton(if (saving) "Saving…" else "Save rule", enabled = !saving && name.isNotBlank() && conditionsJson() != null) {
                if (hidesImportant) confirmImportant = true else save()
            }
            if (existing != null) GhostButton("Delete", color = Ink.urgent) { deleting = true }
        }
        Spacer(Modifier.height(32.dp))
    }

    if (confirmImportant) AlertDialog(
        onDismissRequest = { confirmImportant = false },
        title = { Text("Quiet important mail?") },
        text = { Text("This rule matches ${preview?.importantMatches ?: 0} mails Sift marked as important. New mail like them would no longer notify you. Add an exception, or save anyway.") },
        confirmButton = { TextButton(onClick = { confirmImportant = false; save() }) { Text("Save anyway", color = Ink.urgent) } },
        dismissButton = { TextButton(onClick = { confirmImportant = false }) { Text("Go back", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
    if (deleting && existing != null) AlertDialog(
        onDismissRequest = { deleting = false },
        title = { Text("Delete this rule?") },
        text = { Text("Mail it matched stays where it is. New mail is classified without it.") },
        confirmButton = { TextButton(onClick = { deleting = false; scope.launch { try { Api.get(context).deleteRule(existing.id); RuleEditorSeed.clear(); onDone() } catch (t: Throwable) { error = t.userMessage() } } }) { Text("Delete", color = Ink.urgent) } },
        dismissButton = { TextButton(onClick = { deleting = false }) { Text("Cancel", color = Ink.text2) } },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}

@Composable
private fun ConditionRow(row: CondRow, canRemove: Boolean, onRemove: () -> Unit) {
    var open by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(top = 8.dp).background(Ink.bg2, Radius.lg).padding(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("${row.kind.label} ▾", color = Ink.text, style = MaterialTheme.typography.titleSmall, modifier = Modifier.clickable { open = true }.padding(vertical = 4.dp))
                DropdownMenu(expanded = open, onDismissRequest = { open = false }, containerColor = Ink.surface2) {
                    CondKind.entries.forEach { k -> DropdownMenuItem(text = { Text(k.label) }, onClick = { row.kind = k; open = false }) }
                }
            }
            if (canRemove) Text("✕", color = Ink.text3, modifier = Modifier.clickable(onClick = onRemove).padding(8.dp))
        }
        if (row.kind != CondKind.ATTACHMENT) Field(
            row.text, { row.text = it }, row.kind.inputLabel, mono = row.kind == CondKind.SUBJECT_REGEX,
            keyboard = if (row.kind == CondKind.AMOUNT_ABOVE || row.kind == CondKind.AMOUNT_BELOW) KeyboardType.Number else KeyboardType.Text,
            placeholder = "e.g. ${row.kind.hint}", singleLine = !row.kind.list,
        )
    }
}
