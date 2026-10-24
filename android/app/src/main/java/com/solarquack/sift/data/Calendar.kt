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
}
