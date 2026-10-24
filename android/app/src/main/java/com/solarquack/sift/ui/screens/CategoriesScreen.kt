package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.CategoryDto
import com.solarquack.sift.data.CategoryIn
import com.solarquack.sift.data.userMessage
import com.solarquack.sift.ui.Banner
import com.solarquack.sift.ui.Field
import com.solarquack.sift.ui.GhostButton
import com.solarquack.sift.ui.PrimaryButton
import com.solarquack.sift.ui.SectionLabel
import com.solarquack.sift.ui.SiftCard
import com.solarquack.sift.ui.Tag
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import kotlinx.coroutines.launch

/** Custom categories: a name and a plain-English definition the AI uses when classifying. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CategoriesScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var items by remember { mutableStateOf<List<CategoryDto>>(emptyList()) }
    var editing by remember { mutableStateOf<CategoryDto?>(null) }
    var creating by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun load() = scope.launch { try { items = Api.get(context).categories(); error = null } catch (t: Throwable) { error = t.userMessage() } }
    LaunchedEffect(Unit) { load() }

    Column(Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).padding(18.dp)) {
        Text("‹ More", color = Ink.text2, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onBack).padding(vertical = 6.dp))
        Text("Categories", style = MaterialTheme.typography.headlineMedium, color = Ink.text)
        Text("With AI on, every new mail gets one category. Add your own with a short description; the AI reads it.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
        error?.let { Spacer(Modifier.height(8.dp)); Banner(it, Ink.urgent, "Retry") { load() } }

        SectionLabel("Yours")
        val custom = items.filter { !it.builtin }
        if (custom.isEmpty()) Text("None yet.", color = Ink.text3, style = MaterialTheme.typography.bodyMedium)
        custom.forEach { c ->
            SiftCard(Modifier.padding(bottom = 8.dp).clickable { editing = c }) {
                Text(c.name, color = Ink.text, style = MaterialTheme.typography.titleSmall)
                Text(c.definition ?: "", color = Ink.text2, style = MaterialTheme.typography.bodySmall)
            }
        }
        Spacer(Modifier.height(6.dp))
        PrimaryButton("+ New category") { creating = true }

        SectionLabel("Built in")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items.filter { it.builtin }.forEach { Tag(it.name) }
        }
        Spacer(Modifier.height(24.dp))
    }

    if (creating || editing != null) CategoryDialog(editing, onDismiss = { creating = false; editing = null }, onDelete = editing?.id?.let { id ->
        { scope.launch { try { Api.get(context).deleteCategory(id); editing = null; load() } catch (t: Throwable) { error = t.userMessage() } } }
    }) { name, definition ->
        scope.launch {
            try {
                val id = editing?.id
                if (id != null) Api.get(context).updateCategory(id, CategoryIn(name, definition)) else Api.get(context).createCategory(CategoryIn(name, definition))
                creating = false; editing = null; load()
            } catch (t: Throwable) { error = t.userMessage(); creating = false; editing = null }
        }
    }
}

@Composable
private fun CategoryDialog(existing: CategoryDto?, onDismiss: () -> Unit, onDelete: (() -> Unit)?, onSave: (String, String) -> Unit) {
    var name by remember { mutableStateOf(existing?.name ?: "") }
    var definition by remember { mutableStateOf(existing?.definition ?: "") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (existing != null) "Edit category" else "New category") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Field(name, { name = it }, "Name (e.g. Hackathons)")
                Field(definition, { definition = it }, "What belongs here")
                Text("Example: invites, registrations and results from hackathon platforms like Devfolio or Unstop.", color = Ink.text3, style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = { PrimaryButton("Save", enabled = name.trim().length >= 2 && definition.trim().length >= 5) { onSave(name.trim(), definition.trim()) } },
        dismissButton = {
            Row {
                onDelete?.let { TextButton(onClick = it) { Text("Delete", color = Ink.urgent) } }
                TextButton(onClick = onDismiss) { Text("Cancel", color = Ink.text2) }
            }
        },
        containerColor = Ink.surface, shape = Radius.xl,
    )
}
