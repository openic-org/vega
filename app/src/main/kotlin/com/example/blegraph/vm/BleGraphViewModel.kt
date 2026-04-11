package com.example.blegraph.vm

import androidx.lifecycle.ViewModel
import com.example.blegraph.ble.BleManager
import com.example.blegraph.data.BluetoothDevice
import com.example.blegraph.data.TimeSeriesPoint
import kotlinx.coroutines.flow.StateFlow

class BleGraphViewModel(private val bleManager: BleManager) : ViewModel() {
    
    val isScanning: StateFlow<Boolean> = bleManager.isScanning
    val scannedDevices: StateFlow<List<BluetoothDevice>> = bleManager.scannedDevices
    val isConnected: StateFlow<Boolean> = bleManager.isConnected
    val connectedDeviceName: StateFlow<String?> = bleManager.connectedDeviceName

    // Multi-channel data flows
    val channel0Data: StateFlow<List<TimeSeriesPoint>> = bleManager.channel0Data
    val channel1Data: StateFlow<List<TimeSeriesPoint>> = bleManager.channel1Data
    val channel2Data: StateFlow<List<TimeSeriesPoint>> = bleManager.channel2Data
    val channel3Data: StateFlow<List<TimeSeriesPoint>> = bleManager.channel3Data

    // Display mode: downsampled (10s) vs full resolution (1s)
    val displayFullResolution: StateFlow<Boolean> = bleManager.displayFullResolution
    
    // Debug data: characteristic UUID, hex bytes, parsed value
    val debugData: StateFlow<BleManager.DebugData?> = bleManager.debugData
    
    // Packet counters
    val packetCounts: StateFlow<BleManager.PacketCounts> = bleManager.packetCounts

    fun startScanning() {
        bleManager.startScanning()
    }

    fun stopScanning() {
        bleManager.stopScanning()
    }

    fun connectToDevice(device: BluetoothDevice) {
        bleManager.connectToDevice(device.address, device.name)
    }

    fun disconnect() {
        bleManager.disconnect()
    }

    fun hasBluetoothPermissions(): Boolean {
        return bleManager.hasBluetoothPermissions()
    }

    fun generateSimulatedData() {
        bleManager.generateSimulatedData()
    }

    fun toggleDisplayMode() {
        bleManager.toggleDisplayMode()
    }
}
