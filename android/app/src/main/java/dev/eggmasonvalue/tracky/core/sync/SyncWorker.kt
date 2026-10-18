package dev.eggmasonvalue.tracky.core.sync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import dev.eggmasonvalue.tracky.TrackyApplication
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout

class SyncWorker(
    context: Context,
    workerParams: WorkerParameters,
) : CoroutineWorker(context, workerParams) {
    override suspend fun doWork(): Result {
        val application = applicationContext as? TrackyApplication
            ?: return Result.failure()
        return try {
            val result = withTimeout(SYNC_TIMEOUT_MILLIS) {
                application.runSerializedSync()
            }
            result.toWorkResult(application)
        } catch (_: TimeoutCancellationException) {
            application.diagnostics.save(
                status = "retry",
                message = "Background sync timed out before a durable cursor update",
            )
            Result.retry()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Throwable) {
            application.diagnostics.save(
                status = "retry",
                message = "Background sync timed out or failed before a durable cursor update",
            )
            Result.retry()
        }
    }

    private fun SyncRunResult.toWorkResult(application: TrackyApplication): Result = when (this) {
        is SyncRunResult.Success -> {
            application.diagnostics.save(
                status = "success",
                message = "Imported $imported; quarantined $quarantined; already settled $alreadyTerminal",
            )
            Result.success()
        }
        is SyncRunResult.Retry -> {
            application.diagnostics.save("retry", "Sync will retry: $code")
            Result.retry()
        }
        is SyncRunResult.Failure -> {
            application.diagnostics.save("configuration_error", "Sync stopped: $code")
            Result.failure()
        }
        SyncRunResult.NeedsConfiguration -> {
            application.diagnostics.save(
                "configuration_required",
                "Configure an HTTPS endpoint and bearer token before syncing",
            )
            Result.failure()
        }
        SyncRunResult.HealthConnectUnavailable -> {
            application.diagnostics.save(
                "health_connect_unavailable",
                "Install or update Health Connect, then open Tracky from its permission screen",
            )
            Result.retry()
        }
        SyncRunResult.HealthConnectPermissionsMissing -> {
            application.diagnostics.save(
                "health_connect_permission_required",
                "Grant Tracky height read and weight write permissions in Health Connect",
            )
            Result.retry()
        }
    }

    private companion object {
        const val SYNC_TIMEOUT_MILLIS: Long = 60_000L
    }
}
