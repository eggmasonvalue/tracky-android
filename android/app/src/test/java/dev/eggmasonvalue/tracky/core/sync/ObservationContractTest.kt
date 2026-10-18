package dev.eggmasonvalue.tracky.core.sync

import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test

class ObservationContractTest {
    @Test
    fun `parser keeps only Linux selected weight and opaque cursor`() {
        val page = ObservationPageParser.parse(
            envelope(
                nextCursor = "opaque-page-cursor",
                session = """
                    {
                      "contract_version": 1,
                      "session_id": "session-1",
                      "status": "complete",
                      "quality": "accepted",
                      "quality_version": 1,
                      "selection_policy_version": 1,
                      "started_at_utc": "2026-09-16T10:00:00Z",
                      "selected": {
                        "frame_sequence": 3,
                        "weight": {
                          "raw": 7890,
                          "divisor": 100,
                          "unit": "kg",
                          "provenance": "Linux decoder v1"
                        }
                      },
                      "versions": ${versions()}
                    }
                """.trimIndent(),
            ),
        )

        assertEquals("opaque-page-cursor", page.nextCursor)
        val source = page.observations.single()
        assertEquals("session-1", source.sessionId)
        assertEquals(3L, source.selectedFrameSequence)
        assertEquals(7890L, source.weight?.raw)
        assertEquals(100L, source.weight?.divisor)
        assertEquals("kg", source.weight?.unit)
        assertEquals(null, source.weight?.let { it.copy(raw = null).kilogramsOrNull() })
        assertTrue(ObservationValidator.validate(source) is ObservationValidation.Valid)
    }

    @Test
    fun `missing selected source weight is permanently quarantinable`() {
        val page = ObservationPageParser.parse(
            envelope(
                session = """
                    {
                      "contract_version": 1,
                      "session_id": "session-2",
                      "status": "complete",
                      "quality": "indeterminate",
                      "quality_version": 1,
                      "selection_policy_version": 1,
                      "started_at_utc": "2026-09-16T10:00:00Z",
                      "selected": null,
                      "weight_kg": 78.9,
                      "body_fat_percentage": 21.5,
                      "versions": ${versions()}
                    }
                """.trimIndent(),
            ),
        )

        val validation = ObservationValidator.validate(page.observations.single())
        assertTrue(validation is ObservationValidation.Invalid)
        assertEquals("no_safe_selection", (validation as ObservationValidation.Invalid).errorCode)
        assertFalse(page.observations.single().weight?.kilogramsOrNull() == 78.9)
    }

    @Test
    fun `future or malformed page versions fail before item quarantine`() {
        val future = envelope(versions = versions(decoderVersion = 3))
        assertThrows(ObservationContractException::class.java) {
            ObservationPageParser.parse(future)
        }

        val malformed = envelope(versions = "{\"transport_version\":1}")
        assertThrows(ObservationContractException::class.java) {
            ObservationPageParser.parse(malformed)
        }
    }

    @Test
    fun `retryable source state cannot carry a cursor`() {
        val page = envelope(
            sourceState = "{\"kind\":\"retryable\",\"code\":\"source_session_open\"}",
            nextCursor = null,
        )
        val parsed = ObservationPageParser.parse(page)
        assertEquals("retryable", parsed.sourceState.kind)
        assertEquals("source_session_open", parsed.sourceState.code)
        assertEquals(null, parsed.nextCursor)
    }

    @Test
    fun `source weight uses declared divisor without clamping`() {
        val source = RemoteObservation(
            sessionId = "session-3",
            contractVersion = 1,
            status = "complete",
            quality = "indeterminate",
            qualityVersion = 1,
            startedAt = Instant.parse("2026-09-16T10:00:00Z"),
            selectedFrameSequence = 2,
            selectionPolicyVersion = 1,
            versions = supportedVersions(),
            weight = SourceWeight(7890, 100, "kg", "source"),
        )

        val validation = ObservationValidator.validate(source) as ObservationValidation.Valid
        assertEquals(78.9, validation.projection.weightKg, 0.0)
        assertEquals(1L, validation.projection.clientRecordVersion)
        assertEquals(1, validation.projection.selectionPolicyVersion)
        assertEquals(null, validation.projection.derivationVersion)
        assertTrue(validation.projection.clientRecordId.startsWith("tracky-linux-weight-v1-"))
    }

    @Test
    fun `opaque blocks a and b are mapped to canonical 10-channel impedances`() {
        // Block A (packet 0x21): LF20, LF100, RF20, RF100, LH20
        // Block B (packet 0x22): LH100, RH20, RH100, T20, T100
        val page = ObservationPageParser.parse(
            envelope(
                session = """
                    {
                      "contract_version": 1,
                      "session_id": "session-burst",
                      "status": "complete",
                      "quality": "accepted",
                      "quality_version": 1,
                      "selection_policy_version": 1,
                      "started_at_utc": "2026-09-16T10:00:00Z",
                      "selected": {
                        "frame_sequence": 3,
                        "weight": {
                          "raw": 7000,
                          "divisor": 100,
                          "unit": "kg",
                          "provenance": "Linux decoder v1"
                        }
                      },
                      "opaque_block_a": [4300, 3650, 4200, 3550, 4600],
                      "opaque_block_b": [3900, 4500, 3800, 300, 250],
                      "versions": ${versions()}
                    }
                """.trimIndent(),
            ),
        )
        val source = page.observations.single()
        assertEquals(listOf(4300, 3650, 4200, 3550, 4600), source.opaqueBlockA)
        assertEquals(listOf(3900, 4500, 3800, 300, 250), source.opaqueBlockB)

        val validation = ObservationValidator.validate(source) as ObservationValidation.Valid
        val impedances = validation.impedances
        assertTrue(impedances != null)
        assertEquals(10, impedances!!.size)
        // Canonical order: RH20, LH20, T20, RF20, LF20, RH100, LH100, T100, RF100, LF100
        assertEquals(450.0, impedances[0], 0.0) // RH20 = B[1] * 0.1
        assertEquals(460.0, impedances[1], 0.0) // LH20 = A[4] * 0.1
        assertEquals(30.0, impedances[2], 0.0)  // T20 = B[3] * 0.1
        assertEquals(420.0, impedances[3], 0.0) // RF20 = A[2] * 0.1
        assertEquals(430.0, impedances[4], 0.0) // LF20 = A[0] * 0.1
        assertEquals(380.0, impedances[5], 0.0) // RH100 = B[2] * 0.1
        assertEquals(390.0, impedances[6], 0.0) // LH100 = B[0] * 0.1
        assertEquals(25.0, impedances[7], 0.0)  // T100 = B[4] * 0.1
        assertEquals(355.0, impedances[8], 0.0) // RF100 = A[3] * 0.1
        assertEquals(365.0, impedances[9], 0.0) // LF100 = A[1] * 0.1
    }

    private fun envelope(
        session: String? = null,
        nextCursor: String? = "cursor",
        versions: String = versions(),
        sourceState: String = "{\"kind\":\"ready\"}",
    ): String = """
        {
          "ok": true,
          "contract_version": 1,
          "versions": $versions,
          "source_state": $sourceState,
          "count": ${if (session == null) 0 else 1},
          "next_cursor": ${nextCursor?.let { "\"$it\"" } ?: "null"},
          "sessions": [${session ?: ""}]
        }
    """.trimIndent()

    private fun versions(decoderVersion: Int = 2): String = """
        {
          "transport_version": 1,
          "decoder_version": $decoderVersion,
          "decoder_versions": [$decoderVersion],
          "selection_policy_version": 1,
          "quality_version": 1
        }
    """.trimIndent()

    private fun supportedVersions() = ObservationVersions(1, 2, listOf(2), 1, 1)
}
