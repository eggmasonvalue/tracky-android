package dev.eggmasonvalue.tracky.core.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

object SyncScheduler {
    private const val PERIODIC_WORK_NAME = "tracky_observation_sync_periodic_trigger"
    private const val IMMEDIATE_WORK_NAME = "tracky_observation_sync"

    fun schedulePeriodicSync(context: Context) {
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            PERIODIC_WORK_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            periodicRequest(),
        )
    }

    fun triggerImmediateSync(context: Context) {
        WorkManager.getInstance(context).enqueueUniqueWork(
            IMMEDIATE_WORK_NAME,
            ExistingWorkPolicy.KEEP,
            oneTimeRequest(),
        )
    }

    private fun constraints() = Constraints.Builder()
        .setRequiredNetworkType(NetworkType.CONNECTED)
        .build()

    private fun periodicRequest() = PeriodicWorkRequestBuilder<SyncKickoffWorker>(15, TimeUnit.MINUTES)
        .setConstraints(constraints())
        .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
        .build()

    private fun oneTimeRequest() = OneTimeWorkRequestBuilder<SyncWorker>()
        .setConstraints(constraints())
        .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
        .build()
}
