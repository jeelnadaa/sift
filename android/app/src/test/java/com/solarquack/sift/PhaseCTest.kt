package com.solarquack.sift

import com.solarquack.sift.data.Api
import com.solarquack.sift.data.AttachmentItemDto
import com.solarquack.sift.data.AttachmentListResultDto
import com.solarquack.sift.data.AttachmentStatsDto
import com.solarquack.sift.data.AttachmentTypeStatDto
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class PhaseCTest {

    @Before
    fun setUp() {
        FakeApi.install()
    }

    @After
    fun tearDown() {
        FakeApi.remove()
    }

    @Test
    fun testAttachmentSerialization() {
        val item = AttachmentItemDto(
            id = "att100",
            messageId = "msg200",
            accountId = "acc300",
            filename = "Quarterly_Financials.pdf",
            mime = "application/pdf",
            size = 2048576L,
            sender = "accounting@demo.sift.local",
            senderName = "Accounting Dept",
            subject = "Q3 Financials Attached",
            receivedAt = "2026-10-25T14:30:00Z",
            downloadUrl = "https://demo.sift.local/api/v1/files/tok-sample",
        )

        val json = Api.json.encodeToString(AttachmentItemDto.serializer(), item)
        assertTrue(json.contains("\"filename\":\"Quarterly_Financials.pdf\""))
        assertTrue(json.contains("\"mime\":\"application/pdf\""))
        assertTrue(json.contains("\"size\":2048576"))
        assertTrue(json.contains("\"download_url\":\"https://demo.sift.local/api/v1/files/tok-sample\""))

        val decoded = Api.json.decodeFromString(AttachmentItemDto.serializer(), json)
        assertEquals("att100", decoded.id)
        assertEquals("Quarterly_Financials.pdf", decoded.filename)
        assertEquals(2048576L, decoded.size)
        assertEquals("https://demo.sift.local/api/v1/files/tok-sample", decoded.downloadUrl)
    }

    @Test
    fun testAttachmentStatsSerialization() {
        val stats = AttachmentStatsDto(
            totalCount = 10,
            totalSize = 15000000L,
            byType = mapOf(
                "pdf" to AttachmentTypeStatDto(count = 4, size = 8000000L),
                "image" to AttachmentTypeStatDto(count = 6, size = 7000000L),
            ),
        )

        val json = Api.json.encodeToString(AttachmentStatsDto.serializer(), stats)
        assertTrue(json.contains("\"total_count\":10"))
        assertTrue(json.contains("\"total_size\":15000000"))

        val decoded = Api.json.decodeFromString(AttachmentStatsDto.serializer(), json)
        assertEquals(10, decoded.totalCount)
        assertEquals(15000000L, decoded.totalSize)
        assertEquals(4, decoded.byType["pdf"]?.count)
        assertEquals(6, decoded.byType["image"]?.count)
    }

    @Test
    fun testFakeApiAttachmentsEndpoints() = runBlocking {
        val override = Api.testOverride
        assertNotNull(override)

        val list = override!!.attachments()
        assertEquals(1, list.total)
        assertEquals(1, list.items.size)
        assertEquals("assessment_guide.pdf", list.items[0].filename)
        assertEquals("application/pdf", list.items[0].mime)

        val stats = override.attachmentStats()
        assertEquals(1, stats.totalCount)
        assertEquals(524288L, stats.totalSize)
        assertEquals(1, stats.byType["pdf"]?.count)
    }
}
