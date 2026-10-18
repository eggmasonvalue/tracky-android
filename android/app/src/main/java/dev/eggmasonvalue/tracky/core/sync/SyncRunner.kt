package dev.eggmasonvalue.tracky.core.sync

import dev.eggmasonvalue.tracky.core.data.ImportDisposition
import dev.eggmasonvalue.tracky.core.data.ImportLedger
import dev.eggmasonvalue.tracky.core.derivation.DerivationInput
import dev.eggmasonvalue.tracky.core.derivation.DerivationV1
import java.time.Clock
import java.time.Duration
import java.time.Instant
import kotlinx.coroutines.CancellationException

interface HealthConnectProjector {
    fun isAvailable(): Boolean
    suspend fun hasRequiredPermissions(): Boolean
    suspend fun readLatestApplicableHeight(): HeightObservation?
    suspend fun insertWeight(projection: WeightProjection): String
}

/** Coordinates one page; the cursor is committed only after every item is imported or quarantined. */
class SyncRunner(
    private val configSource: SyncConfigSource,
    private val ledger: ImportLedger,
    private val transport: ObservationTransport,
    private val healthConnect: HealthConnectProjector,
    private val clock: Clock = Clock.systemUTC(),
) {
    suspend fun run(): SyncRunResult {
        val config = configSource.load() ?: return SyncRunResult.NeedsConfiguration
        if (!healthConnect.isAvailable()) return SyncRunResult.HealthConnectUnavailable
        if (!healthConnect.hasRequiredPermissions()) {
            return SyncRunResult.HealthConnectPermissionsMissing
        }

        val cursor = ledger.cursor()
        val page = try {
            transport.fetch(config, cursor)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: SyncTransportException) {
            return if (error.retryable) {
                SyncRunResult.Retry(error.code)
            } else {
                SyncRunResult.Failure(error.code)
            }
        } catch (_: Throwable) {
            return SyncRunResult.Retry("transport_failed")
        }

        if (page.sourceState.kind == "retryable") {
            return SyncRunResult.Retry(page.sourceState.code ?: "source_state_retry")
        }

        var imported = 0
        var alreadyTerminal = 0
        var quarantined = 0
        for (observation in page.observations) {
            val identity = identityFor(observation)
            val existing = ledger.find(identity.clientRecordId)
            if (existing != null &&
                existing.clientRecordVersion >= identity.clientRecordVersion &&
                existing.disposition != ImportDisposition.PENDING
            ) {
                alreadyTerminal++
                continue
            }

            when (val validation = ObservationValidator.validate(observation)) {
                is ObservationValidation.Invalid -> {
                    ledger.markQuarantined(
                        projection = validation.projection,
                        now = clock.instant(),
                        errorCode = validation.errorCode,
                        errorMessage = validation.errorMessage,
                    )
                    quarantined++
                }
                is ObservationValidation.Valid -> {
                    var projection = validation.projection
                    val impedances = validation.impedances
                    if (impedances != null && projection.derivation == null) {
                        val heightObs = runCatching { healthConnect.readLatestApplicableHeight() }.getOrNull()
                        if (heightObs != null) {
                            val derivation = DerivationV1.derive(
                                DerivationInput(
                                    heightCm = heightObs.heightCentimeters,
                                    weightKg = projection.weightKg,
                                    impedances = impedances,
                                ),
                            )
                            if (derivation != null) {
                                projection = projection.copy(
                                    derivation = derivation,
                                    derivationVersion = derivation.derivationVersion,
                                )
                            }
                        }
                    }
                    ledger.markPending(projection, clock.instant())
                    val healthConnectId = try {
                        healthConnect.insertWeight(projection)
                    } catch (cancelled: CancellationException) {
                        throw cancelled
                    } catch (_: Throwable) {
                        ledger.markAttemptFailed(
                            clientRecordId = projection.clientRecordId,
                            now = clock.instant(),
                            errorCode = "health_connect_write_failed",
                            errorMessage = "Health Connect did not accept the weight projection",
                            retryAfter = RETRY_AFTER,
                        )
                        return SyncRunResult.Retry("health_connect_write_failed")
                    }
                    ledger.markImported(
                        clientRecordId = projection.clientRecordId,
                        healthConnectRecordId = healthConnectId,
                        now = clock.instant(),
                    )
                    imported++
                }
            }
        }

        // This is deliberately last. A crash before this line repeats the page safely via the
        // clientRecordId/clientRecordVersion pair and the ledger's terminal disposition.
        ledger.advanceCursor(page.nextCursor)
        return SyncRunResult.Success(imported, alreadyTerminal, quarantined)
    }

    private fun identityFor(observation: RemoteObservation): WeightProjection {
        val sourceId = observation.sessionId.orEmpty().ifBlank { "invalid-session" }
        return WeightProjection(
            sourceSessionId = sourceId,
            clientRecordId = ObservationValidator.clientRecordId(sourceId),
            clientRecordVersion = WEIGHT_PROJECTION_VERSION.toLong(),
            contractVersion = observation.contractVersion,
            selectionPolicyVersion = observation.selectionPolicyVersion,
            derivationVersion = null,
            weightKg = 0.0,
            observedAt = Instant.EPOCH,
            sourceQuality = observation.quality.orEmpty(),
        )
    }

    private companion object {
        val RETRY_AFTER: Duration = Duration.ofSeconds(30)
    }
}
