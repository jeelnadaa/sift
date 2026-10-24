package com.solarquack.sift.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import java.time.Duration
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** "assessment_link" -> "Assessment link". Pills never show snake_case (DESIGN.md). */
fun humanize(value: String?): String {
    if (value.isNullOrBlank()) return ""
    val s = value.replace('_', ' ').trim()
    return s.replaceFirstChar { it.uppercase() }
}

fun relativeTime(iso: String?): String {
    if (iso == null) return ""
    return runCatching {
        val t = OffsetDateTime.parse(iso)
        val d = Duration.between(t, OffsetDateTime.now())
        when {
            d.toMinutes() < 1 -> "now"
            d.toMinutes() < 60 -> "${d.toMinutes()}m"
            d.toHours() < 24 -> "${d.toHours()}h"
            d.toDays() < 7 -> "${d.toDays()}d"
            else -> t.atZoneSameInstant(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("d MMM"))
        }
    }.getOrDefault("")
}

fun fullTime(iso: String?): String = runCatching {
    OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("EEE d MMM, h:mm a"))
}.getOrDefault("")

fun accountColor(hex: String?, key: String): Color =
    hex?.let { runCatching { Color(android.graphics.Color.parseColor(it)) }.getOrNull() }
        ?: Ink.accounts[(key.hashCode() and 0x7fffffff) % Ink.accounts.size]

@Composable
fun PriorityDot(priority: String?, size: Int = 8) {
    Box(Modifier.size(size.dp).background(Ink.tier(priority), CircleShape))
}

/** Filled, squarish, informational (DESIGN.md: tags). */
@Composable
fun Tag(text: String, color: Color? = null) {
    val c = color ?: Ink.text2
    Box(
        Modifier.background(if (color != null) color.copy(alpha = 0.14f) else Ink.surface2, Radius.xs).padding(horizontal = 7.dp, vertical = 3.dp),
    ) { Text(humanize(text), color = c, style = MaterialTheme.typography.labelMedium, maxLines = 1) }
}

/** Outlined, interactive; `on` is inverted (DESIGN.md: chips). */
@Composable
fun Chip(text: String, on: Boolean, dot: Color? = null, onClick: () -> Unit) {
    Row(
        Modifier
            .background(if (on) Ink.text else Color.Transparent, Radius.sm)
            .border(1.dp, if (on) Ink.text else Ink.line2, Radius.sm)
            .clickable(onClick = onClick)
            .padding(horizontal = 11.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (dot != null) Box(Modifier.size(8.dp).background(dot, Radius.xs))
        Text(humanize(text), color = if (on) Ink.bg else Ink.text2, style = MaterialTheme.typography.labelMedium, maxLines = 1)
    }
}

@Composable
fun SiftCard(modifier: Modifier = Modifier, border: Color = Ink.line, content: @Composable () -> Unit) {
    Column(modifier.fillMaxWidth().background(Ink.surface, Radius.lg).border(1.dp, border, Radius.lg).padding(16.dp)) { content() }
}

@Composable
fun SectionLabel(text: String) {
    Text(text.uppercase(), color = Ink.text3, style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(top = 18.dp, bottom = 8.dp))
}

@Composable
fun PrimaryButton(label: String, modifier: Modifier = Modifier, enabled: Boolean = true, onClick: () -> Unit) {
    Button(
        onClick = onClick, enabled = enabled, modifier = modifier.height(44.dp), shape = Radius.md,
        colors = ButtonDefaults.buttonColors(containerColor = Ink.signal, contentColor = Ink.signalInk, disabledContainerColor = Ink.surface2),
    ) { Text(label, style = MaterialTheme.typography.labelLarge) }
}

@Composable
fun GhostButton(label: String, modifier: Modifier = Modifier, color: Color = Ink.text, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick, modifier = modifier.height(44.dp), shape = Radius.md,
        border = androidx.compose.foundation.BorderStroke(1.dp, Ink.line2),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = color),
    ) { Text(label, style = MaterialTheme.typography.labelLarge) }
}

@Composable
fun Field(value: String, onChange: (String) -> Unit, label: String, password: Boolean = false, keyboard: KeyboardType = KeyboardType.Text, mono: Boolean = false) {
    OutlinedTextField(
        value = value, onValueChange = onChange, label = { Text(label) }, singleLine = true, shape = Radius.md,
        modifier = Modifier.fillMaxWidth(),
        visualTransformation = if (password) PasswordVisualTransformation() else VisualTransformation.None,
        keyboardOptions = KeyboardOptions(keyboardType = if (password) KeyboardType.Password else keyboard),
        textStyle = if (mono) MaterialTheme.typography.bodyMedium.copy(fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace) else MaterialTheme.typography.bodyLarge,
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = Ink.signal, unfocusedBorderColor = Ink.line2, focusedLabelColor = Ink.signal,
            unfocusedLabelColor = Ink.text3, cursorColor = Ink.signal, focusedContainerColor = Ink.bg2, unfocusedContainerColor = Ink.bg2,
        ),
    )
}

@Composable
fun Banner(text: String, color: Color, action: String? = null, onAction: () -> Unit = {}) {
    Row(
        Modifier.fillMaxWidth().background(color.copy(alpha = 0.10f), Radius.lg).border(1.dp, color.copy(alpha = 0.35f), Radius.lg).padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text, color = Ink.text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        if (action != null) Text(action, color = color, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable(onClick = onAction).padding(start = 12.dp))
    }
}

@Composable
fun Avatar(text: String, tint: Color? = null) {
    Box(
        Modifier.size(36.dp).background(tint?.copy(alpha = 0.15f) ?: Ink.surface2, Radius.md),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text.trim().take(1).uppercase().ifEmpty { "?" }, color = tint ?: Ink.text,
            style = MaterialTheme.typography.titleMedium.copy(fontFamily = com.solarquack.sift.ui.theme.ClashDisplay), maxLines = 1, overflow = TextOverflow.Clip,
        )
    }
}
