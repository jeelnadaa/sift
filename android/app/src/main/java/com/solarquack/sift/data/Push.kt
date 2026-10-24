package com.solarquack.sift.data

import android.content.Context
import android.os.Build
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

object Push {
    fun firebaseReady(context: Context) = FirebaseApp.getApps(context).isNotEmpty()

    suspend fun fcmToken(context: Context): String? {
        if (!firebaseReady(context)) return null
        return suspendCancellableCoroutine { cont ->
            FirebaseMessaging.getInstance().token
                .addOnSuccessListener { cont.resume(it) }
                .addOnFailureListener { cont.resume(null) }
        }?.also { Session.saveFcmToken(context, it) }
    }

    /** Tell the server where to send this user's notifications. Safe to repeat. */
    suspend fun registerDevice(context: Context) {
        val token = fcmToken(context) ?: return
        Api.get(context).registerDevice(DeviceIn(token, label = "${Build.MANUFACTURER} ${Build.MODEL}".trim()))
    }
}
