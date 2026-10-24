package com.solarquack.sift.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

@Serializable
data class LoginRequest(val email: String, val password: String)

@Serializable
data class UserDto(val id: String, val email: String)

@Serializable
data class LoginResponse(val token: String, val user: UserDto)

@Serializable
data class LinkDto(val url: String, val label: String = "Link")

@Serializable
data class MessageDto(
    val id: String,
    @SerialName("account_id") val accountId: String,
    val account: String? = null,
    @SerialName("account_color") val accountColor: String? = null,
    val sender: String? = null,
    @SerialName("sender_name") val senderName: String? = null,
    val subject: String? = null,
    val snippet: String? = null,
    @SerialName("received_at") val receivedAt: String? = null,
    val priority: String? = null,
    val category: String? = null,
    val status: String? = null,
    @SerialName("has_attachment") val hasAttachment: Boolean = false,
    val unread: Boolean = false,
    val summary: String? = null,
    val company: String? = null,
    val platform: String? = null,
    val deadline: String? = null,
    val links: List<LinkDto> = emptyList(),
    @SerialName("action_needed") val actionNeeded: Boolean = false,
    @SerialName("decided_by") val decidedBy: String? = null,
    @SerialName("notified_at") val notifiedAt: String? = null,
    @SerialName("delivered_at") val deliveredAt: String? = null,
    @SerialName("opportunity_id") val opportunityId: String? = null,
    @SerialName("todo_id") val todoId: String? = null,
    @SerialName("company_question") val companyQuestion: List<CompanyChoice>? = null,
)

@Serializable
data class MessagePage(val items: List<MessageDto>, @SerialName("next_before") val nextBefore: String? = null)

@Serializable
data class BodyDto(val text: String, val attachments: List<String> = emptyList())

@Serializable
data class AccountDto(
    val id: String,
    val email: String,
    val status: String,
    @SerialName("status_detail") val statusDetail: String? = null,
    val label: String? = null,
    val color: String? = null,
)

@Serializable
data class ConnectUrl(@SerialName("auth_url") val authUrl: String)

@Serializable
data class RuleDto(
    val id: String,
    val name: String,
    val position: Int,
    val enabled: Boolean,
    val conditions: JsonElement,
    val action: JsonObject,
    val exceptions: JsonElement? = null,
    @SerialName("account_scope") val accountScope: List<String>? = null,
    val origin: String? = null,
    @SerialName("hit_count") val hitCount: Int = 0,
    @SerialName("last_hit_at") val lastHitAt: String? = null,
)

@Serializable
data class RuleIn(
    val name: String,
    val enabled: Boolean = true,
    val conditions: JsonElement,
    val action: JsonObject,
    val exceptions: JsonElement? = null,
    @SerialName("account_scope") val accountScope: List<String>? = null,
    val origin: String = "editor",
)

@Serializable
data class AiStatus(
    @SerialName("ai_enabled") val aiEnabled: Boolean,
    val status: String,
    val provider: String? = null,
    val model: String? = null,
    @SerialName("key_last4") val keyLast4: String? = null,
    @SerialName("tokens_today") val tokensToday: Int = 0,
    @SerialName("daily_token_cap") val dailyTokenCap: Int = 0,
    @SerialName("suggested_model") val suggestedModel: String? = null,
)

@Serializable
data class KeyIn(val provider: String, val model: String, @SerialName("api_key") val apiKey: String)

@Serializable
data class SettingsDto(
    val timezone: String = "Asia/Kolkata",
    @SerialName("daily_token_cap") val dailyTokenCap: Int = 50000,
    @SerialName("resend_urgent") val resendUrgent: Boolean = true,
    @SerialName("resend_after_minutes") val resendAfterMinutes: Int = 5,
    @SerialName("resend_limit") val resendLimit: Int = 3,
)

@Serializable
data class DeviceIn(@SerialName("fcm_token") val fcmToken: String, val platform: String = "android", val label: String? = null)

@Serializable
data class CompanyChoice(val id: String, val name: String)

@Serializable
data class OpportunityDto(
    val id: String,
    val company: String,
    val aliases: List<String> = emptyList(),
    val domains: List<String> = emptyList(),
    val status: String = "active",
    val deadline: String? = null,
    val events: Int = 0,
    @SerialName("last_kind") val lastKind: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
)

@Serializable
data class TimelineEventDto(
    val id: String,
    val kind: String,
    @SerialName("matched_by") val matchedBy: String? = null,
    @SerialName("occurred_at") val occurredAt: String? = null,
    val deadline: String? = null,
    val links: List<LinkDto> = emptyList(),
    val platform: String? = null,
    val summary: String? = null,
    @SerialName("message_id") val messageId: String? = null,
    val subject: String? = null,
    @SerialName("sender_name") val senderName: String? = null,
    val account: String? = null,
)

@Serializable
data class OpportunityDetail(
    val id: String,
    val company: String,
    val aliases: List<String> = emptyList(),
    val domains: List<String> = emptyList(),
    val status: String = "active",
    val deadline: String? = null,
    val timeline: List<TimelineEventDto> = emptyList(),
)

@Serializable
data class OpportunityIn(val company: String, val aliases: List<String> = emptyList())

@Serializable
data class OpportunityPatch(
    val company: String? = null,
    val aliases: List<String>? = null,
    val status: String? = null,
)

@Serializable
data class CompanyAnswer(
    @SerialName("opportunity_id") val opportunityId: String? = null,
    @SerialName("new_company") val newCompany: String? = null,
)

@Serializable
data class TodoDto(
    val id: String,
    val title: String,
    val notes: String? = null,
    @SerialName("due_at") val dueAt: String? = null,
    val done: Boolean = false,
    val source: String = "manual",
    @SerialName("message_id") val messageId: String? = null,
    val subject: String? = null,
    @SerialName("sender_name") val senderName: String? = null,
    @SerialName("opportunity_id") val opportunityId: String? = null,
    val company: String? = null,
)

@Serializable
data class TodoIn(
    val title: String,
    @SerialName("due_at") val dueAt: String? = null,
    @SerialName("message_id") val messageId: String? = null,
    @SerialName("opportunity_id") val opportunityId: String? = null,
)

@Serializable
data class TodoPatch(
    val done: Boolean? = null,
    val title: String? = null,
    @SerialName("due_at") val dueAt: String? = null,
    @SerialName("clear_due") val clearDue: Boolean = false,
)

@Serializable
data class PreviewSample(val id: String, val sender: String? = null, val subject: String? = null, @SerialName("received_at") val receivedAt: String? = null, val priority: String? = null)

@Serializable
data class PreviewResult(
    val checked: Int = 0,
    val matches: Int = 0,
    val samples: List<PreviewSample> = emptyList(),
    @SerialName("body_not_previewed") val bodyNotPreviewed: Boolean = false,
)

@Serializable
data class PreviewIn(val conditions: JsonElement, val exceptions: JsonElement? = null, @SerialName("account_scope") val accountScope: List<String>? = null)

@Serializable
data class RuleDraft(
    val name: String,
    val conditions: JsonElement,
    val action: JsonObject,
    val exceptions: JsonElement? = null,
    @SerialName("account_scope") val accountScope: List<String>? = null,
)

@Serializable
data class DraftResponse(val draft: RuleDraft, val preview: PreviewResult, @SerialName("rule_id") val ruleId: String? = null)

@Serializable
data class TextIn(val text: String)

@Serializable
data class LikeThisIn(val action: String = "silent", val save: Boolean = true)

@Serializable
data class UnsilenceResult(@SerialName("rule_id") val ruleId: String? = null)

@Serializable
data class SuggestionDto(
    val id: String,
    val domain: String? = null,
    val template: String? = null,
    val count: Int = 0,
    @SerialName("sample_subject") val sampleSubject: String? = null,
    val sender: String? = null,
)

@Serializable
data class ActionIn(val action: String)

@Serializable
data class OrderIn(val ids: List<String>)

@Serializable
data class ScanSender(
    val key: String,
    val kind: String,
    val name: String? = null,
    val count: Int = 0,
    @SerialName("sample_subject") val sampleSubject: String? = null,
    val hints: List<String> = emptyList(),
    val suggested: String = "keep",
)

@Serializable
data class ScanDto(
    val id: String,
    @SerialName("account_id") val accountId: String,
    val status: String,
    val scanned: Int = 0,
    val senders: List<ScanSender> = emptyList(),
    val error: String? = null,
    @SerialName("applied_at") val appliedAt: String? = null,
)

@Serializable
data class ApplyIn(val assignments: Map<String, String>)

@Serializable
data class ApplyResult(val rules: List<RuleDto> = emptyList())

@Serializable
data class CategoryDto(val id: String? = null, val name: String, val definition: String? = null, val builtin: Boolean = false)

@Serializable
data class CategoryIn(val name: String, val definition: String)

@Serializable
data class UsageDay(val day: String, val calls: Int = 0, @SerialName("input_tokens") val inputTokens: Int = 0, @SerialName("output_tokens") val outputTokens: Int = 0)

@Serializable
data class UsageDto(val days: List<UsageDay> = emptyList(), @SerialName("tokens_today") val tokensToday: Int = 0, @SerialName("daily_token_cap") val dailyTokenCap: Int = 0)
