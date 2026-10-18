package dev.eggmasonvalue.tracky.ui

import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import dev.eggmasonvalue.tracky.ui.model.BridgeUiState
import dev.eggmasonvalue.tracky.ui.theme.TrackyTheme

@Preview(name = "Bridge onboarding", showBackground = true)
@Composable
private fun BridgeOnboardingPreview() {
    TrackyTheme(dynamicColor = false) {
        BridgeApp(
            state = BridgeUiState(isRationaleEntry = true),
            onAction = {},
        )
    }
}

@Preview(name = "Bridge configured", showBackground = true)
@Composable
private fun BridgeConfiguredPreview() {
    TrackyTheme(dynamicColor = false) {
        BridgeApp(
            state = BridgeUiState(
                healthConnectAvailable = true,
                healthConnectAuthorized = true,
                latestHeightCm = 178.0,
                configured = true,
                endpoint = "https://appliance.example",
                diagnosticsStatus = "success",
                diagnosticsMessage = "Imported 1; quarantined 0; already settled 0",
            ),
            onAction = {},
        )
    }
}
