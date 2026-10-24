package com.solarquack.sift

import android.Manifest
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.CalendarIntent
import com.solarquack.sift.data.Push
import com.solarquack.sift.data.Session
import kotlinx.coroutines.runBlocking

/**
 * The server sends data-only, high-priority FCM messages; we build the notification here so
 * each priority tier has its own channel, then acknowledge receipt so the server stops
 * re-sending urgent mail.
 */
class SiftMessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        Session.saveFcmToken(this, token)
        if (Session.signedIn(this)) runCatching { runBlocking { Push.registerDevice(this@SiftMessagingService) } }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        data["sent_at_ms"]?.toLongOrNull()?.let {
            val delay = System.currentTimeMillis() - it
            Session.saveLastDelay(this, delay)
            Log.i(TAG, "push received after ${delay}ms")
        }
        show(data)
        val notificationId = data["notification_id"]
        if (notificationId != null && Session.signedIn(this)) {
            // onMessageReceived runs off the main thread with a short time budget; a quick call is fine
            runCatching { runBlocking { Api.get(this@SiftMessagingService).ack(notificationId) } }
                .onFailure { Log.w(TAG, "ack failed; the server may re-send") }
        }
    }

    private fun show(data: Map<String, String>) {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val tier = Tier.from(data["priority"])
        val messageId = data["message_id"]
        val id = (data["notification_id"] ?: data["sent_at_ms"] ?: "0").hashCode()
        val open = PendingIntent.getActivity(
            this, id,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra(MainActivity.EXTRA_MESSAGE_ID, messageId),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val title = data["title"] ?: "Sift"
        val body = data["body"].orEmpty()
        val header = listOfNotNull(tier.channelId.uppercase(), data["account"]?.takeIf { it.isNotBlank() }).joinToString(" · ")
        val builder = NotificationCompat.Builder(this, tier.channelId)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(listOfNotNull(data["subject"]?.takeIf { it.isNotBlank() && it != body }, body).joinToString("\n")))
            .setSubText(header)
            .setColor(0xFFC8FF3D.toInt())
            .setPriority(if (tier == Tier.URGENT) NotificationCompat.PRIORITY_HIGH else NotificationCompat.PRIORITY_DEFAULT)
            .setCategory(NotificationCompat.CATEGORY_EMAIL)
            .setContentIntent(open)
            .setAutoCancel(true)
            .setOnlyAlertOnce(data["resend"] == null)
        addActions(builder, data, id, messageId, open)
        NotificationManagerCompat.from(this).notify(id, builder.build())
    }

    /** Up to three buttons (Android's limit), most useful first. */
    private fun addActions(builder: NotificationCompat.Builder, data: Map<String, String>, id: Int, messageId: String?, open: PendingIntent) {
        var slots = 3
        val choices = data["company_choices"].orEmpty().lines().mapNotNull { line ->
            line.split("|", limit = 2).takeIf { it.size == 2 && it[0].isNotBlank() }?.let { it[0] to it[1] }
        }
        if (choices.isNotEmpty() && messageId != null) {
            // "Which company?": two most likely drives as one-tap answers, then "Other" opens the mail
            choices.take(2).forEachIndexed { i, (oppId, name) ->
                builder.addAction(0, name, broadcast(id * 10 + i, NotificationActionReceiver.ACTION_COMPANY, id) {
                    putExtra(NotificationActionReceiver.EXTRA_MESSAGE_ID, messageId)
                    putExtra(NotificationActionReceiver.EXTRA_OPPORTUNITY_ID, oppId)
                    putExtra(NotificationActionReceiver.EXTRA_LABEL, name)
                })
                slots--
            }
            builder.addAction(0, "Other…", open)
            return
        }
        data["link"]?.takeIf { it.startsWith("http") && slots > 0 }?.let { url ->
            builder.addAction(0, data["link_label"]?.takeIf { it.isNotBlank() } ?: "Open link",
                PendingIntent.getActivity(this, id + 1, Intent(Intent.ACTION_VIEW, Uri.parse(url)), PendingIntent.FLAG_IMMUTABLE))
            slots--
        }
        data["deadline"]?.takeIf { it.isNotBlank() && slots > 0 }?.let { deadline ->
            CalendarIntent.build(data["title"].orEmpty() + ": " + data["body"].orEmpty(), deadline)?.let { cal ->
                builder.addAction(0, "Add to calendar", PendingIntent.getActivity(this, id + 2, cal, PendingIntent.FLAG_IMMUTABLE))
                slots--
            }
        }
        data["todo_id"]?.takeIf { it.isNotBlank() && slots > 0 }?.let { todoId ->
            builder.addAction(0, "Done", broadcast(id + 3, NotificationActionReceiver.ACTION_TODO_DONE, id) {
                putExtra(NotificationActionReceiver.EXTRA_TODO_ID, todoId)
            })
        }
    }

    private fun broadcast(requestCode: Int, action: String, notificationId: Int, extras: Intent.() -> Unit): PendingIntent {
        val intent = Intent(this, NotificationActionReceiver::class.java).setAction(action)
            .putExtra(NotificationActionReceiver.EXTRA_NOTIFICATION_ID, notificationId).apply(extras)
        return PendingIntent.getBroadcast(this, requestCode, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    companion object {
        private const val TAG = "SiftFCM"
    }
}
