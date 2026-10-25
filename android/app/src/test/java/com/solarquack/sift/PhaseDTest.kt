package com.solarquack.sift

import com.solarquack.sift.data.Api
import com.solarquack.sift.data.ReplyTemplateDto
import com.solarquack.sift.data.TemplateInDto
import com.solarquack.sift.data.TemplateListResultDto
import com.solarquack.sift.data.TemplatePatchDto
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class PhaseDTest {

    @Before
    fun setUp() {
        FakeApi.install()
    }

    @After
    fun tearDown() {
        FakeApi.remove()
    }

    @Test
    fun testTemplateSerialization() {
        val template = ReplyTemplateDto(
            id = "tpl100",
            title = "Availability Confirmation",
            body = "I will be available for the technical interview this Wednesday at 3 PM.",
            shortcut = "/avail",
            createdAt = "2026-10-26T00:00:00Z",
            updatedAt = "2026-10-26T00:00:00Z",
        )

        val json = Api.json.encodeToString(ReplyTemplateDto.serializer(), template)
        assertTrue(json.contains("\"title\":\"Availability Confirmation\""))
        assertTrue(json.contains("\"shortcut\":\"/avail\""))
        assertTrue(json.contains("\"created_at\":\"2026-10-26T00:00:00Z\""))

        val decoded = Api.json.decodeFromString(ReplyTemplateDto.serializer(), json)
        assertEquals("tpl100", decoded.id)
        assertEquals("Availability Confirmation", decoded.title)
        assertEquals("/avail", decoded.shortcut)
        assertEquals("I will be available for the technical interview this Wednesday at 3 PM.", decoded.body)
    }

    @Test
    fun testTemplateInAndListSerialization() {
        val input = TemplateInDto(
            title = "Quick Thanks",
            body = "Thank you very much for your time and assistance!",
            shortcut = "/thanks",
        )
        val json = Api.json.encodeToString(TemplateInDto.serializer(), input)
        assertTrue(json.contains("\"title\":\"Quick Thanks\""))
        assertTrue(json.contains("\"shortcut\":\"/thanks\""))

        val list = TemplateListResultDto(
            templates = listOf(
                ReplyTemplateDto("t1", "T1", "Body 1", "/t1"),
                ReplyTemplateDto("t2", "T2", "Body 2", "/t2"),
            ),
            total = 2,
        )
        val listJson = Api.json.encodeToString(TemplateListResultDto.serializer(), list)
        assertTrue(listJson.contains("\"total\":2"))
        val decodedList = Api.json.decodeFromString(TemplateListResultDto.serializer(), listJson)
        assertEquals(2, decodedList.total)
        assertEquals(2, decodedList.templates.size)
    }

    @Test
    fun testFakeApiTemplateEndpoints() = runBlocking {
        val api = Api.testOverride
        assertNotNull(api)

        val list = api!!.templates()
        assertEquals(1, list.total)
        assertEquals("Interview Availability", list.templates[0].title)
        assertEquals("/avail", list.templates[0].shortcut)

        val created = api.createTemplate(TemplateInDto("New Title", "New Body", "/new"))
        assertEquals("New Title", created.title)
        assertEquals("New Body", created.body)

        val updated = api.updateTemplate("tpl1", TemplatePatchDto(title = "Updated Title"))
        assertEquals("Updated Template", updated.title)

        val deleted = api.deleteTemplate("tpl1")
        assertEquals(true, deleted["ok"])
    }

    @Test
    fun testAiStatusAndKeyInSerialization() {
        val status = com.solarquack.sift.data.AiStatus(
            aiEnabled = true,
            status = "valid",
            provider = "openai_compatible",
            model = "gpt-4o-mini",
            keyLast4 = "1234",
            baseUrl = "https://api.openai.com/v1",
            fallbackProvider = "ollama",
            fallbackModel = "llama3.2",
            fallbackBaseUrl = "http://localhost:11434/v1",
            fallbackKeyLast4 = "5678",
            tokensToday = 500,
            dailyTokenCap = 50000,
            suggestedModel = "gpt-4o-mini",
            providers = listOf("gemini", "ollama", "openai_compatible"),
        )

        val json = Api.json.encodeToString(com.solarquack.sift.data.AiStatus.serializer(), status)
        assertTrue(json.contains("\"provider\":\"openai_compatible\""))
        assertTrue(json.contains("\"fallback_provider\":\"ollama\""))
        assertTrue(json.contains("\"base_url\":\"https://api.openai.com/v1\""))

        val decoded = Api.json.decodeFromString(com.solarquack.sift.data.AiStatus.serializer(), json)
        assertEquals("openai_compatible", decoded.provider)
        assertEquals("ollama", decoded.fallbackProvider)
        assertEquals("http://localhost:11434/v1", decoded.fallbackBaseUrl)

        val keyIn = com.solarquack.sift.data.KeyIn(
            provider = "ollama",
            model = "llama3.2",
            baseUrl = "http://localhost:11434/v1",
            fallbackProvider = "gemini",
            fallbackModel = "gemini-2.5-flash",
            fallbackApiKey = "secret-fallback-key",
        )
        val keyJson = Api.json.encodeToString(com.solarquack.sift.data.KeyIn.serializer(), keyIn)
        assertTrue(keyJson.contains("\"provider\":\"ollama\""))
        assertTrue(keyJson.contains("\"fallback_provider\":\"gemini\""))
        val decodedKey = Api.json.decodeFromString(com.solarquack.sift.data.KeyIn.serializer(), keyJson)
        assertEquals("ollama", decodedKey.provider)
        assertEquals("secret-fallback-key", decodedKey.fallbackApiKey)
    }

    @Test
    fun testFakeApiSaveKeyWithFallback() = runBlocking {
        val api = Api.testOverride
        assertNotNull(api)

        val saved = api!!.saveKey(
            com.solarquack.sift.data.KeyIn(
                provider = "openai_compatible",
                model = "gpt-4o-mini",
                apiKey = "sk-test12345678",
                baseUrl = "https://api.groq.com/openai/v1",
                fallbackProvider = "ollama",
                fallbackModel = "llama3.2",
            )
        )
        assertEquals(true, saved.aiEnabled)
        assertEquals("openai_compatible", saved.provider)
        assertEquals("gpt-4o-mini", saved.model)
        assertEquals("ollama", saved.fallbackProvider)
    }

    @Test
    fun testFakeApiFuzzySearch() = runBlocking {
        val api = Api.testOverride
        assertNotNull(api)

        val res = api!!.search("assessment", fuzzy = true)
        assertTrue(res.items.isNotEmpty())
        assertEquals("m1", res.items[0].id)
        assertEquals("Acme Corp online assessment: link inside", res.items[0].subject)
    }

    @Test
    fun testVipAndMutedSerialization() {
        val sender = com.solarquack.sift.data.SenderItemDto(
            email = "ceo@partner.example",
            name = "Executive Officer",
            domain = "partner.example",
            totalCount = 42,
            unreadCount = 2,
            urgentCount = 1,
            isVip = true,
        )
        val senderJson = Api.json.encodeToString(com.solarquack.sift.data.SenderItemDto.serializer(), sender)
        assertTrue(senderJson.contains("\"is_vip\":true"))
        val decodedSender = Api.json.decodeFromString(com.solarquack.sift.data.SenderItemDto.serializer(), senderJson)
        assertEquals(true, decodedSender.isVip)

        val thread = com.solarquack.sift.data.ThreadDto(
            messages = emptyList(),
            accountId = "acc1",
            threadId = "th_999",
            isMuted = true,
        )
        val threadJson = Api.json.encodeToString(com.solarquack.sift.data.ThreadDto.serializer(), thread)
        assertTrue(threadJson.contains("\"is_muted\":true"))
        val decodedThread = Api.json.decodeFromString(com.solarquack.sift.data.ThreadDto.serializer(), threadJson)
        assertEquals(true, decodedThread.isMuted)
        assertEquals("th_999", decodedThread.threadId)

        val msg = com.solarquack.sift.data.MessageDto(
            id = "msg1",
            accountId = "acc1",
            isVip = true,
            isMuted = true,
        )
        val msgJson = Api.json.encodeToString(com.solarquack.sift.data.MessageDto.serializer(), msg)
        assertTrue(msgJson.contains("\"is_vip\":true"))
        assertTrue(msgJson.contains("\"is_muted\":true"))
        val decodedMsg = Api.json.decodeFromString(com.solarquack.sift.data.MessageDto.serializer(), msgJson)
        assertEquals(true, decodedMsg.isVip)
        assertEquals(true, decodedMsg.isMuted)
    }

    @Test
    fun testFakeApiVipAndMuteEndpoints() = runBlocking {
        val api = Api.testOverride
        assertNotNull(api)

        val vipRes = api!!.setSenderVip("founder@demo.sift.local")
        assertEquals(true, vipRes["ok"])
        assertEquals("founder@demo.sift.local", vipRes["email"])
        assertEquals(true, vipRes["is_vip"])

        val unvipRes = api.unsetSenderVip("founder@demo.sift.local")
        assertEquals(true, unvipRes["ok"])
        assertEquals(false, unvipRes["is_vip"])

        val muteRes = api.muteThread("t_demo_1")
        assertEquals(true, muteRes["ok"])
        assertEquals(true, muteRes["muted"])

        val unmuteRes = api.unmuteThread("t_demo_1")
        assertEquals(true, unmuteRes["ok"])
        assertEquals(false, unmuteRes["muted"])

        val checkRes = api.checkThreadMuted("t_demo_1")
        assertEquals(false, checkRes["muted"])
    }
}
