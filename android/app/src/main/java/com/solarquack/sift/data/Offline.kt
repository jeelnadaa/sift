package com.solarquack.sift.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import java.io.File
import java.io.IOException
import java.security.MessageDigest

/** Saved copies of what the app already loaded, so Sift still opens when the server is off (the
 * laptop is shut, or the tunnel answers with its error page).
 *
 * An OkHttp interceptor keeps every successful JSON GET in the app's private storage, one folder
 * per server + account. When the server can't be reached, the last copy is returned instead and
 * [since] says the app is offline (a banner shows it). Changes (send, archive, edit) still need the
 * server and fail as before. Mail bodies are cached by the WebView itself (ThreadView). Settings >
 * "Saved on this device" shows the size and clears it; signing out clears it too.
 * Nothing saved here contains the sign-in token or any key. */
object Offline {
    private const val DIR = "offline"
    private const val MAX_BYTES = 60L * 1024 * 1024  // oldest copies are dropped past this

    private val state = MutableStateFlow<Long?>(null)
    /** When the oldest saved copy on screen was taken, while offline; null when online. */
    val since: StateFlow<Long?> = state

    private fun root(context: Context) = File(context.filesDir, DIR)

    private fun folder(context: Context): File {
        val who = "${Session.server(context)}|${Session.email(context) ?: "anon"}"
        return File(root(context), sha(who).take(16))
    }

    private fun sha(s: String) = MessageDigest.getInstance("SHA-256").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }

    private fun saveable(path: String) = path.startsWith("/api/v1/") && !path.startsWith("/api/v1/auth/") &&
        !path.startsWith("/api/v1/events") && !path.contains("/attachments/")

    fun interceptor(context: Context): Interceptor {
        val app = context.applicationContext
        return Interceptor { chain ->
            val req = chain.request()
            val canSave = req.method == "GET" && saveable(req.url.encodedPath)
            val file = if (canSave) File(folder(app), sha(req.url.toString()) + ".json") else null
            val res = try {
                chain.proceed(req)
            } catch (e: IOException) {
                return@Interceptor savedOrThrow(req, file, e)
            }
            // a 5xx that isn't Sift's own JSON error is a proxy saying the server is unreachable
            val json = res.header("Content-Type")?.contains("application/json") == true
            if (res.code >= 500 && !json) {
                res.close()
                return@Interceptor savedOrThrow(req, file, IOException("Sift server unreachable (${res.code})"))
            }
            state.value = null
            if (file != null && res.isSuccessful && json) {
                val bytes = res.peekBody(8L * 1024 * 1024).bytes()
                runCatching {
                    file.parentFile?.mkdirs()
                    val tmp = File(file.path + ".tmp")
                    tmp.writeBytes(bytes)
                    tmp.renameTo(file)
                    trim(app)
                }
            }
            res
        }
    }

    private fun savedOrThrow(req: okhttp3.Request, file: File?, e: IOException): Response {
        if (file == null || !file.exists()) throw e
        val savedAt = file.lastModified()
        state.value = state.value?.let { minOf(it, savedAt) } ?: savedAt
        return Response.Builder()
            .request(req).protocol(Protocol.HTTP_1_1).code(200).message("Saved copy")
            .header("X-Sift-Saved-At", savedAt.toString())
            .body(file.readBytes().toResponseBody("application/json".toMediaType()))
            .build()
    }

    /** Keeps the store under MAX_BYTES by dropping the least recently saved copies. */
    private fun trim(context: Context) {
        val files = root(context).walkTopDown().filter { it.isFile }.toList()
        var total = files.sumOf { it.length() }
        if (total <= MAX_BYTES) return
        for (f in files.sortedBy { it.lastModified() }) {
            if (total <= MAX_BYTES * 8 / 10) break
            total -= f.length()
            f.delete()
        }
    }

    fun size(context: Context): Pair<Long, Int> {
        val files = root(context).walkTopDown().filter { it.isFile }.toList()
        return files.sumOf { it.length() } to files.size
    }

    /** Deletes every saved copy on this phone (all accounts) and the WebView's saved mail pages. */
    fun clear(context: Context) {
        root(context).deleteRecursively()
        state.value = null
    }
}
