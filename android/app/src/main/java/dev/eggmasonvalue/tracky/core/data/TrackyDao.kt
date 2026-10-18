package dev.eggmasonvalue.tracky.core.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
internal interface TrackyDao {
    @Query("SELECT * FROM import_ledger WHERE client_record_id = :clientRecordId LIMIT 1")
    suspend fun findImport(clientRecordId: String): ImportLedgerEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertImport(entry: ImportLedgerEntity)

    @Query("SELECT * FROM sync_state WHERE state_id = :stateId LIMIT 1")
    suspend fun findSyncState(stateId: String): SyncStateEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertSyncState(state: SyncStateEntity)
}
