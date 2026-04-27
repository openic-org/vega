package com.example.blegraph.ble

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.util.Log
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch

private const val TAG = "BleGattManager"

/**
 * BLE GATT profile for the STM32WB0 Kuntur device.
 *
 *  Service  0xFFF0
 *    0xFFF1  Write-without-response  (phone → STM32, reserved)
 *    0xFFF2  Notify                  (STM32 → phone, StreamDataPacket)
 */
object BleDeviceConfig {
    val DATA_SERVICE_UUID  = UUID.fromString("0000fff0-0000-1000-8000-00805f9b34fb")
    val NOTIFY_CHAR_UUID   = UUID.fromString("0000fff2-0000-1000-8000-00805f9b34fb")
    val CCCD_UUID          = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

    /** Expected ATT MTU for 244-byte packets (packet size + 3 bytes ATT header). */
    const val TARGET_MTU = 247
}

/**
 * Parsed fields from the 8-byte packet header.
 * @param timestampS     RTC seconds component (HH*3600 + MM*60 + SS).
 * @param timestampSubS  Sub-second ticks (0–32767, ~30.5 µs each at 32.768 kHz LSE).
 * @param seqNum         Rolling 0–255 packet counter; gaps indicate dropped packets.
 * @param numPairs       Number of valid sample pairs in this packet.
 */
data class StreamPacketHeader(
    val timestampS: Long,
    val timestampSubS: Int,
    val seqNum: Int,
    val numPairs: Int
)

/**
 * Manages BLE GATT connections to the STM32WB0 Kuntur device.
 *
 * Setup sequence on each connection:
 *   1. discoverServices
 *   2. requestMtu(247)        → onMtuChanged
 *   3. setPreferredPhy(2M)    (best-effort, parallel)
 *   4. enableNotifications    (write CCCD on 0xFFF2)
 *
 * @param onBatchReceived  Callback delivering decoded sample arrays per BLE packet.
 *                         Invoked on [parserScope]'s single-threaded background dispatcher.
 */
class BleGattManager(
    private val context: Context,
    private val bluetoothAdapter: BluetoothAdapter?,
    private val onBatchReceived: (
        ch0: ShortArray,
        ch1: ShortArray,
        header: StreamPacketHeader
    ) -> Unit,
    private val onConnectionStateChange: (isConnected: Boolean, message: String) -> Unit,
    private val onError: (errorMessage: String) -> Unit,
    private val onDebugInfo: ((info: String) -> Unit)? = null
) {
    private var bluetoothGatt: BluetoothGatt? = null
    private var isConnecting = false
    private var deviceAddress: String? = null

    /** Expected sequence number for drop detection (null = first packet). */
    private var expectedSeq: Int? = null
    private var totalDropped = 0L
    private var totalPackets = 0L

    /**
     * Raw packet bytes are enqueued here by [onCharacteristicChanged] and consumed
     * by a single-threaded coroutine so the BLE callback thread returns immediately.
     * Capacity 2048 ≈ 4 seconds of headroom at 500 pkt/s; trySend drops rather than blocks.
     */
    private val rawPacketChannel = Channel<ByteArray>(capacity = 2048)

    /**
     * Single-threaded dispatcher: all coroutines in this scope run serially so
     * [parseStreamPacket] state (expectedSeq, totalDropped, …) needs no locking.
     */
    private val parserScope = CoroutineScope(
        Dispatchers.Default.limitedParallelism(1) + SupervisorJob()
    )

    init {
        parserScope.launch {
            for (rawBytes in rawPacketChannel) {
                parseStreamPacket(rawBytes)
            }
        }
    }

    @SuppressLint("MissingPermission")
    fun connect(address: String) {
        if (isConnecting) {
            onError("Connection already in progress")
            return
        }
        val device = bluetoothAdapter?.getRemoteDevice(address)
        if (device == null) {
            onError("Device not found: $address")
            return
        }
        deviceAddress = address
        isConnecting  = true
        Log.d(TAG, "Connecting to $address")
        bluetoothGatt = device.connectGatt(context, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
    }

    @SuppressLint("MissingPermission")
    fun reconnect() {
        val addr = deviceAddress ?: return
        disconnect()
        connect(addr)
    }

    @SuppressLint("MissingPermission")
    fun disconnect() {
        rawPacketChannel.close()
        parserScope.cancel()
        bluetoothGatt?.close()
        bluetoothGatt = null
        isConnecting  = false
        expectedSeq   = null
    }

    // -------------------------------------------------------------------------
    //  GATT callback
    // -------------------------------------------------------------------------

    private val gattCallback = object : BluetoothGattCallback() {

        @SuppressLint("MissingPermission")
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    isConnecting = false
                    Log.d(TAG, "Connected – discovering services")
                    onConnectionStateChange(true, "Connected")
                    gatt.discoverServices()
                }
                BluetoothProfile.STATE_DISCONNECTED -> {
                    isConnecting = false
                    Log.d(TAG, "Disconnected (status=$status)")
                    onConnectionStateChange(false, "Disconnected")
                }
            }
        }

        @SuppressLint("MissingPermission")
        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                onError("Service discovery failed (status=$status)")
                return
            }
            Log.d(TAG, "Services discovered")

            // Log available services for debugging
            gatt.services.forEach { svc ->
                Log.d(TAG, "  Service: ${svc.uuid}")
                svc.characteristics.forEach { chr ->
                    Log.d(TAG, "    Char: ${chr.uuid}  props=0x%02X".format(chr.properties))
                }
            }

            bluetoothGatt = gatt

            // Step 1: negotiate MTU – triggers onMtuChanged which enables notifications
            Log.d(TAG, "Requesting MTU ${BleDeviceConfig.TARGET_MTU}")
            gatt.requestMtu(BleDeviceConfig.TARGET_MTU)

            // Step 2: request 2M PHY (best-effort, parallel with MTU)
            gatt.setPreferredPhy(
                BluetoothDevice.PHY_LE_2M_MASK,
                BluetoothDevice.PHY_LE_2M_MASK,
                BluetoothDevice.PHY_OPTION_NO_PREFERRED
            )
        }

        @SuppressLint("MissingPermission")
        override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, status: Int) {
            Log.d(TAG, "MTU changed to $mtu (status=$status)")
            onDebugInfo?.invoke("MTU=$mtu")
            // Request high-priority connection interval (7.5–15 ms) for 30 kSps throughput.
            // This replaces the STM32-side hci_le_connection_update call which is not
            // available in the stm32wb0x_ble_stack.a library on this SDK version.
            gatt.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)
            Log.d(TAG, "Requested CONNECTION_PRIORITY_HIGH")
            // Enable notifications regardless of whether target MTU was achieved
            enableNotifications(gatt)
        }

        override fun onPhyUpdate(gatt: BluetoothGatt, txPhy: Int, rxPhy: Int, status: Int) {
            val txName = if (txPhy == BluetoothDevice.PHY_LE_2M) "2M" else "1M"
            val rxName = if (rxPhy == BluetoothDevice.PHY_LE_2M) "2M" else "1M"
            Log.d(TAG, "PHY updated: TX=$txName  RX=$rxName  status=$status")
            onDebugInfo?.invoke("PHY TX=$txName RX=$rxName")
        }

        @SuppressLint("MissingPermission")
        override fun onDescriptorWrite(
            gatt: BluetoothGatt,
            descriptor: BluetoothGattDescriptor,
            status: Int
        ) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                Log.i(TAG, "CCCD written – notifications enabled on ${descriptor.characteristic.uuid}")

                // Re-assert HIGH priority now that the full setup is done (MTU + PHY + CCCD).
                // Some devices only honour this after the link is fully configured.
                gatt.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)
                Log.d(TAG, "Re-requested CONNECTION_PRIORITY_HIGH after CCCD write")

                // Note: Android negotiates LL Data Length Extension (DLE) automatically
                // at connection time — no explicit API call needed on the Android side.
                // The STM32 now has CFG_BLE_CONTROLLER_DATA_LENGTH_EXTENSION_ENABLED=1
                // so it will accept Android's DLE negotiation and use 251-byte LL PDUs.

                onConnectionStateChange(true, "Streaming")
                onDebugInfo?.invoke("Notifications enabled")
            } else {
                onError("CCCD write failed (status=$status)")
            }
        }

        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray
        ) {
            if (characteristic.uuid == BleDeviceConfig.NOTIFY_CHAR_UUID) {
                // Copy before returning — the ByteArray is only valid for this callback.
                // trySend is non-blocking; if the channel is full the packet is dropped
                // (preferable to blocking the BLE callback thread and overflowing the Binder buffer).
                val dropped = rawPacketChannel.trySend(value.copyOf()).isFailure
                if (dropped) Log.w(TAG, "rawPacketChannel full — packet dropped")
            }
        }
    }

    // -------------------------------------------------------------------------
    //  Setup helpers
    // -------------------------------------------------------------------------

    @SuppressLint("MissingPermission")
    private fun enableNotifications(gatt: BluetoothGatt) {
        val service = gatt.getService(BleDeviceConfig.DATA_SERVICE_UUID)
        if (service == null) {
            onError("Stream service 0xFFF0 not found on device")
            return
        }
        val char = service.getCharacteristic(BleDeviceConfig.NOTIFY_CHAR_UUID)
        if (char == null) {
            onError("Notify char 0xFFF2 not found in stream service")
            return
        }
        val hasNotify = (char.properties and BluetoothGattCharacteristic.PROPERTY_NOTIFY) != 0
        if (!hasNotify) {
            onError("0xFFF2 does not have NOTIFY property (properties=0x%02X)".format(char.properties))
            return
        }
        // Android-side: route notifications to our callback
        gatt.setCharacteristicNotification(char, true)

        // Device-side: write CCCD to ask STM32 to send notifications
        val cccd = char.getDescriptor(BleDeviceConfig.CCCD_UUID)
        if (cccd == null) {
            onError("CCCD descriptor not found on 0xFFF2")
            return
        }
        @Suppress("DEPRECATION")
        cccd.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
        @Suppress("DEPRECATION")
        gatt.writeDescriptor(cccd)
        Log.d(TAG, "CCCD write requested for 0xFFF2")
    }

    // -------------------------------------------------------------------------
    //  Packet parser
    // -------------------------------------------------------------------------

    /**
     * Parse a raw BLE notification payload into a [StreamPacketHeader] and two
     * [ShortArray]s of int16 ADC samples, then deliver via [onBatchReceived].
     *
     * Packet layout (little-endian):
     *   offset 0 : uint32  timestamp_s
     *   offset 4 : uint16  timestamp_sub_s
     *   offset 6 : uint8   seq_num
     *   offset 7 : uint8   num_pairs
     *   offset 8 : int16[] samples  (interleaved ch0, ch1)
     */
    private fun parseStreamPacket(data: ByteArray) {
        if (data.size < 8) {
            Log.w(TAG, "Packet too small: ${data.size} bytes")
            return
        }

        val buf = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)

        val timestampS    = buf.int.toLong() and 0xFFFFFFFFL
        val timestampSubS = buf.short.toInt() and 0xFFFF
        val seqNum        = buf.get().toInt() and 0xFF
        val numPairs      = buf.get().toInt() and 0xFF

        // Drop detection
        totalPackets++
        expectedSeq?.let { exp ->
            val gap = (seqNum - exp + 256) % 256
            if (gap != 0) {
                totalDropped += gap
                Log.w(TAG, "Seq gap: expected $exp got $seqNum (dropped ~$gap pkt, total=$totalDropped)")
                onDebugInfo?.invoke("Drops: $totalDropped / $totalPackets")
            }
        }
        expectedSeq = (seqNum + 1) % 256

        val minSize = 8 + numPairs * 4
        if (data.size < minSize) {
            Log.w(TAG, "Packet truncated: got ${data.size}, need $minSize")
            return
        }

        val ch0 = ShortArray(numPairs)
        val ch1 = ShortArray(numPairs)
        for (i in 0 until numPairs) {
            ch0[i] = buf.short
            ch1[i] = buf.short
        }

        val header = StreamPacketHeader(timestampS, timestampSubS, seqNum, numPairs)
        onBatchReceived(ch0, ch1, header)
    }
}

@SuppressLint("MissingPermission")
fun BluetoothGatt.setNotificationEnabled(characteristic: BluetoothGattCharacteristic, enabled: Boolean) {
    val cccd = characteristic.getDescriptor(BleDeviceConfig.CCCD_UUID) ?: return
    @Suppress("DEPRECATION")
    cccd.value = if (enabled) BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                 else         BluetoothGattDescriptor.DISABLE_NOTIFICATION_VALUE
    @Suppress("DEPRECATION")
    writeDescriptor(cccd)
}
