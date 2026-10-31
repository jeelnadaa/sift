package com.solarquack.sift

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.widget.Toast
import androidx.core.app.NotificationManagerCompat
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.CompanyAnswer
import com.solarquack.sift.data.FileIn
import com.solarquack.sift.data.LikeThisIn
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
        if (intent.action == ACTION_COPY_CODE) {  // on the phone only: no server call
            intent.getStringExtra(EXTRA_CODE)?.let { copyCode(app, it) }
            NotificationManagerCompat.from(app).cancel(notificationId)
            return
        }
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
                    ACTION_IGNORE -> {
                        api.likeThis(intent.getStringExtra(EXTRA_MESSAGE_ID)!!, LikeThisIn("silent", save = true))
                        "Mails like this will be silenced"
                    }
                    ACTION_FILE_LAST -> {
                        api.fileLastUsed(FileIn(listOf(intent.getStringExtra(EXTRA_MESSAGE_ID)!!)))
                        "Filed in ${intent.getStringExtra(EXTRA_LABEL)}"
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
        const val ACTION_COPY_CODE = "com.solarquack.sift.action.COPY_CODE"
        const val EXTRA_CODE = "code"

        /** Copies a one-time code, marked sensitive so Android 13+ hides it in the clipboard preview. */
        fun copyCode(context: Context, code: String) {
            val clip = android.content.ClipData.newPlainText("One-time code", code)
            clip.description.extras = android.os.PersistableBundle().apply { putBoolean("android.content.extra.IS_SENSITIVE", true) }
            (context.getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager).setPrimaryClip(clip)
            // Android 13+ confirms copies itself
            if (android.os.Build.VERSION.SDK_INT < 33) Toast.makeText(context, "Code copied", Toast.LENGTH_SHORT).show()
        }
        const val ACTION_COMPANY = "com.solarquack.sift.action.COMPANY"
        const val ACTION_TODO_DONE = "com.solarquack.sift.action.TODO_DONE"
        const val ACTION_IGNORE = "com.solarquack.sift.action.IGNORE"
        const val ACTION_FILE_LAST = "com.solarquack.sift.action.FILE_LAST"
        const val EXTRA_NOTIFICATION_ID = "notification_id"
        const val EXTRA_MESSAGE_ID = "message_id"
        const val EXTRA_OPPORTUNITY_ID = "opportunity_id"
        const val EXTRA_TODO_ID = "todo_id"
        const val EXTRA_LABEL = "label"
    }
}
