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
    private val tonight = OffsetDateTime.now().withHour(23).withMinute(59).withSecond(0).withNano(0).toString()

    // fictional sample data (also used for the launch video): no real people, brands or accounts
    val mails = listOf(
        MessageDto("m1", "a2", account = "College", accountColor = "#6ea8ff", sender = "noreply@assesshub.example", senderName = "AssessHub",
            subject = "Acme Corp online assessment: link inside", snippet = "Your test link is live", receivedAt = ago(0), priority = "urgent",
            category = "assessment_link", status = "processed", unread = true, summary = "Acme Corp online test, closes tonight 11:59 PM",
            company = "Acme Corp", platform = "AssessHub", deadline = tonight, links = listOf(LinkDto("https://assess.example/t/1", "Start test")),
            actionNeeded = true, opportunityId = "o1", decidedBy = "llm"),
        MessageDto("m2", "a1", account = "Personal", accountColor = "#e8c547", sender = "alerts@northbank.example", senderName = "Northbank",
            subject = "Card blocked due to suspicious activity", receivedAt = ago(1), priority = "urgent", category = "action_needed",
            status = "processed", unread = true, summary = "Card blocked after a ₹18,500 attempt. Call the bank if it wasn't you"),
        MessageDto("m3", "a2", account = "College", accountColor = "#6ea8ff", sender = "placement@college.example", senderName = "Placement Cell",
            subject = "Globex campus drive: register by Friday", receivedAt = ago(2), priority = "normal", category = "placement_announcement",
            status = "processed", unread = true, summary = "Globex campus drive, register by Friday 6 PM", company = "Globex", opportunityId = "o2"),
        MessageDto("m4", "a1", account = "Personal", accountColor = "#e8c547", sender = "riya@globex.example", senderName = "Riya at Globex",
            subject = "Backend role at Globex: quick chat?", receivedAt = ago(3), priority = "normal", category = "recruiter",
            status = "processed", unread = true, summary = "Riya wants a 15-minute call about the backend role", company = "Globex"),
        MessageDto("m5", "a2", account = "College", accountColor = "#6ea8ff", sender = "news@college.example", senderName = "Campus Weekly",
            subject = "This week on campus", receivedAt = ago(6), priority = "digest", category = "fyi", status = "processed",
            summary = "Fest dates, library hours, hostel notice"),
    )

    private val api: Any = Proxy.newProxyInstance(SiftApi::class.java.classLoader, arrayOf(SiftApi::class.java)) { _, method, args ->
        when (method.name) {
            "accounts" -> listOf(AccountDto("a1", "you@personal.sift.test", "active", label = "Personal", color = "#e8c547", canModify = true, lastCheckOkAt = ago(0)),
                AccountDto("a2", "you@college.sift.test", "active", label = "College", color = "#6ea8ff", canModify = true, lastCheckOkAt = ago(0)))
            "messages" -> MessagePage(mails)
            "groupedFeed" -> GroupedPage(mails.map { m ->
                JsonObject(Api.json.encodeToJsonElement(MessageDto.serializer(), m).jsonObject + ("type" to JsonPrimitive("mail")))
            })
            "grouping" -> GroupingStatus("yes")
            "ai" -> AiStatus(true, "valid", "gemini", "gemini-2.5-flash", "a91f", 1240, 50000)
            "message" -> mails.first { it.id == args?.get(0) }
            "thread" -> ThreadDto("Acme Corp online assessment: link inside", "College", "a2", messages = listOf(
                ThreadMessageDto("g1", "m1", AddrDto("AssessHub", "noreply@assesshub.example"), listOf(AddrDto("You", "you@college.sift.test")),
                    subject = "Acme Corp online assessment", date = ago(0), snippet = "Your test link is live",
                    text = "Hi,\n\nYour Acme Corp online assessment is ready. It closes tonight at 11:59 PM.\n\nDuration: 60 minutes\n\nAll the best,\nAssessHub"),
            ))
            "opportunities" -> listOf(OpportunityDto("o1", "Acme Corp", deadline = ahead(9), events = 3, lastKind = "assessment"),
                OpportunityDto("o2", "Globex", events = 1, lastKind = "announcement"))
            "opportunity" -> OpportunityDetail("o1", "Acme Corp", aliases = listOf("ACME"), deadline = ahead(9), timeline = listOf(
                TimelineEventDto("e1", "announcement", "name", ago(72), summary = "Acme Corp campus drive announced", subject = "Campus drive", senderName = "Placement Cell", account = "College"),
                TimelineEventDto("e2", "registration", "user", ago(48), title = "Registered on the portal", note = "Roll number login", manual = true),
                TimelineEventDto("e3", "assessment", "ai", ago(1), deadline = tonight, summary = "Online test, closes tonight", senderName = "AssessHub", account = "College",
                    platform = "AssessHub", messageId = "m1", links = listOf(LinkDto("https://assess.example/t/1", "Start test"))),
                TimelineEventDto("e4", "interview", "user", ahead(72), title = "Technical interview, round 2", note = "Room 204, bring two CV copies", remind = true, manual = true),
            ))
            "todos" -> listOf(
                TodoDto("t1", "Acme Corp: finish the online test", dueAt = ahead(9), source = "ai", messageId = "m1", company = "Acme Corp"),
                TodoDto("t2", "Register for the Globex drive", notes = "Needs the latest marksheet", dueAt = ahead(60), company = "Globex"),
                TodoDto("t3", "Send updated CV to the placement cell"),
            )
            "askRuns" -> listOf(
                com.solarquack.sift.data.AskRunDto("r1", "What's due this week?", "Here's what's due in the next 7 days.", "done",
                    steps = listOf(com.solarquack.sift.data.AskStepDto("list_todos", "read", "Show week to-dos")),
                    results = listOf(com.solarquack.sift.data.AskResultDto(true, "2 to-dos due this week", todos = listOf(
                        TodoDto("t1", "Acme Corp: finish the online test", dueAt = tonight), TodoDto("t2", "Register for the Globex drive", dueAt = ahead(60))))),
                    tokens = 1310),
                com.solarquack.sift.data.AskRunDto("r2", "Make timelines from Placements → Globex and archive Northbank alerts older than a month",
                    "I'll build Globex's timeline from that folder and archive the old bank alerts.", "planned",
                    steps = listOf(
                        com.solarquack.sift.data.AskStepDto("create_group", "write", "New group Internships: new mail that the AI reads as \"internship offers\" joins it, and matching mail already here",
                            targets = listOf("New group: Internships"), tokens = 2100),
                        com.solarquack.sift.data.AskStepDto("draft_reply", "gmail", "AI writes a reply to this mail as a Gmail draft (you send it yourself)",
                            targets = listOf("Riya at Globex: Backend role at Globex: quick chat?"), tokens = 2500),
                        com.solarquack.sift.data.AskStepDto("mail_action", "gmail", "In Gmail: archive 14 conversations matching from:northbank older_than:30d",
                            targets = listOf("Northbank: ₹240.00 debited via UPI", "Northbank: ₹1,180.00 debited via UPI", "+ 12 more"))),
                    needsConfirm = true, changesGmail = true, tokens = 1652, estimate = 4600),
            )
            "groups" -> listOf(
                com.solarquack.sift.data.GroupDto("g0", "Internships", "custom", count = 3, unread = 1, latestSender = "Globex Talent", latestSubject = "Summer internship 2027: apply by Nov 10",
                    receivedAt = ago(5), custom = true, instruction = "internship offers"),
                com.solarquack.sift.data.GroupDto("g1", "Northbank alerts", "template", count = 14, unread = 2, latestSender = "Northbank", latestSubject = "₹240.00 debited via UPI", receivedAt = ago(1)),
                com.solarquack.sift.data.GroupDto("g2", "Globex", "opportunity", count = 4, unread = 1, urgent = 0, latestSender = "Riya at Globex", latestSubject = "Backend role at Globex: quick chat?", receivedAt = ago(3)),
                com.solarquack.sift.data.GroupDto("g3", "Campus Weekly", "list", muted = true, count = 6, latestSender = "Campus Weekly", latestSubject = "This week on campus", receivedAt = ago(30)),
            )
            "usage" -> com.solarquack.sift.data.UsageDto(tokensToday = 8420, dailyTokenCap = 50000,
                automatic = listOf(com.solarquack.sift.data.UsagePurpose("extract", "Reading each new mail", 7, 6300)),
                siftAi = com.solarquack.sift.data.SiftAiUsage(3054, 2, listOf(
                    com.solarquack.sift.data.SiftAiRun("r2", "Make a group Internships for internship offers and add old ones too", "done", 2120),
                    com.solarquack.sift.data.SiftAiRun("r1", "What's due this week?", "done", 934))))
            "settings" -> com.solarquack.sift.data.SettingsDto(
                senderName = "Demo User",
                signature = "Demo Signature",
                quietHoursEnabled = true,
                quietHoursStart = "22:00",
                quietHoursEnd = "07:00",
                mutedCategories = listOf("fyi"),
            )
            "patchSettings" -> com.solarquack.sift.data.SettingsDto()
            "pinMessage" -> com.solarquack.sift.data.PinResult("m1", true)
            "notes" -> listOf(com.solarquack.sift.data.MailNoteDto("n1", "m1", "Review by Friday", ago(1), ago(1)))
            "addNote" -> com.solarquack.sift.data.MailNoteDto("n2", "m1", "New note", ago(0), ago(0))
            "updateNote" -> com.solarquack.sift.data.MailNoteDto("n1", "m1", "Updated note", ago(1), ago(0))
            "deleteNote" -> Unit
            "attachments" -> com.solarquack.sift.data.AttachmentListResultDto(
                items = listOf(
                    com.solarquack.sift.data.AttachmentItemDto(
                        id = "att1",
                        messageId = "m1",
                        accountId = "a1",
                        filename = "assessment_guide.pdf",
                        mime = "application/pdf",
                        size = 524288,
                        sender = "noreply@assesshub.example",
                        senderName = "AssessHub",
                        subject = "Acme Corp online assessment",
                        receivedAt = ago(0),
                        downloadUrl = "https://demo.sift.local/api/v1/files/tok1",
                    )
                ),
                total = 1,
            )
            "attachmentStats" -> com.solarquack.sift.data.AttachmentStatsDto(
                totalCount = 1,
                totalSize = 524288,
                byType = mapOf("pdf" to com.solarquack.sift.data.AttachmentTypeStatDto(count = 1, size = 524288)),
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
