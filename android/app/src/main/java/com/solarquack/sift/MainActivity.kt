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
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.selectable
import androidx.compose.material3.Icon
import androidx.compose.ui.Alignment
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.solarquack.sift.ui.SiftIcons
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
import androidx.compose.runtime.collectAsState
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
import com.solarquack.sift.ui.screens.AttachmentsScreen
import com.solarquack.sift.ui.screens.ComposeArgs
import com.solarquack.sift.ui.screens.ComposeScreen
import com.solarquack.sift.ui.screens.OutboxScreen
import com.solarquack.sift.ui.screens.CategoriesScreen
import com.solarquack.sift.ui.screens.DealsScreen
import com.solarquack.sift.ui.screens.RuleEditorScreen
import com.solarquack.sift.ui.screens.ScanScreen
import com.solarquack.sift.ui.screens.UsageScreen
import com.solarquack.sift.ui.screens.MoreScreen
import com.solarquack.sift.ui.screens.OpportunityScreen
import com.solarquack.sift.ui.screens.TodoScreen
import com.solarquack.sift.ui.screens.FeedScreen
import com.solarquack.sift.ui.screens.FolderScreen
import com.solarquack.sift.ui.screens.FoldersScreen
import com.solarquack.sift.ui.screens.GroupScreen
import com.solarquack.sift.ui.screens.ReadThreadScreen
import com.solarquack.sift.ui.screens.SearchScreen
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

    override fun onResume() {
        super.onResume()
        // back on screen: catch up on anything changed meanwhile (read elsewhere, new mail)
        com.solarquack.sift.data.LiveEvents.changed()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.getStringExtra(EXTRA_MESSAGE_ID)?.let { openMessage = it }
    }

    @Composable
    private fun App() {
        val nav = rememberNavController()
        val start = if (Session.signedIn(this)) "feed" else "welcome"
        LaunchedEffect(openMessage) {
            openMessage?.let { if (Session.signedIn(this@MainActivity)) nav.navigate("mail/$it") }
            openMessage = null
        }
        val route = nav.currentBackStackEntryAsState().value?.destination?.route
        Column(Modifier.fillMaxSize().background(Ink.bg).systemBarsPadding()) {
            OfflineBar()
            Box(Modifier.weight(1f)) {
                NavHost(nav, startDestination = start) {
                    composable("welcome") {
                        com.solarquack.sift.ui.screens.LandingScreen(onGetStarted = { nav.navigate("login?register=true") }, onSignIn = { nav.navigate("login") })
                    }
                    composable("login?register={register}", arguments = listOf(androidx.navigation.navArgument("register") {
                        type = androidx.navigation.NavType.BoolType; defaultValue = false
                    })) { entry ->
                        LoginScreen(startRegistering = entry.arguments?.getBoolean("register") == true) { nav.navigate("feed") { popUpTo(0) } }
                    }
                    composable("feed") { FeedScreen(onOpen = { nav.navigate("mail/$it") }, onAccounts = { nav.go("accounts") }, onOpenGroup = { nav.navigate("group/$it") }, onSearch = { nav.navigate("search") }, onAsk = { nav.navigate("ask") }) }
                    composable("ask") {
                        com.solarquack.sift.ui.screens.AskScreen(onBack = { nav.popBackStack() }, onOpenMail = { nav.navigate("mail/$it") },
                            onOpenLink = { l -> askRoute(l)?.let { nav.navigate(it) } },
                            onRuleDraft = { d ->
                                com.solarquack.sift.ui.screens.RuleEditorSeed.clear()
                                com.solarquack.sift.ui.screens.RuleEditorSeed.draft = d
                                com.solarquack.sift.ui.screens.RuleEditorSeed.origin = "english"
                                nav.navigate("rule-edit")
                            })
                    }
                    composable(
                        "compose?mode={mode}&message={message}&account={account}&gmail={gmail}&draft={draft}",
                        arguments = listOf("mode", "message", "account", "gmail", "draft").map { name ->
                            androidx.navigation.navArgument(name) { type = androidx.navigation.NavType.StringType; nullable = true; defaultValue = null }
                        },
                    ) { entry ->
                        val a = entry.arguments
                        ComposeScreen(ComposeArgs(a?.getString("mode") ?: "new", a?.getString("message"), a?.getString("account"), a?.getString("gmail"), a?.getString("draft"))) { message ->
                            message?.let { android.widget.Toast.makeText(this@MainActivity, it, android.widget.Toast.LENGTH_SHORT).show() }
                            nav.popBackStack()
                        }
                    }
                    composable("outbox") {
                        OutboxScreen(onBack = { nav.popBackStack() }, onCompose = { nav.navigate(compose()) },
                            onOpenDraft = { acc, did -> nav.navigate(compose(draft = "$acc:$did")) }, onOpenThread = { a, t -> nav.navigate("read/$a/$t") })
                    }
                    composable("group/{id}") { entry ->
                        GroupScreen(entry.arguments?.getString("id") ?: "", onBack = { nav.popBackStack() }, onOpenMail = { nav.navigate("mail/$it") }, onEditRule = { nav.navigate("rule-edit") })
                    }
                    composable("groups") { com.solarquack.sift.ui.screens.GroupsScreen(onBack = { nav.popBackStack() }, onOpen = { nav.navigate("group/$it") }) }
                    composable("search") {
                        SearchScreen(onOpenMail = { nav.navigate("mail/$it") }, onOpenThread = { a, t -> nav.navigate("read/$a/$t") }, onBack = { nav.popBackStack() })
                    }
                    composable("read/{account}/{thread}") { entry ->
                        ReadThreadScreen(entry.arguments?.getString("account") ?: "", entry.arguments?.getString("thread") ?: "", onBack = { nav.popBackStack() },
                            onWrite = { mode, acc, gmail -> nav.navigate(compose(mode = mode, account = acc, gmail = gmail)) })
                    }
                    composable("attachments") { AttachmentsScreen(onBack = { nav.popBackStack() }, onOpenMail = { nav.navigate("mail/$it") }) }
                    composable("folders") { FoldersScreen(onOpen = { nav.navigate("folder/$it") }, onBack = { nav.popBackStack() }) }
                    composable("folder/{id}") { entry ->
                        FolderScreen(entry.arguments?.getString("id") ?: "", onBack = { nav.popBackStack() }, onOpenMail = { nav.navigate("mail/$it") }, onOpenFolder = { nav.navigate("folder/$it") })
                    }
                    composable("silenced") { FeedScreen(silenced = true, onOpen = { nav.navigate("mail/$it") }, onAccounts = { nav.go("accounts") }) }
                    composable("mail/{id}") { entry ->
                        MailScreen(entry.arguments?.getString("id") ?: "", onBack = { nav.popBackStack() }, onOpenOpportunity = { nav.navigate("deal/$it") }, onEditRule = { nav.navigate("rule-edit") },
                            onWrite = { mode, id -> nav.navigate(compose(mode = mode, message = id)) }, onOpenGroup = { nav.navigate("group/$it") })
                    }
                    composable("deals") { DealsScreen(onOpen = { nav.navigate("deal/$it") }) }
                    composable("deal/{id}") { entry ->
                        OpportunityScreen(entry.arguments?.getString("id") ?: "", onBack = { nav.popBackStack() }, onOpenMail = { nav.navigate("mail/$it") })
                    }
                    composable("todo") { TodoScreen(onOpenMail = { nav.navigate("mail/$it") }) }
                    composable("more") { MoreScreen(onNavigate = { nav.navigate(it) }) }
                    composable("accounts") { AccountsScreen(onScan = { nav.navigate("scan/$it") }) }
                    composable("scan/{id}") { entry -> ScanScreen(entry.arguments?.getString("id") ?: "", onBack = { nav.popBackStack() }) }
                    composable("rules") { RulesScreen(onEdit = { nav.navigate("rule-edit") }) }
                    composable("rule-edit") { RuleEditorScreen(onDone = { nav.popBackStack() }) }
                    composable("categories") { CategoriesScreen(onBack = { nav.popBackStack() }) }
                    composable("usage") { UsageScreen(onBack = { nav.popBackStack() }) }
                    composable("settings") {
                        SettingsScreen(
                            onSignedOut = { nav.navigate("login") { popUpTo(0) } },
                            onSilenced = { nav.navigate("silenced") },
                        )
                    }
                }
                // Deals, To-do and Rules keep their own add button in this corner
                val fab = route != null && (route in setOf("feed", "silenced", "search", "folders", "attachments", "outbox", "more", "accounts") ||
                    route == "groups" || route.startsWith("folder/") || route.startsWith("group/") || route.startsWith("read/"))
                if (fab) WriteFab(Modifier.align(Alignment.BottomEnd)) { nav.navigate(compose()) }
            }
            if (route != null && !route.startsWith("login") && route != "welcome") BottomBar(nav, route)
        }
    }

    /** Where an Ask Sift result's "Open" goes (pages named by the server, see app/assistant.py). */
    private fun askRoute(l: com.solarquack.sift.data.AskLinkDto): String? = when (l.page) {
        "opportunity" -> l.id?.let { "deal/$it" }
        "folder" -> l.id?.let { "folder/$it" }
        "group" -> l.id?.let { "group/$it" }
        "draft" -> l.id?.let { compose(draft = it) }
        "feed" -> "feed"
        "todo" -> "todo"
        "opportunities" -> "deals"
        "folders", "groups", "rules", "settings", "outbox", "silenced", "usage", "search" -> l.page
        else -> null
    }

    /** Shown while screens come from the phone's saved copies (data/Offline.kt). */
    @Composable
    private fun OfflineBar() {
        val since = com.solarquack.sift.data.Offline.since.collectAsState().value ?: return
        val time = java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.MEDIUM, java.text.DateFormat.SHORT).format(java.util.Date(since))
        Row(Modifier.fillMaxWidth().background(androidx.compose.ui.graphics.Color(0xFF2A2210)).padding(horizontal = 16.dp, vertical = 9.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text("Offline", color = Ink.warn, style = MaterialTheme.typography.labelLarge)
            Text("  ·  Showing what this phone saved ($time). Changes need the server.", color = Ink.text2,
                style = MaterialTheme.typography.bodySmall, maxLines = 2)
        }
    }

    /** Bottom tabs, drawn by hand to match DESIGN.md: line icons, a small-cornered tinted block
     * behind the active icon (not Material's pill), 13 sp labels. */
    @Composable
    private fun BottomBar(nav: NavHostController, route: String) {
        Column(Modifier.fillMaxWidth().background(Ink.bg2)) {
            androidx.compose.material3.HorizontalDivider(color = Ink.line)
            Row(Modifier.fillMaxWidth().height(72.dp).padding(horizontal = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                listOf(Triple("feed", "Feed", SiftIcons.Feed), Triple("deals", "Deals", SiftIcons.Deals), Triple("todo", "To-do", SiftIcons.Todo), Triple("more", "More", SiftIcons.More))
                    .forEach { (dest, label, icon) ->
                        val selected = when (dest) {
                            "feed" -> route == "feed" || route.startsWith("mail") || route.startsWith("group/") || route == "search" || route.startsWith("read/") || route.startsWith("compose")
                            "deals" -> route == "deals" || route.startsWith("deal/")
                            "more" -> route in setOf("more", "rules", "rule-edit", "accounts", "settings", "silenced", "categories", "usage", "folders", "outbox") || route.startsWith("scan/") || route.startsWith("folder/")
                            else -> route == dest
                        }
                        Column(
                            Modifier.weight(1f).fillMaxHeight()
                                .selectable(selected = selected, role = androidx.compose.ui.semantics.Role.Tab, onClick = { nav.go(dest) }),
                            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
                        ) {
                            Box(
                                Modifier.size(width = 58.dp, height = 32.dp).background(if (selected) Ink.signal.copy(alpha = 0.14f) else Color.Transparent, Radius.sm),
                                contentAlignment = Alignment.Center,
                            ) { Icon(icon, contentDescription = null, tint = if (selected) Ink.signal else Ink.text3, modifier = Modifier.size(25.dp)) }
                            Text(label, color = if (selected) Ink.text else Ink.text3, style = MaterialTheme.typography.labelMedium.copy(fontSize = 13.sp),
                                modifier = Modifier.padding(top = 4.dp))
                        }
                    }
            }
        }
    }

    /** The floating Write button: same corner on every list screen (like Gmail's compose). */
    @Composable
    private fun WriteFab(modifier: Modifier, onClick: () -> Unit) {
        Row(
            modifier.padding(18.dp).shadow(10.dp, Radius.lg).height(58.dp).background(Ink.signal, Radius.lg).clickable(onClick = onClick)
                .padding(start = 18.dp, end = 22.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(SiftIcons.Pen, contentDescription = null, tint = Ink.signalInk, modifier = Modifier.size(24.dp))
            Text("Write", color = Ink.signalInk, style = MaterialTheme.typography.labelLarge.copy(fontSize = 16.sp), modifier = Modifier.padding(start = 10.dp))
        }
    }

    /** Switch bottom tabs. With "Remember where I was" off (default), a tab opens at its top. */
    private fun NavHostController.go(dest: String) {
        val keep = Session.rememberTabs(this@MainActivity)
        navigate(dest) {
            popUpTo("feed") { saveState = keep }
            launchSingleTop = true
            restoreState = keep
        }
    }

    /** Route to the composer; every part is optional (see ComposeArgs). */
    private fun compose(mode: String? = null, message: String? = null, account: String? = null, gmail: String? = null, draft: String? = null): String =
        "compose?" + listOf("mode" to mode, "message" to message, "account" to account, "gmail" to gmail, "draft" to draft)
            .filter { it.second != null }.joinToString("&") { (k, v) -> "$k=${android.net.Uri.encode(v)}" }

    companion object {
        const val EXTRA_MESSAGE_ID = "message_id"
        private val ICONS = mapOf("feed" to "◉", "deals" to "◈", "todo" to "☑", "more" to "☰")
    }
}
