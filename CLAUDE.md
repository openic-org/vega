# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Vega** is a real-time FPGA data visualisation system for the STM32WB0 "Kuntur" device. It has two front-ends that share the same BLE packet format and CSV recording format:

- **`android-app/`** — Kotlin + Jetpack Compose app for the Lenovo TB305FU tablet (BLE direct)
- **`pc-app/`** — PyQt6 desktop app for Linux/Windows/macOS (WB09KE BLE→UART bridge)
- **`wb09ke-bridge/`** — NUCLEO-WB09KE firmware acting as BLE central → USB UART bridge for the PC app

Shared: `log/`, `CLAUDE.md`.

## Build & Run

### Android app
```bash
cd android-app

# Build debug APK
./gradlew assembleDebug

# Install on connected device
./gradlew installDebug

# Run unit tests
./gradlew test
```
Requirements: Android device API ≥ 31, USB debugging enabled. Target/compile SDK = 34.

### PC app
```bash
cd pc-app
pip install -r requirements.txt
python main.py
```
Requirements: Python ≥ 3.11, PyQt6, pyqtgraph, pyserial, numpy.

## Architecture

### Android app (`android-app/`)

Data flows in one direction through three layers:

```
STM32WB0 (BLE GATT notify 0xFFF2)
    ↓  raw ByteArray via onCharacteristicChanged
BleGattManager          — GATT lifecycle, MTU/PHY negotiation, packet parsing
    ↓  onBatchReceived(ch0: ShortArray, ch1: ShortArray, header)
BleManager              — circular buffer, StateFlow state, CSV recording, UI throttle
    ↓  StateFlow<List<TimeSeriesPoint>>  (per channel, ~30 fps)
BleGraphViewModel       — thin pass-through; exposes all flows to Compose
    ↓  collectAsState()
BleGraphScreen / TimeSeriesGraph  — Compose UI + Canvas graph
```

**`BleGattManager`** (`ble/BleGattManager.kt`) — owns the raw Android GATT stack. Connection sequence: `discoverServices` → `requestMtu(247)` → `setPreferredPhy(2M)` → write CCCD to enable notify on 0xFFF2. Raw packets are queued to a `Channel<ByteArray>(2048)` and consumed by a single-threaded coroutine (`parserScope`) so the BLE callback thread is never blocked. `parseStreamPacket` decodes the 8-byte header + interleaved int16 pairs.

**`BleManager`** (`ble/BleManager.kt`) — orchestrates scanning, connection, data buffering, CSV recording, and auto-reconnect. Key constants at the top of the file control sampling rates and buffer sizes — change `DELIVERED_SPS` and `STREAM_MODE` comments together when switching between Android-BLE (~7,725 SPS) and WB09KE-HF (30,000 SPS) modes.

**`CircularMultiChannelBuffer`** (`data/Models.kt`) — thread-safe ring buffer holding up to `BUFFER_SIZE` 4-channel points. All public methods are `@Synchronized`. `getChannelWindow()` is the primary read path, extracting a single channel's last N points with optional downsampling.

**`BleGraphViewModel`** (`vm/BleGraphViewModel.kt`) — delegates everything to `BleManager`; exists to decouple lifecycle from the Activity. No custom `ViewModelFactory` — `BleManager` is constructed in `MainActivity` and injected manually.

### PC app (`pc-app/`)

```
STM32WB0 (BLE peripheral "Kuntur-N", STREAM_MODE_WB09KE_HF)
    ↓  BLE 2M PHY, 244-byte notify packets
NUCLEO-WB09KE          — BLE central, USB CDC ACM bridge (wb09ke-bridge/)
    ↓  USB serial, framed: 0xAA 0x55 + uint16 length + 244-byte payload
SerialReader (QThread) — re-sync on magic, parse, emit batch_received signal
    ↓  ParsedPacket(ch0, ch1, timestamps_us)
GraphWidget            — circular numpy buffer, pyqtgraph 30 fps plot
CsvRecorder            — timestamp_us,ch0,ch1  (identical format to Android)
```

## BLE Device Protocol

- **Service**: `0xFFF0`
- **Notify characteristic**: `0xFFF2` (STM32 → Android, `StreamDataPacket`)
- **Write characteristic**: `0xFFF1` (reserved, phone → STM32)
- **Packet layout** (little-endian):
  - bytes 0–3: `uint32` timestamp_s
  - bytes 4–5: `uint16` timestamp_sub_s (ms%1000 × 32, range 0–31999)
  - byte 6: `uint8` seq_num (rolling 0–255, for drop detection)
  - byte 7: `uint8` num_pairs
  - bytes 8–243: 59 pairs × (`int16_t` ch0 + `int16_t` ch1), interleaved, signed, little-endian = 236 bytes
- **Timestamp formula**: `packetBaseUs = timestampS × 1_000_000 + timestampSubS × 1_000 / 32`
- A monotonicity clamp in `onBatchDataReceived` prevents backwards jumps caused by HAL_GetTick() 1 ms resolution + BLE CI jitter.

## CSV Recording

Recordings are written to the device's Downloads folder via MediaStore. Format: `timestamp_us,ch0,ch1` at the full sample rate (30,000 SPS × 2 channels ≈ ~178 KB/s). Auto-stop triggers at 10 minutes or < 200 MB free storage. File names: `vega_YYYYMMDD_HHmmss.csv`.

## Stream Modes

Switch by changing **both** `STREAM_ACTIVE_MODE` in `STM32_BLE/App/stream_app.h` **and** `DELIVERED_SPS` in `ble/BleManager.kt`.

| Mode | Value | STM32 `STREAM_SEND_PERIOD_MS` | Burst pipeline | Android `DELIVERED_SPS` | Device name | Result |
|---|---|---|---|---|---|---|
| `STREAM_MODE_LENOVO_SMOOTH` | 2 | 36 U (~13.9 ms) | Off — 1 pkt/CI | `4_000L` | Kuntur-S | ~4 000 SPS, smooth graph ← **active** |
| `STREAM_MODE_ANDROID_BLE` | 0 | 5 U (~1.93 ms) | On — burst | `7_725L` | Kuntur-A | ~7 725 SPS, bursty delivery |
| `STREAM_MODE_WB09KE_HF` | 1 | 2 U (~0.77 ms) | On — burst | `30_000L` | Kuntur-N | 30 000 SPS |

The burst pipeline (`BLEStack_Process_Schedule` + immediate `UTIL_SEQ_SetTask` after each send) is what creates multi-packet-per-CI bursts. Disabled in LENOVO_SMOOTH so the VTIMER alone paces delivery at ~1 pkt/CI.

## Display Modes

Toggle via `BleManager.toggleDisplayMode()`:
- **Downsampled** (default): last 5 s of delivered samples, `DOWNSAMPLING_FACTOR_DISPLAY = 1`
- **Full resolution**: last 0.5 s of delivered samples, no decimation

## STM32 Firmware (Kuntur MCU)

**Path**: `/data/projects/kuntur/kuntur144/mcu/kuntur-mcu`
**IDE**: STM32CubeIDE (Eclipse-based, `.cproject` / `.project`). Build output: `Debug/kuntur-mcu.elf` / `.hex`.
**Target**: STM32WB09TEFX (64 KB RAM, BLE stack in flash). Linker script: `STM32WB09TEFX_FLASH.ld`.

Key application files (under `STM32_BLE/App/`):

| File | Role |
|---|---|
| `stream.h` / `stream.c` | GATT service definition, `StreamDataPacket_t` struct, `STREAM_NotifyData()` |
| `stream_app.h` / `stream_app.c` | Ring buffer (4096 pairs = ~137 ms at 30 kSps), simulation path, VTIMER-driven send task |
| `app_ble.c` | BLE event dispatcher; calls `STREAM_APP_OnCCCDWrite()` and `STREAM_APP_ResumeSending()` |

**STM32 streaming pipeline**:
```
VTIMER (StreamSendTimerCb) → UTIL_SEQ task (StreamSendTask)
  ├─ Ring buffer has ≥59 pairs → send real FPGA data
  └─ Ring buffer empty        → send simulation (10-bit sawtooth: CH0=N, CH1=(N+512)%1024)
→ STREAM_NotifyData() → aci_gatt_srv_notify on 0xFFF2
→ BLEStack_Process_Schedule() + self-reschedule (multi-packet per CI)
```

TX flow control: if `aci_gatt_srv_notify` returns `0x88` (pool full), `s_txFlowOff` is set and sending stops. It resumes via `ACI_GATT_TX_POOL_AVAILABLE_VSEVT_CODE` → `STREAM_APP_ResumeSending()`.

**Switching stream modes** — must change both files together:
- STM32: `STREAM_ACTIVE_MODE` in `STM32_BLE/App/stream_app.h`
- Android: `DELIVERED_SPS` constant at the top of `ble/BleManager.kt`

**RTC timestamp encoding** (LSE 32.768 kHz, `BYPSHAD` set for non-blocking reads):
- `timestamp_s` = H×3600 + M×60 + S
- `timestamp_sub_s` = `(32767 − SSR) × 32000 / 32768` → range 0–31999
- Android decode: `packetBaseUs = timestamp_s × 1_000_000 + timestamp_sub_s × 1_000 / 32`
- **CubeMX warning**: if CubeMX regenerates code, `AsynchPrediv` and `SynchPrediv` must be manually restored to `0` / `32767` (see comment in `MX_RTC_Init` in `Core/Src/main.c`).

**UART debug**: USART1 at 115200 8N1, TX on PA1. `APP_DBG_MSG` / `printf` route through `__io_putchar` → `HAL_UART_Transmit`. On startup there is a 5-second delay to allow ST-LINK debugger attach before the BLE stack starts.

**Ingesting real FPGA data**: call `STREAM_APP_IngestSamples(ch0, ch1, numPairs)` from the SPI DMA completion handler. The ring buffer is ISR-safe (atomic index increments only). When the ring buffer has ≥59 pairs, `StreamSendTask` automatically switches from simulation to real data — no other code change needed.

## Logcat Tags

| Tag | Class |
|---|---|
| `BleGattManager` | GATT lifecycle, MTU, PHY, packet drops |
| `BleManager` | scanning, connection, recording |
