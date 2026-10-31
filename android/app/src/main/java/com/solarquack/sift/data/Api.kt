package com.solarquack.sift.data

import android.content.Context
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query
import java.util.concurrent.TimeUnit

interface SiftApi {
    @POST("api/v1/auth/login") suspend fun login(@Body body: LoginRequest): LoginResponse
    @POST("api/v1/auth/register") suspend fun register(@Body body: LoginRequest): LoginResponse
    @GET("api/v1/auth/options") suspend fun authOptions(): AuthOptions
    @POST("api/v1/folders/{id}/ai-tasks") suspend fun startAiTask(@Path("id") id: String, @Body body: AiTaskIn): AiTaskDto
    @POST("api/v1/folders/{id}/ai-tasks") suspend fun fillFolder(@Path("id") id: String, @Body body: AiTaskIn = AiTaskIn("fill")): FillResult
    @GET("api/v1/ai-tasks") suspend fun aiTasks(): AiTaskList
    @GET("api/v1/me") suspend fun me(): UserDto
    @POST("api/v1/assistant") suspend fun ask(@Body body: AskIn): AskRunDto
    @POST("api/v1/assistant/estimate") suspend fun askEstimate(@Body body: AskSelectionIn = AskSelectionIn()): AskEstimate
    @POST("api/v1/assistant/{id}/run") suspend fun runPlan(@Path("id") id: String): AskRunDto
    @POST("api/v1/assistant/{id}/cancel") suspend fun cancelPlan(@Path("id") id: String): AskRunDto
    @GET("api/v1/assistant/runs") suspend fun askRuns(): List<AskRunDto>

    @GET("api/v1/messages") suspend fun messages(
        @Query("priority") priority: String? = null,
        @Query("account_id") accountId: String? = null,
        @Query("view") view: String = "feed",
        @Query("before") before: String? = null,
        @Query("limit") limit: Int? = null,
    ): MessagePage
    @POST("api/v1/messages/read-state") suspend fun readState(@Body body: ReadStateIn): ReadStateOut
    @GET("api/v1/messages/{id}") suspend fun message(@Path("id") id: String): MessageDto
    @GET("api/v1/messages/{id}/body") suspend fun body(@Path("id") id: String): BodyDto
    @GET("api/v1/messages/{id}/thread") suspend fun thread(@Path("id") id: String, @Query("images") images: Boolean? = null, @Query("bundle") bundle: Boolean? = true): ThreadDto
    @POST("api/v1/messages/{id}/pin") suspend fun pinMessage(@Path("id") id: String, @Query("pinned") pinned: Boolean): PinResult
    @GET("api/v1/messages/{id}/notes") suspend fun notes(@Path("id") messageId: String): List<MailNoteDto>
    @POST("api/v1/messages/{id}/notes") suspend fun addNote(@Path("id") messageId: String, @Body body: NoteIn): MailNoteDto
    @PATCH("api/v1/messages/{id}/notes/{note_id}") suspend fun updateNote(@Path("id") messageId: String, @Path("note_id") noteId: String, @Body body: NoteIn): MailNoteDto
    @DELETE("api/v1/messages/{id}/notes/{note_id}") suspend fun deleteNote(@Path("id") messageId: String, @Path("note_id") noteId: String)

    @GET("api/v1/attachments") suspend fun attachments(
        @Query("q") q: String? = null,
        @Query("type") type: String? = null,
        @Query("min_size") minSize: Long? = null,
        @Query("max_size") maxSize: Long? = null,
        @Query("account_id") accountId: String? = null,
        @Query("before") before: String? = null,
        @Query("limit") limit: Int? = null,
    ): AttachmentListResultDto

    @GET("api/v1/attachments/stats") suspend fun attachmentStats(): AttachmentStatsDto

    @GET("api/v1/senders") suspend fun senders(
        @Query("q") q: String? = null,
        @Query("domain") domain: String? = null,
        @Query("min_count") minCount: Int? = null,
        @Query("sort_by") sortBy: String? = null,
        @Query("limit") limit: Int? = null,
        @Query("offset") offset: Int? = null,
    ): SenderListResultDto

    @GET("api/v1/senders/{sender_email}") suspend fun senderDetail(@Path("sender_email") senderEmail: String): SenderDetailResultDto
    @POST("api/v1/senders/{sender_email}/vip") suspend fun setSenderVip(@Path("sender_email") senderEmail: String): Map<String, Boolean>
    @DELETE("api/v1/senders/{sender_email}/vip") suspend fun unsetSenderVip(@Path("sender_email") senderEmail: String): Map<String, Boolean>
    @POST("api/v1/threads/{thread_id}/mute") suspend fun muteThread(@Path("thread_id") threadId: String): Map<String, Boolean>
    @DELETE("api/v1/threads/{thread_id}/mute") suspend fun unmuteThread(@Path("thread_id") threadId: String): Map<String, Boolean>
    @GET("api/v1/threads/{thread_id}/muted") suspend fun checkThreadMuted(@Path("thread_id") threadId: String): Map<String, Boolean>
    @POST("api/v1/messages/{id}/unsubscribe") suspend fun unsubscribe(@Path("id") id: String): UnsubscribeResultDto

    @GET("api/v1/templates") suspend fun templates(): TemplateListResultDto
    @POST("api/v1/templates") suspend fun createTemplate(@Body body: TemplateInDto): ReplyTemplateDto
    @PATCH("api/v1/templates/{id}") suspend fun updateTemplate(@Path("id") id: String, @Body body: TemplatePatchDto): ReplyTemplateDto
    @DELETE("api/v1/templates/{id}") suspend fun deleteTemplate(@Path("id") id: String): Map<String, Boolean>

    @GET("api/v1/accounts") suspend fun accounts(): List<AccountDto>
    @GET("api/v1/accounts/connect-url") suspend fun connectUrl(): ConnectUrl
    @DELETE("api/v1/accounts/{id}") suspend fun removeAccount(@Path("id") id: String)

    @GET("api/v1/rules") suspend fun rules(): List<RuleDto>
    @PUT("api/v1/rules/{id}") suspend fun updateRule(@Path("id") id: String, @Body body: RuleIn): RuleDto
    @POST("api/v1/rules") suspend fun createRule(@Body body: RuleIn): RuleDto
    @DELETE("api/v1/rules/{id}") suspend fun deleteRule(@Path("id") id: String)
    @POST("api/v1/rules/reorder") suspend fun reorderRules(@Body body: OrderIn): List<RuleDto>
    @POST("api/v1/rules/preview") suspend fun previewRule(@Body body: PreviewIn): PreviewResult
    @POST("api/v1/rules/from-text") suspend fun ruleFromText(@Body body: TextIn): DraftResponse
    @GET("api/v1/rules/suggestions") suspend fun suggestions(): List<SuggestionDto>
    @POST("api/v1/rules/suggestions/{id}/accept") suspend fun acceptSuggestion(@Path("id") id: String, @Body body: ActionIn): RuleDto
    @POST("api/v1/rules/suggestions/{id}/dismiss") suspend fun dismissSuggestion(@Path("id") id: String)
    @POST("api/v1/messages/{id}/like-this") suspend fun likeThis(@Path("id") id: String, @Body body: LikeThisIn): DraftResponse
    @POST("api/v1/messages/{id}/unsilence") suspend fun unsilence(@Path("id") id: String): UnsilenceResult

    @GET("api/v1/accounts/{id}/scan") suspend fun latestScan(@Path("id") accountId: String): ScanDto?
    @POST("api/v1/accounts/{id}/scan") suspend fun startScan(@Path("id") accountId: String): ScanDto
    @POST("api/v1/scans/{id}/apply") suspend fun applyScan(@Path("id") scanId: String, @Body body: ApplyIn): ApplyResult

    @GET("api/v1/categories") suspend fun categories(): List<CategoryDto>
    @POST("api/v1/categories") suspend fun createCategory(@Body body: CategoryIn): CategoryDto
    @PUT("api/v1/categories/{id}") suspend fun updateCategory(@Path("id") id: String, @Body body: CategoryIn): CategoryDto
    @DELETE("api/v1/categories/{id}") suspend fun deleteCategory(@Path("id") id: String)
    @GET("api/v1/usage") suspend fun usage(@Query("days") days: Int = 30): UsageDto

    @GET("api/v1/settings") suspend fun settings(@Query("account_id") accountId: String? = null): SettingsDto
    @PATCH("api/v1/settings") suspend fun patchSettings(@Body changes: JsonObject, @Query("account_id") accountId: String? = null): SettingsDto

    // ---- writing mail (Phase 4) ----
    @GET("api/v1/compose/context") suspend fun replyContext(
        @Query("mode") mode: String, @Query("message_id") messageId: String? = null,
        @Query("account_id") accountId: String? = null, @Query("gmail_id") gmailId: String? = null,
    ): ReplyContextDto
    @POST("api/v1/compose/drafts") suspend fun createDraft(@Body body: DraftCreateIn): DraftDto
    @GET("api/v1/compose/drafts") suspend fun drafts(): DraftList
    @GET("api/v1/compose/drafts/{account}/{draft}") suspend fun draft(@Path("account") accountId: String, @Path("draft") draftId: String): DraftDto
    @PUT("api/v1/compose/drafts/{account}/{draft}") suspend fun saveDraft(@Path("account") accountId: String, @Path("draft") draftId: String, @Body body: DraftFieldsIn): DraftDto
    @DELETE("api/v1/compose/drafts/{account}/{draft}") suspend fun discardDraft(@Path("account") accountId: String, @Path("draft") draftId: String): OkResponse
    @POST("api/v1/compose/drafts/{account}/{draft}/attachments") suspend fun addAttachment(
        @Path("account") accountId: String, @Path("draft") draftId: String, @Query("filename") filename: String, @Body file: okhttp3.RequestBody,
    ): DraftDto
    @DELETE("api/v1/compose/drafts/{account}/{draft}/attachments/{index}") suspend fun removeAttachment(
        @Path("account") accountId: String, @Path("draft") draftId: String, @Path("index") index: Int,
    ): DraftDto
    @POST("api/v1/compose/drafts/{account}/{draft}/send") suspend fun send(@Path("account") accountId: String, @Path("draft") draftId: String, @Body body: SendIn): OutboxDto
    @GET("api/v1/outbox") suspend fun outbox(): OutboxList
    @POST("api/v1/outbox/{id}/cancel") suspend fun cancelSend(@Path("id") id: String): OutboxDto
    @POST("api/v1/outbox/{id}/send-now") suspend fun sendNow(@Path("id") id: String): OutboxDto
    @PATCH("api/v1/outbox/{id}") suspend fun reschedule(@Path("id") id: String, @Body body: SendAtIn): OutboxDto
    @GET("api/v1/follow-ups") suspend fun followUps(): FollowUpList
    @POST("api/v1/follow-ups/{id}/cancel") suspend fun cancelFollowUp(@Path("id") id: String): FollowUpDto
    @POST("api/v1/compose/ai-draft") suspend fun aiDraft(@Body body: AiDraftIn): AiDraftOut

    @GET("api/v1/ai") suspend fun ai(): AiStatus
    @PUT("api/v1/ai/key") suspend fun saveKey(@Body body: KeyIn): AiStatus
    @POST("api/v1/ai/test") suspend fun testKey(): AiStatus
    @DELETE("api/v1/ai/key") suspend fun removeKey()

    @GET("api/v1/opportunities") suspend fun opportunities(@Query("status") status: String = "active"): List<OpportunityDto>
    @GET("api/v1/opportunities/{id}") suspend fun opportunity(@Path("id") id: String): OpportunityDetail
    @POST("api/v1/opportunities") suspend fun createOpportunity(@Body body: OpportunityIn): OpportunityDto
    @PATCH("api/v1/opportunities/{id}") suspend fun updateOpportunity(@Path("id") id: String, @Body body: OpportunityPatch): OpportunityDto
    @DELETE("api/v1/opportunities/{id}") suspend fun deleteOpportunity(@Path("id") id: String)
    @POST("api/v1/opportunities/{id}/sections") suspend fun addSection(@Path("id") id: String, @Body body: SectionIn): OpportunityDetail
    @PATCH("api/v1/opportunities/{id}/events/{event}") suspend fun editEvent(@Path("id") id: String, @Path("event") eventId: String, @Body body: SectionPatch): OpportunityDetail
    @DELETE("api/v1/opportunities/{id}/events/{event}") suspend fun removeEvent(@Path("id") id: String, @Path("event") eventId: String): OpportunityDetail
    @POST("api/v1/messages/{id}/opportunity") suspend fun answerCompany(@Path("id") messageId: String, @Body body: CompanyAnswer)
    @DELETE("api/v1/messages/{id}/opportunity") suspend fun detachOpportunity(@Path("id") messageId: String)

    @GET("api/v1/todos") suspend fun todos(@Query("state") state: String = "open"): List<TodoDto>
    @POST("api/v1/todos") suspend fun createTodo(@Body body: TodoIn): TodoDto
    @PATCH("api/v1/todos/{id}") suspend fun updateTodo(@Path("id") id: String, @Body body: TodoPatch): TodoDto
    @DELETE("api/v1/todos/{id}") suspend fun deleteTodo(@Path("id") id: String)

    @GET("api/v1/messages") suspend fun groupedFeed(
        @Query("priority") priority: String? = null,
        @Query("account_id") accountId: String? = null,
        @Query("before") before: String? = null,
        @Query("grouped") grouped: Boolean = true,
        @Query("limit") limit: Int? = null,
    ): GroupedPage

    @GET("api/v1/folders") suspend fun folders(): FolderTree
    @POST("api/v1/folders") suspend fun createFolder(@Body body: FolderIn): FolderDto
    @PATCH("api/v1/folders/{id}") suspend fun editFolder(@Path("id") id: String, @Body body: FolderPatch): FolderDto
    @POST("api/v1/folders/{id}/move") suspend fun moveFolder(@Path("id") id: String, @Body body: MoveIn): FolderTree
    @POST("api/v1/folders/{id}/merge") suspend fun mergeFolder(@Path("id") id: String, @Body body: TargetIn)
    @DELETE("api/v1/folders/{id}") suspend fun deleteFolder(@Path("id") id: String, @Query("subfolders") subfolders: String): DeleteFolderResult
    @GET("api/v1/folders/{id}/threads") suspend fun folderThreads(
        @Path("id") id: String,
        @Query("include_subfolders") includeSubfolders: Boolean = false,
        @Query("q") q: String? = null,
        @Query("before") before: String? = null,
    ): FolderView
    @POST("api/v1/folders/{id}/threads") suspend fun fileMail(@Path("id") id: String, @Body body: FileIn): FiledResult
    @POST("api/v1/folders/last-used/threads") suspend fun fileLastUsed(@Body body: FileIn): FiledResult
    @POST("api/v1/folders/{id}/threads/remove") suspend fun unfileMail(@Path("id") id: String, @Body body: FileIn): RemoveResult
    @GET("api/v1/folders/for-message/{id}") suspend fun foldersForMessage(@Path("id") messageId: String): List<FolderDto>
    @POST("api/v1/folders/{id}/rule-from-message") suspend fun fileLikeThisHere(@Path("id") id: String, @Body body: LikeThisHereIn): DraftResponse

    @GET("api/v1/grouping") suspend fun grouping(): GroupingStatus
    @POST("api/v1/grouping") suspend fun answerGrouping(@Body body: AnswerIn): GroupingStatus
    @GET("api/v1/groups") suspend fun groups(): List<GroupDto>
    @POST("api/v1/groups/collapse-all") suspend fun collapseAllGroups(@Body body: CollapseIn)
    @POST("api/v1/groups") suspend fun createGroup(@Body body: NewGroupIn): GroupDto
    @DELETE("api/v1/groups/{id}") suspend fun deleteGroup(@Path("id") id: String)
    @POST("api/v1/groups/{id}/fill") suspend fun fillGroup(@Path("id") id: String, @Body body: JsonObject = JsonObject(emptyMap())): FillResult
    @POST("api/v1/groups/{id}/add") suspend fun addToGroup(@Path("id") id: String, @Body body: GroupIdsIn): GroupDto
    @GET("api/v1/groups/{id}") suspend fun group(@Path("id") id: String): GroupDto
    @POST("api/v1/groups/{id}/split") suspend fun splitGroup(@Path("id") id: String, @Body body: SplitIn): GroupDto
    @POST("api/v1/groups/{id}/merge") suspend fun mergeGroup(@Path("id") id: String, @Body body: TargetIn): GroupDto
    @PATCH("api/v1/groups/{id}") suspend fun editGroup(@Path("id") id: String, @Body body: GroupPatch): GroupDto
    @POST("api/v1/groups/{id}/remove") suspend fun removeFromGroup(@Path("id") id: String, @Body body: MessageIdIn)
    @POST("api/v1/groups/{id}/file") suspend fun fileGroup(@Path("id") id: String, @Body body: FolderIdIn): FiledResult
    @POST("api/v1/groups/{id}/rule") suspend fun ruleFromGroup(@Path("id") id: String, @Body body: GroupRuleIn): DraftResponse
    @PUT("api/v1/grouping/preferences") suspend fun setGroupPreference(@Body body: PreferenceIn): List<PreferenceDto>

    @GET("api/v1/search") suspend fun search(@Query("q") q: String, @Query("cursor") cursor: String? = null, @Query("limit") limit: Int = 30, @Query("fuzzy") fuzzy: Boolean = false): SearchResult
    @GET("api/v1/search/semantic") suspend fun semantic(@Query("q") q: String, @Query("offset") offset: Int = 0, @Query("limit") limit: Int = 30): SemanticResult
    @GET("api/v1/search/semantic/status") suspend fun semanticStatus(): SemanticStatus
    @POST("api/v1/search/parse") suspend fun parseQuery(@Body body: QueryIn): ParseResult
    @POST("api/v1/search/from-text") suspend fun searchFromText(@Body body: TextIn): FromTextResult
    @GET("api/v1/saved-searches") suspend fun savedSearches(): List<SavedSearchDto>
    @POST("api/v1/saved-searches") suspend fun saveSearch(@Body body: SavedSearchIn): SavedSearchDto
    @GET("api/v1/accounts/{account}/threads/{thread}") suspend fun accountThread(@Path("account") accountId: String, @Path("thread") threadId: String, @Query("images") images: Boolean? = null, @Query("bundle") bundle: Boolean? = true): ThreadDto

    @POST("api/v1/mail/actions") suspend fun mailAction(@Body body: MailActionIn): MailActionResult
    @POST("api/v1/bulk") suspend fun bulk(@Body body: BulkIn): BulkOut
    @GET("api/v1/bulk/jobs/{id}") suspend fun bulkJob(@Path("id") id: String): BulkJobDto
    @POST("api/v1/snoozes") suspend fun snooze(@Body body: SnoozeIn): List<SnoozeDto>
    @GET("api/v1/accounts/{id}/labels") suspend fun labels(@Path("id") accountId: String): List<LabelDto>
    @GET("api/v1/accounts/{id}/write-access-url") suspend fun writeAccessUrl(@Path("id") accountId: String): AuthUrl

    @POST("api/v1/devices") suspend fun registerDevice(@Body body: DeviceIn)
    @POST("api/v1/notifications/{id}/ack") suspend fun ack(@Path("id") id: String)
}

object Api {
    val json = Json { ignoreUnknownKeys = true; explicitNulls = false; encodeDefaults = true }
    private var cached: Pair<String, SiftApi>? = null

    /** Screenshot tests put a fake here; the app never sets it. */
    @androidx.annotation.VisibleForTesting
    var testOverride: SiftApi? = null

    /** Built for the server and token in the session; rebuilt when either changes. */
    fun get(context: Context): SiftApi {
        testOverride?.let { return it }
        val server = Session.server(context).trimEnd('/') + "/"
        val token = Session.token(context)
        val key = "$server|$token"
        cached?.let { if (it.first == key) return it.second }
        val client = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(90, TimeUnit.SECONDS)  // attachments and sending go through Gmail
            .writeTimeout(120, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                val req = chain.request().newBuilder()
                if (token != null) req.header("Authorization", "Bearer $token")
                chain.proceed(req.build())
            }
            .addInterceptor(Offline.interceptor(context))  // saved copies while the server is off
            .build()
        val api = Retrofit.Builder()
            .baseUrl(server)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(SiftApi::class.java)
        cached = key to api
        return api
    }
}

/** A short message for the user, without stack traces. A cancelled coroutine (the screen was
 * left, or a newer save replaced this one) is not an error: it is re-thrown so the coroutine just
 * ends, and nothing is shown. Every `catch (t: Throwable) { … t.userMessage() }` relies on this. */
fun Throwable.userMessage(): String = when (this) {
    is kotlinx.coroutines.CancellationException -> throw this
    is HttpException -> when (code()) {
        401 -> "Signed out. Sign in again."
        404 -> "Not found."
        409 -> response()?.errorBody()?.string()?.let { Regex("\"detail\":\"([^\"]+)\"").find(it)?.groupValues?.get(1)?.replaceFirstChar { c -> c.uppercase() } } ?: "Conflict."
        422 -> response()?.errorBody()?.string()?.let { Regex("\"detail\":\"([^\"]+)\"").find(it)?.groupValues?.get(1)?.replaceFirstChar { c -> c.uppercase() } } ?: "Please check what you entered."
        503 -> "Server is not configured for this yet."
        else -> "Server error (${code()})."
    }
    is java.net.UnknownHostException, is java.net.ConnectException -> "Can't reach the Sift server. Check the address and that it is running."
    is java.net.SocketTimeoutException -> "The server took too long to answer."
    else -> message ?: "Something went wrong."
}

/** The accounts that still need write access, when the server answered 403 needs_write_access. */
fun Throwable.writeAccessNeeded(): List<WriteAccessAccount>? {
    if (this !is HttpException || code() != 403) return null
    val body = runCatching { response()?.errorBody()?.string() }.getOrNull() ?: return null
    val err = runCatching { Api.json.decodeFromString(WriteAccessError.serializer(), body) }.getOrNull() ?: return null
    return err.detail?.takeIf { it.code == "needs_write_access" }?.accounts
}
