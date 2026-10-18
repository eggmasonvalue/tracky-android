package dev.eggmasonvalue.tracky.core.data

import android.content.Context
import java.time.Instant

/** Small, non-sensitive status record used to make background work actionable. */
class DiagnosticsRepository(context: Context) {
    private val preferences = context.applicationContext.getSharedPreferences(
        PREFERENCES,
        Context.MODE_PRIVATE,
    )

    fun save(status: String, message: String) {
        preferences.edit()
            .putString(KEY_STATUS, status.take(MAX_VALUE_LENGTH))
            .putString(KEY_MESSAGE, message.take(MAX_VALUE_LENGTH))
            .putLong(KEY_AT, Instant.now().toEpochMilli())
            .apply()
    }

    fun read(): SyncDiagnostics? {
        val status = preferences.getString(KEY_STATUS, null) ?: return null
        val message = preferences.getString(KEY_MESSAGE, null) ?: return null
        val at = preferences.getLong(KEY_AT, 0L).takeIf { it > 0L }?.let(Instant::ofEpochMilli)
        return SyncDiagnostics(status, message, at)
    }

    companion object {
        private const val PREFERENCES = "tracky_sync_diagnostics"
        private const val KEY_STATUS = "status"
        private const val KEY_MESSAGE = "message"
        private const val KEY_AT = "at_epoch_ms"
        private const val MAX_VALUE_LENGTH = 256
    }
}

data class SyncDiagnostics(
    val status: String,
    val message: String,
    val at: Instant?,
)
