package com.example.blegraph.ui

import android.Manifest
import android.content.pm.PackageManager
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
import androidx.core.content.ContextCompat
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

    // State for number of channels to display
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
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // Header with connection status
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "BLE Time-Series Graph",
                style = MaterialTheme.typography.headlineSmall
            )
            if (isConnected) {
                Text(
                    text = "Connected: $connectedDeviceName",
                    style = MaterialTheme.typography.bodySmall
                )
            }
        }

        // Scan controls
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Button(
                onClick = {
                    if (isScanning) viewModel.stopScanning()
                    else viewModel.startScanning()
                },
                modifier = Modifier
                    .weight(1f)
            ) {
                if (isScanning) {
                    Text("Stop Scanning")
                } else {
                    Text("Scan")
                }
            }

            Button(
                onClick = { viewModel.generateSimulatedData() },
                modifier = Modifier.weight(1f)
            ) {
                Text("Simulate")
            }

            if (isConnected) {
                Button(
                    onClick = { viewModel.disconnect() },
                    modifier = Modifier.weight(1f)
                ) {
                    Text("Disconnect")
                }
            }
        }

        // Channel selection and display resolution controls
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            androidx.compose.material3.OutlinedButton(
                onClick = { channelDropdownExpanded = true },
                modifier = Modifier.weight(1f)
            ) {
                Text("Channels: $numChannelsToDisplay")
            }

            DropdownMenu(
                expanded = channelDropdownExpanded,
                onDismissRequest = { channelDropdownExpanded = false }
            ) {
                for (numChannels in 1..4) {
                    DropdownMenuItem(
                        text = { Text("$numChannels Channel${if (numChannels > 1) "s" else ""}") },
                        onClick = {
                            numChannelsToDisplay = numChannels
                            channelDropdownExpanded = false
                        }
                    )
                }
            }

            OutlinedButton(
                onClick = { viewModel.toggleDisplayMode() },
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.outlinedButtonColors(
                    containerColor = if (displayFullResolution) MaterialTheme.colorScheme.primaryContainer else Color.Transparent
                )
            ) {
                Text(if (displayFullResolution) "0.5s" else "2s")
            }
        }

        // Scanning indicator
        if (isScanning) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                CircularProgressIndicator(
                    modifier = Modifier.padding(end = 8.dp)
                )
                Text("Scanning for devices...")
            }
        }

        // Devices list
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

        // Multi-channel graphs
        if (isConnected || channel0Data.isNotEmpty()) {
            val timeWindow = if (displayFullResolution) "0.5 second" else "2 seconds"
            Text(
                text = "Signal Data - $numChannelsToDisplay Channel${if (numChannelsToDisplay > 1) "s" else ""} ($timeWindow, ${channel0Data.size} points)",
                style = MaterialTheme.typography.titleMedium
            )
            MultiChannelGraphDisplay(
                channel0 = channel0Data,
                channel1 = channel1Data,
                channel2 = channel2Data,
                channel3 = channel3Data,
                numChannels = numChannelsToDisplay,
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
            )
        }
    }
}

@Composable
fun DeviceCard(device: BluetoothDevice, onConnect: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(8.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(
                modifier = Modifier.weight(1f)
            ) {
                Text(
                    text = device.name ?: "Unknown Device",
                    style = MaterialTheme.typography.titleSmall
                )
                Text(
                    text = device.address,
                    style = MaterialTheme.typography.bodySmall
                )
                Text(
                    text = "RSSI: ${device.rssi} dBm",
                    style = MaterialTheme.typography.bodySmall
                )
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
    modifier: Modifier = Modifier
) {
    androidx.compose.foundation.layout.Column(
        modifier = modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        if (numChannels >= 1) {
            // Channel 0 - Red
            TimeSeriesGraph(
                dataPoints = channel0,
                channelName = "Channel 0",
                lineColor = Color.Red,
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
            )
        }

        if (numChannels >= 2) {
            // Channel 1 - Green
            TimeSeriesGraph(
                dataPoints = channel1,
                channelName = "Channel 1",
                lineColor = Color.Green,
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
            )
        }

        if (numChannels >= 3) {
            // Channel 2 - Blue
            TimeSeriesGraph(
                dataPoints = channel2,
                channelName = "Channel 2",
                lineColor = Color.Blue,
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
            )
        }

        if (numChannels >= 4) {
            // Channel 3 - Magenta
            TimeSeriesGraph(
                dataPoints = channel3,
                channelName = "Channel 3",
                lineColor = Color.Magenta,
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
            )
        }
    }
}
