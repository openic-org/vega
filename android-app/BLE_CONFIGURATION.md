# BLE Device Configuration Guide

## Overview
The app now supports actual BLE device connections with real-time data reception. The implementation is flexible and can be customized for any BLE device.

## Quick Start: Discovering Your Device's UUIDs

### Step 1: Download Nordic UART App (for reference)
The example UUIDs in the code are based on Nordic UART service. If your device uses this:
- **Service UUID**: `6e400001-b5a3-f393-e0a9-e50e24dcca9e`
- **Characteristics**: Use the provided UUIDs or discover your own

### Step 2: Discover Your Device's UUIDs
If your device uses different UUIDs:

1. **Using Android "nRF Connect" app:**
   - Scan and connect to your device
   - Look for the service containing your data
   - Note the Service UUID and Characteristic UUIDs

2. **Using a serial terminal (if you have device source code):**
   - Find the BLE service definition in your device firmware
   - Document the UUIDs

### Step 3: Configure in BleDeviceConfig

Edit `app/src/main/kotlin/com/example/blegraph/ble/BleGattManager.kt`:

```kotlin
object BleDeviceConfig {
    // Replace with your device's Service UUID
    val DATA_SERVICE_UUID = UUID.fromString("YOUR-SERVICE-UUID-HERE")
    
    // Replace with your device's characteristic UUIDs (up to 4 channels)
    val CHANNEL0_CHAR_UUID = UUID.fromString("YOUR-CHANNEL0-UUID-HERE")
    val CHANNEL1_CHAR_UUID = UUID.fromString("YOUR-CHANNEL1-UUID-HERE")
    val CHANNEL2_CHAR_UUID = UUID.fromString("YOUR-CHANNEL2-UUID-HERE")
    val CHANNEL3_CHAR_UUID = UUID.fromString("YOUR-CHANNEL3-UUID-HERE")
    
    // Keep CCCD as-is (standard BLE descriptor)
    val CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
}
```

### Step 4: Configure Data Parsing

Edit the `parseCharacteristicData()` method in `BleGattManager.kt` to match your device's data format.

#### Example: If each characteristic sends a single float value:
```kotlin
private fun parseCharacteristicData(characteristicUuid: UUID, data: ByteArray) {
    if (data.length < 4) return
    
    val value = bytesToFloat(data, 0)
    when (characteristicUuid) {
        BleDeviceConfig.CHANNEL0_CHAR_UUID -> addBlePoint(0, value)
        BleDeviceConfig.CHANNEL1_CHAR_UUID -> addBlePoint(1, value)
        BleDeviceConfig.CHANNEL2_CHAR_UUID -> addBlePoint(2, value)
        BleDeviceConfig.CHANNEL3_CHAR_UUID -> addBlePoint(3, value)
    }
}
```

#### Example: If one characteristic sends all 4 channels (16 bytes):
```kotlin
private fun parseCharacteristicData(characteristicUuid: UUID, data: ByteArray) {
    if (data.length < 16) return
    
    val ch0 = bytesToFloat(data, 0)
    val ch1 = bytesToFloat(data, 4)
    val ch2 = bytesToFloat(data, 8)
    val ch3 = bytesToFloat(data, 12)
    
    // Add all at once
    addMultiChannelBlePoint(ch0, ch1, ch2, ch3)
}
```

### Step 5: Handle Different Data Formats

The provided `bytesToFloat()` assumes IEEE 754 float, little-endian. For other formats:

```kotlin
// For big-endian float:
private fun bytesToFloatBigEndian(data: ByteArray, offset: Int): Float {
    val bits = (data[offset].toInt() and 0xFF) shl 24 or
              ((data[offset + 1].toInt() and 0xFF) shl 16) or
              ((data[offset + 2].toInt() and 0xFF) shl 8) or
              (data[offset + 3].toInt() and 0xFF)
    return Float.fromBits(bits)
}

// For 16-bit integer:
private fun bytesToShort(data: ByteArray, offset: Int): Short {
    return ((data[offset + 1].toInt() and 0xFF) shl 8 or
            (data[offset].toInt() and 0xFF)).toShort()
}

// For 8-bit integer:
private fun byteToInt(data: ByteArray, offset: Int): Int {
    return data[offset].toInt() and 0xFF
}
```

## Testing Your Configuration

1. **Enable Debug Logging:**
   - Check Android Logcat for `BleGattManager` tag
   - You'll see service discovery and characteristic subscription status

2. **Common Issues:**
   - **"Data service not found"**: UUID mismatch or device doesn't advertise the service
   - **"No characteristics subscribed"**: Characteristics don't have notify/indicate property
   - **No data received**: Device not sending notifications, or incorrect CCCD configuration

## Keep Simulation for Testing

The app keeps `generateSimulatedData()` available. You can:
- Test with simulated data while configuring real BLE
- Tap "Simulate" button to use simulated data anytime
- Switch back to real device by "Scan" → "Connect"

## Device Compatibility

This implementation uses Android's standard BLE APIs (Android 12+) and works with any standard BLE device that:
- Advertises GATT services with characteristics
- Supports notifications or indications
- Sends data as byte arrays in any format (float, int, etc.)

## Next Steps

1. Identify your BLE device's UUIDs
2. Update `BleDeviceConfig` in `BleGattManager.kt`
3. Customize `parseCharacteristicData()` for your data format
4. Test with the app and monitor Logcat for debug messages
5. Adjust as needed based on your device's behavior
