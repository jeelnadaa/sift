package com.solarquack.sift.data

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import java.util.Collections

/** Downloads the newest mails ahead of time (owner, 2026-10-31: the newest 100 feed mails, on
 * Wi-Fi and mobile data), so opening one shows its contents at once, even on a slow connection or
 * with the server off. Each mail is one request (`thread?bundle=true`: the conversation with its
 * reader documents inline), saved by the [Offline] interceptor under the conversation's key.
 * Two at a time; mail saved in the last few hours is skipped; failures are simply retried on the
 * next feed load. Nothing here runs while signed out. */
object Prefetch {
    const val NEWEST = 100
    private const val FRESH_MS = 6L * 3600 * 1000
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val gate = Semaphore(2)
    private val inFlight = Collections.synchronizedSet(HashSet<String>())

    fun mails(context: Context, ids: List<String>) {
        val app = context.applicationContext
        if (!Session.signedIn(app) || Offline.since.value != null) return
        ids.distinct().take(NEWEST).forEach { id ->
            if (Offline.hasFreshThread(app, id, FRESH_MS) || !inFlight.add(id)) return@forEach
            scope.launch {
                try {
                    gate.withPermit { runCatching { Api.get(app).thread(id) } }
                } finally {
                    inFlight.remove(id)
                }
            }
        }
    }

    /** One mail, right now (a notification just arrived for it); the caller bounds the time. */
    suspend fun one(context: Context, id: String) {
        runCatching { Api.get(context.applicationContext).thread(id) }
    }
}
