package io.github.obliviousodin.fabric.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.obliviousodin.fabric.mobile.AppViewModel
import io.github.obliviousodin.fabric.mobile.SocialSessionEntry
import io.github.obliviousodin.fabric.mobile.core.SocialChannel
import io.github.obliviousodin.fabric.mobile.core.SocialFormat
import io.github.obliviousodin.fabric.mobile.core.SocialGoal
import io.github.obliviousodin.fabric.mobile.core.SocialRequest
import io.github.obliviousodin.fabric.mobile.core.SocialTone
import io.github.obliviousodin.fabric.mobile.core.buildSocialPrompt

/**
 * Social Studio for Android: a Compose tab that turns a brief into a post prompt
 * handed to a fresh chat, and a Library tab that lists conversations which
 * already produced a post so the caption can be copied and pasted. Text-first
 * v1 — the caption is always shown; inbound workspace images are a separate
 * gateway capability and are intentionally not rendered here yet.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SocialStudioScreen(viewModel: AppViewModel, enabled: Boolean) {
    var tab by remember { mutableStateOf(0) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Social Studio") },
                navigationIcon = {
                    IconButton(onClick = viewModel::backToSessions) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            TabRow(selectedTabIndex = tab) {
                Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("Compose") })
                Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("Library") })
            }

            if (tab == 0) {
                SocialComposer(viewModel = viewModel, enabled = enabled)
            } else {
                SocialLibrary(viewModel = viewModel)
            }
        }
    }
}

@Composable
private fun SocialComposer(viewModel: AppViewModel, enabled: Boolean) {
    var brief by remember { mutableStateOf("") }
    var goal by remember { mutableStateOf(SocialGoal.AUTHORITY) }
    var tone by remember { mutableStateOf(SocialTone.CANDID) }
    var format by remember { mutableStateOf(SocialFormat.HOOK_STORY) }
    var includeImage by remember { mutableStateOf(true) }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(
            "Turn a conversation into a ready-to-post update. Draft it here, then review and send.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        OutlinedTextField(
            value = brief,
            onValueChange = { brief = it },
            label = { Text("What's the post about?") },
            modifier = Modifier.fillMaxWidth().height(140.dp),
        )

        EnumField("Goal", goal.label, SocialGoal.entries.map { it.label to { goal = it } })
        EnumField("Voice", tone.label, SocialTone.entries.map { it.label to { tone = it } })
        EnumField("Format", format.label, SocialFormat.entries.map { it.label to { format = it } })

        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Switch(checked = includeImage, onCheckedChange = { includeImage = it })
            Text("Include a matching image", style = MaterialTheme.typography.bodyMedium)
        }

        Button(
            onClick = {
                viewModel.startChatWithPrompt(
                    buildSocialPrompt(
                        SocialRequest(
                            brief = brief,
                            channel = SocialChannel.LINKEDIN,
                            goal = goal,
                            tone = tone,
                            format = format,
                            includeImage = includeImage,
                        ),
                    ),
                )
            },
            enabled = enabled && brief.isNotBlank(),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Draft in chat")
        }
    }
}

@Composable
private fun EnumField(label: String, selectedLabel: String, options: List<Pair<String, () -> Unit>>) {
    var open by remember { mutableStateOf(false) }

    Column {
        Text(label, style = MaterialTheme.typography.labelMedium)
        Box {
            OutlinedButton(onClick = { open = true }, modifier = Modifier.fillMaxWidth()) {
                Text(selectedLabel, modifier = Modifier.weight(1f))
            }
            DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                options.forEach { (optionLabel, onSelect) ->
                    DropdownMenuItem(
                        text = { Text(optionLabel) },
                        onClick = {
                            onSelect()
                            open = false
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun SocialLibrary(viewModel: AppViewModel) {
    var loading by remember { mutableStateOf(true) }
    var entries by remember { mutableStateOf<List<SocialSessionEntry>>(emptyList()) }
    var reloadKey by remember { mutableStateOf(0) }

    LaunchedEffect(reloadKey) {
        loading = true
        entries =
            try {
                viewModel.loadSocialLibrary()
            } catch (_: Exception) {
                emptyList()
            }
        loading = false
    }

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.End,
        ) {
            TextButton(onClick = { reloadKey++ }) {
                Icon(Icons.Filled.Refresh, contentDescription = null)
                Spacer(Modifier.width(6.dp))
                Text("Refresh")
            }
        }

        when {
            loading ->
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
            entries.isEmpty() ->
                Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
                    Text(
                        "No posts yet. Draft one in Compose; when the agent writes a post it shows up here to copy.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            else ->
                LazyColumn(
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    items(entries) { entry -> SocialCard(entry = entry, viewModel = viewModel) }
                }
        }
    }
}

@Composable
private fun SocialCard(entry: SocialSessionEntry, viewModel: AppViewModel) {
    val clipboard = LocalClipboardManager.current
    val latest = entry.artifacts.last()

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                entry.session.displayTitle,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Text(latest.caption, style = MaterialTheme.typography.bodyMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { clipboard.setText(AnnotatedString(latest.caption)) }) {
                    Icon(Icons.Filled.ContentCopy, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text("Copy caption")
                }
                OutlinedButton(
                    onClick = { viewModel.openSession(entry.session.id, entry.session.displayTitle) },
                ) {
                    Text("Open")
                }
            }
        }
    }
}
