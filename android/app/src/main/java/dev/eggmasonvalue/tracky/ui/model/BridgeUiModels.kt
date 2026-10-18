package dev.eggmasonvalue.tracky.ui.model

import androidx.compose.runtime.Immutable
@Immutable
data class BridgeUiState(
    val healthConnectAvailable: Boolean = false,
    val healthConnectAuthorized: Boolean = false,
    val latestHeightCm: Double? = null,
    val latestHeightAt: String? = null,
    val heightReadError: String? = null,
    val configured: Boolean = false,
    val endpoint: String? = null,
    val configurationError: String? = null,
    val diagnosticsStatus: String? = null,
    val diagnosticsMessage: String? = null,
    val isRationaleEntry: Boolean = false,
)

@Immutable
sealed interface BridgeAction {
    data object RequestHealthPermissions : BridgeAction
    data object SyncNow : BridgeAction
    data object Refresh : BridgeAction
    data class SaveConfiguration(val endpoint: String, val token: String) : BridgeAction
}
