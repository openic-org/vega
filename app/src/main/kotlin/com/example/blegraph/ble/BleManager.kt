package com.example.blegraph.ble

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.content.Context
import android.content.pm.PackageManager
import android.util.Log
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

private const val TAG = "BleManager"

// Configuration for circular buffer
// 10 kHz sampling rate, stores 2 seconds of data (largest window displayed)
private const val SAMPLE_RATE_HZ = 10000  // 10 kHz
private const val BUFFER_DURATION_SECONDS = 2
private const val BUFFER_SIZE = SAMPLE_RATE_HZ * BUFFER_DURATION_SECONDS  // 20,000 points = 2 seconds at 10 kHz
private const val POINTS_PER_BATCH = 1000  // Receive 1000 points per 100ms (10 kHz * 0.1s)
private const val BATCH_INTERVAL_MS = 100L  // 100ms between batches
private const val NUM_CHANNELS = 4

// Display window sizes (in sample points at 10 kHz)
private const val FULL_RESOLUTION_WINDOW_POINTS = 5000  // 0.5 seconds at 10 kHz
private const val DOWNSAMPLED_WINDOW_POINTS = 20000  // 2 seconds at 10 kHz (entire buffer)

// Downsampling for visualization (to keep rendering fast)
private const val DOWNSAMPLING_FACTOR_DISPLAY = 100  // Show 1 point per 100 samples (10 kHz / 100 = 100 Hz display)

class BleManager(private val context: Context) {
    private val bluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
    private val bluetoothAdapter = bluetoothManager?.adapter

    private val _isBluetoothEnabled = MutableStateFlow(bluetoothAdapter?.isEnabled ?: false)
    val isBluetoothEnabled: StateFlow<Boolean> = _isBluetoothEnabled

    private val _isScanning = MutableStateFlow(false)
    val isScanning: StateFlow<Boolean> = _isScanning

    private val _scannedDevices = MutableStateFlow<List<com.example.blegraph.data.BluetoothDevice>>(emptyList())
    val scannedDevices: StateFlow<List<com.example.blegraph.data.BluetoothDevice>> = _scannedDevices

    // Multi-channel circular FIFO buffer: 100 points * 100ms = 10 seconds, 4 channels each
    private val multiChannelBuffer = com.example.blegraph.data.CircularMultiChannelBuffer(BUFFER_SIZE)
    
    // StateFlows for each channel
    private val _channel0Data = MutableStateFlow<List<com.example.blegraph.data.TimeSeriesPoint>>(emptyList())
    val channel0Data: StateFlow<List<com.example.blegraph.data.TimeSeriesPoint>> = _channel0Data

    private val _channel1Data = MutableStateFlow<List<com.example.blegraph.data.TimeSeriesPoint>>(emptyList())
    val channel1Data: StateFlow<List<com.example.blegraph.data.TimeSeriesPoint>> = _channel1Data

    private val _channel2Data = MutableStateFlow<List<com.example.blegraph.data.TimeSeriesPoint>>(emptyList())
    val channel2Data: StateFlow<List<com.example.blegraph.data.TimeSeriesPoint>> = _channel2Data

    private val _channel3Data = MutableStateFlow<List<com.example.blegraph.data.TimeSeriesPoint>>(emptyList())
    val channel3Data: StateFlow<List<com.example.blegraph.data.TimeSeriesPoint>> = _channel3Data

    private val _isConnected = MutableStateFlow(false)
    val isConnected: StateFlow<Boolean> = _isConnected

    private val _connectedDeviceName = MutableStateFlow<String?>(null)
    val connectedDeviceName: StateFlow<String?> = _connectedDeviceName

    // Display mode: true = full resolution (1 second), false = downsampled (10 seconds)
    private val _displayFullResolution = MutableStateFlow(false)
    val displayFullResolution: StateFlow<Boolean> = _displayFullResolution

    private val scope = CoroutineScope(Dispatchers.Main + Job())
    private var activeScanCallback: android.bluetooth.le.ScanCallback? = null

    fun hasBluetoothPermissions(): Boolean {
        return ContextCompat.checkSelfPermission(
            context,
            android.Manifest.permission.BLUETOOTH_CONNECT
        ) == PackageManager.PERMISSION_GRANTED &&
                ContextCompat.checkSelfPermission(
                    context,
                    android.Manifest.permission.BLUETOOTH_SCAN
                ) == PackageManager.PERMISSION_GRANTED &&
                ContextCompat.checkSelfPermission(
                    context,
                    android.Manifest.permission.ACCESS_FINE_LOCATION
                ) == PackageManager.PERMISSION_GRANTED
    }

    @SuppressLint("MissingPermission")
    fun startScanning() {
        try {
            if (!hasBluetoothPermissions()) {
                Log.w(TAG, "Missing Bluetooth permissions")
                return
            }
            if (_isScanning.value) {
                Log.d(TAG, "Scan already in progress")
                return
            }

            if (bluetoothAdapter == null) {
                Log.e(TAG, "Bluetooth adapter is null")
                return
            }

            val scanner = bluetoothAdapter.bluetoothLeScanner
            if (scanner == null) {
                Log.e(TAG, "Bluetooth LE scanner is not available")
                return
            }

            _isScanning.value = true
            _scannedDevices.value = emptyList()
            Log.d(TAG, "Starting BLE scan")

            val scanSettings = android.bluetooth.le.ScanSettings.Builder()
                .setScanMode(android.bluetooth.le.ScanSettings.SCAN_MODE_LOW_LATENCY)
                .build()

            activeScanCallback = object : android.bluetooth.le.ScanCallback() {
                override fun onScanResult(callbackType: Int, result: android.bluetooth.le.ScanResult?) {
                    result?.let {
                        val device = com.example.blegraph.data.BluetoothDevice(
                            address = it.device.address,
                            name = it.device.name ?: "Unknown",
                            rssi = it.rssi
                        )
                        val currentList = _scannedDevices.value.toMutableList()
                        val existingIndex = currentList.indexOfFirst { d -> d.address == device.address }
                        if (existingIndex >= 0) {
                            currentList[existingIndex] = device
                        } else {
                            currentList.add(device)
                        }
                        _scannedDevices.value = currentList
                        Log.d(TAG, "Found device: ${device.name} (${device.address})")
                    }
                }

                override fun onScanFailed(errorCode: Int) {
                    Log.e(TAG, "Scan failed with error code: $errorCode")
                    _isScanning.value = false
                }
            }

            scanner.startScan(null, scanSettings, activeScanCallback!!)
        } catch (e: Exception) {
            Log.e(TAG, "Error starting scan: ${e.message}", e)
            _isScanning.value = false
        }
    }

    @SuppressLint("MissingPermission")
    fun stopScanning() {
        try {
            if (!hasBluetoothPermissions()) return
            if (!_isScanning.value) return

            val scanner = bluetoothAdapter?.bluetoothLeScanner
            if (scanner != null && activeScanCallback != null) {
                scanner.stopScan(activeScanCallback!!)
                Log.d(TAG, "Stopped BLE scan")
            }
            _isScanning.value = false
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping scan: ${e.message}", e)
        }
    }

    @SuppressLint("MissingPermission")
    fun connectToDevice(deviceAddress: String, deviceName: String?) {
        try {
            if (!hasBluetoothPermissions()) return

            val device = bluetoothAdapter?.getRemoteDevice(deviceAddress)
            if (device == null) {
                Log.e(TAG, "Device not found: $deviceAddress")
                return
            }

            _isConnected.value = true
            _connectedDeviceName.value = deviceName ?: deviceAddress
            Log.d(TAG, "Connected to device: ${deviceName ?: deviceAddress}")
            
            simulateDataReception()
        } catch (e: Exception) {
            Log.e(TAG, "Error connecting to device: ${e.message}", e)
        }
    }

    fun disconnect() {
        try {
            _isConnected.value = false
            _connectedDeviceName.value = null
            multiChannelBuffer.clear()
            updateChannelFlows()
            Log.d(TAG, "Disconnected from device")
        } catch (e: Exception) {
            Log.e(TAG, "Error disconnecting: ${e.message}", e)
        }
    }

    /**
     * Toggle between downsampled (2 seconds) and full resolution (0.5 seconds) display modes.
     * Full resolution: shows 5,000 raw points at 10 kHz (0.5 second window)
     * Downsampled: shows 200 points at 100 Hz (2 second window)
     */
    fun toggleDisplayMode() {
        _displayFullResolution.value = !_displayFullResolution.value
        val mode = if (_displayFullResolution.value) "Full Resolution (0.5s)" else "Downsampled (2s)"
        Log.d(TAG, "Display mode changed to: $mode")
        updateChannelFlows()
    }

    /**
     * Add a multi-channel data point to the circular buffer.
     * Call this for each 100ms interval with values from all 4 channels.
     * Automatically maintains exactly 100 points (10 seconds at 100ms intervals).
     * When full, oldest data (FIFO) is replaced.
     */
    fun addMultiChannelDataPoint(channel0: Float, channel1: Float, channel2: Float, channel3: Float) {
        multiChannelBuffer.addPoint(channel0, channel1, channel2, channel3)
        updateChannelFlows()
        Log.d(TAG, "Multi-channel data added: [%.1f, %.1f, %.1f, %.1f], buffer_size=${multiChannelBuffer.size()}".format(channel0, channel1, channel2, channel3))
    }

    /**
     * Update all channel StateFlows from the multi-channel buffer.
     * Uses window size and downsampling based on display mode:
     * - Full Resolution: 5,000 points (0.5 seconds @ 10 kHz), no downsampling
     * - Downsampled: 20,000 points (2 seconds @ 10 kHz), factor=100 downsampling
     */
    private fun updateChannelFlows() {
        if (_displayFullResolution.value) {
            // Full resolution: show last 0.5 seconds (5,000 points), no downsampling
            _channel0Data.value = multiChannelBuffer.getChannelWindow(0, FULL_RESOLUTION_WINDOW_POINTS, 1)
            _channel1Data.value = multiChannelBuffer.getChannelWindow(1, FULL_RESOLUTION_WINDOW_POINTS, 1)
            _channel2Data.value = multiChannelBuffer.getChannelWindow(2, FULL_RESOLUTION_WINDOW_POINTS, 1)
            _channel3Data.value = multiChannelBuffer.getChannelWindow(3, FULL_RESOLUTION_WINDOW_POINTS, 1)
        } else {
            // Downsampled: show last 2 seconds (20,000 points), with 100x downsampling = 200 points
            _channel0Data.value = multiChannelBuffer.getChannelWindow(0, DOWNSAMPLED_WINDOW_POINTS, DOWNSAMPLING_FACTOR_DISPLAY)
            _channel1Data.value = multiChannelBuffer.getChannelWindow(1, DOWNSAMPLED_WINDOW_POINTS, DOWNSAMPLING_FACTOR_DISPLAY)
            _channel2Data.value = multiChannelBuffer.getChannelWindow(2, DOWNSAMPLED_WINDOW_POINTS, DOWNSAMPLING_FACTOR_DISPLAY)
            _channel3Data.value = multiChannelBuffer.getChannelWindow(3, DOWNSAMPLED_WINDOW_POINTS, DOWNSAMPLING_FACTOR_DISPLAY)
        }
    }

    /**
     * Simulate real-time multi-channel data reception at 10 kHz.
     * Each batch (every 100ms) contains 1000 data points (4 channels each).
     * Maintains continuous 10-second window of data (100,000 points per channel).
     */
    private fun simulateDataReception() {
        scope.launch {
            multiChannelBuffer.clear()
            updateChannelFlows()
            
            var globalCounter = 0
            
            while (_isConnected.value) {
                // Generate batch of POINTS_PER_BATCH (1000) points
                for (batch in 0 until POINTS_PER_BATCH) {
                    val timeIndex = globalCounter + batch
                    
                    // Generate 4 different sine waves with different phases for each channel
                    val ch0 = (Math.sin(timeIndex * 0.002) * 40 + 50).toFloat()
                    val ch1 = (Math.sin(timeIndex * 0.002 + Math.PI / 2) * 40 + 50).toFloat()
                    val ch2 = (Math.sin(timeIndex * 0.002 + Math.PI) * 40 + 50).toFloat()
                    val ch3 = (Math.sin(timeIndex * 0.002 + 3 * Math.PI / 2) * 40 + 50).toFloat()
                    
                    // Add directly to buffer without triggering update yet
                    multiChannelBuffer.addPoint(ch0, ch1, ch2, ch3)
                }
                
                globalCounter += POINTS_PER_BATCH
                // Update display only once per batch (not per point)
                updateChannelFlows()
                Log.d(TAG, "Batch received: $POINTS_PER_BATCH points added, total: ${multiChannelBuffer.size()}")
                delay(BATCH_INTERVAL_MS)
            }
        }
    }

    /**
     * Generate multi-channel simulated data points (100,000 per channel at 10 kHz = 10 seconds total).
     * Processes data in batches of 1000 points (1 batch per 100ms).
     * Creates 4 different sine waves with individual characteristics.
     */
    fun generateSimulatedData() {
        Log.d(TAG, "Generating $BUFFER_SIZE multi-channel simulated data points (${BUFFER_SIZE / SAMPLE_RATE_HZ} seconds at $SAMPLE_RATE_HZ Hz)")
        multiChannelBuffer.clear()
        updateChannelFlows()
        
        scope.launch {
            var pointsGenerated = 0
            
            while (pointsGenerated < BUFFER_SIZE) {
                // Generate batch of POINTS_PER_BATCH points
                val batchSize = minOf(POINTS_PER_BATCH, BUFFER_SIZE - pointsGenerated)
                
                for (i in 0 until batchSize) {
                    val timeIndex = pointsGenerated + i
                    
                    // Generate 4 different sine waves with different frequencies and noise
                    val ch0 = (Math.sin(timeIndex * 0.001) * 30 + 50 + (Math.random() * 3 - 1.5)).toFloat()
                    val ch1 = (Math.cos(timeIndex * 0.001) * 30 + 50 + (Math.random() * 3 - 1.5)).toFloat()
                    val ch2 = (Math.sin(timeIndex * 0.0015) * 30 + 50 + (Math.random() * 3 - 1.5)).toFloat()
                    val ch3 = (Math.cos(timeIndex * 0.0015) * 30 + 50 + (Math.random() * 3 - 1.5)).toFloat()
                    
                    // Add directly to buffer without triggering update yet
                    multiChannelBuffer.addPoint(ch0, ch1, ch2, ch3)
                }
                
                pointsGenerated += batchSize
                // Update display only once per batch (not per point)
                updateChannelFlows()
                Log.d(TAG, "Generated batch: $pointsGenerated/$BUFFER_SIZE points")
                delay(10) // Small delay between batches to simulate real-time reception
            }
            Log.d(TAG, "Simulation complete: ${multiChannelBuffer.size()} points generated for each of $NUM_CHANNELS channels")
        }
    }
}
