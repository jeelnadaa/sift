package com.solarquack.sift

import com.solarquack.sift.data.AccountDto
import com.solarquack.sift.data.AiStatus
import com.solarquack.sift.data.AddrDto
import com.solarquack.sift.data.Api
import com.solarquack.sift.data.GroupedPage
import com.solarquack.sift.data.GroupingStatus
import com.solarquack.sift.data.LinkDto
import com.solarquack.sift.data.MessageDto
import com.solarquack.sift.data.MessagePage
import com.solarquack.sift.data.OpportunityDetail
import com.solarquack.sift.data.OpportunityDto
import com.solarquack.sift.data.SiftApi
import com.solarquack.sift.data.ThreadDto
import com.solarquack.sift.data.ThreadMessageDto
import com.solarquack.sift.data.TimelineEventDto
import com.solarquack.sift.data.TodoDto
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import java.lang.reflect.Proxy
import java.time.OffsetDateTime

/** An in-memory stand-in for the Sift server, so screens can be rendered with realistic data.
 * Calls it doesn't know fail like an unreachable server would. */
object FakeApi {
    private fun ago(hours: Long) = OffsetDateTime.now().minusHours(hours).toString()
    private fun ahead(hours: Long) = OffsetDateTime.now().plusHours(hours).toString()

    val mails = listOf(
        MessageDto("m1", "a1", account = "jeelnadaa", accountColor = "#e8c547", sender = "noreply@hirepro.in", senderName = "HirePro",
            subject = "Acme Corp online assessment: link inside", snippet = "Your test link is live", receivedAt = ago(1), priority = "urgent",
            category = "assessment_link", status = "processed", unread = true, summary = "Acme Corp online test, closes tonight 11:59 PM",
            company = "Acme Corp", platform = "HirePro", deadline = ahead(9), links = listOf(LinkDto("https://assess.hirepro.in/t/1", "Start test")),
            actionNeeded = true, opportunityId = "o1"),
        MessageDto("m2", "a1", account = "jeelnadaa", accountColor = "#e8c547", sender = "placement@univ.edu", senderName = "Placement Cell",
            subject = "Globex campus drive: register by Friday", snippet = "Globex is visiting", receivedAt = ago(3), priority = "normal",
            category = "placement_announcement", status = "processed", company = "Globex", opportunityId = "o2"),
        MessageDto("m3", "a1", account = "jeelnadaa", accountColor = "#e8c547", sender = "alerts@slice.bank.in", senderName = "slice",
            subject = "₹217 debited from your slice account to Zepto", snippet = "UPI", receivedAt = ago(5), priority = "normal",
            category = "fyi", status = "processed"),
        MessageDto("m4", "a1", account = "jeelnadaa", accountColor = "#e8c547", sender = "news@linkedin.com", senderName = "LinkedIn",
            subject = "Naveen S reacted to this post", snippet = "I'm happy to share that I've started a new position", receivedAt = ago(7),
            priority = "digest", category = "other", status = "processed"),
    )

    private val api: Any = Proxy.newProxyInstance(SiftApi::class.java.classLoader, arrayOf(SiftApi::class.java)) { _, method, args ->
        when (method.name) {
            "accounts" -> listOf(AccountDto("a1", "jeelnadaa@gmail.com", "active", color = "#e8c547", canModify = true, lastCheckOkAt = ago(0)))
            "messages" -> MessagePage(mails)
            "groupedFeed" -> GroupedPage(mails.map { m ->
                JsonObject(Api.json.encodeToJsonElement(MessageDto.serializer(), m).jsonObject + ("type" to JsonPrimitive("mail")))
            })
            "grouping" -> GroupingStatus("yes")
            "ai" -> AiStatus(true, "valid", "gemini", "gemini-2.5-flash", "a91f", 1240, 50000)
            "message" -> mails.first { it.id == args?.get(0) }
            "thread" -> ThreadDto("Acme Corp online assessment: link inside", "jeelnadaa", "a1", messages = listOf(
                ThreadMessageDto("g1", "m1", AddrDto("HirePro", "noreply@hirepro.in"), listOf(AddrDto("Jeel", "jeelnadaa@gmail.com")),
                    subject = "Acme Corp online assessment", date = ago(1), snippet = "Your test link is live",
                    text = "Hi,\n\nYour Acme Corp online assessment is live. Start before 11:59 PM tonight.\n\nHirePro"),
            ))
            "opportunities" -> listOf(OpportunityDto("o1", "Acme Corp", deadline = ahead(9), events = 3, lastKind = "assessment"),
                OpportunityDto("o2", "Globex", events = 1, lastKind = "announcement"))
            "opportunity" -> OpportunityDetail("o1", "Acme Corp", aliases = listOf("ACME"), deadline = ahead(9), timeline = listOf(
                TimelineEventDto("e1", "announcement", "name", ago(72), summary = "Acme Corp campus drive announced", subject = "Campus drive", senderName = "Placement Cell", account = "jeelnadaa"),
                TimelineEventDto("e2", "registration", "user", ago(48), title = "Registered on the portal", note = "Used roll number login", manual = true),
                TimelineEventDto("e3", "assessment", "ai", ago(1), deadline = ahead(9), summary = "Online test, closes tonight", senderName = "HirePro", account = "jeelnadaa",
                    platform = "HirePro", messageId = "m1", links = listOf(LinkDto("https://assess.hirepro.in/t/1", "Start test"))),
                TimelineEventDto("e4", "interview", "user", ahead(72), title = "Technical interview, round 1", note = "Room 204, bring two CV copies", remind = true, manual = true),
            ))
            "todos" -> listOf(
                TodoDto("t1", "Acme Corp: finish the online test", dueAt = ahead(9), source = "ai", messageId = "m1", company = "Acme Corp"),
                TodoDto("t2", "Register for the Globex drive", notes = "Needs the latest marksheet", dueAt = ahead(60), company = "Globex"),
                TodoDto("t3", "Send updated CV to the placement cell"),
            )
            "toString" -> "FakeApi"
            "hashCode" -> 0
            "equals" -> false
            else -> throw java.io.IOException("not available in screenshots: ${method.name}")
        }
    }

    fun install() { Api.testOverride = api as SiftApi }
    fun remove() { Api.testOverride = null }
}
