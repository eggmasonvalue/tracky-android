package dev.eggmasonvalue.tracky.core.sync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

/** Periodic work only queues the single unique one-shot sync; it never runs a second runner. */
class SyncKickoffWorker(
    context: Context,
    workerParams: WorkerParameters,
) : CoroutineWorker(context, workerParams) {
    override suspend fun doWork(): Result {
        SyncScheduler.triggerImmediateSync(applicationContext)
        return Result.success()
    }
}
