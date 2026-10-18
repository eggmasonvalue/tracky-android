package dev.eggmasonvalue.tracky.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import dev.eggmasonvalue.tracky.ui.model.BridgeAction
import dev.eggmasonvalue.tracky.ui.model.BridgeUiState
import java.text.NumberFormat

@Composable
fun BridgeApp(
    state: BridgeUiState,
    onAction: (BridgeAction) -> Unit,
    modifier: Modifier = Modifier,
) {
    var endpoint by rememberSaveable(state.endpoint) { mutableStateOf(state.endpoint.orEmpty()) }
    // Bearer tokens must not enter the saved-instance-state bundle.
    var token by remember { mutableStateOf("") }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .windowInsetsPadding(androidx.compose.foundation.layout.WindowInsets.safeDrawing)
            .padding(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Tracky bridge", style = MaterialTheme.typography.headlineLarge)
        Text(
            "A background projection from the Linux acquisition appliance to Health Connect. " +
                "This app does not scan Bluetooth or start weigh-ins.",
            style = MaterialTheme.typography.bodyLarge,
        )
        if (state.isRationaleEntry) {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer)) {
                Text(
                    "Tracky reads height only to support future approved algorithms and writes weight observations received from Linux. " +
                        "It never writes height, body fat, lean mass, or other unsupported body-composition values.",
                    modifier = Modifier.padding(16.dp),
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }

        Card {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Health Connect", style = MaterialTheme.typography.titleLarge)
                Text(
                    when {
                        !state.healthConnectAvailable -> "Health Connect is unavailable. Install or update it, then return through its permission screen."
                        state.healthConnectAuthorized -> "Height history read and weight write access is granted."
                        else -> "Permission is required to read height history and write weight projections."
                    },
                    style = MaterialTheme.typography.bodyMedium,
                )
                if (state.healthConnectAuthorized) {
                    state.heightReadError?.let { error ->
                        Text(
                            error,
                            color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    } ?: Text(
                        state.latestHeightCm?.let {
                            "Latest applicable height: ${formatCentimeters(it)} cm" +
                                (state.latestHeightAt?.let { at -> " • $at" } ?: "")
                        } ?: "No applicable HeightRecord is available. Tracky does not invent or write height.",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                } else {
                    Button(onClick = { onAction(BridgeAction.RequestHealthPermissions) }) {
                        Text("Connect Health Connect")
                    }
                }
            }
        }

        Card {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Secure Linux endpoint", style = MaterialTheme.typography.titleLarge)
                Text(
                    "Use the HTTPS base URL for the authenticated observation endpoint. The bearer token is encrypted with Android Keystore and is never shown or logged.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                OutlinedTextField(
                    value = endpoint,
                    onValueChange = { endpoint = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("HTTPS endpoint") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                )
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Bearer token") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                )
                state.configurationError?.let { error ->
                    Text(error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        onClick = {
                            onAction(BridgeAction.SaveConfiguration(endpoint.trim(), token))
                            token = ""
                        },
                        enabled = endpoint.isNotBlank() && token.isNotBlank(),
                    ) {
                        Text("Save and sync")
                    }
                    TextButton(onClick = { onAction(BridgeAction.SyncNow) }, enabled = state.configured) {
                        Text("Sync now")
                    }
                }
            }
        }

        Card {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Background diagnostics", style = MaterialTheme.typography.titleLarge)
                Text(
                    state.diagnosticsMessage ?: "No sync has run yet. WorkManager retries network and Health Connect failures with backoff.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                state.diagnosticsStatus?.let { Text("Status: $it", style = MaterialTheme.typography.labelLarge) }
                TextButton(onClick = { onAction(BridgeAction.Refresh) }) { Text("Refresh status") }
            }
        }
        Spacer(Modifier.height(8.dp))
    }
}

private fun formatCentimeters(value: Double): String = NumberFormat.getNumberInstance().apply {
    minimumFractionDigits = 1
    maximumFractionDigits = 1
}.format(value)
