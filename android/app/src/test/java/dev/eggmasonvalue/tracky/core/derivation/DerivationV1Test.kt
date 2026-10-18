package dev.eggmasonvalue.tracky.core.derivation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DerivationV1Test {

    private val normalInput = DerivationInput(
        heightCm = 170.0,
        weightKg = 70.0,
        impedances = listOf(
            450.0, 460.0, 30.0, 420.0, 430.0,
            380.0, 390.0, 25.0, 355.0, 365.0,
        ),
    )

    private val overweightInput = DerivationInput(
        heightCm = 175.0,
        weightKg = 90.0,
        impedances = listOf(
            400.0, 410.0, 35.0, 380.0, 390.0,
            340.0, 350.0, 28.0, 320.0, 330.0,
        ),
    )

    private val underweightInput = DerivationInput(
        heightCm = 165.0,
        weightKg = 48.0,
        impedances = listOf(
            520.0, 530.0, 40.0, 500.0, 510.0,
            440.0, 450.0, 33.0, 420.0, 430.0,
        ),
    )

    private val obeseInput = DerivationInput(
        heightCm = 160.0,
        weightKg = 100.0,
        impedances = listOf(
            350.0, 360.0, 25.0, 330.0, 340.0,
            300.0, 310.0, 20.0, 280.0, 290.0,
        ),
    )

    @Test
    fun `version constant is 1`() {
        assertEquals(1, DERIVATION_VERSION)
    }

    @Test
    fun `golden normal matches python reference`() {
        val result = DerivationV1.derive(normalInput)
        assertNotNull(result)
        result!!
        assertEquals(1, result.derivationVersion)
        assertEquals(31.5, result.bodyFatPct, 0.0)
        assertEquals(35.1, result.waterKg, 0.0)
        assertEquals(10.1, result.proteinKg, 0.0)
        assertEquals(26.4, result.skeletalMuscleKg, 0.0)
        assertEquals(2.8, result.boneKg, 0.0)
        assertEquals(48.0, result.leanBodyMassKg, 0.0)
        assertEquals(1406, result.bmrKcal)
    }

    @Test
    fun `golden overweight matches python reference`() {
        val result = DerivationV1.derive(overweightInput)
        assertNotNull(result)
        result!!
        assertEquals(1, result.derivationVersion)
        assertEquals(39.5, result.bodyFatPct, 0.0)
        assertEquals(39.9, result.waterKg, 0.0)
        assertEquals(11.0, result.proteinKg, 0.0)
        assertEquals(31.0, result.skeletalMuscleKg, 0.0)
        assertEquals(3.6, result.boneKg, 0.0)
        assertEquals(54.5, result.leanBodyMassKg, 0.0)
        assertEquals(1547, result.bmrKcal)
    }

    @Test
    fun `golden underweight matches python reference`() {
        val result = DerivationV1.derive(underweightInput)
        assertNotNull(result)
        result!!
        assertEquals(1, result.derivationVersion)
        assertEquals(19.4, result.bodyFatPct, 0.0)
        assertEquals(28.3, result.waterKg, 0.0)
        assertEquals(8.4, result.proteinKg, 0.0)
        assertEquals(20.9, result.skeletalMuscleKg, 0.0)
        assertEquals(1.9, result.boneKg, 0.0)
        assertEquals(38.7, result.leanBodyMassKg, 0.0)
        assertEquals(1206, result.bmrKcal)
    }

    @Test
    fun `golden obese matches python reference`() {
        val result = DerivationV1.derive(obeseInput)
        assertNotNull(result)
        result!!
        assertEquals(1, result.derivationVersion)
        assertEquals(44.6, result.bodyFatPct, 0.0)
        assertEquals(40.5, result.waterKg, 0.0)
        assertEquals(10.8, result.proteinKg, 0.0)
        assertEquals(27.8, result.skeletalMuscleKg, 0.0)
        assertEquals(4.0, result.boneKg, 0.0)
        assertEquals(55.4, result.leanBodyMassKg, 0.0)
        assertEquals(1566, result.bmrKcal)
    }

    @Test
    fun `rejects invalid impedance counts`() {
        val nine = normalInput.copy(impedances = normalInput.impedances.take(9))
        assertNull(DerivationV1.derive(nine))

        val eleven = normalInput.copy(impedances = normalInput.impedances + listOf(300.0))
        assertNull(DerivationV1.derive(eleven))
    }

    @Test
    fun `rejects zero negative or non-finite weight`() {
        assertNull(DerivationV1.derive(normalInput.copy(weightKg = 0.0)))
        assertNull(DerivationV1.derive(normalInput.copy(weightKg = -70.0)))
        assertNull(DerivationV1.derive(normalInput.copy(weightKg = Double.NaN)))
        assertNull(DerivationV1.derive(normalInput.copy(weightKg = Double.POSITIVE_INFINITY)))
    }

    @Test
    fun `rejects non-finite height`() {
        assertNull(DerivationV1.derive(normalInput.copy(heightCm = Double.NaN)))
        assertNull(DerivationV1.derive(normalInput.copy(heightCm = Double.POSITIVE_INFINITY)))
    }

    @Test
    fun `rejects zero negative or non-finite impedance`() {
        val zZero = normalInput.impedances.toMutableList().also { it[0] = 0.0 }
        assertNull(DerivationV1.derive(normalInput.copy(impedances = zZero)))

        val zNeg = normalInput.impedances.toMutableList().also { it[4] = -100.0 }
        assertNull(DerivationV1.derive(normalInput.copy(impedances = zNeg)))

        val zNan = normalInput.impedances.toMutableList().also { it[7] = Double.NaN }
        assertNull(DerivationV1.derive(normalInput.copy(impedances = zNan)))
    }

    @Test
    fun `determinism and height clamping`() {
        val r1 = DerivationV1.derive(normalInput)
        val r2 = DerivationV1.derive(normalInput)
        assertEquals(r1, r2)

        val rLow = DerivationV1.derive(normalInput.copy(heightCm = 30.0))
        val rAt40 = DerivationV1.derive(normalInput.copy(heightCm = 40.0))
        assertNotNull(rLow)
        assertNotNull(rAt40)
        assertEquals(rLow, rAt40)
    }
}
