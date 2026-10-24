package com.solarquack.sift.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
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
import com.solarquack.sift.data.AiRuleDto
import com.solarquack.sift.data.AiTaskDto
import com.solarquack.sift.data.AiTaskIn
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.FolderDto
import com.solarquack.sift.data.FolderPatch
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.Field
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.SectionLabel
import com.solarquack.sift.ui.SiftSwitch
import com.solarquack.sift.ui.fullTime
import com.solarquack.sift.ui.theme.Ink
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

val CATEGORY_LABELS = linkedMapOf(
    "placement_announcement" to "Placement drive", "registration" to "Registration", "assessment_link" to "Online test",
    "interview" to "Interview", "result" to "Result", "recruiter" to "Recruiter", "action_needed" to "Needs action", "fyi" to "FYI",
)
val TASK_LABELS = mapOf("timelines" to "Build company timelines", "todos" to "Make to-dos", "sort" to "Sort into subfolders")
val TASK_DONE = mapOf("timelines" to "joined timelines", "todos" to "to-dos made", "sort" to "moved")

/** "AI for this folder": file new mail here by what the AI understood, sort into subfolders, and
 * ask the AI to work over the mail already here. */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun FolderAiSheet(start: FolderDto, onDismiss: () -> Unit, onChanged: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var f by remember { mutableStateOf(start) }
    var aiOn by remember { mutableStateOf(true) }
    var tasks by remember { mutableStateOf<List<AiTaskDto>>(emptyList()) }
    var instruction by remember { mutableStateOf(start.autoSortInstruction ?: "") }
    var taskInstruction by remember { mutableStateOf("") }
    var withSub by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    val running = tasks.any { it.status == "queued" || it.status == "running" }

    suspend fun loadTasks() { tasks = Api.get(context).aiTasks().tasks.filter { it.folderId == f.id }.take(5) }
    LaunchedEffect(Unit) {
        try { aiOn = Api.get(context).ai().aiEnabled; loadTasks() } catch (t: Throwable) { error = t.userMessage() }
    }
    LaunchedEffect(running) { while (running) { delay(2000); runCatching { loadTasks() } } }

    fun save(p: FolderPatch) = scope.launch {
        try { f = Api.get(context).editFolder(f.id, p); onChanged() } catch (t: Throwable) { error = t.userMessage() }
    }
    val rule = f.aiRule ?: AiRuleDto()

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = Ink.surface,
        shape = androidx.compose.foundation.shape.RoundedCornerShape(topStart = 14.dp, topEnd = 14.dp)) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(start = 20.dp, end = 20.dp, bottom = 32.dp)) {
            Text("✦ AI for ${f.name}", color = Ink.text, style = MaterialTheme.typography.titleLarge)
            if (!aiOn) Text("Add an API key to enable AI filing, sorting by instruction and AI tasks (Settings → AI provider). Sorting by sender works without one.",
                color = Ink.warn, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
            error?.let { Spacer(Modifier.height(8.dp)); Banner(it, Ink.urgent, "OK") { error = null } }

            SectionLabel("File new mail here when the AI reads it as")
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                CATEGORY_LABELS.forEach { (c, label) ->
                    Chip(label, c in rule.categories) {
                        if (!aiOn) return@Chip
                        val cats = if (c in rule.categories) rule.categories - c else rule.categories + c
                        save(FolderPatch(aiRule = AiRuleDto(cats, rule.timeline)))
                    }
                }
            }
            Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("…or mail that joins a company timeline", color = Ink.text2, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                SiftSwitch(rule.timeline, { on -> if (aiOn) save(FolderPatch(aiRule = AiRuleDto(rule.categories, on))) })
            }

            SectionLabel("Sort mail filed here into subfolders")
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("off" to "Off", "company" to "By company", "sender" to "By sender", "ai" to "By your instruction").forEach { (mode, label) ->
                    Chip(label, (f.autoSort ?: "off") == mode) {
                        if (mode == "ai") { if (aiOn && instruction.isNotBlank()) save(FolderPatch(autoSort = "ai", autoSortInstruction = instruction.trim())) else if (aiOn) error = "Write how to group first, then tap again" }
                        else save(FolderPatch(autoSort = mode))
                    }
                }
            }
            Text(when (f.autoSort) {
                "company" -> "One subfolder per company, made as needed. No extra AI cost."
                "sender" -> "One subfolder per sender. No AI needed."
                "ai" -> "The AI picks or makes a subfolder for each mail (a small AI call per mail)."
                else -> "Mail stays in this folder."
            }, color = Ink.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
            Spacer(Modifier.height(8.dp))
            Field(instruction, { instruction = it.take(500) }, "How to group (for \"By your instruction\")", placeholder = "e.g. one folder per course code")
            if (f.autoSort == "ai" && instruction.trim() != (f.autoSortInstruction ?: "")) {
                Spacer(Modifier.height(8.dp))
                PrimaryButton("Save instruction") { save(FolderPatch(autoSort = "ai", autoSortInstruction = instruction.trim())) }
            }

            SectionLabel("Ask the AI to work on the mail already here")
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Include subfolders", color = Ink.text2, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                SiftSwitch(withSub, { withSub = it })
            }
            Spacer(Modifier.height(8.dp))
            Field(taskInstruction, { taskInstruction = it.take(500) }, "For sorting: how to group this time (optional)")
            Spacer(Modifier.height(8.dp))
            TASK_LABELS.forEach { (kind, label) ->
                GhostButton(label, Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                    if (running) { error = "An AI task is already running here"; return@GhostButton }
                    scope.launch {
                        try {
                            Api.get(context).startAiTask(f.id, AiTaskIn(kind, withSub, taskInstruction.trim().takeIf { kind == "sort" && it.isNotEmpty() }))
                            android.widget.Toast.makeText(context, "Started. You'll get a notification when it's done", android.widget.Toast.LENGTH_SHORT).show()
                            loadTasks()
                        } catch (t: Throwable) { error = t.userMessage() }
                    }
                }
            }
            tasks.forEach { t ->
                Column(Modifier.padding(top = 10.dp)) {
                    Text("${TASK_LABELS[t.kind]} · ${fullTime(t.createdAt)}", color = Ink.text, style = MaterialTheme.typography.bodyMedium)
                    Text(
                        when (t.status) {
                            "queued" -> "Waiting…"
                            "running" -> "${t.done} of ${t.total}…"
                            else -> "${t.changed} ${TASK_DONE[t.kind]} of ${t.done}" + if (t.status == "stopped") " · stopped at the daily cap" else if (t.status == "failed") " · failed" else ""
                        } + " · ${"%,d".format(t.tokens)} tokens",
                        color = Ink.text3, style = MaterialTheme.typography.bodySmall,
                    )
                    t.note?.let { Text(it, color = Ink.text3, style = MaterialTheme.typography.bodySmall) }
                }
            }
        }
    }
}
