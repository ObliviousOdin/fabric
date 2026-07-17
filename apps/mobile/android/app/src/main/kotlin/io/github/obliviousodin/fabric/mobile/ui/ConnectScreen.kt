package io.github.obliviousodin.fabric.mobile.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
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
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import io.github.obliviousodin.fabric.mobile.AppViewModel
import io.github.obliviousodin.fabric.mobile.ConnectionPhase
import io.github.obliviousodin.fabric.mobile.core.ConnectionSettings
import io.github.obliviousodin.fabric.mobile.core.GatewayApi
import io.github.obliviousodin.fabric.mobile.core.GatewayAuthMode
import io.github.obliviousodin.fabric.mobile.core.PairingPayload
import kotlinx.coroutines.launch

/**
 * First-run / reconnect screen. Three ways in:
 *
 * 1. **Scan** the pairing QR from `fabric serve --qr` — token QRs connect
 *    immediately; gated QRs drop into the sign-in form.
 * 2. Type a URL + session token (loopback/tunnel gateways).
 * 3. Type a URL + username/password (gated gateways, e.g. a direct
 *    Tailscale bind with the bundled password provider).
 */
@Composable
fun ConnectScreen(viewModel: AppViewModel) {
    val phase by viewModel.phase.collectAsState()
    val connectError by viewModel.connectError.collectAsState()
    val scope = rememberCoroutineScope()

    val saved = viewModel.savedSettings
    var url by rememberSaveable { mutableStateOf(saved?.baseUrl ?: "") }
    var passwordMode by rememberSaveable {
        mutableStateOf(saved?.authMode == GatewayAuthMode.GATED)
    }
    var token by rememberSaveable { mutableStateOf(saved?.token ?: "") }
    var username by rememberSaveable { mutableStateOf(saved?.username ?: "") }
    var password by remember { mutableStateOf("") }
    var providerName by remember { mutableStateOf<String?>(null) }
    var probeResult by remember { mutableStateOf<String?>(null) }
    var probing by remember { mutableStateOf(false) }

    val urlValid = url.trim().startsWith("http://") || url.trim().startsWith("https://")
    val canConnect = urlValid && phase != ConnectionPhase.Connecting &&
        if (passwordMode) username.isNotBlank() && password.isNotEmpty() else token.isNotBlank()

    fun resolveProviderAndConnect(base: String) {
        scope.launch {
            val provider = providerName ?: runCatching {
                viewModel.api.listAuthProviders(base)
                    .firstOrNull { it.supportsPassword }?.name
            }.getOrNull()
            if (provider == null) {
                probeResult = "This gateway offers no password sign-in " +
                    "(OAuth-only gateways are not supported yet)."
                return@launch
            }
            providerName = provider
            viewModel.connectGated(base, provider, username.trim(), password)
        }
    }

    fun connect() {
        val base = url.trim().trimEnd('/')
        if (passwordMode) {
            resolveProviderAndConnect(base)
        } else {
            viewModel.connect(ConnectionSettings(base, token.trim()))
        }
    }

    val scanLauncher = rememberLauncherForActivityResult(ScanContract()) { result ->
        val payload = result.contents?.let(PairingPayload::parse)
        if (payload == null) {
            if (result.contents != null) {
                probeResult = "Scanned code is not a Fabric pairing QR."
            }
            return@rememberLauncherForActivityResult
        }
        url = payload.baseUrl
        if (payload.token != null) {
            passwordMode = false
            token = payload.token
            // Token QRs are complete credentials — connect immediately.
            viewModel.connect(ConnectionSettings(payload.baseUrl, payload.token))
        } else {
            passwordMode = true
            probeResult = "Gateway requires sign-in — enter your username and password."
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Fabric", style = MaterialTheme.typography.headlineLarge)
        Text(
            "Run `fabric serve --qr` on the machine that hosts your Fabric " +
                "profile and scan the QR — or enter its address by hand. " +
                "Tailscale, LAN, and SSH-tunnel addresses all work.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        OutlinedButton(
            onClick = {
                scanLauncher.launch(
                    ScanOptions()
                        .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                        .setPrompt("Scan the Fabric pairing QR")
                        .setBeepEnabled(false)
                        .setOrientationLocked(true),
                )
            },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Scan pairing QR")
        }

        OutlinedTextField(
            value = url,
            onValueChange = { url = it },
            label = { Text("Gateway URL") },
            placeholder = { Text("http://my-machine:9119") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(
                selected = !passwordMode,
                onClick = { passwordMode = false },
                label = { Text("Token") },
            )
            FilterChip(
                selected = passwordMode,
                onClick = { passwordMode = true },
                label = { Text("Sign in") },
            )
        }

        if (passwordMode) {
            OutlinedTextField(
                value = username,
                onValueChange = { username = it },
                label = { Text("Username") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = password,
                onValueChange = { password = it },
                label = { Text("Password") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(),
            )
            providerName?.let {
                Text(
                    "Provider: $it",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        } else {
            OutlinedTextField(
                value = token,
                onValueChange = { token = it },
                label = { Text("Session token") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(),
            )
        }

        OutlinedButton(
            onClick = {
                probing = true
                probeResult = null
                scope.launch {
                    probeResult = try {
                        val status = GatewayApi.probeStatus(url.trim())
                        if (status.authRequired) {
                            passwordMode = true
                            providerName = runCatching {
                                viewModel.api.listAuthProviders(url.trim())
                                    .firstOrNull { it.supportsPassword }?.name
                            }.getOrNull()
                            if (providerName == null) {
                                "Reachable, but no password sign-in is offered " +
                                    "(OAuth-only gateways are not supported yet)."
                            } else {
                                "Gateway reachable — sign-in required."
                            }
                        } else {
                            passwordMode = false
                            "Gateway reachable — token auth."
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
            onClick = { connect() },
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
