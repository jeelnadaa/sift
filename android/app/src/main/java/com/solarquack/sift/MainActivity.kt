package com.solarquack.sift

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.sp
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.solarquack.sift.data.Session
import com.solarquack.sift.ui.screens.AccountsScreen
import com.solarquack.sift.ui.screens.FeedScreen
import com.solarquack.sift.ui.screens.LoginScreen
import com.solarquack.sift.ui.screens.MailScreen
import com.solarquack.sift.ui.screens.RulesScreen
import com.solarquack.sift.ui.screens.SettingsScreen
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.Radius
import com.solarquack.sift.ui.theme.SiftTheme

class MainActivity : ComponentActivity() {
    /** Message to open, from a notification tap. */
    private var openMessage by mutableStateOf<String?>(null)

    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        openMessage = intent.getStringExtra(EXTRA_MESSAGE_ID)
        if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        setContent { SiftTheme { App() } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.getStringExtra(EXTRA_MESSAGE_ID)?.let { openMessage = it }
    }

    @Composable
    private fun App() {
        val nav = rememberNavController()
        val start = if (Session.signedIn(this)) "feed" else "login"
        LaunchedEffect(openMessage) {
            openMessage?.let { if (Session.signedIn(this@MainActivity)) nav.navigate("mail/$it") }
            openMessage = null
        }
        val route = nav.currentBackStackEntryAsState().value?.destination?.route
        Column(Modifier.fillMaxSize().background(Ink.bg).systemBarsPadding()) {
            Box(Modifier.weight(1f)) {
                NavHost(nav, startDestination = start) {
                    composable("login") { LoginScreen { nav.navigate("feed") { popUpTo("login") { inclusive = true } } } }
                    composable("feed") { FeedScreen(onOpen = { nav.navigate("mail/$it") }, onAccounts = { nav.go("accounts") }) }
                    composable("silenced") { FeedScreen(silenced = true, onOpen = { nav.navigate("mail/$it") }, onAccounts = { nav.go("accounts") }) }
                    composable("mail/{id}") { entry -> MailScreen(entry.arguments?.getString("id") ?: "") { nav.popBackStack() } }
                    composable("accounts") { AccountsScreen() }
                    composable("rules") { RulesScreen() }
                    composable("settings") {
                        SettingsScreen(
                            onSignedOut = { nav.navigate("login") { popUpTo(0) } },
                            onSilenced = { nav.navigate("silenced") },
                        )
                    }
                }
            }
            if (route != null && route != "login") BottomBar(nav, route)
        }
    }

    @Composable
    private fun BottomBar(nav: NavHostController, route: String) {
        NavigationBar(containerColor = Ink.bg2, tonalElevation = androidx.compose.ui.unit.Dp(0f)) {
            listOf("feed" to "Feed", "rules" to "Rules", "accounts" to "Accounts", "settings" to "Settings").forEach { (dest, label) ->
                val selected = route == dest || (dest == "feed" && (route.startsWith("mail") || route == "silenced"))
                NavigationBarItem(
                    selected = selected,
                    onClick = { nav.go(dest) },
                    icon = { Text(ICONS.getValue(dest), fontSize = 17.sp) },
                    label = { Text(label, style = MaterialTheme.typography.labelMedium) },
                    colors = NavigationBarItemDefaults.colors(
                        selectedIconColor = Ink.signal, selectedTextColor = Ink.text, indicatorColor = Ink.signal.copy(alpha = 0.16f),
                        unselectedIconColor = Ink.text3, unselectedTextColor = Ink.text3,
                    ),
                )
            }
        }
    }

    private fun NavHostController.go(dest: String) = navigate(dest) {
        popUpTo("feed") { saveState = true }
        launchSingleTop = true
        restoreState = true
    }

    companion object {
        const val EXTRA_MESSAGE_ID = "message_id"
        private val ICONS = mapOf("feed" to "◉", "rules" to "⚙", "accounts" to "✉", "settings" to "☰")
    }
}
