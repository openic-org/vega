# BLE Time-Series Graph Android App

A lightweight Android application built with Kotlin and Jetpack Compose that visualizes time-series signals received via Bluetooth Low Energy (BLE) in real-time.

## Features

- **BLE Device Discovery & Connection**: Scan for nearby BLE devices and establish connections
- **Real-time Visualization**: Display time-series data in an interactive 2D canvas graph
- **Lightweight Graph**: Custom Canvas-based implementation with:
  - Automatic scaling and normalization
  - Grid background for reference
  - Line and point visualization
  - Y-axis labels
- **Modern UI**: Built with Jetpack Compose and Material Design 3
- **Full BLE Stack**: Device scanning, connection management, and data reception

## Project Structure

```
app/src/main/
├── kotlin/com/example/blegraph/
│   ├── MainActivity.kt              # Entry point
│   ├── data/
│   │   └── Models.kt                # TimeSeriesPoint, BluetoothDevice
│   ├── ble/
│   │   └── BleManager.kt            # BLE scanning, connection, data handling
│   ├── vm/
│   │   └── BleGraphViewModel.kt     # State management
│   └── ui/
│       ├── BleGraphScreen.kt        # Main UI composable
│       ├── TimeSeriesGraph.kt       # Graph visualization
│       └── theme/
│           └── Theme.kt             # Compose theme
└── res/
    └── values/
        ├── strings.xml              # App strings
        └── themes.xml               # Android themes
```

## Setup & Build

### Prerequisites
- Android Studio Iguana or later
- Android SDK 34 (target API)
- Kotlin 1.9.20+
- Gradle 8.2.0+

### Build Steps
1. Open the project in Android Studio
2. Sync Gradle files (File → Sync Now)
3. Connect an Android device (API 31+) with USB debugging enabled
4. Run the app (Shift + F10)

## Dependencies

### Core
- `androidx.core:core-ktx:1.12.0`
- `androidx.lifecycle:lifecycle-runtime-ktx:2.7.0`
- `androidx.activity:activity-compose:1.8.0`

### Compose
- `androidx.compose.ui:ui:1.6.0`
- `androidx.compose.material3:material3:1.1.2`
- `androidx.lifecycle:lifecycle-viewmodel-compose:2.7.0`

### Bluetooth
- `no.nordicsemi.android:ble:2.6.1`

### Coroutines
- `org.jetbrains.kotlinx:kotlinx-coroutines-core:1.7.3`
- `org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3`

## Permissions Required (Android 12+)

```xml
<uses-permission android:name="android.permission.BLUETOOTH" />
<uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
<uses-permission android:name="android.permission.BLUETOOTH_SCAN" />
<uses-permission android:name="android.permission.BLUETOOTH_ADMIN" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
```

These are requested at runtime using Android's permission request system.

## Usage

1. **Launch the app**: After granting permissions, the main screen appears
2. **Scan for devices**: Tap "Scan" to discover BLE devices in range
3. **Connect to a device**: Select a device from the list to connect
4. **View real-time data**: The graph displays incoming time-series data
5. **Disconnect**: Tap "Disconnect" to end the connection

## Architecture

### Model-View-ViewModel (MVVM)
- **ViewModel** (`BleGraphViewModel`): Manages BLE state and exposes data flows
- **BleManager**: Handles all Bluetooth operations (scanning, connection, data reading)
- **Composables**: UI layers that observe and react to state changes

### State Management
- Uses Kotlin `StateFlow` for reactive updates
- All state is centralized in the ViewModel
- UI automatically recomposes when state changes

## Customization

### To integrate real BLE data:
1. In [BleManager.kt](app/src/main/kotlin/com/example/blegraph/ble/BleManager.kt), replace `simulateDataReception()` with actual BLE characteristic reading
2. Use the Nordic Semiconductor BLE library's `readCharacteristic()` method
3. Parse incoming data and call `addDataPoint()` to update the graph

### To change graph appearance:
- Modify colors in [TimeSeriesGraph.kt](app/src/main/kotlin/com/example/blegraph/ui/TimeSeriesGraph.kt)
- Adjust grid spacing, point radius, line width, etc.

### To add more UI features:
- Extend [BleGraphScreen.kt](app/src/main/kotlin/com/example/blegraph/ui/BleGraphScreen.kt)
- Use Compose's built-in components from `androidx.compose.material3`

## Technical Highlights

- **Clean Architecture**: Separation of concerns with dedicated layers
- **Coroutine-based**: Non-blocking operations for smooth UI
- **Type-safe**: Full Kotlin implementation with null safety
- **Modular**: Easy to extend with new features
- **Memory efficient**: Graph maintains only last 100 data points by default

## Testing

Run tests with:
```bash
./gradlew test
./gradlew connectedAndroidTest
```

## Future Enhancements

- Multi-device simultaneous monitoring
- Data export functionality (CSV, JSON)
- Advanced signal processing (filtering, decimation)
- Historical data persistence
- Graph zoom and pan gestures
- Multiple signal channels

## License

MIT License - See LICENSE file

## Author Notes

This app demonstrates a production-ready BLE integration with real-time visualization. The modular architecture makes it easy to adapt for different BLE device types and data formats.
