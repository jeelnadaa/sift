package com.solarquack.sift

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager

/** One channel per priority tier, each with its own importance (brief section 11). */
enum class Tier(val channelId: String, val title: String, val importance: Int) {
    URGENT("urgent", "Urgent mail", NotificationManager.IMPORTANCE_HIGH),
    NORMAL("normal", "Normal mail", NotificationManager.IMPORTANCE_DEFAULT),
    DIGEST("digest", "Digest", NotificationManager.IMPORTANCE_LOW);

    companion object {
        fun from(value: String?): Tier = entries.firstOrNull { it.channelId == value } ?: NORMAL
    }
}

class SiftApp : Application() {
    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        Tier.entries.forEach { tier ->
            val channel = NotificationChannel(tier.channelId, tier.title, tier.importance).apply {
                enableVibration(tier == Tier.URGENT)
                if (tier == Tier.URGENT) vibrationPattern = longArrayOf(0, 300, 150, 300)
            }
            manager.createNotificationChannel(channel)
        }
    }
}
