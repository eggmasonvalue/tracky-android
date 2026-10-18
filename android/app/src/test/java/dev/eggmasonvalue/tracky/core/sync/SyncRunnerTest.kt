package dev.eggmasonvalue.tracky.core.sync

import dev.eggmasonvalue.tracky.core.data.ImportDisposition
import dev.eggmasonvalue.tracky.core.data.ImportLedger
import dev.eggmasonvalue.tracky.core.data.ImportLedgerEntry
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SyncRunnerTest {
    private val now = Instant.parse("2026-09-16T10:00:00Z")
    private val clock = Clock.fixed(now, ZoneOffset.UTC)

    @Test
    fun `cursor advances only after import or quarantine`() = runTest {
        val ledger = FakeLedger()
        val health = FakeHealth()
        val runner = runner(ledger, health, page(valid("ok"), invalidMissingWeight("bad"), nextCursor = "opaque-2"))

        val result = runner.run()

        assertEquals(SyncRunResult.Success(imported = 1, alreadyTerminal = 0, quarantined = 1), result)
        assertEquals("opaque-2", ledger.savedCursor)
        assertEquals(ImportDisposition.IMPORTED, ledger.entries.getValue(ObservationValidator.clientRecordId("ok")).disposition)
        assertEquals(ImportDisposition.QUARANTINED, ledger.entries.getValue(ObservationValidator.clientRecordId("bad")).disposition)
    }

    @Test
    fun `cursor is not advanced when Health Connect write fails`() = runTest {
        val ledger = FakeLedger()
        val health = FakeHealth(failWrites = true)
        val runner = runner(ledger, health, page(valid("retry"), nextCursor = "opaque-retry"))

        assertEquals(SyncRunResult.Retry("health_connect_write_failed"), runner.run())
        assertNull(ledger.savedCursor)
        val entry = ledger.entries.getValue(ObservationValidator.clientRecordId("retry"))
        assertEquals(ImportDisposition.PENDING, entry.disposition)
        assertEquals("health_connect_write_failed", entry.lastErrorCode)
    }

    @Test
    fun `replaying an imported pair is a no-op and can settle the cursor`() = runTest {
        val ledger = FakeLedger()
        val health = FakeHealth()
        val observation = valid("replay")
        val id = ObservationValidator.clientRecordId("replay")
        ledger.entries[id] = importedEntry(observation, id)
        val runner = runner(ledger, health, page(observation, nextCursor = "opaque-replay"))

        assertEquals(SyncRunResult.Success(0, 1, 0), runner.run())
        assertEquals(0, health.writeCount)
        assertEquals("opaque-replay", ledger.savedCursor)
    }

    @Test
    fun `derivation is calculated and recorded when height and impedances are available`() = runTest {
        val ledger = FakeLedger()
        val health = FakeHealth(height = HeightObservation(now, 1.70))
        val obsWithImpedances = valid("with-bia").copy(
            impedances = listOf(
                450.0, 460.0, 30.0, 420.0, 430.0,
                380.0, 390.0, 25.0, 355.0, 365.0,
            ),
        )
        val runner = runner(ledger, health, page(obsWithImpedances, nextCursor = "opaque-bia"))

        val result = runner.run()
        assertEquals(SyncRunResult.Success(1, 0, 0), result)
        val written = health.writtenProjections.single()
        assertEquals(1, written.derivationVersion)
        val derivation = written.derivation
        assertTrue(derivation != null)
        assertEquals(1, derivation!!.derivationVersion)
        assertEquals(38.3, derivation.bodyFatPct, 0.0) // 78.9 kg, 170 cm overweight bracket
        assertEquals(48.7, derivation.leanBodyMassKg, 0.0)
        assertEquals(1421, derivation.bmrKcal)

        val entry = ledger.entries.getValue(written.clientRecordId)
        assertEquals(ImportDisposition.IMPORTED, entry.disposition)
        assertEquals(1, entry.derivationVersion)
    }

    @Test
    fun `derivation is skipped when height is missing`() = runTest {
        val ledger = FakeLedger()
        val health = FakeHealth(height = null)
        val obsWithImpedances = valid("no-height").copy(
            impedances = listOf(
                450.0, 460.0, 30.0, 420.0, 430.0,
                380.0, 390.0, 25.0, 355.0, 365.0,
            ),
        )
        val runner = runner(ledger, health, page(obsWithImpedances, nextCursor = "opaque-no-h"))

        val result = runner.run()
        assertEquals(SyncRunResult.Success(1, 0, 0), result)
        val written = health.writtenProjections.single()
        assertEquals(null, written.derivationVersion)
        assertEquals(null, written.derivation)

        val entry = ledger.entries.getValue(written.clientRecordId)
        assertEquals(ImportDisposition.IMPORTED, entry.disposition)
        assertEquals(null, entry.derivationVersion)
    }

    private fun runner(
        ledger: FakeLedger,
        health: FakeHealth,
        page: ObservationPage,
    ) = SyncRunner(
        configSource = object : SyncConfigSource {
            override fun load() = SyncEndpointValidator.validate("https://appliance.example", "test-token")
        },
        ledger = ledger,
        transport = object : ObservationTransport {
            override suspend fun fetch(config: SyncEndpointConfig, cursor: String?): ObservationPage {
                assertEquals(null, cursor)
                return page
            }
        },
        healthConnect = health,
        clock = clock,
    )

    private fun page(
        vararg observations: RemoteObservation,
        nextCursor: String?,
    ) = ObservationPage(
        observations = observations.toList(),
        nextCursor = nextCursor,
        versions = ObservationVersions(1, 2, listOf(2), 1, 1),
        sourceState = PageSourceState("ready", null),
    )

    private fun valid(id: String) = RemoteObservation(
        sessionId = id,
        contractVersion = 1,
        status = "complete",
        quality = "accepted",
        qualityVersion = 1,
        startedAt = now,
        selectedFrameSequence = 3,
        selectionPolicyVersion = 1,
        versions = ObservationVersions(1, 2, listOf(2), 1, 1),
        weight = SourceWeight(7890, 100, "kg", "Linux source"),
    )

    private fun invalidMissingWeight(id: String) = valid(id).copy(weight = null)

    private fun importedEntry(observation: RemoteObservation, id: String) = ImportLedgerEntry(
        clientRecordId = id,
        sourceSessionId = observation.sessionId!!,
        clientRecordVersion = 1,
        contractVersion = 1,
        selectionPolicyVersion = 1,
        derivationVersion = null,
        disposition = ImportDisposition.IMPORTED,
        healthConnectRecordId = "hc-id",
        attemptCount = 1,
        lastAttemptAt = now,
        nextRetryAt = null,
        lastErrorCode = null,
        lastErrorMessage = null,
        updatedAt = now,
    )
}

private class FakeHealth(
    private val failWrites: Boolean = false,
    var height: HeightObservation? = null,
) : HealthConnectProjector {
    var writeCount = 0
    val writtenProjections = mutableListOf<WeightProjection>()

    override fun isAvailable(): Boolean = true
    override suspend fun hasRequiredPermissions(): Boolean = true
    override suspend fun readLatestApplicableHeight(): HeightObservation? = height
    override suspend fun insertWeight(projection: WeightProjection): String {
        writeCount++
        writtenProjections.add(projection)
        if (failWrites) error("test failure")
        return "hc-${projection.clientRecordId}"
    }
}

private class FakeLedger : ImportLedger {
    val entries = linkedMapOf<String, ImportLedgerEntry>()
    var savedCursor: String? = null
        private set

    override suspend fun find(clientRecordId: String): ImportLedgerEntry? = entries[clientRecordId]

    override suspend fun markPending(projection: WeightProjection, now: Instant) {
        val old = entries[projection.clientRecordId]
        entries[projection.clientRecordId] = ImportLedgerEntry(
            clientRecordId = projection.clientRecordId,
            sourceSessionId = projection.sourceSessionId,
            clientRecordVersion = projection.clientRecordVersion,
            contractVersion = projection.contractVersion,
            selectionPolicyVersion = projection.selectionPolicyVersion,
            derivationVersion = projection.derivationVersion,
            disposition = ImportDisposition.PENDING,
            healthConnectRecordId = null,
            attemptCount = old?.attemptCount ?: 0,
            lastAttemptAt = old?.lastAttemptAt,
            nextRetryAt = null,
            lastErrorCode = null,
            lastErrorMessage = null,
            updatedAt = now,
        )
    }

    override suspend fun markImported(clientRecordId: String, healthConnectRecordId: String, now: Instant) {
        val old = entries.getValue(clientRecordId)
        entries[clientRecordId] = old.copy(
            disposition = ImportDisposition.IMPORTED,
            healthConnectRecordId = healthConnectRecordId,
            attemptCount = old.attemptCount + 1,
            lastAttemptAt = now,
            nextRetryAt = null,
            lastErrorCode = null,
            lastErrorMessage = null,
            updatedAt = now,
        )
    }

    override suspend fun markAttemptFailed(
        clientRecordId: String,
        now: Instant,
        errorCode: String,
        errorMessage: String,
        retryAfter: Duration,
    ) {
        val old = entries.getValue(clientRecordId)
        entries[clientRecordId] = old.copy(
            disposition = ImportDisposition.PENDING,
            attemptCount = old.attemptCount + 1,
            lastAttemptAt = now,
            nextRetryAt = now.plus(retryAfter),
            lastErrorCode = errorCode,
            lastErrorMessage = errorMessage,
            updatedAt = now,
        )
    }

    override suspend fun markQuarantined(
        projection: WeightProjection,
        now: Instant,
        errorCode: String,
        errorMessage: String,
    ) {
        entries[projection.clientRecordId] = ImportLedgerEntry(
            clientRecordId = projection.clientRecordId,
            sourceSessionId = projection.sourceSessionId,
            clientRecordVersion = projection.clientRecordVersion,
            contractVersion = projection.contractVersion,
            selectionPolicyVersion = projection.selectionPolicyVersion,
            derivationVersion = projection.derivationVersion,
            disposition = ImportDisposition.QUARANTINED,
            healthConnectRecordId = null,
            attemptCount = 0,
            lastAttemptAt = now,
            nextRetryAt = null,
            lastErrorCode = errorCode,
            lastErrorMessage = errorMessage,
            updatedAt = now,
        )
    }

    override suspend fun cursor(): String? = savedCursor
    override suspend fun advanceCursor(cursor: String?) { savedCursor = cursor }
}
