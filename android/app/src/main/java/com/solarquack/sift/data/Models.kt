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
data class PreviewSample(val id: String, val sender: String? = null, val subject: String? = null, @SerialName("received_at") val receivedAt: String? = null, val priority: String? = null, val important: Boolean = false)

@Serializable
data class PreviewResult(
    val checked: Int = 0,
    val matches: Int = 0,
    @SerialName("important_matches") val importantMatches: Int = 0,
    val samples: List<PreviewSample> = emptyList(),
    @SerialName("kept_by_exceptions") val keptByExceptions: Int = 0,
    @SerialName("kept_samples") val keptSamples: List<PreviewSample> = emptyList(),
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
    val notes: List<String> = emptyList(),
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

// ---- folders (brief section 18) ----

@Serializable
data class FolderDto(
    val id: String,
    @SerialName("parent_id") val parentId: String? = null,
    val name: String,
    val color: String? = null,
    val icon: String? = null,
    val position: Int = 0,
    val pinned: Boolean = false,
    @SerialName("notify_mode") val notifyMode: String = "default",
    val smart: Boolean = false,
    val threads: Int = 0,
    val unread: Int = 0,
    @SerialName("unread_total") val unreadTotal: Int = 0,
    val children: List<FolderDto> = emptyList(),
)

@Serializable
data class FolderTree(val folders: List<FolderDto> = emptyList(), @SerialName("max_depth") val maxDepth: Int = 10, @SerialName("last_used_id") val lastUsedId: String? = null)

@Serializable
data class FolderIn(val name: String, @SerialName("parent_id") val parentId: String? = null, val color: String? = null)

@Serializable
data class FolderPatch(
    val name: String? = null,
    val color: String? = null,
    val pinned: Boolean? = null,
    @SerialName("notify_mode") val notifyMode: String? = null,
    @SerialName("clear_color") val clearColor: Boolean = false,
)

@Serializable
data class MoveIn(@SerialName("parent_id") val parentId: String? = null, val position: Int? = null)

@Serializable
data class TargetIn(@SerialName("target_id") val targetId: String)

@Serializable
data class PathPart(val id: String, val name: String)

@Serializable
data class ThreadRow(
    val id: String,
    @SerialName("account_id") val accountId: String,
    val account: String? = null,
    @SerialName("account_color") val accountColor: String? = null,
    val sender: String? = null,
    @SerialName("sender_name") val senderName: String? = null,
    val subject: String? = null,
    val summary: String? = null,
    @SerialName("received_at") val receivedAt: String? = null,
    val priority: String? = null,
    val unread: Boolean = false,
    @SerialName("thread_count") val threadCount: Int = 1,
    @SerialName("thread_unread") val threadUnread: Int = 0,
) {
    fun asMessage() = MessageDto(id = id, accountId = accountId, account = account, accountColor = accountColor, sender = sender,
        senderName = senderName, subject = subject, summary = summary, receivedAt = receivedAt, priority = priority, unread = unread)
}

@Serializable
data class FolderView(val folder: FolderDto, val path: List<PathPart> = emptyList(), val items: List<ThreadRow> = emptyList(), @SerialName("next_before") val nextBefore: String? = null)

@Serializable
data class FileIn(@SerialName("message_ids") val messageIds: List<String>)

@Serializable
data class FiledResult(val filed: Int = 0, @SerialName("folder_id") val folderId: String? = null)

@Serializable
data class RemoveResult(val removed: Int = 0)

@Serializable
data class DeleteFolderResult(@SerialName("deleted_folders") val deletedFolders: Int = 0, @SerialName("rules_updated") val rulesUpdated: Int = 0)

@Serializable
data class LikeThisHereIn(@SerialName("message_id") val messageId: String, val save: Boolean = false)

// ---- grouping (brief section 21) ----

@Serializable
data class GroupingStatus(@SerialName("grouping_enabled") val groupingEnabled: String = "not_asked", val prompts: Int = 0, @SerialName("should_ask") val shouldAsk: Boolean = false)

@Serializable
data class AnswerIn(val answer: String)

@Serializable
data class GroupDto(
    val id: String,
    val title: String,
    val kind: String = "",
    val muted: Boolean = false,
    val collapsed: Boolean = true,
    val count: Int = 0,
    val unread: Int = 0,
    val urgent: Int = 0,
    @SerialName("latest_sender") val latestSender: String? = null,
    @SerialName("latest_subject") val latestSubject: String? = null,
    @SerialName("received_at") val receivedAt: String? = null,
    val items: List<MessageDto> = emptyList(),
)

/** A grouped feed page mixes mail rows and group rows; "type" tells them apart. */
@Serializable
data class GroupedPage(val items: List<JsonObject> = emptyList(), @SerialName("next_before") val nextBefore: String? = null)

sealed interface FeedItem { val key: String }
data class MailItem(val m: MessageDto) : FeedItem { override val key get() = "m:" + m.id }
data class GroupItem(val g: GroupDto) : FeedItem { override val key get() = "g:" + g.id }

@Serializable
data class GroupPatch(val title: String? = null, val muted: Boolean? = null, val collapsed: Boolean? = null)

@Serializable
data class SplitIn(@SerialName("message_ids") val messageIds: List<String>, val title: String? = null)

@Serializable
data class MessageIdIn(@SerialName("message_id") val messageId: String)

@Serializable
data class FolderIdIn(@SerialName("folder_id") val folderId: String)

@Serializable
data class GroupRuleIn(val action: String, @SerialName("folder_id") val folderId: String? = null, val save: Boolean = false)

@Serializable
data class PreferenceIn(@SerialName("sender_or_domain") val senderOrDomain: String, val mode: String? = null)

@Serializable
data class PreferenceDto(@SerialName("sender_or_domain") val senderOrDomain: String, val mode: String)

// ---- reader (Phase 3a) ----

@Serializable
data class AddrDto(val name: String = "", val email: String = "")

@Serializable
data class ThreadAttachmentDto(val filename: String, val mime: String = "", val size: Long = 0, val url: String, @SerialName("view_url") val viewUrl: String? = null)

@Serializable
data class ThreadMessageDto(
    @SerialName("gmail_id") val gmailId: String,
    val id: String? = null,
    val from: AddrDto? = null,
    val to: List<AddrDto> = emptyList(),
    val cc: List<AddrDto> = emptyList(),
    val subject: String = "",
    val date: String? = null,
    val unread: Boolean = false,
    val snippet: String = "",
    val text: String = "",
    @SerialName("html_url") val htmlUrl: String? = null,
    @SerialName("images_blocked") val imagesBlocked: Int = 0,
    val attachments: List<ThreadAttachmentDto> = emptyList(),
)

@Serializable
data class ThreadDto(val subject: String = "", val account: String? = null, val images: Boolean = false, val messages: List<ThreadMessageDto> = emptyList())

// ---- search (Phase 3b) ----

@Serializable
data class SearchHit(
    val id: String? = null,
    @SerialName("account_id") val accountId: String,
    val account: String? = null,
    @SerialName("account_color") val accountColor: String? = null,
    @SerialName("thread_id") val threadId: String = "",
    val sender: String? = null,
    @SerialName("sender_name") val senderName: String? = null,
    val subject: String? = null,
    val snippet: String? = null,
    val summary: String? = null,
    @SerialName("received_at") val receivedAt: String? = null,
    val priority: String? = null,
    val category: String? = null,
    val company: String? = null,
    val unread: Boolean = false,
    val score: Double? = null,
) {
    fun asMessage() = MessageDto(id = id ?: "g:$accountId:$threadId", accountId = accountId, account = account, accountColor = accountColor,
        sender = sender, senderName = senderName, subject = subject, snippet = snippet, summary = summary, receivedAt = receivedAt,
        priority = priority, category = category, company = company, unread = unread)
}

@Serializable
data class QueryChip(val text: String, val kind: String, val label: String, val negated: Boolean = false)

@Serializable
data class SearchResult(
    val items: List<SearchHit> = emptyList(),
    @SerialName("next_cursor") val nextCursor: String? = null,
    val total: Int = 0,
    val estimated: Boolean = false,
    @SerialName("failed_accounts") val failedAccounts: List<String> = emptyList(),
    @SerialName("gmail_query") val gmailQuery: String = "",
    val chips: List<QueryChip> = emptyList(),
)

@Serializable
data class SemanticResult(val items: List<SearchHit> = emptyList(), val total: Int = 0, @SerialName("next_offset") val nextOffset: Int? = null)

@Serializable
data class SemanticStatus(@SerialName("ai_enabled") val aiEnabled: Boolean = false, val indexed: Int = 0, @SerialName("recent_total") val recentTotal: Int = 0)

@Serializable
data class ParseResult(val error: String? = null, val chips: List<QueryChip> = emptyList(), @SerialName("gmail_query") val gmailQuery: String = "")

@Serializable
data class QueryIn(val q: String)

@Serializable
data class SavedSearchDto(val id: String, val name: String, val query: String, val pinned: Boolean = false, val notify: Boolean = false, @SerialName("smart_folder_id") val smartFolderId: String? = null)

@Serializable
data class SavedSearchIn(val name: String, val query: String, val pinned: Boolean = false, val notify: Boolean = false, @SerialName("smart_folder") val smartFolder: Boolean = false)

@Serializable
data class FromTextResult(val query: String, val explanation: String = "")
