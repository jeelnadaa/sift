package com.solarquack.sift

import com.solarquack.sift.data.Api
import com.solarquack.sift.data.MailNoteDto
import com.solarquack.sift.data.MessageDto
import com.solarquack.sift.data.NoteIn
import com.solarquack.sift.data.PinResult
import com.solarquack.sift.data.SettingsDto
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class PhaseBTest {

    @Before
    fun setUp() {
        FakeApi.install()
    }

    @After
    fun tearDown() {
        FakeApi.remove()
    }

    @Test
    fun testMessageDtoWithPinnedAndNotesSerialization() {
        val note = MailNoteDto(
            id = "n1",
            messageId = "m1",
            content = "Interview reminder",
            createdAt = "2026-10-26T00:00:00Z",
            updatedAt = "2026-10-26T00:00:00Z",
        )
        val msg = MessageDto(
            id = "m1",
            accountId = "a1",
            subject = "Test mail",
            pinned = true,
            hasNote = true,
            notesCount = 1,
            notes = listOf(note),
        )

        val json = Api.json.encodeToString(MessageDto.serializer(), msg)
        assertTrue(json.contains("\"pinned\":true"))
        assertTrue(json.contains("\"has_note\":true"))
        assertTrue(json.contains("\"notes_count\":1"))

        val decoded = Api.json.decodeFromString(MessageDto.serializer(), json)
        assertTrue(decoded.pinned)
        assertTrue(decoded.hasNote)
        assertEquals(1, decoded.notesCount)
        assertEquals(1, decoded.notes.size)
        assertEquals("Interview reminder", decoded.notes[0].content)
    }

    @Test
    fun testSettingsDtoWithQuietHoursSerialization() {
        val settings = SettingsDto(
            senderName = "Demo User",
            signature = "Best regards",
            quietHoursEnabled = true,
            quietHoursStart = "23:00",
            quietHoursEnd = "08:00",
            mutedCategories = listOf("fyi", "promotions"),
        )

        val json = Api.json.encodeToString(SettingsDto.serializer(), settings)
        assertTrue(json.contains("\"quiet_hours_enabled\":true"))
        assertTrue(json.contains("\"quiet_hours_start\":\"23:00\""))
        assertTrue(json.contains("\"quiet_hours_end\":\"08:00\""))
        assertTrue(json.contains("\"muted_categories\":[\"fyi\",\"promotions\"]"))

        val decoded = Api.json.decodeFromString(SettingsDto.serializer(), json)
        assertTrue(decoded.quietHoursEnabled)
        assertEquals("23:00", decoded.quietHoursStart)
        assertEquals("08:00", decoded.quietHoursEnd)
        assertEquals(listOf("fyi", "promotions"), decoded.mutedCategories)
    }

    @Test
    fun testPinAndNoteDtoSerialization() {
        val pin = PinResult(id = "m1", pinned = true)
        val pinJson = Api.json.encodeToString(PinResult.serializer(), pin)
        val decodedPin = Api.json.decodeFromString(PinResult.serializer(), pinJson)
        assertEquals("m1", decodedPin.id)
        assertTrue(decodedPin.pinned)

        val noteIn = NoteIn(content = "Confidential feedback")
        val noteInJson = Api.json.encodeToString(NoteIn.serializer(), noteIn)
        val decodedNoteIn = Api.json.decodeFromString(NoteIn.serializer(), noteInJson)
        assertEquals("Confidential feedback", decodedNoteIn.content)
    }

    @Test
    fun testFakeApiPhaseBEndpoints() = runBlocking {
        val override = Api.testOverride!!
        val settings = override.settings()
        assertTrue(settings.quietHoursEnabled)
        assertEquals("22:00", settings.quietHoursStart)
        assertEquals("07:00", settings.quietHoursEnd)

        val pinResult = override.pinMessage("m1", true)
        assertTrue(pinResult.pinned)

        val notes = override.notes("m1")
        assertEquals(1, notes.size)
        assertEquals("Review by Friday", notes[0].content)

        val added = override.addNote("m1", NoteIn("New note"))
        assertEquals("New note", added.content)
    }
}
