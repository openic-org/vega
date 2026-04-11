package com.example.blegraph.ble

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.util.Log
import java.util.UUID
import kotlin.concurrent.thread

private const val TAG = "BleGattManager"

/**
 * Configuration for BLE device characteristics.
 * Customize these UUIDs to match your BLE device.
 */
object BleDeviceConfig {
    // Health Thermometer Service (0x180D)
    val DATA_SERVICE_UUID = UUID.fromString("0000180d-0000-1000-8000-00805f9b34fb")
    
    // Characteristics for 4 channels (0x2A37, 0x2A38, 0x2A39)
    val CHANNEL0_CHAR_UUID = UUID.fromString("00002a37-0000-1000-8000-00805f9b34fb") // 0x2A37
    val CHANNEL1_CHAR_UUID = UUID.fromString("00002a38-0000-1000-8000-00805f9b34fb") // 0x2A38
    val CHANNEL2_CHAR_UUID = UUID.fromString("00002a39-0000-1000-8000-00805f9b34fb") // 0x2A39
    val CHANNEL3_CHAR_UUID = UUID.fromString("00002a37-0000-1000-8000-00805f9b34fb") // 0x2A37 (reused for 4th channel)
    
    // Client Characteristic Configuration Descriptor
    val CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
}

/**
 * Manages BLE GATT connections and characteristic subscriptions.
 * Parses incoming BLE data and feeds it to the data buffer.
 */
class BleGattManager(
    private val context: Context,
    private val bluetoothAdapter: BluetoothAdapter?,
    private val onDataReceived: (channel0: Float, channel1: Float, channel2: Float, channel3: Float) -> Unit,
    private val onConnectionStateChange: (isConnected: Boolean, message: String) -> Unit,
    private val onError: (errorMessage: String) -> Unit,
    private val onDebugData: ((characteristicUuid: String, hexData: String, parsed: String) -> Unit)? = null,
    private val onPacketCountUpdate: ((ch0: Long, ch1: Long, ch2: Long, ch3: Long) -> Unit)? = null
) {
    
    private var bluetoothGatt: BluetoothGatt? = null
    private var isConnecting = false
    private var receivedDataCount = 0L
    
    // Packet counters for each characteristic
    private var channel0PacketCount = 0L
    private var channel1PacketCount = 0L
    private var channel2PacketCount = 0L
    private var channel3PacketCount = 0L
    
    // Store last received values for each characteristic
    private var channel0Value = 0f
    private var channel1Value = 0f
    private var channel2Value = 0f
    private var channel3Value = 0f
    
    // Polling thread for reading characteristics if notifications don't arrive
    private var pollingThread: Thread? = null
    private var shouldPoll = false
    private var readInProgress = false
    private var characteristic0x2A37: BluetoothGattCharacteristic? = null
    private val POLLING_INTERVAL_MS = 100L  // Poll every 100ms (disabled - 0x2A37 not readable)
    
    /**
     * Initiate connection to a BLE device.
     */
    @SuppressLint("MissingPermission")
    fun connect(deviceAddress: String) {
        if (isConnecting) {
            onError("Connection already in progress")
            return
        }
        
        val device = bluetoothAdapter?.getRemoteDevice(deviceAddress)
        if (device == null) {
            onError("Device not found: $deviceAddress")
            return
        }
        
        isConnecting = true
        Log.d(TAG, "Initiating GATT connection to $deviceAddress")
        
        bluetoothGatt = device.connectGatt(context, false, gattCallback)
    }
    
    /**
     * Disconnect from the current BLE device.
     */
    fun disconnect() {
        stopPolling()  // Stop polling before disconnecting
        bluetoothGatt?.let {
            Log.d(TAG, "Disconnecting from device")
            it.close()
        }
        bluetoothGatt = null
        isConnecting = false
    }
    
    /**
     * GATT callback that handles connection state changes and characteristic reads/notifications.
     */
    private val gattCallback = object : BluetoothGattCallback() {
        
        @SuppressLint("MissingPermission")
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            super.onConnectionStateChange(gatt, status, newState)
            
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    isConnecting = false
                    Log.d(TAG, "Connected to device, discovering services...")
                    onConnectionStateChange(true, "Connected to device")
                    
                    // Start service discovery
                    gatt.discoverServices()
                }
                
                BluetoothProfile.STATE_DISCONNECTED -> {
                    isConnecting = false
                    Log.d(TAG, "Disconnected from device")
                    onConnectionStateChange(false, "Disconnected from device")
                }
                
                else -> {
                    Log.w(TAG, "Connection state changed to: $newState, Status: $status")
                }
            }
        }
        
        @SuppressLint("MissingPermission")
        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            super.onServicesDiscovered(gatt, status)
            
            if (status == BluetoothGatt.GATT_SUCCESS) {
                Log.d(TAG, "Services discovered successfully")
                
                // Find and subscribe to data characteristics
                val dataService = gatt.getService(BleDeviceConfig.DATA_SERVICE_UUID)
                if (dataService != null) {
                    subscribeToCharacteristics(gatt, dataService)
                } else {
                    onError("Data service not found (UUID: ${BleDeviceConfig.DATA_SERVICE_UUID})")
                    Log.e(TAG, "Data service not found. Available services:")
                    gatt.services.forEach { service ->
                        Log.e(TAG, "  Service: ${service.uuid}")
                    }
                }
            } else {
                onError("Service discovery failed with status: $status")
                Log.e(TAG, "Service discovery failed")
            }
        }
        
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray
        ) {
            super.onCharacteristicChanged(gatt, characteristic, value)
            
            Log.i(TAG, "🔔 *** NOTIFICATION RECEIVED *** from ${characteristic.uuid}: ${value.size} bytes")
            Log.d(TAG, "   Hex: ${value.joinToString("") { "%02X".format(it) }}")
            receivedDataCount++
            
            // Parse the received data based on characteristic UUID
            parseCharacteristicData(characteristic.uuid, value)
        }
        
        override fun onCharacteristicRead(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray,
            status: Int
        ) {
            super.onCharacteristicRead(gatt, characteristic, value, status)
            
            readInProgress = false
            
            if (status == BluetoothGatt.GATT_SUCCESS) {
                Log.d(TAG, "📖 ✅ Characteristic read succeeded from ${characteristic.uuid}: ${value.size} bytes")
                parseCharacteristicData(characteristic.uuid, value)
            } else {
                Log.e(TAG, "📖 ❌ Characteristic read failed from ${characteristic.uuid} with status: $status (0=success, 2=read not permitted)")
            }
        }
        
        override fun onCharacteristicWrite(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) {
            super.onCharacteristicWrite(gatt, characteristic, status)
            
            if (status == BluetoothGatt.GATT_SUCCESS) {
                Log.d(TAG, "Characteristic written successfully")
            } else {
                Log.e(TAG, "Characteristic write failed with status: $status")
            }
        }
        
        override fun onDescriptorWrite(gatt: BluetoothGatt, descriptor: android.bluetooth.BluetoothGattDescriptor, status: Int) {
            super.onDescriptorWrite(gatt, descriptor, status)
            
            if (status == BluetoothGatt.GATT_SUCCESS) {
                Log.d(TAG, "✅ Descriptor written successfully for characteristic: ${descriptor.characteristic.uuid}")
                Log.i(TAG, "📊 READY TO RECEIVE NOTIFICATIONS")
                Log.i(TAG, "🎯 Listening for data from device 0x2A37 (Heart Rate Measurement)...")
            } else {
                Log.e(TAG, "❌ Descriptor write failed with status: $status for characteristic: ${descriptor.characteristic.uuid}")
            }
        }
    }
    
    /**
     * Subscribe to notifications from data characteristics.
     */
    @SuppressLint("MissingPermission")
    private fun subscribeToCharacteristics(gatt: BluetoothGatt, service: android.bluetooth.BluetoothGattService) {
        // Only subscribe to characteristics that support notifications
        // 0x2A37 is the measurement characteristic (supports notify)
        // 0x2A38 and 0x2A39 are read-only characteristics (no notify support)
        val notifiableCharacteristics = listOf(
            BleDeviceConfig.CHANNEL0_CHAR_UUID  // 0x2A37 supports notify
        )
        
        var successCount = 0
        
        for (charUuid in notifiableCharacteristics) {
            val characteristic = service.getCharacteristic(charUuid)
            if (characteristic != null) {
                Log.d(TAG, "📍 Attempting to subscribe to characteristic: $charUuid")
                
                // Store reference for polling
                characteristic0x2A37 = characteristic
                
                // Enable notification
                val hasNotifyProperty = (characteristic.properties and BluetoothGattCharacteristic.PROPERTY_NOTIFY) != 0
                val hasIndicateProperty = (characteristic.properties and BluetoothGattCharacteristic.PROPERTY_INDICATE) != 0
                
                Log.d(TAG, "  Properties - Notify: $hasNotifyProperty, Indicate: $hasIndicateProperty")
                
                if (hasNotifyProperty || hasIndicateProperty) {
                    Log.d(TAG, "📍 Enabling notifications for characteristic: $charUuid")
                    
                    // CRITICAL: Enable client-side notification delivery on Android FIRST
                    val notificationEnabled = gatt.setCharacteristicNotification(characteristic, true)
                    Log.d(TAG, "  ✓ setCharacteristicNotification result: $notificationEnabled")
                    
                    // Then write CCCD to tell device to send notifications
                    val descriptor = characteristic.getDescriptor(BleDeviceConfig.CCCD_UUID)
                    if (descriptor != null) {
                        descriptor.value = android.bluetooth.BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                        gatt.writeDescriptor(descriptor)
                        successCount++
                        Log.d(TAG, "  ✓ CCCD write requested for $charUuid")
                    } else {
                        Log.w(TAG, "❌ CCCD descriptor not found for characteristic: $charUuid")
                    }
                } else {
                    Log.w(TAG, "❌ Characteristic does not support notify or indicate: $charUuid")
                }
            } else {
                Log.w(TAG, "❌ Characteristic not found: $charUuid")
            }
        }
        
        if (successCount > 0) {
            Log.i(TAG, "✅ Successfully subscribed to $successCount characteristic(s)")
            Log.i(TAG, "⏳ Waiting for device notifications on 0x2A37...")
            Log.i(TAG, "ℹ️  0x2A37 is NOTIFICATION-ONLY (not readable) - Device must actively send data")
            Log.i(TAG, "💡 If no data arrives, ensure BLE device is in measurement/active mode")
            
            // NOTE: Polling disabled - 0x2A37 doesn't support READ operations
            bluetoothGatt = gatt
            
            onConnectionStateChange(true, "Receiving data from $successCount channel")
        } else {
            onError("No characteristics subscribed")
        }
    }
    
    /**
     * Parse incoming BLE characteristic data.
     * Extracts uint16_t values and updates channel data.
     */
    private fun parseCharacteristicData(characteristicUuid: UUID, data: ByteArray) {
        receivedDataCount++
        
        // Log raw data as hex
        val hexData = data.joinToString(" ") { String.format("%02X", it) }
        val charName = when (characteristicUuid) {
            BleDeviceConfig.CHANNEL0_CHAR_UUID -> "CH0/3 (0x2A37)"
            BleDeviceConfig.CHANNEL1_CHAR_UUID -> "CH1 (0x2A38)"
            BleDeviceConfig.CHANNEL2_CHAR_UUID -> "CH2 (0x2A39)"
            else -> "UNKNOWN"
        }
        
        Log.d(TAG, "[$receivedDataCount] $charName - Raw bytes: $hexData (${data.size} bytes)")
        
        if (data.size < 2) {
            Log.w(TAG, "ERROR: Received data too short: ${data.size} bytes, expected at least 2")
            onDebugData?.invoke(characteristicUuid.toString(), hexData, "ERROR: Too short")
            return
        }
        
        // Parse as uint16_t (2 bytes, little-endian)
        val value = bytesToUInt16(data, 0).toFloat()
        val parsedValue = "uint16: $value"
        
        // Update the appropriate channel based on characteristic UUID
        val dataReceived = when (characteristicUuid) {
            BleDeviceConfig.CHANNEL0_CHAR_UUID -> {
                channel0PacketCount++
                channel0Value = value
                channel3Value = value  // Reuse 0x2A37 for both channel 0 and 3
                Log.d(TAG, "$charName: $value (hex: $hexData)")
                true
            }
            BleDeviceConfig.CHANNEL1_CHAR_UUID -> {
                channel1PacketCount++
                channel1Value = value
                Log.d(TAG, "$charName: $value (hex: $hexData)")
                true
            }
            BleDeviceConfig.CHANNEL2_CHAR_UUID -> {
                channel2PacketCount++
                channel2Value = value
                Log.d(TAG, "$charName: $value (hex: $hexData)")
                true
            }
            else -> {
                Log.w(TAG, "Unknown characteristic: $characteristicUuid")
                false
            }
        }
        
        // Send debug callback for UI display
        onDebugData?.invoke(characteristicUuid.toString(), hexData, parsedValue)
        
        // Send packet count update
        onPacketCountUpdate?.invoke(channel0PacketCount, channel1PacketCount, channel2PacketCount, channel3PacketCount)
        
        // Send data update when any characteristic changes
        if (dataReceived) {
            Log.d(TAG, "Data updated: CH0=$channel0Value, CH1=$channel1Value, CH2=$channel2Value, CH3=$channel3Value")
            onDataReceived(channel0Value, channel1Value, channel2Value, channel3Value)
        }
    }
    
    /**
     * Convert 2 bytes to uint16 (little-endian).
     */
    private fun bytesToUInt16(data: ByteArray, offset: Int): Int {
        return (data[offset].toInt() and 0xFF) or
               ((data[offset + 1].toInt() and 0xFF) shl 8)
    }
    
    /**
     * Start polling thread to read characteristic if notifications don't arrive.
     */
    @SuppressLint("MissingPermission")
    private fun startPolling() {
        stopPolling()  // Stop any existing polling
        
        shouldPoll = true
        readInProgress = false
        pollingThread = thread(isDaemon = true, name = "BlePollingThread") {
            Log.i(TAG, "🔄 Polling thread started - reading characteristic every ${POLLING_INTERVAL_MS}ms with proper sequencing")
            var attemptCount = 0
            var loopCount = 0
            var queueRejectedCount = 0
            
            while (shouldPoll) {
                loopCount++
                try {
                    if (loopCount % 5 == 1) {
                        Log.d(TAG, "🔄 Polling loop iteration #$loopCount, readInProgress=$readInProgress")
                    }
                    
                    Thread.sleep(POLLING_INTERVAL_MS)
                    
                    if (shouldPoll && !readInProgress) {  // Only read if no read is in flight
                        attemptCount++
                        Log.d(TAG, "📖 [Attempt #$attemptCount] Checking GATT state: GATT=${bluetoothGatt != null}, Char=${characteristic0x2A37 != null}")
                        
                        if (bluetoothGatt != null && characteristic0x2A37 != null) {
                            Log.d(TAG, "📖 [Attempt #$attemptCount] Issuing read request for 0x2A37...")
                            readInProgress = true  // Mark read as in flight
                            val success = bluetoothGatt?.readCharacteristic(characteristic0x2A37!!)
                            if (success == true) {
                                Log.d(TAG, "✅ [Attempt #$attemptCount] Read queued successfully")
                            } else {
                                Log.w(TAG, "⚠️  [Attempt #$attemptCount] Read rejected - GATT queue may be full")
                                readInProgress = false  // Reset flag since operation wasn't queued
                                queueRejectedCount++
                                if (queueRejectedCount % 10 == 0) {
                                    Log.w(TAG, "⚠️  Queue rejections so far: $queueRejectedCount - Device may not be responding")
                                }
                            }
                        } else {
                            Log.w(TAG, "❌ [Attempt #$attemptCount] Cannot read: GATT=${bluetoothGatt != null}, Char=${characteristic0x2A37 != null}")
                        }
                    } else if (readInProgress && loopCount % 20 == 1) {
                        Log.d(TAG, "⏳ [Loop #$loopCount] Waiting for read response...")
                    }
                } catch (e: InterruptedException) {
                    Log.d(TAG, "Polling thread interrupted at loop iteration #$loopCount")
                    break
                } catch (e: Exception) {
                    Log.e(TAG, "❌ Error during polling at iteration #$loopCount: ${e.message}", e)
                    readInProgress = false
                }
            }
            
            Log.i(TAG, "🔄 Polling thread stopped (Total rejections: $queueRejectedCount)")
        }
    }
    
    /**
     * Stop the polling thread.
     */
    private fun stopPolling() {
        shouldPoll = false
        pollingThread?.interrupt()
        pollingThread = null
    }
}

/**
 * Extension function to enable/disable notifications for a characteristic.
 */
@SuppressLint("MissingPermission")
fun BluetoothGatt.setNotificationEnabled(characteristic: BluetoothGattCharacteristic, enabled: Boolean) {
    val cccd = characteristic.getDescriptor(BleDeviceConfig.CCCD_UUID) ?: return
    
    if (enabled) {
        cccd.value = android.bluetooth.BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
    } else {
        cccd.value = android.bluetooth.BluetoothGattDescriptor.DISABLE_NOTIFICATION_VALUE
    }
    
    writeDescriptor(cccd)
}
