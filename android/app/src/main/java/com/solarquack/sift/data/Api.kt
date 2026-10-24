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

    @GET("api/v1/settings") suspend fun settings(): SettingsDto
    @PATCH("api/v1/settings") suspend fun patchSettings(@Body changes: JsonObject): SettingsDto

    @GET("api/v1/ai") suspend fun ai(): AiStatus
    @PUT("api/v1/ai/key") suspend fun saveKey(@Body body: KeyIn): AiStatus
    @POST("api/v1/ai/test") suspend fun testKey(): AiStatus
    @DELETE("api/v1/ai/key") suspend fun removeKey()

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
        409 -> "This account needs attention in Accounts."
        422 -> response()?.errorBody()?.string()?.let { Regex("\"detail\":\"([^\"]+)\"").find(it)?.groupValues?.get(1) } ?: "Invalid input."
        503 -> "Server is not configured for this yet."
        else -> "Server error (${code()})."
    }
    is java.net.UnknownHostException, is java.net.ConnectException -> "Can't reach the Sift server. Check the address and that it is running."
    is java.net.SocketTimeoutException -> "The server took too long to answer."
    else -> message ?: "Something went wrong."
}
