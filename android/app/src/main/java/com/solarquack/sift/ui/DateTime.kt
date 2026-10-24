package com.solarquack.sift.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDefaults
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.TimePickerDefaults
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.unit.dp
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

fun parseZoned(iso: String?): ZonedDateTime? =
    iso?.let { runCatching { OffsetDateTime.parse(it).atZoneSameInstant(ZoneId.systemDefault()) }.getOrNull() }

fun ZonedDateTime.iso(): String = format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)

/** A date button and a time button (any day, any minute), plus Clear when `allowNone`. */
@OptIn(ExperimentalMaterial3Api::class, androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun DateTimeRow(value: ZonedDateTime?, onChange: (ZonedDateTime?) -> Unit, allowNone: Boolean = true, pastAllowed: Boolean = true) {
    var pickingDate by remember { mutableStateOf(false) }
    var pickingTime by remember { mutableStateOf(false) }
    // wraps onto a second line in narrow dialogs instead of cutting a button off
    androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        GhostButton(value?.format(DateTimeFormatter.ofPattern("EEE d MMM yyyy")) ?: "Pick a day…") { pickingDate = true }
        if (value != null) GhostButton(value.format(DateTimeFormatter.ofPattern("HH:mm"))) { pickingTime = true }
        if (value != null && allowNone) GhostButton("Clear", color = Ink.text3) { onChange(null) }
    }
    if (pickingDate) {
        val start = (value ?: ZonedDateTime.now()).toLocalDate().atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
        val state = rememberDatePickerState(initialSelectedDateMillis = start, selectableDates = object : androidx.compose.material3.SelectableDates {
            override fun isSelectableDate(utcTimeMillis: Long) = pastAllowed || utcTimeMillis >= LocalDate.now().atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
        })
        DatePickerDialog(
            onDismissRequest = { pickingDate = false },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let {
                        val day = Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate()
                        val time = value?.toLocalTime() ?: LocalTime.of(10, 0)
                        onChange(day.atTime(time).atZone(ZoneId.systemDefault()))
                    }
                    pickingDate = false
                }) { Text("OK", color = Ink.signal) }
            },
            dismissButton = { TextButton(onClick = { pickingDate = false }) { Text("Cancel", color = Ink.text2) } },
            colors = DatePickerDefaults.colors(containerColor = Ink.surface),
        ) { DatePicker(state = state) }
    }
    if (pickingTime && value != null) {
        val state = rememberTimePickerState(initialHour = value.hour, initialMinute = value.minute, is24Hour = true)
        AlertDialog(
            onDismissRequest = { pickingTime = false },
            title = { Text("Time") },
            text = {
                TimePicker(state = state, colors = TimePickerDefaults.colors(
                    clockDialColor = Ink.bg2, selectorColor = Ink.signal, timeSelectorSelectedContainerColor = Ink.signal.copy(alpha = 0.2f),
                    timeSelectorSelectedContentColor = Ink.signal, timeSelectorUnselectedContainerColor = Ink.bg2,
                ))
            },
            confirmButton = { TextButton(onClick = { onChange(value.withHour(state.hour).withMinute(state.minute).withSecond(0).withNano(0)); pickingTime = false }) { Text("OK", color = Ink.signal) } },
            dismissButton = { TextButton(onClick = { pickingTime = false }) { Text("Cancel", color = Ink.text2) } },
            containerColor = Ink.surface, shape = Radius.xl,
        )
    }
}

object DateTimeIso {
    fun ZonedDateTime.isoString(): String = format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)
}
