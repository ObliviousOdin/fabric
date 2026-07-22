package io.github.obliviousodin.fabric.mobile

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.obliviousodin.fabric.mobile.core.supportsGatewayMethod
import io.github.obliviousodin.fabric.mobile.ui.ChatScreen
import io.github.obliviousodin.fabric.mobile.ui.GatewayListScreen
import io.github.obliviousodin.fabric.mobile.ui.SessionsScreen
import io.github.obliviousodin.fabric.mobile.ui.SocialStudioScreen
import io.github.obliviousodin.fabric.mobile.ui.theme.FabricTheme

class MainActivity : ComponentActivity() {
    private val viewModel: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handlePairingIntent(intent)
        setContent {
            FabricTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    FabricRoot(viewModel)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handlePairingIntent(intent)
    }

    private fun handlePairingIntent(intent: Intent?) {
        if (intent?.action == Intent.ACTION_VIEW) {
            viewModel.receivePairingUrl(intent.dataString)
        }
    }

    override fun onStart() {
        super.onStart()
        viewModel.onForeground()
    }

    override fun onStop() {
        if (!isChangingConfigurations) viewModel.onBackground()
        super.onStop()
    }
}

@Composable
private fun FabricRoot(viewModel: AppViewModel) {
    val phase by viewModel.phase.collectAsState()
    val screen by viewModel.screen.collectAsState()
    val activeGatewayId by viewModel.activeGatewayId.collectAsState()
    val connectError by viewModel.connectError.collectAsState()
    val capabilityNegotiation by viewModel.capabilityNegotiation.collectAsState()

    if (activeGatewayId == null) {
        GatewayListScreen(viewModel)
        return
    }

    Column(modifier = Modifier.fillMaxSize()) {
        if (phase != ConnectionPhase.Connected) {
            Surface(color = FabricTheme.extras.warning.copy(alpha = 0.1f)) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    if (phase == ConnectionPhase.Reconnecting) {
                        CircularProgressIndicator(modifier = Modifier.size(20.dp))
                    }
                    Text(
                        text = if (phase == ConnectionPhase.Reconnecting) {
                            "Reconnecting to Fabric…"
                        } else {
                            connectError ?: "Fabric is offline."
                        },
                        modifier = Modifier.weight(1f),
                    )
                    if (phase == ConnectionPhase.Disconnected) {
                        Button(onClick = viewModel::retryConnection) { Text("Retry") }
                        Button(onClick = viewModel::disconnect) { Text("Servers") }
                    }
                }
            }
        }
        when (val current = screen) {
            is Screen.Sessions -> SessionsScreen(
                viewModel = viewModel,
                enabled = phase == ConnectionPhase.Connected,
                capabilityNegotiation = capabilityNegotiation,
            )
            is Screen.Social -> SocialStudioScreen(
                viewModel = viewModel,
                enabled = phase == ConnectionPhase.Connected,
            )
            is Screen.Chat -> ChatScreen(
                controller = current.controller,
                title = current.title,
                onBack = viewModel::backToSessions,
                supportsMethod = { method ->
                    capabilityNegotiation.supportsGatewayMethod(method)
                },
            )
        }
    }
}
