package io.github.obliviousodin.fabric.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import io.github.obliviousodin.fabric.mobile.ui.ChatScreen
import io.github.obliviousodin.fabric.mobile.ui.ConnectScreen
import io.github.obliviousodin.fabric.mobile.ui.SessionsScreen
import io.github.obliviousodin.fabric.mobile.ui.theme.FabricTheme

class MainActivity : ComponentActivity() {
    private val viewModel: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            FabricTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    FabricRoot(viewModel)
                }
            }
        }
    }
}

@Composable
private fun FabricRoot(viewModel: AppViewModel) {
    val phase by viewModel.phase.collectAsState()
    val screen by viewModel.screen.collectAsState()

    when (phase) {
        ConnectionPhase.Disconnected, ConnectionPhase.Connecting -> {
            ConnectScreen(viewModel)
        }

        ConnectionPhase.Connected -> when (val current = screen) {
            is Screen.Sessions -> SessionsScreen(viewModel)
            is Screen.Chat -> ChatScreen(
                controller = current.controller,
                title = current.title,
                onBack = viewModel::backToSessions,
            )
        }
    }
}
