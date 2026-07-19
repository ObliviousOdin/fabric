package io.github.obliviousodin.fabric.mobile.ui

import android.graphics.BitmapFactory
import android.util.Base64
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import io.github.obliviousodin.fabric.mobile.core.GatewayApi
import io.github.obliviousodin.fabric.mobile.core.ScreenCapture
import io.github.obliviousodin.fabric.mobile.ui.theme.FabricTheme
import kotlinx.coroutines.delay

/**
 * Read-only live view of the gateway host's screen — a window onto what a
 * `computer_use` turn is doing. Polls `computer.screenshot` on a fixed
 * cadence; no input is ever sent back. When the host can't capture
 * (unsupported OS, cua-driver missing), it says so and stops.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LiveViewSheet(api: GatewayApi, onDismiss: () -> Unit) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var frame by remember { mutableStateOf<androidx.compose.ui.graphics.ImageBitmap?>(null) }
    var dimensions by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var paused by remember { mutableStateOf(false) }

    LaunchedEffect(paused) {
        while (true) {
            if (!paused) {
                try {
                    val capture: ScreenCapture = api.captureScreen()
                    val bytes = Base64.decode(capture.pngBase64, Base64.DEFAULT)
                    val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    if (bmp != null) {
                        frame = bmp.asImageBitmap()
                        dimensions = "${capture.width}×${capture.height}"
                        error = null
                    }
                } catch (e: Exception) {
                    // A one-off failure mid-turn is normal; only hard-stop
                    // when we have no frame at all yet.
                    if (frame == null) {
                        error = e.message ?: e.toString()
                        return@LaunchedEffect
                    }
                }
            }
            delay(1500)
        }
    }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(modifier = Modifier.fillMaxSize().padding(bottom = 12.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
            ) {
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .background(
                            if (paused) MaterialTheme.colorScheme.onSurfaceVariant else FabricTheme.extras.threadActive,
                            RoundedCornerShape(4.dp),
                        ),
                )
                Text(
                    if (paused) "  Paused" else "  Live",
                    style = MaterialTheme.typography.labelMedium,
                )
                if (dimensions.isNotEmpty()) {
                    Text(
                        "  $dimensions",
                        style = MaterialTheme.typography.labelSmall,
                        fontFamily = FontFamily.Monospace,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    "read-only",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                    textAlign = androidx.compose.ui.text.style.TextAlign.End,
                )
                if (error == null) {
                    TextButton(onClick = { paused = !paused }) { Text(if (paused) "Resume" else "Pause") }
                }
                TextButton(onClick = onDismiss) { Text("Done") }
            }

            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                when {
                    error != null -> Text(
                        "Live view unavailable: $error",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(24.dp),
                    )
                    frame != null -> Image(
                        bitmap = frame!!,
                        contentDescription = "Live screen view",
                        modifier = Modifier.fillMaxWidth(),
                    )
                    else -> Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp))
                        Text("Connecting to the screen…")
                    }
                }
            }
        }
    }
}
