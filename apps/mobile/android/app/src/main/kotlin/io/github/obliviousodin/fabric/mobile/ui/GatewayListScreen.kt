package io.github.obliviousodin.fabric.mobile.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Key
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember

import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.obliviousodin.fabric.mobile.AppViewModel
import io.github.obliviousodin.fabric.mobile.ConnectionPhase
import io.github.obliviousodin.fabric.mobile.core.GatewayApi
import io.github.obliviousodin.fabric.mobile.core.GatewayAuthMode
import io.github.obliviousodin.fabric.mobile.core.SavedGateway
import io.github.obliviousodin.fabric.mobile.ui.theme.FabricTheme
import kotlinx.coroutines.launch

/**
 * The saved-server library — home when no socket is open. Tap a token
 * server to connect instantly; a gated server prompts for its password
 * unless a live session is still around. Add servers here or by scanning a
 * pairing QR.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GatewayListScreen(viewModel: AppViewModel) {
    val phase by viewModel.phase.collectAsState()
    val gateways by viewModel.gateways.collectAsState()
    val connectError by viewModel.connectError.collectAsState()
    val pendingSignIn by viewModel.pendingSignInGateway.collectAsState()

    var showAdd by remember { mutableStateOf(false) }
    var signInFor by remember { mutableStateOf<SavedGateway?>(null) }

    androidx.compose.runtime.LaunchedEffect(pendingSignIn?.id) {
        pendingSignIn?.let {
            signInFor = it
            viewModel.consumePendingSignInGateway()
        }
    }

    if (showAdd) {
        AddGatewaySheet(viewModel = viewModel, onDismiss = { showAdd = false })
    }
    signInFor?.let { gateway ->
        SignInDialog(
            viewModel = viewModel,
            gateway = gateway,
            onDismiss = { signInFor = null },
        )
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("Fabric") }) },
        floatingActionButton = {
            FloatingActionButton(onClick = { showAdd = true }) {
                Icon(Icons.Filled.Add, contentDescription = "Add server")
            }
        },
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            Column(modifier = Modifier.fillMaxSize()) {
                Text(
                    "Servers",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(16.dp, 12.dp, 16.dp, 4.dp),
                )
                if (gateways.isEmpty()) {
                    Text(
                        "Run `fabric mobile` on the machine, then scan its QR or enter the address and credential.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(16.dp),
                    )
                } else {
                    LazyColumn(modifier = Modifier.fillMaxWidth()) {
                        items(gateways, key = { it.id }) { gateway ->
                            GatewayRow(
                                gateway = gateway,
                                autoReady = viewModel.canAutoConnect(gateway),
                                onOpen = {
                                    when (gateway.authMode) {
                                        GatewayAuthMode.TOKEN -> viewModel.connectToken(gateway)
                                        GatewayAuthMode.GATED -> signInFor = gateway
                                    }
                                },
                                onDelete = { viewModel.removeGateway(gateway.id) },
                            )
                            HorizontalDivider()
                        }
                    }
                }
                connectError?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.bodySmall,
                        color = FabricTheme.extras.danger,
                        modifier = Modifier.padding(16.dp),
                    )
                }
            }

            if (phase == ConnectionPhase.Connecting) {
                Surface(
                    color = MaterialTheme.colorScheme.surfaceContainerHigh,
                    shape = MaterialTheme.shapes.large,
                    modifier = Modifier.align(Alignment.Center),
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        modifier = Modifier.padding(20.dp),
                    ) {
                        CircularProgressIndicator(modifier = Modifier.size(20.dp))
                        Text("Connecting…")
                    }
                }
            }
        }
    }
}

@Composable
private fun GatewayRow(
    gateway: SavedGateway,
    autoReady: Boolean,
    onOpen: () -> Unit,
    onDelete: () -> Unit,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpen)
            .padding(horizontal = 16.dp, vertical = 12.dp),
    ) {
        Icon(
            if (gateway.authMode == GatewayAuthMode.TOKEN) Icons.Filled.Key else Icons.Filled.Person,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(end = 12.dp),
        )
        Column(modifier = Modifier.weight(1f)) {
            Text(gateway.label, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                gateway.baseUrl,
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Text(
            if (autoReady) "Tap to connect" else if (gateway.authMode == GatewayAuthMode.GATED) "Sign in" else "Add token",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        IconButton(onClick = onDelete) {
            Icon(Icons.Filled.Delete, contentDescription = "Remove ${gateway.label}", tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** Password re-auth for a saved gated server whose cookie session has lapsed. */
@Composable
private fun SignInDialog(
    viewModel: AppViewModel,
    gateway: SavedGateway,
    onDismiss: () -> Unit,
) {
    var username by remember(gateway.id) { mutableStateOf(gateway.username) }
    var password by remember { mutableStateOf("") }
    var otp by remember { mutableStateOf("") }
    var providerName by remember { mutableStateOf<String?>(null) }
    var requiresTotp by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val phase by viewModel.phase.collectAsState()
    val connectError by viewModel.connectError.collectAsState()

    // Resolve the provider (and whether it needs a code) when the dialog opens.
    androidx.compose.runtime.LaunchedEffect(gateway.id) {
        val provider = runCatching {
            viewModel.api.listAuthProviders(gateway.baseUrl).firstOrNull { it.supportsPassword }
        }.getOrNull()
        providerName = provider?.name
        requiresTotp = provider?.requiresTotp ?: false
    }
    androidx.compose.runtime.LaunchedEffect(phase, connectError) {
        if (phase == ConnectionPhase.Connected) onDismiss()
        if (phase == ConnectionPhase.Disconnected && connectError != null) {
            error = connectError
        }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(gateway.label) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
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
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = FabricTheme.extras.danger) }
            }
        },
        confirmButton = {
            TextButton(
                enabled = username.isNotBlank() && password.isNotEmpty() &&
                    phase != ConnectionPhase.Connecting &&
                    (!requiresTotp || otp.length >= 6),
                onClick = {
                    val provider = providerName
                    if (provider == null) {
                        error = "This server offers no password sign-in."
                        return@TextButton
                    }
                    error = null
                    val updated = viewModel.saveGatedGateway(
                        gateway.label,
                        gateway.baseUrl,
                        username.trim(),
                    )
                    viewModel.connectGated(updated, provider, password, otp.trim())
                },
            ) { Text("Sign in") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
