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
}
