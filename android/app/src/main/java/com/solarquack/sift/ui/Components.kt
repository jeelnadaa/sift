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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.selection.toggleable
import androidx.compose.runtime.getValue
import androidx.compose.ui.unit.sp
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
    ) { Text(label, style = MaterialTheme.typography.labelLarge, maxLines = 1, softWrap = false) }
}

@Composable
fun GhostButton(label: String, modifier: Modifier = Modifier, color: Color = Ink.text, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick, modifier = modifier.height(44.dp), shape = Radius.md,
        border = androidx.compose.foundation.BorderStroke(1.dp, Ink.line2),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = color),
    ) { Text(label, style = MaterialTheme.typography.labelLarge, maxLines = 1, softWrap = false) }
}

/** On/off switch in the app's shape (DESIGN.md: small corners, no pill controls). Off is a dark
 * track with a light square knob at the left; on is a lime track with a dark knob at the right, so
 * the two states differ in position as well as colour. */
@Composable
fun SiftSwitch(checked: Boolean, onCheckedChange: ((Boolean) -> Unit)?, modifier: Modifier = Modifier, enabled: Boolean = true) {
    val offset by androidx.compose.animation.core.animateDpAsState(if (checked) 20.dp else 0.dp, label = "knob")
    Box(
        modifier
            .padding(start = 8.dp)
            .size(width = 48.dp, height = 28.dp)
            .background(if (checked) Ink.signal else Ink.surface2, Radius.sm)
            .border(1.dp, if (checked) Ink.signal else Ink.line2, Radius.sm)
            .then(
                if (onCheckedChange != null) Modifier.toggleable(
                    value = checked, enabled = enabled, role = androidx.compose.ui.semantics.Role.Switch,
                    onValueChange = onCheckedChange,
                ) else Modifier
            )
            .padding(4.dp),
    ) {
        Box(Modifier.offset(x = offset).size(18.dp).background(if (checked) Ink.signalInk else Ink.text2, Radius.xs))
    }
}

/** The floating "+ New" / "+ Add" button at the bottom right of a list screen. */
@Composable
fun AddButton(label: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Row(
        modifier.padding(18.dp).heightIn(min = 56.dp).background(Ink.signal, Radius.lg).clickable(onClick = onClick)
            .padding(horizontal = 22.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("+", color = Ink.signalInk, fontSize = 26.sp, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
            modifier = Modifier.padding(end = 8.dp))
        Text(label, color = Ink.signalInk, style = MaterialTheme.typography.labelLarge.copy(fontSize = 16.sp))
    }
}

@Composable
fun Field(
    value: String, onChange: (String) -> Unit, label: String, password: Boolean = false, keyboard: KeyboardType = KeyboardType.Text,
    mono: Boolean = false, placeholder: String? = null, singleLine: Boolean = true,
) {
    // Plain text wraps onto more lines (up to 6) instead of scrolling sideways, so long values can be
    // read without moving the cursor. Passwords, emails and addresses stay one line. Line breaks are
    // never inserted: the keyboard's action key is Done and pasted breaks become spaces.
    val wrap = !password && keyboard == KeyboardType.Text && singleLine
    OutlinedTextField(
        value = value, onValueChange = { onChange(if (wrap) it.replace(Regex("\r?\n"), " ") else it) }, label = { Text(label) },
        singleLine = !wrap && singleLine, maxLines = if (wrap || !singleLine) 6 else 1, shape = Radius.md,
        placeholder = placeholder?.let { { Text(it, color = Ink.text3) } },
        modifier = Modifier.fillMaxWidth(),
        visualTransformation = if (password) PasswordVisualTransformation() else VisualTransformation.None,
        keyboardOptions = KeyboardOptions(keyboardType = if (password) KeyboardType.Password else keyboard, imeAction = androidx.compose.ui.text.input.ImeAction.Done),
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
