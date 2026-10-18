package dev.eggmasonvalue.tracky.core.healthconnect

import androidx.health.connect.client.records.BasalMetabolicRateRecord
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.BoneMassRecord
import androidx.health.connect.client.records.LeanBodyMassRecord
import androidx.health.connect.client.records.WeightRecord
import dev.eggmasonvalue.tracky.core.derivation.DerivationResult
import dev.eggmasonvalue.tracky.core.sync.WeightProjection
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class HealthConnectManagerTest {

    private val now = Instant.parse("2026-09-16T10:00:00Z")

    private val weightOnlyProjection = WeightProjection(
        sourceSessionId = "session-1",
        clientRecordId = "tracky-linux-weight-v1-abcdef1234567890",
        clientRecordVersion = 1L,
        contractVersion = 1,
        selectionPolicyVersion = 1,
        derivationVersion = null,
        weightKg = 70.0,
        observedAt = now,
        sourceQuality = "accepted",
        derivation = null,
    )

    private val derivation = DerivationResult(
        derivationVersion = 1,
        bodyFatPct = 31.5,
        waterKg = 35.1,
        proteinKg = 10.1,
        skeletalMuscleKg = 26.4,
        boneKg = 2.8,
        leanBodyMassKg = 48.0,
        bmrKcal = 1406,
    )

    private val fullProjection = weightOnlyProjection.copy(
        derivationVersion = 1,
        derivation = derivation,
    )

    @Test
    fun `buildRecords with weight only creates single WeightRecord`() {
        val records = HealthConnectManager.buildRecords(weightOnlyProjection)
        assertEquals(1, records.size)
        val weightRecord = records[0] as WeightRecord
        assertEquals(70.0, weightRecord.weight.inKilograms, 0.0)
        assertEquals(now, weightRecord.time)
        assertEquals("tracky-linux-weight-v1-abcdef1234567890", weightRecord.metadata.clientRecordId)
        assertEquals(1L, weightRecord.metadata.clientRecordVersion)
        assertEquals("Tracky", weightRecord.metadata.device?.manufacturer)
    }

    @Test
    fun `buildRecords with derivation creates all 5 Health Connect records`() {
        val records = HealthConnectManager.buildRecords(fullProjection)
        assertEquals(5, records.size)

        // 1. WeightRecord
        val weightRecord = records[0] as WeightRecord
        assertEquals(70.0, weightRecord.weight.inKilograms, 0.0)
        assertEquals(now, weightRecord.time)
        assertEquals("tracky-linux-weight-v1-abcdef1234567890", weightRecord.metadata.clientRecordId)

        // 2. BodyFatRecord
        val fatRecord = records[1] as BodyFatRecord
        assertEquals(31.5, fatRecord.percentage.value, 0.0)
        assertEquals(now, fatRecord.time)
        assertEquals("tracky-linux-weight-v1-abcdef1234567890-fat", fatRecord.metadata.clientRecordId)
        assertEquals(1L, fatRecord.metadata.clientRecordVersion)

        // 3. LeanBodyMassRecord
        val lbmRecord = records[2] as LeanBodyMassRecord
        assertEquals(48.0, lbmRecord.mass.inKilograms, 0.0)
        assertEquals(now, lbmRecord.time)
        assertEquals("tracky-linux-weight-v1-abcdef1234567890-lbm", lbmRecord.metadata.clientRecordId)
        assertEquals(1L, lbmRecord.metadata.clientRecordVersion)

        // 4. BoneMassRecord
        val boneRecord = records[3] as BoneMassRecord
        assertEquals(2.8, boneRecord.mass.inKilograms, 0.0)
        assertEquals(now, boneRecord.time)
        assertEquals("tracky-linux-weight-v1-abcdef1234567890-bone", boneRecord.metadata.clientRecordId)
        assertEquals(1L, boneRecord.metadata.clientRecordVersion)

        // 5. BasalMetabolicRateRecord
        val bmrRecord = records[4] as BasalMetabolicRateRecord
        assertEquals(1406.0, bmrRecord.basalMetabolicRate.inKilocaloriesPerDay, 0.0)
        assertEquals(now, bmrRecord.time)
        assertEquals("tracky-linux-weight-v1-abcdef1234567890-bmr", bmrRecord.metadata.clientRecordId)
        assertEquals(1L, bmrRecord.metadata.clientRecordVersion)
    }
}
