package dev.eggmasonvalue.tracky.core.data

import java.time.Instant

/** Terminal or in-flight disposition for one source observation projection. */
enum class ImportDisposition {
    PENDING,
    IMPORTED,
    QUARANTINED,
}

data class ImportLedgerEntry(
    val clientRecordId: String,
    val sourceSessionId: String,
    val clientRecordVersion: Long,
    val contractVersion: Int,
    val selectionPolicyVersion: Int,
    val derivationVersion: Int?,
    val disposition: ImportDisposition,
    val healthConnectRecordId: String?,
    val attemptCount: Int,
    val lastAttemptAt: Instant?,
    val nextRetryAt: Instant?,
    val lastErrorCode: String?,
    val lastErrorMessage: String?,
    val updatedAt: Instant,
)

internal fun ImportLedgerEntity.toDomain(): ImportLedgerEntry = ImportLedgerEntry(
    clientRecordId = clientRecordId,
    sourceSessionId = sourceSessionId,
    clientRecordVersion = clientRecordVersion,
    contractVersion = contractVersion,
    selectionPolicyVersion = selectionPolicyVersion,
    derivationVersion = derivationVersion,
    disposition = disposition,
    healthConnectRecordId = healthConnectRecordId,
    attemptCount = attemptCount,
    lastAttemptAt = lastAttemptEpochMs?.let(Instant::ofEpochMilli),
    nextRetryAt = nextRetryEpochMs?.let(Instant::ofEpochMilli),
    lastErrorCode = lastErrorCode,
    lastErrorMessage = lastErrorMessage,
    updatedAt = Instant.ofEpochMilli(updatedAtEpochMs),
)

internal fun ImportLedgerEntry.toEntity(): ImportLedgerEntity = ImportLedgerEntity(
    clientRecordId = clientRecordId,
    sourceSessionId = sourceSessionId,
    clientRecordVersion = clientRecordVersion,
    contractVersion = contractVersion,
    selectionPolicyVersion = selectionPolicyVersion,
    derivationVersion = derivationVersion,
    disposition = disposition,
    healthConnectRecordId = healthConnectRecordId,
    attemptCount = attemptCount,
    lastAttemptEpochMs = lastAttemptAt?.toEpochMilli(),
    nextRetryEpochMs = nextRetryAt?.toEpochMilli(),
    lastErrorCode = lastErrorCode,
    lastErrorMessage = lastErrorMessage,
    updatedAtEpochMs = updatedAt.toEpochMilli(),
)
