package io.github.obliviousodin.fabric.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Redo
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
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
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import io.github.obliviousodin.fabric.mobile.ChatSessionController
import io.github.obliviousodin.fabric.mobile.PendingApproval
import io.github.obliviousodin.fabric.mobile.PendingPrompt
import io.github.obliviousodin.fabric.mobile.Role
import io.github.obliviousodin.fabric.mobile.TranscriptMessage
import io.github.obliviousodin.fabric.mobile.ui.theme.FabricTheme

/**
 * Chat transcript + composer for one Fabric session, with the same
 * dispatch/remote-control surface the TUI composer exposes: slash commands,
 * steering, background tasks, and process control.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    controller: ChatSessionController,
    title: String,
    onBack: () -> Unit,
) {
    val messages by controller.messages.collectAsState()
    val statusLine by controller.statusLine.collectAsState()
    val busy by controller.busy.collectAsState()
    val pendingApproval by controller.pendingApproval.collectAsState()
    val pendingPrompt by controller.pendingPrompt.collectAsState()
    val sessionReady by controller.sessionReady.collectAsState()
    val fatalError by controller.fatalError.collectAsState()

    var draft by rememberSaveable { mutableStateOf("") }
    var menuOpen by remember { mutableStateOf(false) }
    var showCommands by remember { mutableStateOf(false) }
    var showProcesses by remember { mutableStateOf(false) }
    var showLiveView by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()

    LaunchedEffect(messages.size, (messages.lastOrNull()?.text ?: "").length) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.lastIndex)
        }
    }

    if (showCommands) {
        CommandCatalogSheet(
            api = controller.api,
            onSelect = { command ->
                draft = "$command "
                showCommands = false
            },
            onDismiss = { showCommands = false },
        )
    }

    if (showProcesses) {
        ProcessListSheet(
            api = controller.api,
            sessionId = controller.sessionId,
            onDismiss = { showProcesses = false },
        )
    }

    if (showLiveView) {
        LiveViewSheet(
            api = controller.api,
            onDismiss = { showLiveView = false },
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(title, maxLines = 1) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(onClick = { menuOpen = true }, enabled = sessionReady) {
                        Icon(Icons.Filled.MoreVert, contentDescription = "More")
                    }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        DropdownMenuItem(
                            text = { Text("Commands…") },
                            onClick = {
                                menuOpen = false
                                showCommands = true
                            },
                        )
                        DropdownMenuItem(
                            text = { Text("Run draft in background") },
                            enabled = draft.isNotBlank(),
                            onClick = {
                                menuOpen = false
                                val text = draft
                                draft = ""
                                controller.sendInBackground(text)
                            },
                        )
                        DropdownMenuItem(
                            text = { Text("Background processes…") },
                            onClick = {
                                menuOpen = false
                                showProcesses = true
                            },
                        )
                        DropdownMenuItem(
                            text = { Text("Live screen view…") },
                            onClick = {
                                menuOpen = false
                                showLiveView = true
                            },
                        )
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .imePadding(),
        ) {
            if (fatalError != null) {
                Text(
                    fatalError.orEmpty(),
                    color = MaterialTheme.colorScheme.error,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth().padding(24.dp),
                )
            }

            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).fillMaxWidth(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                items(messages, key = { it.id }) { message ->
                    MessageBubble(message)
                }
            }

            pendingApproval?.let { approval ->
                ApprovalBanner(
                    approval = approval,
                    onRespond = controller::respondToApproval,
                )
            }

            pendingPrompt?.let { prompt ->
                PromptBanner(
                    prompt = prompt,
                    onRespond = controller::respondToPrompt,
                )
            }

            statusLine?.let { status ->
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                ) {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp))
                    Text(
                        status,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                    )
                }
            }

            Row(
                verticalAlignment = Alignment.Bottom,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxWidth().padding(16.dp),
            ) {
                OutlinedTextField(
                    value = draft,
                    onValueChange = { draft = it },
                    placeholder = {
                        Text(if (busy) "Steer the running turn…" else "Message Fabric… (/ for commands)")
                    },
                    enabled = sessionReady,
                    maxLines = 5,
                    modifier = Modifier.weight(1f),
                )
                if (busy) {
                    // Steering send: injects the note without interrupting.
                    IconButton(
                        onClick = {
                            val text = draft
                            draft = ""
                            controller.send(text)
                        },
                        enabled = draft.isNotBlank(),
                    ) {
                        Icon(
                            Icons.AutoMirrored.Filled.Redo,
                            contentDescription = "Steer",
                            tint = FabricTheme.extras.threadActive,
                        )
                    }
                    IconButton(onClick = controller::interrupt) {
                        Icon(Icons.Filled.Stop, contentDescription = "Interrupt")
                    }
                } else {
                    IconButton(
                        onClick = {
                            val text = draft
                            draft = ""
                            controller.send(text)
                        },
                        enabled = sessionReady && draft.isNotBlank(),
                    ) {
                        Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Send")
                    }
                }
            }
        }
    }
}

/**
 * Waiting-for-approval banner. Status language per the design contract:
 * an amber marker + explicit label, with the status color held to a tint
 * and an edge marker — never a fully saturated panel. One primary action.
 */
@Composable
private fun ApprovalBanner(
    approval: PendingApproval,
    onRespond: (Boolean) -> Unit,
) {
    val warning = FabricTheme.extras.warning
    Surface(
        color = warning.copy(alpha = 0.1f),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row {
            Box(
                modifier = Modifier
                    .width(3.dp)
                    .fillMaxHeight()
                    .background(warning),
            )
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .size(8.dp)
                            .background(warning, CircleShape),
                    )
                    Text("Waiting for approval", style = MaterialTheme.typography.titleSmall)
                }
                approval.command?.takeIf { it.isNotEmpty() }?.let { command ->
                    Text(
                        command,
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                        maxLines = 4,
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { onRespond(true) }) { Text("Allow") }
                    OutlinedButton(onClick = { onRespond(false) }) { Text("Deny") }
                }
            }
        }
    }
}

/**
 * Blocking agent prompt: clarify choices as buttons, plus a free-text
 * (or secure, for sudo/secret) answer field.
 */
@Composable
private fun PromptBanner(
    prompt: PendingPrompt,
    onRespond: (String) -> Unit,
) {
    var answer by remember(prompt.requestId) { mutableStateOf("") }

    val info = FabricTheme.extras.info
    Surface(
        color = info.copy(alpha = 0.1f),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                if (prompt.kind == PendingPrompt.Kind.CLARIFY) {
                    "The agent has a question"
                } else {
                    "Credential requested"
                },
                style = MaterialTheme.typography.titleSmall,
            )
            Text(prompt.question, style = MaterialTheme.typography.bodyMedium)

            prompt.choices.forEach { choice ->
                OutlinedButton(onClick = { onRespond(choice) }) { Text(choice) }
            }

            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedTextField(
                    value = answer,
                    onValueChange = { answer = it },
                    placeholder = { Text("Answer") },
                    singleLine = true,
                    visualTransformation = if (prompt.isSecureEntry) {
                        PasswordVisualTransformation()
                    } else {
                        VisualTransformation.None
                    },
                    modifier = Modifier.weight(1f),
                )
                Button(
                    onClick = { onRespond(answer) },
                    enabled = answer.isNotEmpty(),
                ) {
                    Text("Send")
                }
                TextButton(onClick = { onRespond("") }) { Text("Dismiss") }
            }
        }
    }
}

@Composable
private fun MessageBubble(message: TranscriptMessage) {
    when (message.role) {
        // Purple marks user-controlled elements (contract): the user's own
        // words are the one solid-accent surface in the transcript.
        Role.USER -> {
            Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
                Text(
                    message.text,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onPrimary,
                    modifier = Modifier
                        .widthIn(max = 320.dp)
                        .background(
                            MaterialTheme.colorScheme.primary,
                            MaterialTheme.shapes.large,
                        )
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                )
            }
        }

        Role.ASSISTANT -> {
            Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                Text(
                    if (message.text.isEmpty() && message.streaming) "…" else message.text,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier
                        .widthIn(max = 320.dp)
                        .background(
                            MaterialTheme.colorScheme.surfaceContainerHigh,
                            MaterialTheme.shapes.large,
                        )
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                )
            }
        }

        // Technical output (slash results, task notices): mono on an inset
        // surface, full width — a ledger row, not a speech bubble.
        Role.INFO -> {
            Text(
                message.text,
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier
                    .fillMaxWidth()
                    .background(
                        MaterialTheme.colorScheme.surfaceContainerHighest,
                        MaterialTheme.shapes.small,
                    )
                    .padding(10.dp),
            )
        }

        // Failures read as status, not as chat: danger dot + left-aligned copy.
        Role.SYSTEM -> {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .background(FabricTheme.extras.danger, CircleShape),
                )
                Text(
                    message.text,
                    style = MaterialTheme.typography.labelSmall,
                    color = FabricTheme.extras.danger,
                )
            }
        }
    }
}
