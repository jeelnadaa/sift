package com.solarquack.sift.data

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/** The same live stream the web app uses (GET /api/v1/events, server-sent events), open only while
 * the app is on screen, so new mail and changes made elsewhere show within about a second without
 * waiting for a silent push (which Android may delay). Every event becomes [LiveEvents.changed];
 * screens then reload quietly. Reconnects with backoff (1 s … 30 s); after a reconnect a change is
 * announced too, so anything missed meanwhile is fetched. Closed in onStop: no battery cost in the
 * background, where the silent FCM "sync" push still covers changes. */
object LiveStream {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var job: Job? = null
    @Volatile private var call: Call? = null

    private val client by lazy {
        OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)  // the server pings every 20 s
            .build()
    }

    fun start(context: Context) {
        val app = context.applicationContext
        if (job?.isActive == true || !Session.signedIn(app)) return
        job = scope.launch {
            var attempt = 0
            while (isActive && Session.signedIn(app)) {
                val gotData = runCatching { listen(app, reconnect = attempt > 0) }.getOrDefault(false)
                if (!isActive) break
                attempt = if (gotData) 1 else attempt + 1
                delay(if (gotData) 1_000L else minOf(30_000L, 1_000L shl minOf(attempt, 5)))
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
        call?.cancel()
        call = null
    }

    /** Reads the stream until it ends; true when the server answered with events. */
    private fun listen(context: Context, reconnect: Boolean): Boolean {
        val token = Session.token(context) ?: return false
        val req = Request.Builder()
            .url(Session.server(context).trimEnd('/') + "/api/v1/events")
            .header("Authorization", "Bearer $token")
            .header("Accept", "text/event-stream")
            .build()
        val c = client.newCall(req)
        call = c
        c.execute().use { res ->
            if (!res.isSuccessful) return false
            val source = res.body?.source() ?: return false
            var gotData = false
            while (true) {
                val line = source.readUtf8Line() ?: break
                if (!line.startsWith("data:")) continue
                val hello = line.contains("\"hello\"")
                if (hello) {
                    gotData = true
                    if (reconnect) LiveEvents.changed()  // catch up on what happened while away
                } else {
                    LiveEvents.changed()
                }
            }
            return gotData
        }
    }
}
