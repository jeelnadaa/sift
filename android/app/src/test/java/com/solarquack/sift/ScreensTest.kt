package com.solarquack.sift

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import com.solarquack.sift.data.TodoDto
import com.solarquack.sift.ui.AddButton
import com.solarquack.sift.ui.Chip
import com.solarquack.sift.ui.SiftSwitch
import com.solarquack.sift.ui.screens.EditTodoDialog
import com.solarquack.sift.ui.screens.LandingScreen
import com.solarquack.sift.ui.screens.LoginScreen
import com.solarquack.sift.ui.theme.Ink
import com.solarquack.sift.ui.theme.SiftTheme
import org.junit.Rule
import org.junit.Test

/** Renders screens on the computer to look at them (no device or emulator needed):
 * ./gradlew :app:recordPaparazziDebug writes PNGs to app/src/test/snapshots. */
class ScreensTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, maxPercentDifference = 0.1)

    private fun shot(content: @Composable () -> Unit) = paparazzi.snapshot {
        SiftTheme { Box(Modifier.fillMaxSize().background(Ink.bg)) { content() } }
    }

    @org.junit.Before fun fake() = FakeApi.install()
    @org.junit.After fun real() = FakeApi.remove()

    @Test fun feed() = shot { com.solarquack.sift.ui.screens.FeedScreen(onOpen = {}, onAccounts = {}, onSearch = {}, onAsk = {}) }
    @Test fun mail() = shot { com.solarquack.sift.ui.screens.MailScreen("m1", onBack = {}) }
    @Test fun timeline() = shot { com.solarquack.sift.ui.screens.OpportunityScreen("o1", onBack = {}, onOpenMail = {}) }
    @Test fun todos() = shot { com.solarquack.sift.ui.screens.TodoScreen(onOpenMail = {}) }
    @Test fun deals() = shot { com.solarquack.sift.ui.screens.DealsScreen(onOpen = {}) }
    @Test fun more() = shot { com.solarquack.sift.ui.screens.MoreScreen(onNavigate = {}) }
    @Test fun ask() = shot { com.solarquack.sift.ui.screens.AskScreen(onBack = {}, onOpenMail = {}, onOpenLink = {}, onRuleDraft = {}) }
    @Test fun groups() = shot { com.solarquack.sift.ui.screens.GroupsScreen(onBack = {}, onOpen = {}) }
    @Test fun editTodoDelete() = shot {
        com.solarquack.sift.ui.screens.EditTodoDialog(TodoDto("t1", "Register for the Globex drive", notes = "Needs the latest marksheet"), onDismiss = {}, onDelete = {}) { _, _, _ -> }
    }

    @Test fun landing() = shot { LandingScreen(onGetStarted = {}, onSignIn = {}, animate = false) }

    @Test fun login() = shot { LoginScreen(startRegistering = true) {} }

    @Test fun controls() = shot {
        Column(Modifier.padding(24.dp)) {
            Row2 { SiftSwitch(true, {}); SiftSwitch(false, {}); Chip("By company", true) {}; Chip("Off", false) {} }
        }
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomEnd) { AddButton("New rule") {} }
    }

    @Test fun editTodo() = shot {
        EditTodoDialog(TodoDto(id = "t", title = "Send updated CV to Acme", notes = "PDF, under 2 MB", dueAt = "2026-10-28T18:00:00+05:30"), onDismiss = {}) { _, _, _ -> }
    }

    @Test fun addSection() = shot { com.solarquack.sift.ui.screens.SectionDialog("Acme Corp", null, onDismiss = {}) { _, _ -> } }

    @Composable private fun Row2(content: @Composable () -> Unit) =
        androidx.compose.foundation.layout.Row(horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) { content() }
}
