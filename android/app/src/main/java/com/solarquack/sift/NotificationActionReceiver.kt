package com.solarquack.sift

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.widget.Toast
import androidx.core.app.NotificationManagerCompat
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.CompanyAnswer
import com.solarquack.sift.data.Session
import com.solarquack.sift.data.TodoPatch
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Notification buttons that act without opening the app: "which company?" answers and Done. */
class NotificationActionReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val app = context.applicationContext
        val notificationId = intent.getIntExtra(EXTRA_NOTIFICATION_ID, 0)
        if (!Session.signedIn(app)) return
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            val message = try {
                val api = Api.get(app)
                when (intent.action) {
                    ACTION_COMPANY -> {
                        api.answerCompany(intent.getStringExtra(EXTRA_MESSAGE_ID)!!, CompanyAnswer(opportunityId = intent.getStringExtra(EXTRA_OPPORTUNITY_ID)))
                        "Added to ${intent.getStringExtra(EXTRA_LABEL)}"
                    }
                    ACTION_TODO_DONE -> {
                        api.updateTodo(intent.getStringExtra(EXTRA_TODO_ID)!!, TodoPatch(done = true))
                        "Marked done"
                    }
                    else -> null
                }
            } catch (t: Throwable) {
                Log.w(TAG, "notification action failed: ${t.javaClass.simpleName}")
                "Couldn't reach Sift. Open the app to try again."
            }
            withContext(Dispatchers.Main) {
                if (message != null && !message.startsWith("Couldn't")) NotificationManagerCompat.from(app).cancel(notificationId)
                message?.let { Toast.makeText(app, it, Toast.LENGTH_SHORT).show() }
                pending.finish()
            }
        }
    }

    companion object {
        private const val TAG = "SiftAction"
        const val ACTION_COMPANY = "com.solarquack.sift.action.COMPANY"
        const val ACTION_TODO_DONE = "com.solarquack.sift.action.TODO_DONE"
        const val EXTRA_NOTIFICATION_ID = "notification_id"
        const val EXTRA_MESSAGE_ID = "message_id"
        const val EXTRA_OPPORTUNITY_ID = "opportunity_id"
        const val EXTRA_TODO_ID = "todo_id"
        const val EXTRA_LABEL = "label"
    }
}
