package dev.eggmasonvalue.tracky.core.data

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "import_ledger",
    indices = [
        Index(value = ["source_session_id", "client_record_version"], unique = true),
        Index(value = ["disposition"]),
    ],
)
data class ImportLedgerEntity(
    @PrimaryKey
    @ColumnInfo(name = "client_record_id")
    val clientRecordId: String,
    @ColumnInfo(name = "source_session_id")
    val sourceSessionId: String,
    @ColumnInfo(name = "client_record_version")
    val clientRecordVersion: Long,
    @ColumnInfo(name = "contract_version")
    val contractVersion: Int,
    @ColumnInfo(name = "selection_policy_version")
    val selectionPolicyVersion: Int,
    @ColumnInfo(name = "derivation_version")
    val derivationVersion: Int?,
    @ColumnInfo(name = "disposition")
    val disposition: ImportDisposition,
    @ColumnInfo(name = "health_connect_record_id")
    val healthConnectRecordId: String?,
    @ColumnInfo(name = "attempt_count")
    val attemptCount: Int,
    @ColumnInfo(name = "last_attempt_epoch_ms")
    val lastAttemptEpochMs: Long?,
    @ColumnInfo(name = "next_retry_epoch_ms")
    val nextRetryEpochMs: Long?,
    @ColumnInfo(name = "last_error_code")
    val lastErrorCode: String?,
    @ColumnInfo(name = "last_error_message")
    val lastErrorMessage: String?,
    @ColumnInfo(name = "updated_at_epoch_ms")
    val updatedAtEpochMs: Long,
)

@Entity(tableName = "sync_state")
data class SyncStateEntity(
    @PrimaryKey
    @ColumnInfo(name = "state_id")
    val stateId: String = STATE_ID,
    @ColumnInfo(name = "cursor")
    val cursor: String?,
) {
    companion object {
        const val STATE_ID: String = "linux-observation-cursor"
    }
}
