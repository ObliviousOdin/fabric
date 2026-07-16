package io.github.obliviousodin.fabric.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import io.github.obliviousodin.fabric.mobile.AppViewModel
import io.github.obliviousodin.fabric.mobile.ConnectionPhase
import io.github.obliviousodin.fabric.mobile.core.ConnectionSettings
import io.github.obliviousodin.fabric.mobile.core.GatewayApi
import kotlinx.coroutines.launch

/**
 * First-run / reconnect screen: gateway URL + session token, with an
 * explicit reachability test against the public `/api/status` probe.
 */
@Composable
fun ConnectScreen(viewModel: AppViewModel) {
    val phase by viewModel.phase.collectAsState()
    val connectError by viewModel.connectError.collectAsState()
    val scope = rememberCoroutineScope()

    val saved = viewModel.savedSettings
    var url by rememberSaveable { mutableStateOf(saved?.baseUrl ?: "") }
    var token by rememberSaveable { mutableStateOf(saved?.token ?: "") }
    var probeResult by remember { mutableStateOf<String?>(null) }
    var probing by remember { mutableStateOf(false) }

    val urlValid = url.trim().startsWith("http://") || url.trim().startsWith("https://")
    val canConnect = urlValid && token.isNotBlank() && phase != ConnectionPhase.Connecting

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Fabric", style = MaterialTheme.typography.headlineLarge)
        Text(
            "Run `fabric serve` on the machine that hosts your Fabric profile, " +
                "then enter its URL and dashboard session token. LAN, Tailscale, " +
                "and SSH-tunnel addresses all work.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        OutlinedTextField(
            value = url,
            onValueChange = { url = it },
            label = { Text("Gateway URL") },
            placeholder = { Text("http://my-machine:9119") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        OutlinedTextField(
            value = token,
            onValueChange = { token = it },
            label = { Text("Session token") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth(),
        )

        OutlinedButton(
            onClick = {
                probing = true
                probeResult = null
                scope.launch {
                    probeResult = try {
                        val status = GatewayApi.probeStatus(url.trim())
                        if (status.authRequired) {
                            "Reachable, but OAuth-gated — token auth will be rejected."
                        } else {
                            "Gateway reachable."
                        }
                    } catch (e: Exception) {
                        "Unreachable: ${e.message ?: e}"
                    } finally {
                        probing = false
                    }
                }
            },
            enabled = urlValid && !probing,
            modifier = Modifier.fillMaxWidth(),
        ) {
            if (probing) {
                CircularProgressIndicator(modifier = Modifier.padding(4.dp))
            } else {
                Text("Test connection")
            }
        }

        probeResult?.let {
            Text(
                it,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        Button(
            onClick = {
                viewModel.connect(ConnectionSettings(url.trim().trimEnd('/'), token.trim()))
            },
            enabled = canConnect,
            modifier = Modifier.fillMaxWidth(),
        ) {
            if (phase == ConnectionPhase.Connecting) {
                CircularProgressIndicator(modifier = Modifier.padding(4.dp))
            } else {
                Text("Connect")
            }
        }

        connectError?.let {
            Text(
                it,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}
