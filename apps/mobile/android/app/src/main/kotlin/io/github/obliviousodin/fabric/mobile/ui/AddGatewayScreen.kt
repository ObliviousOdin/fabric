package io.github.obliviousodin.fabric.mobile.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import io.github.obliviousodin.fabric.mobile.AppViewModel
import io.github.obliviousodin.fabric.mobile.ConnectionPhase
import io.github.obliviousodin.fabric.mobile.core.GatewayApi
import io.github.obliviousodin.fabric.mobile.core.PairingPayload
import io.github.obliviousodin.fabric.mobile.ui.theme.FabricTheme
import kotlinx.coroutines.launch

/**
 * Add a server to the library. Scan a pairing QR or enter the address plus
 * a token (loopback/tunnel) or username/password (gated). Saving stores the
 * server and connects; the library remembers it for next time.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddGatewaySheet(viewModel: AppViewModel, onDismiss: () -> Unit) {
    val phase by viewModel.phase.collectAsState()
    val connectError by viewModel.connectError.collectAsState()
    val scope = rememberCoroutineScope()

    var label by remember { mutableStateOf("") }
    var url by remember { mutableStateOf("") }
    var passwordMode by remember { mutableStateOf(false) }
    var token by remember { mutableStateOf("") }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var otp by remember { mutableStateOf("") }
    var providerName by remember { mutableStateOf<String?>(null) }
    var requiresTotp by remember { mutableStateOf(false) }
    var probeResult by remember { mutableStateOf<String?>(null) }
    var probing by remember { mutableStateOf(false) }

    val urlValid = url.trim().startsWith("http://") || url.trim().startsWith("https://")
    val canSave = urlValid && phase != ConnectionPhase.Connecting &&
        if (passwordMode) {
            username.isNotBlank() && password.isNotEmpty() &&
                (!requiresTotp || otp.trim().length >= 6)
        } else {
            token.isNotBlank()
        }

    // Dismiss once a connect lands.
    androidx.compose.runtime.LaunchedEffect(phase) {
        if (phase == ConnectionPhase.Connected) onDismiss()
    }

    suspend fun resolveProvider(base: String): String? {
        providerName?.let { return it }
        val provider = runCatching {
            viewModel.api.listAuthProviders(base).firstOrNull { it.supportsPassword }
        }.getOrNull()
        providerName = provider?.name
        requiresTotp = provider?.requiresTotp ?: false
        return provider?.name
    }

    fun save() {
        val base = url.trim().trimEnd('/')
        scope.launch {
            if (passwordMode) {
                val provider = resolveProvider(base)
                if (provider == null) {
                    probeResult = "This server offers no password sign-in (OAuth-only isn't supported yet)."
                    return@launch
                }
                val gateway = viewModel.saveGatedGateway(label, base, username.trim())
                viewModel.connectGated(gateway, provider, password, otp.trim())
            } else {
                val gateway = viewModel.saveTokenGateway(label, base, token.trim())
                viewModel.connectToken(gateway)
            }
        }
    }

    val scanLauncher = rememberLauncherForActivityResult(ScanContract()) { result ->
        val payload = result.contents?.let(PairingPayload::parse)
        if (payload == null) {
            if (result.contents != null) probeResult = "Scanned code is not a Fabric pairing QR."
            return@rememberLauncherForActivityResult
        }
        url = payload.baseUrl
        if (payload.token != null) {
            passwordMode = false
            token = payload.token
            save()
        } else {
            passwordMode = true
            probeResult = "Server requires sign-in — enter your username and password."
        }
    }

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp)
                .padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("Add server", style = MaterialTheme.typography.titleMedium)

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
            ) { Text("Scan pairing QR") }

            OutlinedTextField(
                value = label,
                onValueChange = { label = it },
                label = { Text("Name (optional)") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = url,
                onValueChange = { url = it },
                label = { Text("Gateway URL") },
                placeholder = { Text("http://my-machine:9119") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = !passwordMode, onClick = { passwordMode = false }, label = { Text("Token") })
                FilterChip(selected = passwordMode, onClick = { passwordMode = true }, label = { Text("Sign in") })
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
                if (requiresTotp) {
                    OutlinedTextField(
                        value = otp,
                        onValueChange = { otp = it.filter(Char::isDigit).take(6) },
                        label = { Text("6-digit code") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                        supportingText = { Text("From your authenticator app") },
                        modifier = Modifier.fillMaxWidth(),
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
                                if (resolveProvider(url.trim().trimEnd('/')) == null) {
                                    "Reachable, but no password sign-in is offered (OAuth-only isn't supported yet)."
                                } else {
                                    "Reachable — sign-in required."
                                }
                            } else {
                                passwordMode = false
                                "Reachable — token auth."
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
                if (probing) CircularProgressIndicator(modifier = Modifier.padding(4.dp)) else Text("Test connection")
            }

            probeResult?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }

            Button(onClick = { save() }, enabled = canSave, modifier = Modifier.fillMaxWidth()) {
                if (phase == ConnectionPhase.Connecting) {
                    CircularProgressIndicator(modifier = Modifier.padding(4.dp))
                } else {
                    Text("Save and connect")
                }
            }

            connectError?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = FabricTheme.extras.danger)
            }
        }
    }
}
