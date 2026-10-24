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
    val enabled: Boolean,
    val conditions: JsonElement,
    val action: JsonObject,
    val exceptions: JsonElement? = null,
    @SerialName("account_scope") val accountScope: List<String>? = null,
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
