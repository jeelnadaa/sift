package com.solarquack.sift

import android.content.Context

object Prefs {
    private const val FILE = "sift"

    private fun prefs(context: Context) = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun saveToken(context: Context, token: String) = prefs(context).edit().putString("fcm_token", token).apply()
    fun token(context: Context): String? = prefs(context).getString("fcm_token", null)

    fun saveLastDelay(context: Context, ms: Long) = prefs(context).edit().putLong("last_delay_ms", ms).apply()
    fun lastDelay(context: Context): Long? = prefs(context).getLong("last_delay_ms", -1).takeIf { it >= 0 }
}
