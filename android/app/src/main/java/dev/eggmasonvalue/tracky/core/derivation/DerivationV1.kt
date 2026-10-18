package dev.eggmasonvalue.tracky.core.derivation

import java.math.BigDecimal
import java.math.RoundingMode
import kotlin.math.max

const val DERIVATION_VERSION: Int = 1

data class DerivationInput(
    val heightCm: Double,
    val weightKg: Double,
    val impedances: List<Double>,
)

data class DerivationResult(
    val derivationVersion: Int,
    val bodyFatPct: Double,
    val waterKg: Double,
    val proteinKg: Double,
    val skeletalMuscleKg: Double,
    val boneKg: Double,
    val leanBodyMassKg: Double,
    val bmrKcal: Int,
)

private data class Bank(
    val intercept: Double,
    val coefficients: Map<String, Double>,
)

private val FAT_UNDERWEIGHT = Bank(
    intercept = -62.0719292073132,
    coefficients = mapOf(
        "Height" to 0.036839834257782,
        "Weight" to 0.117346516934577,
        "BMI" to 3.45595189922899,
        "Z_RH20" to 0.0597823384076915,
        "Z_LH20" to -0.0616480615352019,
        "Z_T20" to -0.463379762695084,
        "Z_RF20" to -0.186575010739835,
        "Z_LF20" to 0.154847544230755,
        "Z_RH100" to -0.0170962517342159,
        "Z_LH100" to 0.0722113346676602,
        "Z_T100" to 0.814030967044537,
        "Z_RF100" to 0.206149677821911,
        "Z_LF100" to -0.178536259008776,
        "LL_RH_20K" to 0.791405620837228,
        "LL_T_20K" to -0.0121626216579239,
        "LL_RF_20K" to -0.0626974574944824,
        "LL_LF_20K" to 0.865430740005401,
        "LL_RH_100K" to -0.559457501452672,
        "LL_LH_100K" to -0.135380460991728,
        "LL_T_100K" to 0.00153436018138699,
        "LL_LF_100K" to -0.833669634955733,
    ),
)

private val FAT_NORMAL = Bank(
    intercept = -84.332816512093,
    coefficients = mapOf(
        "Height" to 0.138551403224977,
        "Weight" to -0.229638126411852,
        "BMI" to 3.5380079792298,
        "Z_RH20" to 0.0316047765299857,
        "Z_LH20" to -0.0456856094717298,
        "Z_T20" to -0.381011675527324,
        "Z_RF20" to -0.16735090326332,
        "Z_LF20" to -0.0877589672167205,
        "Z_RH100" to 0.00260679672345121,
        "Z_LH100" to 0.0730061552968283,
        "Z_T100" to 0.876003772432261,
        "Z_RF100" to 0.224774420521255,
        "Z_LF100" to 0.0735371840926183,
        "LL_RH_20K" to 0.541779102847987,
        "LL_T_20K" to -0.0047991564060679,
        "LL_LF_20K" to 0.162537864764221,
        "LL_RH_100K" to -0.443024531997328,
        "LL_LH_100K" to -0.0260945733658815,
        "LL_T_100K" to -0.00163585952146194,
        "LL_RF_100K" to 0.0389918890376868,
        "LL_LF_100K" to -0.23721366452991,
    ),
)

private val FAT_OVERWEIGHT = Bank(
    intercept = -51.793305197286,
    coefficients = mapOf(
        "Height" to -0.0169194883077701,
        "Weight" to -0.101817514694878,
        "BMI" to 2.51905588455144,
        "Z_RH20" to 0.140290549506976,
        "Z_LH20" to -0.0435357324556074,
        "Z_T20" to -0.104885740189388,
        "Z_RF20" to 0.125732198644235,
        "Z_LF20" to -0.348363448973619,
        "Z_RH100" to -0.0900681924878712,
        "Z_LH100" to 0.052816858496536,
        "Z_T100" to 0.558860341050186,
        "Z_RF100" to -0.111714031322363,
        "Z_LF100" to 0.381046130361682,
        "LL_RH_20K" to 0.736380305349612,
        "LL_T_20K" to 0.00256324936451522,
        "LL_RF_20K" to 0.512554241117436,
        "LL_LF_20K" to -0.25456178296025,
        "LL_RH_100K" to -0.544909559181151,
        "LL_LH_100K" to -0.0892105113773864,
        "LL_T_100K" to -0.00762367319464728,
        "LL_RF_100K" to -0.441481841333243,
        "LL_LF_100K" to 0.181677570558573,
    ),
)

private val FAT_OBESE = Bank(
    intercept = -46.7525373477897,
    coefficients = mapOf(
        "Height" to 0.445770045773053,
        "Weight" to -0.216923234016041,
        "BMI" to 1.87284418558527,
        "Z_RH20" to -0.464444098327764,
        "Z_LH20" to 0.298646058032808,
        "Z_T20" to 0.000795515611502758,
        "Z_RF20" to 0.338137304663717,
        "Z_LF20" to -0.532486268981483,
        "Z_RH100" to 0.345097223009627,
        "Z_LH100" to -0.055754925061094,
        "Z_T100" to -0.794653212666266,
        "Z_RF100" to -0.328523953616789,
        "Z_LF100" to 0.483203986537538,
        "LL_RH_20K" to -0.482099548984409,
        "LL_T_20K" to 0.0105183084635134,
        "LL_RF_20K" to 0.0967161464479232,
        "LL_LF_20K" to 0.0963700965982488,
        "LL_LH_100K" to 0.496298279624006,
        "LL_T_100K" to -0.0262851904508251,
        "LL_LF_100K" to -0.260727801265288,
    ),
)

private val SKELETAL_MUSCLE = Bank(
    intercept = 0.63206395940795,
    coefficients = mapOf(
        "Height" to 0.051036467315893,
        "Weight" to 0.236860359732721,
        "BMI" to -0.470722275662929,
        "Z_RH20" to 0.0411350401147831,
        "Z_LH20" to -0.0503462809653475,
        "Z_T20" to 0.310599852501293,
        "Z_RF20" to -0.0017898609678593,
        "Z_LF20" to 0.0181092601577931,
        "Z_RH100" to -0.0433891795451644,
        "Z_LH100" to 0.049510057273899,
        "Z_T100" to -0.356764255601546,
        "Z_RF100" to -0.0134391496272278,
        "Z_LF100" to -0.00820980883043372,
        "LL_RH_20K" to 0.0559418855214566,
        "LL_LH_20K" to -0.410390268396024,
        "LL_T_20K" to 0.00355213309084269,
        "LL_RF_20K" to -0.0246853665587738,
        "LL_LF_20K" to -0.274331162001714,
        "LL_LH_100K" to 0.391830240595914,
        "LL_T_100K" to 0.00101901758486269,
        "LL_LF_100K" to 0.287735234938504,
    ),
)

private const val BMI_UNDERWEIGHT = 19.0
private const val BMI_NORMAL_UPPER = 24.0
private const val BMI_OVERWEIGHT_UPPER = 31.0

private const val BONE_LOWER_FRAC = 0.039
private const val BONE_UPPER_FRAC = 0.051

object DerivationV1 {
    fun derive(input: DerivationInput): DerivationResult? {
        if (input.impedances.size != 10) return null
        if (!input.weightKg.isFinite() || input.weightKg <= 0.0) return null
        if (!input.heightCm.isFinite()) return null

        val height = input.heightCm.coerceIn(40.0, 240.0)
        if (height < 40.0 || height > 240.0) return null
        val weight = input.weightKg

        for (z in input.impedances) {
            if (!z.isFinite() || z <= 0.0) return null
        }

        val zRh20 = input.impedances[0]
        val zLh20 = input.impedances[1]
        val zT20 = input.impedances[2]
        val zRf20 = input.impedances[3]
        val zLf20 = input.impedances[4]

        val zRh100 = input.impedances[5]
        val zLh100 = input.impedances[6]
        val zT100 = input.impedances[7]
        val zRf100 = input.impedances[8]
        val zLf100 = input.impedances[9]

        val bmi = weight / ((height / 100.0) * (height / 100.0))
        val hSq = height * height

        val features = mapOf(
            "Height" to height,
            "Weight" to weight,
            "BMI" to bmi,
            "Z_RH20" to zRh20,
            "Z_LH20" to zLh20,
            "Z_T20" to zT20,
            "Z_RF20" to zRf20,
            "Z_LF20" to zLf20,
            "Z_RH100" to zRh100,
            "Z_LH100" to zLh100,
            "Z_T100" to zT100,
            "Z_RF100" to zRf100,
            "Z_LF100" to zLf100,
            "LL_RH_20K" to hSq / zRh20,
            "LL_LH_20K" to hSq / zLh20,
            "LL_T_20K" to hSq / zT20,
            "LL_RF_20K" to hSq / zRf20,
            "LL_LF_20K" to hSq / zLf20,
            "LL_RH_100K" to hSq / zRh100,
            "LL_LH_100K" to hSq / zLh100,
            "LL_T_100K" to hSq / zT100,
            "LL_RF_100K" to hSq / zRf100,
            "LL_LF_100K" to hSq / zLf100,
        )

        val fatBank = selectBmiBank(bmi, FAT_UNDERWEIGHT, FAT_NORMAL, FAT_OVERWEIGHT, FAT_OBESE)
        val bodyFatRaw = evaluate(fatBank, features)
        if (!bodyFatRaw.isFinite()) return null
        val bodyFatPct = bodyFatRaw.coerceIn(3.0, 75.0)

        val leanBodyMassKg = weight * (1.0 - bodyFatPct / 100.0)
        if (leanBodyMassKg <= 0.0) return null

        val waterKg = 0.732 * leanBodyMassKg
        val boneLower = BONE_LOWER_FRAC * weight
        val boneUpper = BONE_UPPER_FRAC * weight
        val boneKg = (0.04 * weight).coerceIn(boneLower, boneUpper)

        val proteinKg = max(0.1, leanBodyMassKg - waterKg - boneKg)

        val skeletalMuscleRaw = evaluate(SKELETAL_MUSCLE, features)
        val skeletalMuscleKg = if (skeletalMuscleRaw > 0.0 && skeletalMuscleRaw < leanBodyMassKg) {
            skeletalMuscleRaw
        } else {
            0.70 * leanBodyMassKg
        }

        val bmrRaw = 370.0 + 21.6 * leanBodyMassKg

        return DerivationResult(
            derivationVersion = DERIVATION_VERSION,
            bodyFatPct = round1(bodyFatPct),
            waterKg = round1(waterKg),
            proteinKg = round1(proteinKg),
            skeletalMuscleKg = round1(skeletalMuscleKg),
            boneKg = round1(boneKg),
            leanBodyMassKg = round1(leanBodyMassKg),
            bmrKcal = Math.round(bmrRaw).toInt(),
        )
    }

    private fun evaluate(bank: Bank, features: Map<String, Double>): Double {
        var total = bank.intercept
        for ((term, coeff) in bank.coefficients) {
            val f = features[term] ?: 0.0
            total += coeff * f
        }
        return total
    }

    private fun selectBmiBank(bmi: Double, under: Bank, normal: Bank, over: Bank, obese: Bank): Bank =
        when {
            bmi < BMI_UNDERWEIGHT -> under
            bmi < BMI_NORMAL_UPPER -> normal
            bmi < BMI_OVERWEIGHT_UPPER -> over
            else -> obese
        }

    fun mapOpaqueBlocksToImpedances(blockA: List<Int>, blockB: List<Int>): List<Double>? {
        if (blockA.size != 5 || blockB.size != 5) return null
        return listOf(
            blockB[1] * 0.1, // Z_RH20
            blockA[4] * 0.1, // Z_LH20
            blockB[3] * 0.1, // Z_T20
            blockA[2] * 0.1, // Z_RF20
            blockA[0] * 0.1, // Z_LF20
            blockB[2] * 0.1, // Z_RH100
            blockB[0] * 0.1, // Z_LH100
            blockB[4] * 0.1, // Z_T100
            blockA[3] * 0.1, // Z_RF100
            blockA[1] * 0.1, // Z_LF100
        )
    }

    private fun round1(v: Double): Double =
        BigDecimal.valueOf(v).setScale(1, RoundingMode.HALF_UP).toDouble()
}
