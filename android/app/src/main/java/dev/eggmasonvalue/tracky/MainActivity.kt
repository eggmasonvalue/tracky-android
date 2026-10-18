package dev.eggmasonvalue.tracky

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.health.connect.client.PermissionController
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.LaunchedEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.fillMaxSize
import dev.eggmasonvalue.tracky.core.healthconnect.HealthConnectManager
import dev.eggmasonvalue.tracky.ui.BridgeApp
import dev.eggmasonvalue.tracky.ui.theme.TrackyTheme
import kotlinx.coroutines.flow.collect

/** Health Connect rationale/onboarding entry point; it is intentionally not a launcher activity. */
class MainActivity : ComponentActivity() {
    private val viewModel: BridgeViewModel by viewModels {
        val application = application as TrackyApplication
        BridgeViewModel.Factory(
            context = application,
            configStore = application.configStore,
            healthConnectManager = application.healthConnectManager,
            diagnostics = application.diagnostics,
        )
    }

    private val healthPermissionLauncher = registerForActivityResult(
        PermissionController.createRequestPermissionResultContract(),
    ) {
        viewModel.refresh()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        viewModel.setRationaleEntry(
            intent?.action == "androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE",
        )
        setContent {
            val state by viewModel.uiState.collectAsStateWithLifecycle()
            LaunchedEffect(viewModel) {
                viewModel.effects.collect { effect ->
                    if (effect is BridgeViewModel.HostEffect.RequestHealthPermissions) {
                        healthPermissionLauncher.launch(HealthConnectManager.REQUIRED_PERMISSIONS)
                    }
                }
            }
            TrackyTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    BridgeApp(
                        state = state,
                        onAction = viewModel::onAction,
                    )
                }
            }
        }
    }
}
