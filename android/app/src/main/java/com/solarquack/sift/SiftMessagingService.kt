package com.solarquack.sift

import android.Manifest
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

/**
 * The backend sends data-only, high-priority FCM messages; we build the notification here
 * so each priority tier gets its own channel. Phase 1 adds action buttons and acknowledgements.
 */
class SiftMessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        Prefs.saveToken(this, token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        val tier = Tier.from(data["priority"])
        val sentAt = data["sent_at_ms"]?.toLongOrNull()
        if (sentAt != null) {
            val delayMs = System.currentTimeMillis() - sentAt
            Prefs.saveLastDelay(this, delayMs)
            Log.i(TAG, "push received, delay ${delayMs}ms")
        }
        show(tier, data["title"] ?: "Sift", data["body"].orEmpty())
    }

    private fun show(tier: Tier, title: String, body: String) {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = NotificationCompat.Builder(this, tier.channelId)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setSubText(tier.channelId.uppercase())
            .setColor(0xFFC8FF3D.toInt())
            .setPriority(if (tier == Tier.URGENT) NotificationCompat.PRIORITY_HIGH else NotificationCompat.PRIORITY_DEFAULT)
            .setCategory(NotificationCompat.CATEGORY_EMAIL)
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(this).notify(System.currentTimeMillis().toInt(), notification)
    }

    companion object {
        private const val TAG = "SiftFCM"
    }
}
