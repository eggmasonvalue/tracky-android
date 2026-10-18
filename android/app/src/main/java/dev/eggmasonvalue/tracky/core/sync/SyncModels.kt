package dev.eggmasonvalue.tracky.core.sync

import dev.eggmasonvalue.tracky.core.derivation.DerivationResult
import dev.eggmasonvalue.tracky.core.derivation.DerivationV1
import java.math.BigDecimal
import java.math.RoundingMode
import java.security.MessageDigest
import java.time.Instant

const val OBSERVATION_CONTRACT_VERSION: Int = 1
const val TRANSPORT_VERSION: Int = 1
const val SUPPORTED_DECODER_VERSION: Int = 2
const val WEIGHT_PROJECTION_VERSION: Int = 1
const val WEIGHT_SELECTION_POLICY_VERSION: Int = 1
const val QUALITY_VERSION: Int = 1

data class HeightObservation(
    val recordedAt: Instant,
    val heightMeters: Double,
) {
    val heightCentimeters: Double
        get() = heightMeters * 100.0
}

data class ObservationVersions(
    val transportVersion: Int,
    val decoderVersion: Int?,
    val decoderVersions: List<Int>,
    val selectionPolicyVersion: Int,
    val qualityVersion: Int,
)

data class PageSourceState(
    val kind: String,
    val code: String?,
)

/** One source-declared weight value; no electrical or body-composition meaning is carried here. */
data class SourceWeight(
    val raw: Long?,
    val divisor: Long?,
    val unit: String?,
    val provenance: String?,
) {
    fun kilogramsOrNull(): Double? {
        val rawValue = raw ?: return null
        val divisorValue = divisor ?: return null
        if (rawValue <= 0L || divisorValue <= 0L) return null
        val exact = BigDecimal.valueOf(rawValue)
            .divide(BigDecimal.valueOf(divisorValue), 12, RoundingMode.HALF_UP)
        val value = exact.toDouble()
        return value.takeIf { it.isFinite() && it > 0.0 }
    }
}

data class RemoteObservation(
    val sessionId: String?,
    val contractVersion: Int,
    val status: String?,
    val quality: String?,
    val qualityVersion: Int?,
    val startedAt: Instant?,
    val selectedFrameSequence: Long?,
    val selectionPolicyVersion: Int,
    val versions: ObservationVersions,
    val weight: SourceWeight?,
    val opaqueBlockA: List<Int>? = null,
    val opaqueBlockB: List<Int>? = null,
    val impedances: List<Double>? = null,
)

data class ObservationPage(
    val observations: List<RemoteObservation>,
    /** Opaque server cursor. Android stores and returns it without decoding or constructing it. */
    val nextCursor: String?,
    val versions: ObservationVersions,
    val sourceState: PageSourceState,
)

data class WeightProjection(
    val sourceSessionId: String,
    val clientRecordId: String,
    val clientRecordVersion: Long,
    val contractVersion: Int,
    val selectionPolicyVersion: Int,
    val derivationVersion: Int?,
    val weightKg: Double,
    val observedAt: Instant,
    val sourceQuality: String,
    val derivation: DerivationResult? = null,
)

sealed interface ObservationValidation {
    data class Valid(
        val projection: WeightProjection,
        val impedances: List<Double>? = null,
    ) : ObservationValidation
    data class Invalid(
        val projection: WeightProjection,
        val errorCode: String,
        val errorMessage: String,
    ) : ObservationValidation
}

/** Validates the narrow weight-only import boundary before any Health Connect write. */
object ObservationValidator {
    fun validate(observation: RemoteObservation): ObservationValidation {
        val sessionId = observation.sessionId
        val projection = WeightProjection(
            sourceSessionId = sessionId.orEmpty().ifBlank { INVALID_SESSION_ID },
            clientRecordId = clientRecordId(sessionId ?: INVALID_SESSION_ID),
            clientRecordVersion = WEIGHT_PROJECTION_VERSION.toLong(),
            contractVersion = observation.contractVersion,
            selectionPolicyVersion = observation.selectionPolicyVersion,
            derivationVersion = null,
            weightKg = 0.0,
            observedAt = observation.startedAt ?: Instant.EPOCH,
            sourceQuality = observation.quality.orEmpty(),
        )

        fun invalid(code: String, message: String): ObservationValidation.Invalid =
            ObservationValidation.Invalid(projection, code, message)

        if (observation.contractVersion != OBSERVATION_CONTRACT_VERSION) {
            return invalid("unsupported_contract", "Observation contract version is not supported")
        }
        if (sessionId.isNullOrBlank() || !SESSION_ID_PATTERN.matches(sessionId)) {
            return invalid("invalid_session_id", "Observation session ID is missing or malformed")
        }
        if (observation.status != "complete") {
            return invalid("ineligible_status", "Only completed Linux sessions can be projected")
        }
        if (observation.quality != null && observation.quality !in ALLOWED_QUALITY) {
            return invalid("invalid_quality", "Observation quality is not recognized")
        }
        if (observation.qualityVersion != QUALITY_VERSION) {
            return invalid("unsupported_quality_version", "Observation quality version is not supported")
        }
        if (observation.selectionPolicyVersion != WEIGHT_SELECTION_POLICY_VERSION) {
            return invalid("unsupported_selection_policy", "Weight selection policy is not supported")
        }
        if (observation.selectedFrameSequence == null) {
            return invalid("no_safe_selection", "Linux completed the session without a safe selected frame")
        }
        val weight = observation.weight
            ?: return invalid("missing_weight", "The Linux selected frame has no source weight")
        if (weight.unit != "kg") {
            return invalid("unsupported_weight_unit", "Only the source-declared kg weight is supported")
        }
        if (weight.provenance.isNullOrBlank()) {
            return invalid("missing_weight_provenance", "The source weight has no provenance")
        }
        val kilograms = weight.kilogramsOrNull()
            ?: return invalid("invalid_weight", "The source weight is not a positive finite value")
        if (kilograms > MAX_WEIGHT_KG) {
            return invalid("weight_out_of_range", "The source weight exceeds the supported import range")
        }
        val observedAt = observation.startedAt
            ?: return invalid("missing_observed_at", "The source observation has no timestamp")

        val impedances = observation.impedances
            ?: if (observation.opaqueBlockA != null && observation.opaqueBlockB != null) {
                DerivationV1.mapOpaqueBlocksToImpedances(
                    observation.opaqueBlockA,
                    observation.opaqueBlockB,
                )
            } else {
                null
            }

        return ObservationValidation.Valid(
            projection = projection.copy(
                sourceSessionId = sessionId,
                weightKg = kilograms,
                observedAt = observedAt,
                sourceQuality = observation.quality ?: "indeterminate",
            ),
            impedances = impedances,
        )
    }

    fun clientRecordId(sourceSessionId: String): String =
        "tracky-linux-weight-v$WEIGHT_PROJECTION_VERSION-${sha256(sourceSessionId).take(32)}"

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8))
        .joinToString(separator = "") { byte -> "%02x".format(byte) }

    private const val INVALID_SESSION_ID = "invalid-session"
    private const val MAX_WEIGHT_KG = 1000.0
    private val SESSION_ID_PATTERN = Regex("[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
    private val ALLOWED_QUALITY = setOf("accepted", "contact_failed", "indeterminate")
}

class ObservationContractException(message: String) : Exception(message)

class SyncTransportException(
    val retryable: Boolean,
    val code: String,
    message: String,
) : Exception(message)

sealed interface SyncRunResult {
    data class Success(
        val imported: Int,
        val alreadyTerminal: Int,
        val quarantined: Int,
    ) : SyncRunResult

    data class Retry(val code: String) : SyncRunResult
    data class Failure(val code: String) : SyncRunResult
    data object NeedsConfiguration : SyncRunResult
    data object HealthConnectUnavailable : SyncRunResult
    data object HealthConnectPermissionsMissing : SyncRunResult
}
