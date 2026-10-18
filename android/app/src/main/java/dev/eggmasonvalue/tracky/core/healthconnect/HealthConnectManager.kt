package dev.eggmasonvalue.tracky.core.healthconnect

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.BasalMetabolicRateRecord
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.BoneMassRecord
import androidx.health.connect.client.records.HeightRecord
import androidx.health.connect.client.records.LeanBodyMassRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.records.metadata.Device
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import androidx.health.connect.client.units.Length
import androidx.health.connect.client.units.Mass
import androidx.health.connect.client.units.Percentage
import androidx.health.connect.client.units.Power
import dev.eggmasonvalue.tracky.core.sync.HealthConnectProjector
import dev.eggmasonvalue.tracky.core.sync.HeightObservation
import dev.eggmasonvalue.tracky.core.sync.WeightProjection
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset

class HealthConnectManager(
    context: Context,
    private val clock: Clock = Clock.systemUTC(),
) : HealthConnectProjector {
    private val appContext = context.applicationContext

    private val client: HealthConnectClient?
        get() = if (isAvailable()) HealthConnectClient.getOrCreate(appContext) else null

    override fun isAvailable(): Boolean =
        HealthConnectClient.getSdkStatus(appContext) == HealthConnectClient.SDK_AVAILABLE

    override suspend fun hasRequiredPermissions(): Boolean {
        val healthConnect = client ?: return false
        return healthConnect.permissionController
            .getGrantedPermissions()
            .containsAll(REQUIRED_PERMISSIONS)
    }

    suspend fun hasHeightReadPermission(): Boolean {
        val healthConnect = client ?: return false
        return healthConnect.permissionController
            .getGrantedPermissions()
            .contains(HEIGHT_READ_PERMISSION)
    }

    override suspend fun readLatestApplicableHeight(): HeightObservation? {
        val healthConnect = client ?: throw HeightReadException("Health Connect is unavailable")
        if (!hasHeightReadPermission()) {
            throw HeightReadException("Health Connect height read permission is not granted")
        }
        val now = clock.instant()
        val records = buildList {
            var pageToken: String? = null
            do {
                val response = healthConnect.readRecords(
                    ReadRecordsRequest(
                        recordType = HeightRecord::class,
                        timeRangeFilter = TimeRangeFilter.before(now),
                        ascendingOrder = false,
                        pageSize = HEIGHT_PAGE_SIZE,
                        pageToken = pageToken,
                    ),
                )
                addAll(response.records)
                pageToken = response.pageToken?.takeIf { it.isNotBlank() }
            } while (pageToken != null)
        }
        return records
            .asSequence()
            .filter { !it.time.isAfter(now) }
            .maxByOrNull(HeightRecord::time)
            ?.let { record ->
                HeightObservation(
                    recordedAt = record.time,
                    heightMeters = record.height.inMeters(),
                )
            }
    }

    override suspend fun insertWeight(projection: WeightProjection): String {
        val healthConnect = client
            ?: throw IllegalStateException("Health Connect is not available")
        val records = buildRecords(projection)
        val response = healthConnect.insertRecords(records)
        return response.recordIdsList.firstOrNull()
            ?: throw IllegalStateException("Health Connect returned no record ID")
    }

    companion object {
        fun buildRecords(projection: WeightProjection): List<Record> {
            val device = Device(
                manufacturer = "Tracky",
                model = "Linux acquisition projection",
                type = Device.TYPE_SCALE,
            )
            return buildList {
                add(
                    WeightRecord(
                        time = projection.observedAt,
                        zoneOffset = ZoneOffset.UTC,
                        weight = Mass.kilograms(projection.weightKg),
                        metadata = Metadata(
                            clientRecordId = projection.clientRecordId,
                            clientRecordVersion = projection.clientRecordVersion,
                            device = device,
                            recordingMethod = Metadata.RECORDING_METHOD_ACTIVELY_RECORDED,
                        ),
                    ),
                )
                projection.derivation?.let { derivation ->
                    add(
                        BodyFatRecord(
                            time = projection.observedAt,
                            zoneOffset = ZoneOffset.UTC,
                            percentage = Percentage(derivation.bodyFatPct),
                            metadata = Metadata(
                                clientRecordId = "${projection.clientRecordId}-fat",
                                clientRecordVersion = projection.clientRecordVersion,
                                device = device,
                                recordingMethod = Metadata.RECORDING_METHOD_ACTIVELY_RECORDED,
                            ),
                        ),
                    )
                    add(
                        LeanBodyMassRecord(
                            time = projection.observedAt,
                            zoneOffset = ZoneOffset.UTC,
                            mass = Mass.kilograms(derivation.leanBodyMassKg),
                            metadata = Metadata(
                                clientRecordId = "${projection.clientRecordId}-lbm",
                                clientRecordVersion = projection.clientRecordVersion,
                                device = device,
                                recordingMethod = Metadata.RECORDING_METHOD_ACTIVELY_RECORDED,
                            ),
                        ),
                    )
                    add(
                        BoneMassRecord(
                            time = projection.observedAt,
                            zoneOffset = ZoneOffset.UTC,
                            mass = Mass.kilograms(derivation.boneKg),
                            metadata = Metadata(
                                clientRecordId = "${projection.clientRecordId}-bone",
                                clientRecordVersion = projection.clientRecordVersion,
                                device = device,
                                recordingMethod = Metadata.RECORDING_METHOD_ACTIVELY_RECORDED,
                            ),
                        ),
                    )
                    add(
                        BasalMetabolicRateRecord(
                            time = projection.observedAt,
                            zoneOffset = ZoneOffset.UTC,
                            basalMetabolicRate = Power.kilocaloriesPerDay(derivation.bmrKcal.toDouble()),
                            metadata = Metadata(
                                clientRecordId = "${projection.clientRecordId}-bmr",
                                clientRecordVersion = projection.clientRecordVersion,
                                device = device,
                                recordingMethod = Metadata.RECORDING_METHOD_ACTIVELY_RECORDED,
                            ),
                        ),
                    )
                }
            }
        }

        val HEIGHT_READ_PERMISSION = HealthPermission.getReadPermission(HeightRecord::class)
        val REQUIRED_PERMISSIONS = setOf(
            HEIGHT_READ_PERMISSION,
            HealthPermission.PERMISSION_READ_HEALTH_DATA_HISTORY,
            HealthPermission.getWritePermission(WeightRecord::class),
            HealthPermission.getWritePermission(BodyFatRecord::class),
            HealthPermission.getWritePermission(LeanBodyMassRecord::class),
            HealthPermission.getWritePermission(BoneMassRecord::class),
            HealthPermission.getWritePermission(BasalMetabolicRateRecord::class),
        )

        private const val HEIGHT_PAGE_SIZE = 1000
    }
}

class HeightReadException(message: String) : Exception(message)

private fun Length.inMeters(): Double = this.inMeters
