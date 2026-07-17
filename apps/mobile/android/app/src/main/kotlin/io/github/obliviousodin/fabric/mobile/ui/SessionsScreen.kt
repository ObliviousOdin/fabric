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
import io.github.obliviousodin.fabric.mobile.core.SessionSummary
import io.github.obliviousodin.fabric.mobile.ui.theme.FabricTheme
import kotlinx.coroutines.launch

/**
 * Session picker: live gateway sessions (`session.active_list`) with
 * remote-control actions on top, the historical `session.list` below.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SessionsScreen(viewModel: AppViewModel) {
    var sessions by remember { mutableStateOf<List<SessionSummary>>(emptyList()) }
    var activeSessions by remember { mutableStateOf<List<ActiveSession>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var reloadKey by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(reloadKey) {
        loading = true
        try {
            sessions = viewModel.api.listSessions()
            // Live sessions are best-effort decoration; the historical list
            // is the primary content.
            activeSessions = runCatching { viewModel.api.activeSessions() }
                .getOrDefault(emptyList())
            loadError = null
        } catch (e: Exception) {
            loadError = e.message ?: e.toString()
        } finally {
            loading = false
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Sessions") },
                actions = {
                    IconButton(onClick = { reloadKey++ }) {
                        Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
                    }
                    IconButton(onClick = viewModel::disconnect) {
                        Icon(Icons.AutoMirrored.Filled.Logout, contentDescription = "Disconnect")
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = viewModel::openNewChat) {
                Icon(Icons.Filled.Add, contentDescription = "New chat")
            }
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            when {
                loading && sessions.isEmpty() -> {
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

                sessions.isEmpty() -> {
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
                                ActiveSessionRow(session) {
                                    scope.launch {
                                        runCatching { viewModel.api.interrupt(session.id) }
                                        reloadKey++
                                    }
                                }
                                HorizontalDivider()
                            }
                            item(key = "recent-header") {
                                Text(
                                    "Recent sessions",
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                                )
                            }
                        }
                        items(sessions, key = { it.id }) { session ->
                            SessionRow(session) {
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

/**
 * A live gateway session with its runtime status and an interrupt control —
 * the "remote control" row: watch a working agent, stop it from the phone.
 */
@Composable
private fun ActiveSessionRow(session: ActiveSession, onInterrupt: () -> Unit) {
    // Contract status language: working rides the active-thread purple,
    // waiting is amber, starting is info; idle stays neutral.
    val statusColor = FabricTheme.extras.sessionStatusColor(session.status)

    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
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
            IconButton(onClick = onInterrupt) {
                Icon(Icons.Filled.StopCircle, contentDescription = "Interrupt")
            }
        }
    }
}

@Composable
private fun SessionRow(session: SessionSummary, onClick: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
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
