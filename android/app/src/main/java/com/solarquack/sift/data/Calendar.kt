package com.solarquack.sift.data

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.provider.CalendarContract
import android.widget.Toast
import java.time.OffsetDateTime

/**
 * "Add to calendar" through the phone's calendar app (CalendarContract insert intent).
 * The user confirms the event there, so Sift needs no Google Calendar permission.
 */
object CalendarIntent {
    fun build(title: String, deadlineIso: String, description: String? = null): Intent? {
        val end = runCatching { OffsetDateTime.parse(deadlineIso).toInstant().toEpochMilli() }.getOrNull() ?: return null
        return Intent(Intent.ACTION_INSERT)
            .setData(CalendarContract.Events.CONTENT_URI)
            .putExtra(CalendarContract.EXTRA_EVENT_BEGIN_TIME, end - 60 * 60 * 1000) // one-hour block ending at the deadline
            .putExtra(CalendarContract.EXTRA_EVENT_END_TIME, end)
            .putExtra(CalendarContract.Events.TITLE, title)
            .putExtra(CalendarContract.Events.DESCRIPTION, description ?: "Deadline from Sift")
            .putExtra(CalendarContract.Events.HAS_ALARM, true)
    }

    fun open(context: Context, title: String, deadlineIso: String, description: String? = null) {
        val intent = build(title, deadlineIso, description) ?: return
        try {
            context.startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(context, "No calendar app found", Toast.LENGTH_SHORT).show()
        }
    }

    fun googleCalendarUrl(title: String, deadlineIso: String, description: String? = null): String? {
        val endMs = runCatching { OffsetDateTime.parse(deadlineIso).toInstant().toEpochMilli() }.getOrNull() ?: return null
        val startMs = endMs - 60 * 60 * 1000
        val toBasic = { ms: Long ->
            java.time.Instant.ofEpochMilli(ms).toString().replace("-", "").replace(":", "").replace(Regex("\\.\\d{3}"), "")
        }
        val dates = "${toBasic(startMs)}/${toBasic(endMs)}"
        val encodedTitle = java.net.URLEncoder.encode(title, "UTF-8")
        val encodedDates = java.net.URLEncoder.encode(dates, "UTF-8")
        var url = "https://calendar.google.com/calendar/render?action=TEMPLATE&text=$encodedTitle&dates=$encodedDates"
        if (description != null) {
            url += "&details=" + java.net.URLEncoder.encode(description, "UTF-8")
        }
        return url
    }
}
