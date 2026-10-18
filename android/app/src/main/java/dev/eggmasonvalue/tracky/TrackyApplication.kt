package dev.eggmasonvalue.tracky

import android.app.Application
import dev.eggmasonvalue.tracky.core.data.DiagnosticsRepository
import dev.eggmasonvalue.tracky.core.data.RoomImportLedger
import dev.eggmasonvalue.tracky.core.data.TrackyDatabase
import dev.eggmasonvalue.tracky.core.healthconnect.HealthConnectManager
import dev.eggmasonvalue.tracky.core.sync.HttpObservationTransport
import dev.eggmasonvalue.tracky.core.sync.SecureSyncConfigStore
import dev.eggmasonvalue.tracky.core.sync.SyncRunner
import dev.eggmasonvalue.tracky.core.sync.SyncRunResult
import dev.eggmasonvalue.tracky.core.sync.SyncScheduler
import java.time.Clock
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class TrackyApplication : Application() {
    lateinit var database: TrackyDatabase
        private set
    lateinit var importLedger: RoomImportLedger
        private set
    lateinit var configStore: SecureSyncConfigStore
        private set
    lateinit var diagnostics: DiagnosticsRepository
        private set
    lateinit var healthConnectManager: HealthConnectManager
        private set
    lateinit var syncRunner: SyncRunner
        private set
    private val syncMutex = Mutex()

    suspend fun runSerializedSync(): SyncRunResult = syncMutex.withLock { syncRunner.run() }

    override fun onCreate() {
        super.onCreate()
        retireLegacyState()
        val clock = Clock.systemUTC()
        database = TrackyDatabase.build(this)
        importLedger = RoomImportLedger(database)
        configStore = SecureSyncConfigStore(this)
        diagnostics = DiagnosticsRepository(this)
        healthConnectManager = HealthConnectManager(this, clock)
        syncRunner = SyncRunner(
            configSource = configStore,
            ledger = importLedger,
            transport = HttpObservationTransport(),
            healthConnect = healthConnectManager,
            clock = clock,
        )
        SyncScheduler.schedulePeriodicSync(this)
    }

    /** Retire the old evidence/profile/token state without importing it into the projection. */
    private fun retireLegacyState() {
        deleteDatabase("tracky.db")
        getSharedPreferences("tracky_sync_settings", MODE_PRIVATE).edit().clear().apply()
        getSharedPreferences("tracky_user_profile", MODE_PRIVATE).edit().clear().apply()
    }
}
