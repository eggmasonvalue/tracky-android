package dev.eggmasonvalue.tracky.core.data

import dev.eggmasonvalue.tracky.core.sync.ObservationValidator
import dev.eggmasonvalue.tracky.core.sync.WeightProjection
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class ImportLedgerModelTest {
    @Test
    fun `ledger entry contains projection identity and disposition but no source evidence`() {
        val projection = WeightProjection(
            sourceSessionId = "linux-session",
            clientRecordId = ObservationValidator.clientRecordId("linux-session"),
            clientRecordVersion = 1,
            contractVersion = 1,
            selectionPolicyVersion = 1,
            derivationVersion = null,
            weightKg = 78.9,
            observedAt = Instant.EPOCH,
            sourceQuality = "accepted",
        )
        val entry = ImportLedgerEntry(
            clientRecordId = projection.clientRecordId,
            sourceSessionId = projection.sourceSessionId,
            clientRecordVersion = projection.clientRecordVersion,
            contractVersion = projection.contractVersion,
            selectionPolicyVersion = projection.selectionPolicyVersion,
            derivationVersion = projection.derivationVersion,
            disposition = ImportDisposition.IMPORTED,
            healthConnectRecordId = "health-connect-id",
            attemptCount = 1,
            lastAttemptAt = Instant.EPOCH,
            nextRetryAt = null,
            lastErrorCode = null,
            lastErrorMessage = null,
            updatedAt = Instant.EPOCH,
        )

        assertEquals(ImportDisposition.IMPORTED, entry.disposition)
        assertEquals(null, entry.derivationVersion)
        assertEquals("linux-session", entry.sourceSessionId)
        assertNotEquals("78.9", entry.lastErrorMessage)
    }
}
