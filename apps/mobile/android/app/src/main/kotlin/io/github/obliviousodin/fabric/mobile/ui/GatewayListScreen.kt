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
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
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

    var showAdd by remember { mutableStateOf(false) }
    var signInFor by remember { mutableStateOf<SavedGateway?>(null) }

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
                        "Add the machine running `fabric serve`. Scan its `--qr` code or enter the address and credential.",
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
    var password by remember { mutableStateOf("") }
    var providerName by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    val phase by viewModel.phase.collectAsState()
    val scope = rememberCoroutineScope()

    // Try a silent reconnect on a live cookie session as soon as the dialog
    // opens; resolve the provider in parallel for the manual path.
    androidx.compose.runtime.LaunchedEffect(gateway.id) {
        providerName = runCatching {
            viewModel.api.listAuthProviders(gateway.baseUrl).firstOrNull { it.supportsPassword }?.name
        }.getOrNull()
    }
    androidx.compose.runtime.LaunchedEffect(phase) {
        if (phase == ConnectionPhase.Connected) onDismiss()
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(gateway.label) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Signed in as ${gateway.username}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    label = { Text("Password") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth(),
                )
                error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = FabricTheme.extras.danger) }
            }
        },
        confirmButton = {
            TextButton(
                enabled = password.isNotEmpty() && phase != ConnectionPhase.Connecting,
                onClick = {
                    val provider = providerName
                    if (provider == null) {
                        error = "This server offers no password sign-in."
                        return@TextButton
                    }
                    scope.launch {
                        viewModel.connectGated(gateway, provider, password)
                        if (viewModel.phase.value != ConnectionPhase.Connected) {
                            error = viewModel.connectError.value ?: "Sign-in failed."
                        }
                    }
                },
            ) { Text("Sign in") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
