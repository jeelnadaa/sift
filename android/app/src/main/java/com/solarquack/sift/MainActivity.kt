package com.solarquack.sift

import android.Manifest
import android.annotation.SuppressLint
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging

/** Phase 0 setup screen: FCM token, notification permission, battery exemption, last push delay. */
class MainActivity : ComponentActivity() {

    private var refresh by mutableStateOf(0)
    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { refresh++ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { SetupScreen() }
    }

    override fun onResume() {
        super.onResume()
        refresh++
    }

    private fun notificationsGranted() = Build.VERSION.SDK_INT < 33 ||
        ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun batteryExempt() = getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(packageName)

    @SuppressLint("BatteryLife") // a personal notifier is a permitted use; the user confirms in a system dialog
    private fun requestBatteryExemption() {
        startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
    }

    @Composable
    private fun SetupScreen() {
        var token by remember { mutableStateOf(Prefs.token(this)) }
        val firebaseReady = remember { FirebaseApp.getApps(this).isNotEmpty() }
        val tick = refresh // recompose on resume and permission result

        LaunchedEffect(firebaseReady) {
            if (firebaseReady) {
                FirebaseMessaging.getInstance().token.addOnSuccessListener {
                    Prefs.saveToken(this@MainActivity, it)
                    token = it
                }
            }
        }

        Column(
            Modifier.fillMaxSize().background(Ink.bg).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 48.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("Sift", color = Ink.text, fontSize = 28.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Text("Phase 0 · push setup", color = Ink.text3, fontSize = 13.sp)
            Spacer(Modifier.height(12.dp))

            StatusRow("Notifications", if (notificationsGranted()) "Granted" else "Not granted", notificationsGranted(), tick) {
                if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
            StatusRow("Battery optimization", if (batteryExempt()) "Exempt" else "Restricted", batteryExempt(), tick) {
                requestBatteryExemption()
            }

            Card {
                Text("FCM TOKEN", color = Ink.text3, fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
                Spacer(Modifier.height(8.dp))
                when {
                    !firebaseReady -> Text("Firebase not configured. Add app/google-services.json and rebuild.", color = Ink.warn, fontSize = 14.sp)
                    token == null -> Text("Fetching…", color = Ink.text2, fontSize = 14.sp)
                    else -> {
                        Text(token!!, color = Ink.text, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                        Spacer(Modifier.height(12.dp))
                        PrimaryButton("Copy token") {
                            getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("FCM token", token))
                        }
                    }
                }
            }

            Prefs.lastDelay(this@MainActivity)?.let { delay ->
                Card {
                    Text("LAST TEST PUSH", color = Ink.text3, fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
                    Text("${delay} ms from server to phone", color = Ink.signal, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                }
            }
        }
    }

    @Composable
    private fun StatusRow(label: String, value: String, ok: Boolean, @Suppress("UNUSED_PARAMETER") tick: Int, onFix: () -> Unit) {
        Card {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(label, color = Ink.text, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                    Text(value, color = if (ok) Ink.signal else Ink.urgent, fontSize = 13.sp)
                }
                if (!ok) PrimaryButton("Fix", onFix)
            }
        }
    }

    @Composable
    private fun Card(content: @Composable () -> Unit) {
        Column(
            Modifier.fillMaxWidth().background(Ink.surface, RoundedCornerShape(10.dp)).border(1.dp, Ink.line, RoundedCornerShape(10.dp)).padding(16.dp),
        ) { content() }
    }

    @Composable
    private fun PrimaryButton(label: String, onClick: () -> Unit) {
        Button(
            onClick = onClick,
            shape = RoundedCornerShape(8.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Ink.signal, contentColor = Ink.signalInk),
        ) { Text(label, fontWeight = FontWeight.Bold) }
    }
}

/** Colors from DESIGN.md. Satoshi and Clash Display arrive with the Phase 1 UI. */
object Ink {
    val bg = Color(0xFF0A0A0B)
    val surface = Color(0xFF151518)
    val line = Color(0xFF26262B)
    val text = Color(0xFFF4F3EE)
    val text2 = Color(0xFFA9A9B1)
    val text3 = Color(0xFF6E6E78)
    val signal = Color(0xFFC8FF3D)
    val signalInk = Color(0xFF10150A)
    val urgent = Color(0xFFFF5A3C)
    val warn = Color(0xFFFFB938)
}
