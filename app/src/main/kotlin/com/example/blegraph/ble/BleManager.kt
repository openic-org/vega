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

// ── Stream mode ───────────────────────────────────────────────────────────────
// Must match STREAM_ACTIVE_MODE in STM32 stream_app.h.
// Change DELIVERED_SPS below (and STREAM_ACTIVE_MODE on the STM32) to switch.
//
//   STREAM_MODE_ANDROID_BLE    Burst pipeline.  VTIMER 5 ms (actual ~1.93 ms).
//                              ~7 725 SPS.  Device name: "Kuntur-A".
//
//   STREAM_MODE_LENOVO_SMOOTH  1 pkt/CI, no burst.  VTIMER 36 ms (~13.9 ms).
//                              ~4 000 SPS — smooth plotting on Lenovo TB305FU.
//                              Device name: "Kuntur-S".
//
//   STREAM_MODE_NORDIC_HF      Nordic nRF52840 dongle. Target 30 000 SPS (future).
//                              Device name: "Kuntur-N".
private const val STREAM_MODE_ANDROID_BLE   = 0
private const val STREAM_MODE_LENOVO_SMOOTH = 2
private const val STREAM_MODE_NORDIC_HF     = 1

// ── Sampling rates ────────────────────────────────────────────────────────────
// ADC_RATE_HZ: STM32 ADC clock — used for intra-packet timestamp spacing only.
// Samples within each packet are always spaced at 1_000_000 / ADC_RATE_HZ µs
// regardless of which stream mode is active.
private const val ADC_RATE_HZ = 30_000L

// DELIVERED_SPS: samples that actually arrive at Android per second.
// Drives buffer sizing and display-window point counts.
// Change this line (and STREAM_ACTIVE_MODE on the STM32) to switch modes.
// private const val DELIVERED_SPS = 7_725L    // STREAM_MODE_ANDROID_BLE
private const val DELIVERED_SPS   = 4_000L    // STREAM_MODE_LENOVO_SMOOTH ← active
// private const val DELIVERED_SPS = 30_000L  // STREAM_MODE_NORDIC_HF

// Legacy alias — keeps existing code using SAMPLE_RATE_HZ unchanged.
// Points to ADC_RATE_HZ so intra-packet timestamps remain correct.
private const val SAMPLE_RATE_HZ = ADC_RATE_HZ

private const val BUFFER_DURATION_SECONDS = 10
// Buffer holds BUFFER_DURATION_SECONDS of DELIVERED data (not ADC-rate data).
private const val BUFFER_SIZE             = (DELIVERED_SPS * BUFFER_DURATION_SECONDS).toInt()
private const val NUM_CHANNELS            = 4

// Display windows — sized to DELIVERED_SPS so both modes fill the screen correctly.
// Full-res : last 0.5 s of delivered samples  (no decimation)
// Downsampled: last 5 s of delivered samples  (no decimation needed at this rate)
private const val FULL_RESOLUTION_WINDOW_POINTS = (DELIVERED_SPS / 2L).toInt()  // 0.5 s
private const val DOWNSAMPLED_WINDOW_POINTS     = (DELIVERED_SPS * 5L).toInt()  // 5 s
private const val DOWNSAMPLING_FACTOR_DISPLAY   = 1

// Recording limits
// Write rate Android BLE: ~7 725 sps × ~23 bytes/row ≈ 178 KB/s ≈ 10.7 MB/min
// Write rate Nordic HF  : ~30 000 sps × ~23 bytes/row ≈ 690 KB/s ≈ 41.4 MB/min
private const val MAX_RECORDING_SECONDS  = 10 * 60              // 10-minute hard cap
private const val MIN_FREE_STORAGE_BYTES = 200L * 1_024 * 1_024 // stop if < 200 MB free
private const val BYTES_PER_SAMPLE_ROW   = 23L                  // conservative estimate for MB counter

// Throttle UI refresh to ~30 fps to avoid overwhelming the Compose renderer
private const val UI_REFRESH_INTERVAL_MS      = 33L

// Auto-reconnect: wait this long after a disconnect before attempting
private const val RECONNECT_DELAY_MS          = 1_500L

// BLE packet payload size in bytes (8-byte header + 59 pairs × 4 bytes)
private const val BYTES_PER_BLE_PACKET        = 244

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

    /** Measured BLE data rate, updated every ~2 s over a rolling window. */
    data class DataRate(
        val packetsPerSecond: Float = 0f,
        val kbitsPerSecond: Float   = 0f
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

    private val _dataRate = MutableStateFlow(DataRate())
    val dataRate: StateFlow<DataRate> = _dataRate

    // Rate calculation: rolling window updated every ~2 s
    private var rateWindowStartMs      = 0L
    private var rateWindowStartPackets = 0L

    // Auto-reconnect state
    private var lastDeviceAddress: String? = null
    private var lastDeviceName: String?    = null
    private var shouldAutoReconnect        = false

    // UI refresh throttle
    private var lastUiUpdateMs = 0L
    /** Timestamp of the last sample written in the previous BLE packet (µs).
     *  Used to clamp the next packet's base timestamp so it is never earlier
     *  than one sample-period after the previous packet ended, preventing the
     *  −4881 µs backwards-jump artefact caused by HAL_GetTick() 1 ms
     *  resolution combining with BLE CI jitter on the STM32 side. */
    private var lastPacketEndUs = 0L

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

            stopScanning()

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
            _scannedDevices.value = emptyList()
            multiChannelBuffer.clear()
            lastPacketEndUs        = 0L
            rateWindowStartMs      = 0L
            rateWindowStartPackets = 0L
            _dataRate.value        = DataRate()
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
     *   sampleUs     = packetBaseUs + i × 1_000_000 / SAMPLE_RATE_HZ
     *
     * timestampSubS encodes ms%1000 × 32 (range 0–31999), so dividing by 32 gives ms,
     * then × 1000 converts to µs.
     *
     * Monotonicity clamp: HAL_GetTick() has 1 ms resolution, and BLE CI jitter can
     * cause a packet's MCU timestamp to be slightly earlier than the extrapolated
     * end of the previous packet (observed as −4881 µs jumps in CSV analysis).
     * We clamp so that each packet starts at least one sample-period after the
     * previous packet ended, keeping timestamps strictly monotonically increasing.
     */
    private fun onBatchDataReceived(ch0: ShortArray, ch1: ShortArray, header: StreamPacketHeader) {
        totalBlePackets++

        val rawBaseUs = header.timestampS * 1_000_000L +
                        header.timestampSubS.toLong() * 1_000L / 32L
        val samplePeriodUs = 1_000_000L / SAMPLE_RATE_HZ
        val packetBaseUs = if (lastPacketEndUs > 0L && rawBaseUs < lastPacketEndUs + samplePeriodUs)
                               lastPacketEndUs + samplePeriodUs
                           else
                               rawBaseUs

        // Feed all pairs from this packet into channels 0 and 1 (ch2/ch3 = 0)
        // and optionally stream each sample to the active CSV recording.
        //
        // We capture a local ref to avoid the race where stopRecording() closes the
        // writer between our null-check and the actual write call.  If the writer
        // was closed concurrently we catch the IOException and clear the local ref so
        // we stop trying to write (the recording has already been finalised).
        val writer = recordingWriter
        var writeOk = writer != null
        for (i in ch0.indices) {
            val sampleUs = packetBaseUs + i.toLong() * 1_000_000L / SAMPLE_RATE_HZ
            multiChannelBuffer.addPoint(ch0[i].toFloat(), ch1[i].toFloat(), 0f, 0f, sampleUs)
            if (writeOk) {
                try {
                    writer!!.write("$sampleUs,${ch0[i]},${ch1[i]}\n")
                } catch (e: java.io.IOException) {
                    // Writer was closed by stopRecording() racing with this coroutine.
                    // Clear our flag so we stop writing for the rest of this packet.
                    writeOk = false
                    Log.w(TAG, "CSV write skipped — writer closed mid-packet: ${e.message}")
                }
            }
        }
        if (writeOk) recordingSamplesWritten += ch0.size
        // Track the end of this packet so the next packet's base can be clamped.
        // Use the same per-sample formula as the loop (i * 1_000_000 / SAMPLE_RATE_HZ)
        // rather than (size-1) * samplePeriodUs — integer division makes them differ
        // by up to (size-1) µs, which would create spurious short gaps at boundaries.
        if (ch0.isNotEmpty()) {
            lastPacketEndUs = packetBaseUs + (ch0.size - 1).toLong() * 1_000_000L / SAMPLE_RATE_HZ
        }

        // Throttle UI refresh to ~30 fps
        val now = System.currentTimeMillis()
        if (now - lastUiUpdateMs >= UI_REFRESH_INTERVAL_MS) {
            lastUiUpdateMs = now
            updateChannelFlows()
            _packetCounts.value = PacketCounts(ch0 = totalBlePackets)

            // Update data rate over a ~2-second rolling window
            if (rateWindowStartMs == 0L) {
                rateWindowStartMs      = now
                rateWindowStartPackets = totalBlePackets
            } else {
                val elapsed = now - rateWindowStartMs
                if (elapsed >= 2_000L) {
                    val pps  = (totalBlePackets - rateWindowStartPackets).toFloat() / (elapsed / 1_000f)
                    val kbps = pps * BYTES_PER_BLE_PACKET * 8f / 1_000f
                    _dataRate.value        = DataRate(pps, kbps)
                    rateWindowStartMs      = now
                    rateWindowStartPackets = totalBlePackets
                }
            }
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

}
