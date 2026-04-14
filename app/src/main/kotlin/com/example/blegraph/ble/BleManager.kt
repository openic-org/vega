package com.example.blegraph.ble

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Environment
import android.os.StatFs
import android.provider.MediaStore
import android.util.Log
import androidx.core.content.ContextCompat
import java.io.BufferedWriter
import java.io.OutputStreamWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

private const val TAG = "BleManager"

// Sampling rate and buffer configuration for the STM32 stream (30 kSps per channel)
private const val SAMPLE_RATE_HZ              = 30_000
private const val BUFFER_DURATION_SECONDS     = 10
private const val BUFFER_SIZE                 = SAMPLE_RATE_HZ * BUFFER_DURATION_SECONDS  // 300 000 points (10 s)
private const val NUM_CHANNELS                = 4

// Display windows
private const val FULL_RESOLUTION_WINDOW_POINTS  = 15_000   // 0.5 s at 30 kSps (full data rate, no decimation)
private const val DOWNSAMPLED_WINDOW_POINTS      = 300_000  // 10.0 s at 30 kSps (full buffer, decimated)
private const val DOWNSAMPLING_FACTOR_DISPLAY    = 100      // 300 000 / 100 = 3 000 points on screen

// Recording limits
// Write rate: 30 000 sps × ~23 bytes/row ≈ 690 KB/s ≈ 41 MB/min
private const val MAX_RECORDING_SECONDS  = 10 * 60              // 10-minute hard cap → max ~410 MB
private const val MIN_FREE_STORAGE_BYTES = 200L * 1_024 * 1_024 // stop if < 200 MB free
private const val BYTES_PER_SAMPLE_ROW   = 23L                  // conservative estimate for MB counter

// Throttle UI refresh to ~30 fps to avoid overwhelming the Compose renderer
private const val UI_REFRESH_INTERVAL_MS      = 33L

// Auto-reconnect: wait this long after a disconnect before attempting
private const val RECONNECT_DELAY_MS          = 1_500L

// Legacy simulation constants (Android-side demo, separate from STM32 simulation)
private const val BATCH_INTERVAL_MS           = 100L
private const val POINTS_PER_BATCH            = 1000

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
    
    // GATT connection manager
    private var gattManager: BleGattManager? = null

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

    // Display mode: true = full resolution (0.5 s), false = downsampled (2 s)
    private val _displayFullResolution = MutableStateFlow(false)
    val displayFullResolution: StateFlow<Boolean> = _displayFullResolution

    // Debug / status string for the UI overlay
    data class DebugData(
        val characteristicUuid: String,
        val hexBytes: String,
        val parsedValue: String,
        val timestamp: Long = System.currentTimeMillis()
    )

    data class PacketCounts(
        val ch0: Long = 0L,
        val ch1: Long = 0L,
        val ch2: Long = 0L,
        val ch3: Long = 0L
    )

    /**
     * Live state of an in-progress or just-finished recording.
     *
     * @param isRecording   True while the CSV file is open and being written.
     * @param elapsedSec    Seconds since [startRecording] was called.
     * @param estimatedMb   Approximate file size so far (based on [BYTES_PER_SAMPLE_ROW]).
     * @param autoStopped   True if the recording was ended automatically (time/storage limit).
     */
    data class RecordingInfo(
        val isRecording: Boolean = false,
        val elapsedSec:  Int     = 0,
        val estimatedMb: Int     = 0,
        val autoStopped: Boolean = false
    )

    private val _debugData = MutableStateFlow<DebugData?>(null)
    val debugData: StateFlow<DebugData?> = _debugData

    private val _packetCounts = MutableStateFlow(PacketCounts())
    val packetCounts: StateFlow<PacketCounts> = _packetCounts

    // Auto-reconnect state
    private var lastDeviceAddress: String? = null
    private var lastDeviceName: String?    = null
    private var shouldAutoReconnect        = false

    // UI refresh throttle
    private var lastUiUpdateMs = 0L

    // Packet statistics
    private var totalBlePackets = 0L

    // CSV recording
    // recordingWriter is written from the Main thread (start/stop) and read from the parser
    // coroutine (Dispatchers.Default). @Volatile + read-once local ref keeps this race-free.
    private val _recordingInfo = MutableStateFlow(RecordingInfo())
    val recordingInfo: StateFlow<RecordingInfo> = _recordingInfo

    @Volatile private var recordingWriter: BufferedWriter? = null
    @Volatile private var recordingUri: Uri? = null
    @Volatile private var recordingSamplesWritten = 0L
    private var recordingStartMs  = 0L
    private var recordingMonitorJob: Job? = null

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

            // Prevent multiple simultaneous connections
            if (gattManager != null) {
                Log.w(TAG, "⚠️ Already connecting to a device, disconnect first before connecting to another")
                return
            }

            _connectedDeviceName.value = deviceName ?: deviceAddress
            lastDeviceAddress          = deviceAddress
            lastDeviceName             = deviceName
            shouldAutoReconnect        = true
            Log.d(TAG, "Connecting to: ${deviceName ?: deviceAddress}")

            gattManager = BleGattManager(
                context = context,
                bluetoothAdapter = bluetoothAdapter,
                onBatchReceived = { ch0, ch1, header ->
                    onBatchDataReceived(ch0, ch1, header)
                },
                onConnectionStateChange = { isConn, message ->
                    _isConnected.value = isConn
                    Log.d(TAG, "BLE: $message")
                    if (!isConn && shouldAutoReconnect) {
                        scheduleReconnect()
                    }
                },
                onError = { msg ->
                    Log.e(TAG, "BLE error: $msg")
                },
                onDebugInfo = { info ->
                    _debugData.value = DebugData("stream/0xFFF2", "", info)
                }
            )

            gattManager?.connect(deviceAddress)
            
        } catch (e: Exception) {
            Log.e(TAG, "Error connecting to device: ${e.message}", e)
        }
    }

    /**
     * Open a new CSV file in the device's Downloads folder and begin writing every
     * received sample at full rate (30 kSps × 2 channels).
     *
     * File format:
     *   timestamp_us,ch0,ch1
     *   <µs since MCU boot>,<int16>,<int16>
     *   ...
     *
     * Recording is automatically stopped after [MAX_RECORDING_SECONDS] (10 min, ~410 MB)
     * or when available storage drops below [MIN_FREE_STORAGE_BYTES] (200 MB).
     */
    fun startRecording() {
        if (_recordingInfo.value.isRecording) return
        try {
            val ts       = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            val fileName = "vega_$ts.csv"

            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, fileName)
                put(MediaStore.Downloads.MIME_TYPE, "text/csv")
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = context.contentResolver.insert(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI, values
            ) ?: run { Log.e(TAG, "Recording: failed to create MediaStore entry"); return }

            val os = context.contentResolver.openOutputStream(uri)
                ?: run { Log.e(TAG, "Recording: failed to open output stream"); return }

            recordingUri            = uri
            recordingSamplesWritten = 0L
            recordingStartMs        = System.currentTimeMillis()
            recordingWriter         = BufferedWriter(OutputStreamWriter(os), 1 shl 16)
            recordingWriter!!.write("timestamp_us,ch0,ch1\n")
            _recordingInfo.value    = RecordingInfo(isRecording = true)
            Log.i(TAG, "Recording started → Downloads/$fileName  (max ${MAX_RECORDING_SECONDS / 60} min)")

            // Monitor elapsed time, estimated size, and storage every second.
            recordingMonitorJob = scope.launch {
                var lastStorageCheckSec = 0
                while (_recordingInfo.value.isRecording) {
                    delay(1_000L)
                    if (!_recordingInfo.value.isRecording) break

                    val elapsedSec  = ((System.currentTimeMillis() - recordingStartMs) / 1_000L).toInt()
                    val estimatedMb = (recordingSamplesWritten * BYTES_PER_SAMPLE_ROW / (1_024 * 1_024)).toInt()
                    _recordingInfo.value = RecordingInfo(
                        isRecording = true,
                        elapsedSec  = elapsedSec,
                        estimatedMb = estimatedMb
                    )

                    // Hard time cap
                    if (elapsedSec >= MAX_RECORDING_SECONDS) {
                        Log.w(TAG, "Recording auto-stopped: ${MAX_RECORDING_SECONDS / 60}-min limit reached")
                        stopRecordingInternal(autoStopped = true)
                        break
                    }

                    // Storage guard — check every 10 s
                    if (elapsedSec - lastStorageCheckSec >= 10) {
                        lastStorageCheckSec = elapsedSec
                        val stat      = StatFs(Environment.getExternalStorageDirectory().absolutePath)
                        val freeBytes = stat.availableBlocksLong * stat.blockSizeLong
                        if (freeBytes < MIN_FREE_STORAGE_BYTES) {
                            Log.w(TAG, "Recording auto-stopped: only ${freeBytes / 1_024 / 1_024} MB free")
                            stopRecordingInternal(autoStopped = true)
                            break
                        }
                    }
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "startRecording: ${e.message}", e)
        }
    }

    /** Stop recording on user request. No-op if not recording. */
    fun stopRecording() = stopRecordingInternal(autoStopped = false)

    /**
     * Flush, close, and publish the CSV file.
     * Sets [RecordingInfo.autoStopped] so the UI can distinguish user stop from limit stop.
     */
    private fun stopRecordingInternal(autoStopped: Boolean) {
        if (!_recordingInfo.value.isRecording) return

        recordingMonitorJob?.cancel()
        recordingMonitorJob = null

        // Snapshot counters before clearing writer (parser may still be mid-write)
        val finalElapsed = _recordingInfo.value.elapsedSec
        val finalMb      = _recordingInfo.value.estimatedMb

        // Null the writer first — the parser coroutine sees null and stops appending rows
        val writer = recordingWriter
        recordingWriter = null

        try {
            writer?.close()
            recordingUri?.let { uri ->
                val values = ContentValues().apply {
                    put(MediaStore.Downloads.IS_PENDING, 0)
                }
                context.contentResolver.update(uri, values, null, null)
                val reason = if (autoStopped) " (auto-stopped)" else ""
                Log.i(TAG, "Recording saved: $recordingSamplesWritten samples$reason")
            }
        } catch (e: Exception) {
            Log.e(TAG, "stopRecording: ${e.message}", e)
        } finally {
            recordingUri = null
        }

        _recordingInfo.value = RecordingInfo(
            isRecording = false,
            elapsedSec  = finalElapsed,
            estimatedMb = finalMb,
            autoStopped = autoStopped
        )
    }

    fun disconnect() {
        try {
            shouldAutoReconnect = false
            stopRecording()          // finalise any active CSV before tearing down the stream
            gattManager?.disconnect()
            gattManager = null
            _isConnected.value = false
            _connectedDeviceName.value = null
            multiChannelBuffer.clear()
            updateChannelFlows()
            Log.d(TAG, "Disconnected")
        } catch (e: Exception) {
            Log.e(TAG, "Error disconnecting: ${e.message}", e)
        }
    }

    /**
     * Called for each received BLE notification packet.
     * Inserts all sample pairs from the packet into the circular buffer
     * and throttles the UI update to ~30 fps.
     *
     * Timestamp formula (little-endian STM32 HAL_GetTick-based clock):
     *   packetBaseUs = timestampS × 1_000_000 + timestampSubS × 1_000 / 32
     *   sampleUs     = packetBaseUs + i × 1_000_000 / 30_000
     *
     * timestampSubS encodes ms%1000 × 32 (range 0–31999), so dividing by 32 gives ms,
     * then × 1000 converts to µs.
     */
    private fun onBatchDataReceived(ch0: ShortArray, ch1: ShortArray, header: StreamPacketHeader) {
        totalBlePackets++

        val packetBaseUs = header.timestampS * 1_000_000L +
                           header.timestampSubS.toLong() * 1_000L / 32L

        // Feed all pairs from this packet into channels 0 and 1 (ch2/ch3 = 0)
        // and optionally stream each sample to the active CSV recording.
        val writer = recordingWriter   // local ref — safe even if stopRecording() runs concurrently
        for (i in ch0.indices) {
            val sampleUs = packetBaseUs + i.toLong() * 1_000_000L / SAMPLE_RATE_HZ
            multiChannelBuffer.addPoint(ch0[i].toFloat(), ch1[i].toFloat(), 0f, 0f, sampleUs)
            writer?.write("$sampleUs,${ch0[i]},${ch1[i]}\n")
        }
        if (writer != null) recordingSamplesWritten += ch0.size

        // Throttle UI refresh to ~30 fps
        val now = System.currentTimeMillis()
        if (now - lastUiUpdateMs >= UI_REFRESH_INTERVAL_MS) {
            lastUiUpdateMs = now
            updateChannelFlows()
            _packetCounts.value = PacketCounts(ch0 = totalBlePackets)
        }

        if (totalBlePackets % 500L == 0L) {
            Log.d(TAG, "BLE packets=$totalBlePackets  bufSize=${multiChannelBuffer.size()}  seq=${header.seqNum}")
        }
    }

    /** Schedule an auto-reconnect attempt after a short delay. */
    private fun scheduleReconnect() {
        val addr = lastDeviceAddress ?: return
        val name = lastDeviceName
        scope.launch {
            delay(RECONNECT_DELAY_MS)
            if (!_isConnected.value && shouldAutoReconnect) {
                Log.d(TAG, "Auto-reconnecting to $addr")
                gattManager?.disconnect()
                gattManager = null
                connectToDevice(addr, name)
            }
        }
    }

    /**
     * Toggle between downsampled (2 seconds) and full resolution (0.5 seconds) display modes.
     * Full resolution: shows 5,000 raw points at 10 kHz (0.5 second window)
     * Downsampled: shows 200 points at 100 Hz (2 second window)
     */
    fun toggleDisplayMode() {
        _displayFullResolution.value = !_displayFullResolution.value
        val mode = if (_displayFullResolution.value) "Full Resolution (0.3s)" else "Decimated (3s)"
        Log.d(TAG, "Display mode changed to: $mode")
        updateChannelFlows()
    }

    /**
     * Add a multi-channel data point to the circular buffer.
     * Call this for each 100ms interval with values from all 4 channels.
     * Automatically maintains exactly 100 points (10 seconds at 100ms intervals).
     * When full, oldest data (FIFO) is replaced.
     */
    fun addMultiChannelDataPoint(channel0: Float, channel1: Float, channel2: Float, channel3: Float, timestampUs: Long) {
        multiChannelBuffer.addPoint(channel0, channel1, channel2, channel3, timestampUs)
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
                    val sampleUs  = timeIndex.toLong() * 1_000_000L / SAMPLE_RATE_HZ

                    // Generate 4 different sine waves with different phases for each channel
                    val ch0 = (Math.sin(timeIndex * 0.002) * 40 + 50).toFloat()
                    val ch1 = (Math.sin(timeIndex * 0.002 + Math.PI / 2) * 40 + 50).toFloat()
                    val ch2 = (Math.sin(timeIndex * 0.002 + Math.PI) * 40 + 50).toFloat()
                    val ch3 = (Math.sin(timeIndex * 0.002 + 3 * Math.PI / 2) * 40 + 50).toFloat()

                    multiChannelBuffer.addPoint(ch0, ch1, ch2, ch3, sampleUs)
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
                    val sampleUs  = timeIndex.toLong() * 1_000_000L / SAMPLE_RATE_HZ

                    // Generate 4 different sine waves with different frequencies and noise
                    val ch0 = (Math.sin(timeIndex * 0.001) * 30 + 50 + (Math.random() * 3 - 1.5)).toFloat()
                    val ch1 = (Math.cos(timeIndex * 0.001) * 30 + 50 + (Math.random() * 3 - 1.5)).toFloat()
                    val ch2 = (Math.sin(timeIndex * 0.0015) * 30 + 50 + (Math.random() * 3 - 1.5)).toFloat()
                    val ch3 = (Math.cos(timeIndex * 0.0015) * 30 + 50 + (Math.random() * 3 - 1.5)).toFloat()

                    multiChannelBuffer.addPoint(ch0, ch1, ch2, ch3, sampleUs)
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
