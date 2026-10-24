package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
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
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
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
enum class CondKind(val label: String, val field: String, val op: String, val hint: String) {
    SENDER_DOMAIN("Sender domain is", "sender_domain", "in", "kotak.com, sliceit.com"),
    SENDER("Sender address is", "sender", "in", "alerts@kotak.com"),
    SUBJECT_ANY("Subject contains any of", "subject", "contains_any", "debited, credited, UPI"),
    SUBJECT_REGEX("Subject matches (regex)", "subject", "matches", "\\b(debited|credited)\\b"),
    BODY_ANY("Body contains any of", "body", "contains_any", "fraud, blocked"),
    LABEL("Gmail label is", "label", "has", "CATEGORY_PROMOTIONS"),
    HEADER("Header is present", "header", "present", "List-Unsubscribe"),
    ATTACHMENT("Has an attachment", "has_attachment", "is", ""),
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
        is JsonPrimitive -> v.contentOrNull ?: ""
        else -> ""
    }
    val kind = when {
        field == "sender_domain" -> CondKind.SENDER_DOMAIN
        field == "sender" && op in setOf("is", "in") -> CondKind.SENDER
        field == "subject" && op == "matches" -> CondKind.SUBJECT_REGEX
        field == "subject" -> CondKind.SUBJECT_ANY
        field == "body" -> CondKind.BODY_ANY
        field == "label" -> CondKind.LABEL
        field == "header" -> CondKind.HEADER
        field == "has_attachment" && (v as? JsonPrimitive)?.booleanOrNull != false -> CondKind.ATTACHMENT
        else -> return null
    }
    return CondRow(kind, text)
}

/** Flat {all|any: [leaves]} or a single leaf -> rows. Null when the tree is nested (not editable here). */
private fun treeToRows(tree: JsonElement?): Pair<Boolean, List<CondRow>>? {
    if (tree == null || tree !is JsonObject) return true to emptyList()
    val (all, items) = when {
        "all" in tree -> true to tree["all"]!!.jsonArray
        "any" in tree -> false to tree["any"]!!.jsonArray
        "field" in tree -> return true to listOfNotNull(leafToRow(tree)).ifEmpty { return null }
        else -> return null
    }
    val rows = items.map { (it as? JsonObject)?.let(::leafToRow) ?: return null }
    return all to rows
}

private val ACTIONS = listOf("notify_urgent" to "Notify urgent", "notify_normal" to "Notify normal", "digest" to "Digest", "silent" to "Store silently", "ignore" to "Ignore", "llm" to "Ask AI")

@Composable
fun RuleEditorScreen(onDone: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val seed = remember { Triple(RuleEditorSeed.rule, RuleEditorSeed.draft, RuleEditorSeed.origin) }
    val (existing, draft, origin) = seed
    val source = existing?.let { RuleDraft(it.name, it.conditions, it.action, it.exceptions, it.accountScope) } ?: draft

    val parsed = remember { treeToRows(source?.conditions) }
    val parsedExc = remember { treeToRows(source?.exceptions) }
    val editable = source == null || (parsed != null && parsedExc != null)

    var name by remember { mutableStateOf(source?.name ?: "") }
    var matchAll by remember { mutableStateOf(parsed?.first ?: true) }
    val conds: SnapshotStateList<CondRow> = remember { mutableStateListOf<CondRow>().apply { addAll(parsed?.second?.ifEmpty { null } ?: listOf(CondRow(CondKind.SENDER_DOMAIN, ""))) } }
    val excs: SnapshotStateList<CondRow> = remember { mutableStateListOf<CondRow>().apply { addAll(parsedExc?.second ?: emptyList()) } }
    var action by remember { mutableStateOf(source?.action?.get("type")?.jsonPrimitive?.contentOrNull ?: "silent") }
    var preview by remember { mutableStateOf<PreviewResult?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var saving by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }

    fun conditionsJson(): JsonElement? {
        val leaves = conds.mapNotNull { it.toJson() }
        if (leaves.isEmpty()) return null
        return buildJsonObject { put(if (matchAll) "all" else "any", JsonArray(leaves)) }
    }
    fun exceptionsJson(): JsonElement? {
        val leaves = excs.mapNotNull { it.toJson() }
        return if (leaves.isEmpty()) null else buildJsonObject { put("any", JsonArray(leaves)) }
    }

    // live preview, debounced; keyed on everything that changes the match
    val previewKey = conds.joinToString { "${it.kind}:${it.text}" } + matchAll + excs.joinToString { "${it.kind}:${it.text}" }
    LaunchedEffect(previewKey) {
        if (!editable) return@LaunchedEffect
        delay(600)
        val c = conditionsJson() ?: run { preview = null; return@LaunchedEffect }
        preview = runCatching { Api.get(context).previewRule(PreviewIn(c, exceptionsJson())) }.getOrNull()
    }

    Column(Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).imePadding().padding(18.dp)) {
        Text("‹ Rules", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable { RuleEditorSeed.clear(); onDone() }.padding(vertical = 6.dp))
        Text(if (existing != null) "Edit rule" else "New rule", style = MaterialTheme.typography.headlineMedium, color = Ink.text, modifier = Modifier.padding(vertical = 8.dp))
        if (origin == "english" && existing == null) Banner("Drafted from your sentence. Check it, then save.", Ink.signal)
        if (!editable) {
            Banner("This rule uses nested conditions, which this screen can't edit. You can still turn it off or delete it.", Ink.warn)
        }
        error?.let { Spacer(Modifier.height(8.dp)); Banner(it, Ink.urgent) }

        if (editable) {
            SectionLabel("Name")
            Field(name, { name = it }, "e.g. Bank alerts: silent")

            SectionLabel("When")
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Chip("all of these", matchAll) { matchAll = true }
                Chip("any of these", !matchAll) { matchAll = false }
            }
            conds.forEachIndexed { i, row -> ConditionRow(row, canRemove = conds.size > 1) { conds.removeAt(i) } }
            Text("+ condition", color = Ink.signal, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable { conds.add(CondRow(CondKind.SUBJECT_ANY, "")) }.padding(vertical = 10.dp))

            SectionLabel("Unless any of these (exceptions)")
            excs.forEachIndexed { i, row -> ConditionRow(row, canRemove = true) { excs.removeAt(i) } }
            Text("+ exception", color = Ink.signal, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable { excs.add(CondRow(CondKind.SUBJECT_ANY, "")) }.padding(vertical = 10.dp))
            Text("Sender conditions only match mail Gmail verified, so spoofed senders never match.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)

            SectionLabel("Then")
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                ACTIONS.forEach { (key, label) -> Chip(label, action == key, dot = Ink.tier(when (key) { "notify_urgent" -> "urgent"; "notify_normal", "llm" -> "normal"; "digest" -> "digest"; else -> null })) { action = key } }
            }

            Spacer(Modifier.height(16.dp))
            SiftCard(border = Ink.line2) {
                val p = preview
                if (p == null) Text("Add a condition to see which of your recent mail it matches.", color = Ink.text3, style = MaterialTheme.typography.bodyMedium)
                else {
                    Row(verticalAlignment = Alignment.Bottom) {
                        Text("${p.matches}", style = MaterialTheme.typography.displaySmall, color = Ink.signal)
                        Text("  of your last ${p.checked} mails would match", color = Ink.text2, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(bottom = 6.dp))
                    }
                    p.samples.take(5).forEach { s ->
                        Text("${s.sender ?: ""} · ${s.subject ?: ""}", color = Ink.text2, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 4.dp))
                    }
                    if (p.bodyNotPreviewed) Text("Body conditions can't be previewed (mail bodies are never stored); they apply to new mail.", color = Ink.warn, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
                }
            }
        }

        Spacer(Modifier.height(18.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (editable) PrimaryButton(if (saving) "Saving…" else "Save rule", enabled = !saving && name.isNotBlank() && conditionsJson() != null) {
                saving = true
                scope.launch {
                    try {
                        val body = RuleIn(name.trim(), existing?.enabled ?: true, conditionsJson()!!, buildJsonObject { put("type", action) }, exceptionsJson(), existing?.accountScope, origin = origin)
                        if (existing != null) Api.get(context).updateRule(existing.id, body) else Api.get(context).createRule(body)
                        RuleEditorSeed.clear()
                        onDone()
                    } catch (t: Throwable) { error = t.userMessage() } finally { saving = false }
                }
            }
            if (existing != null) GhostButton("Delete", color = Ink.urgent) { deleting = true }
        }
        Spacer(Modifier.height(32.dp))
    }

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
        if (row.kind != CondKind.ATTACHMENT) Field(row.text, { row.text = it }, row.kind.hint, mono = row.kind == CondKind.SUBJECT_REGEX)
    }
}
