package com.solarquack.sift.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.solarquack.sift.ui.SectionLabel
import com.solarquack.sift.ui.theme.Ink

/** Everything that is not a daily view (mobile design: Feed, Deals, To-do, More). */
@Composable
fun MoreScreen(onNavigate: (String) -> Unit) {
    Column(Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).padding(start = 18.dp, end = 18.dp, top = 18.dp, bottom = 96.dp)) {
        Text("More", style = MaterialTheme.typography.headlineMedium, color = Ink.text)
        Item("✦ Ask Sift", "Tell it what to do in plain words: timelines, folders, to-dos, rules, mail") { onNavigate("ask") }
        SectionLabel("Write")
        Item("Outbox", "Drafts, scheduled mail, follow-up reminders") { onNavigate("outbox") }
        SectionLabel("Organize")
        Item("Attachments", "All files, PDFs, spreadsheets and images across accounts") { onNavigate("attachments") }
        Item("Folders", "Your own folders, nested; rules can file into them") { onNavigate("folders") }
        Item("Groups", "Similar mail stacked together: bank alerts, newsletters, one company's drive") { onNavigate("groups") }
        SectionLabel("Control")
        Item("Rules", "What gets silenced, digested or marked urgent") { onNavigate("rules") }
        Item("Silenced mail", "Stored and searchable, never notified") { onNavigate("silenced") }
        Item("Categories", "Your own categories for the AI to use") { onNavigate("categories") }
        SectionLabel("Account")
        Item("Accounts", "Connected Gmail accounts and their status") { onNavigate("accounts") }
        Item("Token usage", "What your own AI key has spent") { onNavigate("usage") }
        Item("Settings", "AI key, notifications, this phone") { onNavigate("settings") }
    }
}

@Composable
private fun Item(title: String, subtitle: String, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, color = Ink.text, style = MaterialTheme.typography.titleMedium)
            Text(subtitle, color = Ink.text3, style = MaterialTheme.typography.bodySmall)
        }
        Text("›", color = Ink.text3, style = MaterialTheme.typography.titleMedium)
    }
    HorizontalDivider(color = Ink.line)
}
