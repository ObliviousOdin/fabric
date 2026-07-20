package io.github.obliviousodin.fabric.mobile.ui

import androidx.compose.foundation.background
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.StopCircle
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.obliviousodin.fabric.mobile.AppViewModel
import io.github.obliviousodin.fabric.mobile.core.ActiveSession
import io.github.obliviousodin.fabric.mobile.core.GatewayCapabilityNegotiation
import io.github.obliviousodin.fabric.mobile.core.SessionSummary
import io.github.obliviousodin.fabric.mobile.core.supportsGatewayMethod
import io.github.obliviousodin.fabric.mobile.ui.theme.FabricTheme
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

/**
 * Session picker: live gateway sessions (`session.active_list`) with
 * remote-control actions on top, the historical `session.list` below.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SessionsScreen(
    viewModel: AppViewModel,
    enabled: Boolean,
    capabilityNegotiation: GatewayCapabilityNegotiation?,
) {
    var sessions by remember { mutableStateOf<List<SessionSummary>>(emptyList()) }
    var activeSessions by remember { mutableStateOf<List<ActiveSession>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var reloadKey by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(reloadKey, enabled) {
        if (!enabled) {
            loading = false
            return@LaunchedEffect
        }
        loading = true
        try {
            coroutineScope {
                val recent = async { viewModel.api.listSessions() }
                val active = async {
                    if (!capabilityNegotiation.supportsGatewayMethod("session.active_list")) {
                        return@async emptyList()
                    }
                    try {
                        viewModel.api.activeSessions()
                    } catch (e: CancellationException) {
                        throw e
                    } catch (_: Exception) {
                        emptyList()
                    }
                }
                sessions = recent.await()
                // Live sessions are best-effort decoration; the historical
                // list is the primary content.
                activeSessions = active.await()
            }
            loadError = null
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            loadError = e.message ?: e.toString()
        } finally {
            loading = false
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                // Title names the connected server; disconnect() returns to
                // the library, which is the switcher for other saved servers.
                title = { Text(viewModel.activeGateway?.label ?: "Sessions", maxLines = 1) },
                actions = {
                    IconButton(onClick = { reloadKey++ }, enabled = enabled) {
                        Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
                    }
                    IconButton(onClick = viewModel::disconnect) {
                        Icon(
                            Icons.AutoMirrored.Filled.Logout,
                            contentDescription = "Switch server",
                        )
                    }
                },
            )
        },
        floatingActionButton = {
            if (enabled) {
                FloatingActionButton(onClick = viewModel::openNewChat) {
                    Icon(Icons.Filled.Add, contentDescription = "New chat")
                }
            }
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            ExecutionTruthCard(capabilityNegotiation)
            when {
                loading && sessions.isEmpty() && activeSessions.isEmpty() -> {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(24.dp),
                        horizontalArrangement = Arrangement.Center,
                    ) {
                        CircularProgressIndicator()
                    }
                }

                loadError != null -> {
                    Text(
                        loadError.orEmpty(),
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(16.dp),
                    )
                }

                sessions.isEmpty() && activeSessions.isEmpty() -> {
                    Text(
                        "No sessions yet — start one with the + button.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(16.dp),
                    )
                }

                else -> {
                    LazyColumn(modifier = Modifier.fillMaxSize()) {
                        if (activeSessions.isNotEmpty()) {
                            item(key = "active-header") {
                                Text(
                                    "Active now",
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                                )
                            }
                            items(activeSessions, key = { "active-${it.id}" }) { session ->
                                ActiveSessionRow(
                                    session = session,
                                    enabled = enabled,
                                    canInterrupt = capabilityNegotiation
                                        .supportsGatewayMethod("session.interrupt"),
                                    onClick = {
                                        viewModel.openSession(
                                            session.sessionKey,
                                            session.title.ifEmpty { "Untitled session" },
                                        )
                                    },
                                    onInterrupt = {
                                        scope.launch {
                                            runCatching { viewModel.api.interrupt(session.id) }
                                            reloadKey++
                                        }
                                    },
                                )
                                HorizontalDivider()
                            }
                            if (sessions.isNotEmpty()) {
                                item(key = "recent-header") {
                                    Text(
                                        "Recent sessions",
                                        style = MaterialTheme.typography.labelMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                                    )
                                }
                            }
                        }
                        items(sessions, key = { it.id }) { session ->
                            SessionRow(session, enabled = enabled) {
                                viewModel.openSession(session.id, session.displayTitle)
                            }
                            HorizontalDivider()
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ExecutionTruthCard(negotiation: GatewayCapabilityNegotiation?) {
    val (title, body, accent) = when (negotiation) {
        is GatewayCapabilityNegotiation.Verified -> {
            val execution = negotiation.capabilities.execution
            val disconnect = if (execution.survivesClientDisconnect) {
                "Work continues if this phone disconnects."
            } else {
                "Work stops if this phone disconnects."
            }
            val restart = if (execution.survivesGatewayRestart) {
                "It survives a gateway restart."
            } else {
                "It does not survive a gateway restart."
            }
            val host = if (execution.requiresGatewayHostOnline) {
                "The gateway host must remain online."
            } else {
                "The gateway host may go offline."
            }
            Triple(
                if (execution.location == "gateway") {
                    "Runs on this gateway"
                } else {
                    "Execution: ${execution.location}"
                },
                "Gateway ${negotiation.capabilities.serverVersion} · " +
                    "$disconnect $restart $host",
                FabricTheme.extras.info,
            )
        }
        GatewayCapabilityNegotiation.Legacy -> Triple(
            "Compatibility mode",
            "This gateway predates capability verification. Existing mobile controls remain " +
                "available, but execution guarantees are unverified.",
            FabricTheme.extras.warning,
        )
        is GatewayCapabilityNegotiation.Incompatible -> Triple(
            "Mobile update required",
            "This gateway requires mobile contract ${negotiation.minimumCompatibleVersion} " +
                "or newer. Session controls are disabled.",
            MaterialTheme.colorScheme.error,
        )
        is GatewayCapabilityNegotiation.Invalid -> Triple(
            "Gateway contract invalid",
            "Session controls are disabled: ${negotiation.reason}",
            MaterialTheme.colorScheme.error,
        )
        GatewayCapabilityNegotiation.Negotiating -> Triple(
            "Checking gateway capabilities…",
            "Session controls will unlock after the authenticated contract is verified.",
            FabricTheme.extras.info,
        )
        null -> Triple(
            "Gateway capabilities unavailable",
            "Reconnect to verify which mobile controls this gateway supports.",
            FabricTheme.extras.warning,
        )
    }

    Surface(
        color = accent.copy(alpha = 0.1f),
        shape = MaterialTheme.shapes.medium,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(title, style = MaterialTheme.typography.titleSmall, color = accent)
            Text(
                body,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * A live gateway session that can be reopened by tapping the row. Running
 * sessions retain a separate interrupt control.
 */
@Composable
private fun ActiveSessionRow(
    session: ActiveSession,
    enabled: Boolean,
    canInterrupt: Boolean,
    onClick: () -> Unit,
    onInterrupt: () -> Unit,
) {
    // Contract status language: working rides the active-thread purple,
    // waiting is amber, starting is info; idle stays neutral.
    val statusColor = FabricTheme.extras.sessionStatusColor(session.status)

    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp),
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .background(statusColor, CircleShape),
                )
                Text(
                    session.title.ifEmpty { "Untitled session" },
                    style = MaterialTheme.typography.bodyLarge,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (session.preview.isNotEmpty()) {
                Text(
                    session.preview,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                listOf(session.status, session.model, "${session.messageCount} messages")
                    .filter { it.isNotEmpty() }
                    .joinToString(" · "),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        if (session.status == "working" || session.status == "starting") {
            IconButton(onClick = onInterrupt, enabled = enabled && canInterrupt) {
                Icon(Icons.Filled.StopCircle, contentDescription = "Interrupt")
            }
        }
    }
}

@Composable
private fun SessionRow(
    session: SessionSummary,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(
            session.displayTitle,
            style = MaterialTheme.typography.bodyLarge,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (session.source.isNotEmpty()) {
                Text(
                    session.source,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                "${session.messageCount} messages",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
