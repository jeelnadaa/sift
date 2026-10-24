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
    @GET("api/v1/me") suspend fun me(): UserDto

    @GET("api/v1/messages") suspend fun messages(
        @Query("priority") priority: String? = null,
        @Query("account_id") accountId: String? = null,
        @Query("view") view: String = "feed",
        @Query("before") before: String? = null,
    ): MessagePage
    @GET("api/v1/messages/{id}") suspend fun message(@Path("id") id: String): MessageDto
    @GET("api/v1/messages/{id}/body") suspend fun body(@Path("id") id: String): BodyDto

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

    @GET("api/v1/settings") suspend fun settings(): SettingsDto
    @PATCH("api/v1/settings") suspend fun patchSettings(@Body changes: JsonObject): SettingsDto

    @GET("api/v1/ai") suspend fun ai(): AiStatus
    @PUT("api/v1/ai/key") suspend fun saveKey(@Body body: KeyIn): AiStatus
    @POST("api/v1/ai/test") suspend fun testKey(): AiStatus
    @DELETE("api/v1/ai/key") suspend fun removeKey()

    @GET("api/v1/opportunities") suspend fun opportunities(@Query("status") status: String = "active"): List<OpportunityDto>
    @GET("api/v1/opportunities/{id}") suspend fun opportunity(@Path("id") id: String): OpportunityDetail
    @POST("api/v1/opportunities") suspend fun createOpportunity(@Body body: OpportunityIn): OpportunityDto
    @PATCH("api/v1/opportunities/{id}") suspend fun updateOpportunity(@Path("id") id: String, @Body body: OpportunityPatch): OpportunityDto
    @DELETE("api/v1/opportunities/{id}") suspend fun deleteOpportunity(@Path("id") id: String)
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
    @GET("api/v1/groups/{id}") suspend fun group(@Path("id") id: String): GroupDto
    @POST("api/v1/groups/{id}/split") suspend fun splitGroup(@Path("id") id: String, @Body body: SplitIn): GroupDto
    @POST("api/v1/groups/{id}/merge") suspend fun mergeGroup(@Path("id") id: String, @Body body: TargetIn): GroupDto
    @PATCH("api/v1/groups/{id}") suspend fun editGroup(@Path("id") id: String, @Body body: GroupPatch): GroupDto
    @POST("api/v1/groups/{id}/remove") suspend fun removeFromGroup(@Path("id") id: String, @Body body: MessageIdIn)
    @POST("api/v1/groups/{id}/file") suspend fun fileGroup(@Path("id") id: String, @Body body: FolderIdIn): FiledResult
    @POST("api/v1/groups/{id}/rule") suspend fun ruleFromGroup(@Path("id") id: String, @Body body: GroupRuleIn): DraftResponse
    @PUT("api/v1/grouping/preferences") suspend fun setGroupPreference(@Body body: PreferenceIn): List<PreferenceDto>

    @POST("api/v1/devices") suspend fun registerDevice(@Body body: DeviceIn)
    @POST("api/v1/notifications/{id}/ack") suspend fun ack(@Path("id") id: String)
}

object Api {
    val json = Json { ignoreUnknownKeys = true; explicitNulls = false; encodeDefaults = true }
    private var cached: Pair<String, SiftApi>? = null

    /** Built for the server and token in the session; rebuilt when either changes. */
    fun get(context: Context): SiftApi {
        val server = Session.server(context).trimEnd('/') + "/"
        val token = Session.token(context)
        val key = "$server|$token"
        cached?.let { if (it.first == key) return it.second }
        val client = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                val req = chain.request().newBuilder()
                if (token != null) req.header("Authorization", "Bearer $token")
                chain.proceed(req.build())
            }
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

/** A short message for the user, without stack traces. */
fun Throwable.userMessage(): String = when (this) {
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
