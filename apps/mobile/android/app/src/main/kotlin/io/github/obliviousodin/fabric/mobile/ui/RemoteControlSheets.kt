package io.github.obliviousodin.fabric.mobile.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import kotlinx.coroutines.launch
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.obliviousodin.fabric.mobile.core.BackgroundProcess
import io.github.obliviousodin.fabric.mobile.core.GatewayApi
import io.github.obliviousodin.fabric.mobile.core.SlashCommandCategory

/**
 * The slash-command catalog (`commands.catalog`), grouped by category.
 * Tapping a command hands it back to the composer for arguments.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CommandCatalogSheet(
    api: GatewayApi,
    onSelect: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var categories by remember { mutableStateOf<List<SlashCommandCategory>>(emptyList()) }
    var filter by remember { mutableStateOf("") }
    var loadError by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        try {
            categories = api.commandCatalog()
        } catch (e: Exception) {
            loadError = e.message ?: e.toString()
        }
    }

    val query = filter.trim().lowercase()
    val visible = if (query.isEmpty()) {
        categories
    } else {
        categories.mapNotNull { category ->
            val commands = category.commands.filter {
                it.name.lowercase().contains(query) || it.detail.lowercase().contains(query)
            }
            if (commands.isEmpty()) null else category.copy(commands = commands)
        }
    }

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(modifier = Modifier.padding(horizontal = 16.dp)) {
            Text("Commands", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = filter,
                onValueChange = { filter = it },
                placeholder = { Text("Filter commands") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
            )
            loadError?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            LazyColumn(modifier = Modifier.fillMaxWidth()) {
                visible.forEach { category ->
                    item(key = "cat-${category.name}") {
                        Text(
                            category.name,
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 12.dp, bottom = 4.dp),
                        )
                    }
                    items(category.commands, key = { "${category.name}-${it.name}" }) { command ->
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { onSelect(command.name) }
                                .padding(vertical = 8.dp),
                        ) {
                            Text(
                                command.name,
                                style = MaterialTheme.typography.bodyMedium,
                                fontFamily = FontFamily.Monospace,
                            )
                            if (command.detail.isNotEmpty()) {
                                Text(
                                    command.detail,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                        }
                        HorizontalDivider()
                    }
                }
            }
        }
    }
}

/**
 * Background processes owned by this session (`process.list`), with kill
 * control and the output tail for a quick health check.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProcessListSheet(
    api: GatewayApi,
    sessionId: String?,
    onDismiss: () -> Unit,
) {
    var processes by remember { mutableStateOf<List<BackgroundProcess>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var reloadKey by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(reloadKey) {
        if (sessionId == null) {
            loadError = "No live session."
            loading = false
            return@LaunchedEffect
        }
        loading = true
        try {
            processes = api.listProcesses(sessionId)
            loadError = null
        } catch (e: Exception) {
            loadError = e.message ?: e.toString()
        } finally {
            loading = false
        }
    }

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(modifier = Modifier.padding(horizontal = 16.dp)) {
            Row(
                horizontalArrangement = Arrangement.SpaceBetween,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Background processes", style = MaterialTheme.typography.titleMedium)
                OutlinedButton(onClick = { reloadKey++ }) { Text("Refresh") }
            }

            when {
                loading -> CircularProgressIndicator(
                    modifier = Modifier.padding(16.dp).size(24.dp),
                )

                loadError != null -> Text(
                    loadError.orEmpty(),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(vertical = 16.dp),
                )

                processes.isEmpty() -> Text(
                    "No background processes for this session.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(vertical = 16.dp),
                )

                else -> LazyColumn(modifier = Modifier.fillMaxWidth()) {
                    items(processes, key = { it.id }) { process ->
                        Column(
                            modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Text(
                                process.command,
                                style = MaterialTheme.typography.bodySmall,
                                fontFamily = FontFamily.Monospace,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Row(
                                horizontalArrangement = Arrangement.SpaceBetween,
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text(
                                    "pid ${process.pid} · up ${process.uptimeSeconds}s · ${process.status}",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                                if (process.status == "running" && sessionId != null) {
                                    OutlinedButton(onClick = {
                                        // Kill then refresh; errors land in loadError.
                                        scope.launch {
                                            try {
                                                api.killProcess(sessionId, process.id)
                                            } catch (e: Exception) {
                                                loadError = e.message ?: e.toString()
                                            }
                                            reloadKey++
                                        }
                                    }) {
                                        Text("Kill")
                                    }
                                }
                            }
                            if (process.outputTail.isNotEmpty()) {
                                Text(
                                    process.outputTail.takeLast(400),
                                    style = MaterialTheme.typography.labelSmall,
                                    fontFamily = FontFamily.Monospace,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    maxLines = 6,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                        }
                        HorizontalDivider()
                    }
                }
            }
        }
    }
}
