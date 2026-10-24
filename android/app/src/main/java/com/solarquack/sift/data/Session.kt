package com.solarquack.sift.data

import android.content.Context

/** Server address, sign-in token and small device state, in app-private preferences. */
object Session {
    private const val FILE = "sift"

    private fun prefs(context: Context) = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun server(context: Context): String = prefs(context).getString("server", null) ?: "http://192.168.1.2:8000"
    fun token(context: Context): String? = prefs(context).getString("jwt", null)
    fun email(context: Context): String? = prefs(context).getString("email", null)
    fun signedIn(context: Context) = token(context) != null

    fun signIn(context: Context, server: String, email: String, token: String) =
        prefs(context).edit().putString("server", server.trim().trimEnd('/')).putString("email", email).putString("jwt", token).apply()

    fun setServer(context: Context, server: String) = prefs(context).edit().putString("server", server.trim().trimEnd('/')).apply()

    fun signOut(context: Context) = prefs(context).edit().remove("jwt").apply()

    fun saveFcmToken(context: Context, token: String) = prefs(context).edit().putString("fcm_token", token).apply()
    fun fcmToken(context: Context): String? = prefs(context).getString("fcm_token", null)

    fun saveLastDelay(context: Context, ms: Long) = prefs(context).edit().putLong("last_delay_ms", ms).apply()
    fun lastDelay(context: Context): Long? = prefs(context).getLong("last_delay_ms", -1).takeIf { it >= 0 }
}
