package com.example.blegraph.ui

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.example.blegraph.vm.BleGraphViewModel
import com.example.blegraph.data.BluetoothDevice

@Composable
fun BleGraphScreen(viewModel: BleGraphViewModel) {
    val context = LocalContext.current
    val isScanning by viewModel.isScanning.collectAsState()
    val scannedDevices by viewModel.scannedDevices.collectAsState()
    val channel0Data by viewModel.channel0Data.collectAsState()
    val channel1Data by viewModel.channel1Data.collectAsState()
    val channel2Data by viewModel.channel2Data.collectAsState()
    val channel3Data by viewModel.channel3Data.collectAsState()
    val isConnected by viewModel.isConnected.collectAsState()
    val connectedDeviceName by viewModel.connectedDeviceName.collectAsState()
    val displayFullResolution by viewModel.displayFullResolution.collectAsState()
    val debugData by viewModel.debugData.collectAsState()
    val packetCounts by viewModel.packetCounts.collectAsState()
    val recordingInfo by viewModel.recordingInfo.collectAsState()
    val dataRate by viewModel.dataRate.collectAsState()
    val isRecording = recordingInfo.isRecording

    var numChannelsToDisplay by remember { mutableStateOf(4) }
    var channelDropdownExpanded by remember { mutableStateOf(false) }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        if (permissions.all { it.value }) {
            viewModel.startScanning()
        }
    }

    LaunchedEffect(Unit) {
        if (!viewModel.hasBluetoothPermissions()) {
            permissionLauncher.launch(
                arrayOf(
                    Manifest.permission.BLUETOOTH_CONNECT,
                    Manifest.permission.BLUETOOTH_SCAN,
                    Manifest.permission.ACCESS_FINE_LOCATION
                )
            )
        }
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        // ── Header ──────────────────────────────────────────────────────────
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "Vega",
                style = MaterialTheme.typography.headlineSmall
            )
            if (isConnected) {
                Text(
                    text = connectedDeviceName ?: "",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.Green
                )
            }
        }

        // ── Debug panel (connected only) ─────────────────────────────────────
        if (isConnected) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    Text("Debug Info", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary)

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(16.dp)
                    ) {
                        // Left column
                        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            val streaming = packetCounts.ch0 > 0
                            DebugItem("Status", if (streaming) "Streaming" else "Connected",
                                valueColor = if (streaming) Color(0xFF2E7D32) else Color.Gray)
                            DebugItem("Packets", packetCounts.ch0.toString())
                            DebugItem("Char", "0xFFF2 (notify)")
                            debugData?.let { d ->
                                if (d.parsedValue.isNotEmpty())
                                    DebugItem("Info", d.parsedValue)
                            }
                        }
                        // Right column
                        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            val pps  = dataRate.packetsPerSecond
                            val kbps = dataRate.kbitsPerSecond
                            if (pps > 0f) {
                                DebugItem("Rate", "%.1f pkt/s".format(pps))
                                DebugItem("Thru", "%.0f kbit/s".format(kbps))
                            } else {
                                DebugItem("Rate", "—")
                                DebugItem("Thru", "—")
                            }
                        }
                    }
                }
            }
        }

        // ── Controls — single row (4 buttons disconnected, 5 connected) ─────
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Button(
                onClick = {
                    if (isScanning) viewModel.stopScanning()
                    else viewModel.startScanning()
                },
                modifier = Modifier.weight(1f)
            ) {
                Text(if (isScanning) "Stop" else "Scan",
                    style = MaterialTheme.typography.labelSmall)
            }

            if (isConnected) {
                Button(
                    onClick = { viewModel.disconnect() },
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.error
                    ),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("Disconnect", style = MaterialTheme.typography.labelSmall)
                }
            }

            androidx.compose.foundation.layout.Box(modifier = Modifier.weight(1f)) {
                OutlinedButton(
                    onClick = { channelDropdownExpanded = true },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("CH: $numChannelsToDisplay", style = MaterialTheme.typography.labelSmall)
                }
                DropdownMenu(
                    expanded = channelDropdownExpanded,
                    onDismissRequest = { channelDropdownExpanded = false }
                ) {
                    for (n in 1..4) {
                        DropdownMenuItem(
                            text = { Text("$n channel${if (n > 1) "s" else ""}") },
                            onClick = { numChannelsToDisplay = n; channelDropdownExpanded = false }
                        )
                    }
                }
            }

            OutlinedButton(
                onClick = { viewModel.toggleDisplayMode() },
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.outlinedButtonColors(
                    containerColor = if (displayFullResolution)
                        MaterialTheme.colorScheme.primaryContainer else Color.Transparent
                )
            ) {
                Text(if (displayFullResolution) "0.5s" else "10s",
                    style = MaterialTheme.typography.labelSmall)
            }

            OutlinedButton(
                onClick = {
                    if (isRecording) viewModel.stopRecording()
                    else viewModel.startRecording()
                },
                enabled = isConnected,
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.outlinedButtonColors(
                    containerColor = if (isRecording) Color(0xFFFFCDD2) else Color.Transparent
                )
            ) {
                val label = if (isRecording) {
                    val m = recordingInfo.elapsedSec / 60
                    val s = recordingInfo.elapsedSec % 60
                    "■ %d:%02d".format(m, s)
                } else "● REC"
                Text(label, style = MaterialTheme.typography.labelSmall)
            }
        }

        // ── Recording status line ────────────────────────────────────────────
        val recStatusText = when {
            isRecording -> {
                val m = recordingInfo.elapsedSec / 60
                val s = recordingInfo.elapsedSec % 60
                "Recording  %d:%02d / 10:00  •  ~%d MB".format(m, s, recordingInfo.estimatedMb)
            }
            recordingInfo.autoStopped ->
                "Stopped automatically  •  %d:%02d  •  ~%d MB  •  saved to Downloads".format(
                    recordingInfo.elapsedSec / 60, recordingInfo.elapsedSec % 60, recordingInfo.estimatedMb)
            recordingInfo.elapsedSec > 0 ->
                "Last recording: %d:%02d  •  ~%d MB  •  saved to Downloads".format(
                    recordingInfo.elapsedSec / 60, recordingInfo.elapsedSec % 60, recordingInfo.estimatedMb)
            isConnected ->
                "Max 10 min  •  auto-stops if < 200 MB free"
            else -> null
        }
        if (recStatusText != null) {
            Text(
                text = recStatusText,
                style = MaterialTheme.typography.bodySmall,
                color = if (isRecording) Color(0xFFB71C1C) else Color.Gray,
                modifier = Modifier.padding(horizontal = 2.dp)
            )
        }

        // ── Scanning indicator ───────────────────────────────────────────────
        if (isScanning) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(4.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                CircularProgressIndicator(modifier = Modifier.padding(end = 8.dp))
                Text("Scanning for devices…")
            }
        }

        // ── Device list ──────────────────────────────────────────────────────
        if (scannedDevices.isNotEmpty() && !isConnected) {
            Text(
                text = "Available Devices (${scannedDevices.size})",
                style = MaterialTheme.typography.titleMedium
            )
            LazyColumn(
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.heightIn(max = 200.dp)
            ) {
                items(scannedDevices) { device ->
                    DeviceCard(device = device, onConnect = {
                        viewModel.connectToDevice(device)
                    })
                }
            }
        }

        // ── Graph ────────────────────────────────────────────────────────────
        if (isConnected || channel0Data.isNotEmpty()) {
            val windowSec = if (displayFullResolution) 0.5f else 10.0f
            val windowLabel = if (displayFullResolution) "0.5 s" else "10 s"
            Text(
                text = "$numChannelsToDisplay ch  •  $windowLabel  •  ${channel0Data.size} pts",
                style = MaterialTheme.typography.bodySmall,
                color = Color.Gray
            )
            MultiChannelGraphDisplay(
                channel0 = channel0Data,
                channel1 = channel1Data,
                channel2 = channel2Data,
                channel3 = channel3Data,
                numChannels = numChannelsToDisplay,
                windowDurationSec = windowSec,
                modifier = Modifier.fillMaxWidth().weight(1f)
            )
        }
    }
}

@Composable
private fun DebugItem(label: String, value: String, valueColor: Color = Color.Unspecified) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = "$label:",
            style = MaterialTheme.typography.labelSmall,
            color = Color.Gray
        )
        Text(
            text = value,
            style = MaterialTheme.typography.labelSmall,
            color = valueColor
        )
    }
}

@Composable
fun DeviceCard(device: BluetoothDevice, onConnect: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 0.dp, vertical = 4.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = device.name ?: "Unknown Device",
                    style = MaterialTheme.typography.titleSmall
                )
                Text(text = device.address, style = MaterialTheme.typography.bodySmall)
                Text(text = "RSSI: ${device.rssi} dBm", style = MaterialTheme.typography.bodySmall)
            }
            Button(onClick = onConnect) {
                Text("Connect")
            }
        }
    }
}

@Composable
fun MultiChannelGraphDisplay(
    channel0: List<com.example.blegraph.data.TimeSeriesPoint>,
    channel1: List<com.example.blegraph.data.TimeSeriesPoint>,
    channel2: List<com.example.blegraph.data.TimeSeriesPoint>,
    channel3: List<com.example.blegraph.data.TimeSeriesPoint>,
    numChannels: Int = 4,
    windowDurationSec: Float = 10f,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        if (numChannels >= 1) TimeSeriesGraph(
            dataPoints = channel0, channelName = "CH0", lineColor = Color.Red,
            windowDurationSec = windowDurationSec,
            modifier = Modifier.fillMaxWidth().weight(1f)
        )
        if (numChannels >= 2) TimeSeriesGraph(
            dataPoints = channel1, channelName = "CH1", lineColor = Color.Green,
            windowDurationSec = windowDurationSec,
            modifier = Modifier.fillMaxWidth().weight(1f)
        )
        if (numChannels >= 3) TimeSeriesGraph(
            dataPoints = channel2, channelName = "CH2", lineColor = Color.Blue,
            windowDurationSec = windowDurationSec,
            modifier = Modifier.fillMaxWidth().weight(1f)
        )
        if (numChannels >= 4) TimeSeriesGraph(
            dataPoints = channel3, channelName = "CH3", lineColor = Color.Magenta,
            windowDurationSec = windowDurationSec,
            modifier = Modifier.fillMaxWidth().weight(1f)
        )
    }
}
