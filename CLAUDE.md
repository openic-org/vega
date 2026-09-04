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

### Firmware (both STM32 targets)

The ARM toolchain ships inside STM32CubeIDE and is **not** on `PATH` by default —
it lives deep enough that a shallow `find` misses it:

```bash
export PATH=/opt/st/stm32cubeide_2.1.1/plugins/com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.14.3.rel1.linux64_1.0.100.202602081740/tools/bin:$PATH

# Kuntur MCU (headstage) — writes Debug/kuntur-mcu.elf / .hex
cd /data/projects/kuntur/kuntur144/mcu/kuntur-mcu/Debug && make all -j8

# WB09KE bridge — writes build/Vega_Bridge.bin / .elf / .hex
cd wb09ke-bridge && make -j8      # TOOLCHAIN_PATH is already set in its Makefile
```

Both build clean from the CLI; STM32CubeIDE is not required to compile, only to
debug. Flashing is separate — see the memory note on WB09KE NUCLEO flashing
(GUI + physical RESET presses; the CLI fails "Unable to get core ID").

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
    ↓  USB serial, three frame types, all [magic][uint16 len][payload]:
    ↓    0xAA 0x55  sample data     (244-byte payload)
    ↓    0xEE 0x11  command response
    ↓    0xDD 0x22  telemetry       (bridge appends its own TX-ring counters)
SerialReader (QThread) — re-sync on magic, parse, emit batch_received signal
    ↓  ParsedPacket(ch0, ch1, timestamps_us)
GraphWidget            — circular numpy buffer, pyqtgraph 30 fps plot
CsvRecorder            — timestamp_us,ch0,ch1  (identical format to Android)
```

## BLE Device Protocol

- **Service**: `0xFFF0`
- **Notify characteristic**: `0xFFF2` (STM32 → host, `StreamDataPacket`)
- **Write characteristic**: `0xFFF1` (host → STM32, command frames — see below)
- **Response characteristic**: `0xFFF3` (notify, STM32 → host, command responses)
- **Telemetry characteristic**: `0xFFF4` (notify, STM32 → host, ~1 Hz loss/anchor
  frame — see below and `docs/interfaces/stream-packet-format.md` §6)
- **Packet layout** (little-endian):
  - bytes 0–3: `uint32` timestamp_s
  - bytes 4–5: `uint16` timestamp_sub_s (ms%1000 × 32, range 0–31999)
  - byte 6: `uint8` seq_num (rolling 0–255, for drop detection)
  - byte 7: `uint8` num_pairs
  - bytes 8–243: 59 pairs × (`int16_t` ch0 + `int16_t` ch1), interleaved, signed, little-endian = 236 bytes
- **Timestamp formula**: `packetBaseUs = timestampS × 1_000_000 + timestampSubS × 1_000 / 32`
- A monotonicity clamp in `onBatchDataReceived` prevents backwards jumps caused by HAL_GetTick() 1 ms resolution + BLE CI jitter.

### Control plane (`0xFFF1` write → `0xFFF3` notify)

Commands are **validated in the BLE callback and deferred** — the callback stashes a
pending flag and returns; the SPI work runs later inside `StreamSendTask`, and only from
its stopped branch. That is what keeps regbank traffic from interleaving with an
in-progress `FPGA_SPI_ReadSamples()`. `s_command_busy` rejects a second command while one
is in flight.

| Cmd | Name | Length | Requires streaming stopped |
|---|---|---|---|
| `0x01` | `SET_CHANNELS` (ch_a, ch_b — friendly 0–127) | 3 | yes |
| `0x02` | `STOP_STREAMING` | 1 | — (this is what stops it) |
| `0x03` | `START_STREAMING` | 1 | — |
| `0x04` | `REG_WRITE16` (addr, val_lo, val_hi) | 4 | yes |
| `0x05` | `REG_READ16` (addr) | 2 | yes |

Responses on `0xFFF3` — first byte always echoes the command opcode it answers:

- `[0x01, ch_a, ch_b]` — channel readback, converted back to friendly indices
- `[0x02\|0x03, success]` — stop/start ack; `success` is an **FPGA readback**
  confirmation of `stream_enable`, not a host-side timer
- `[0x04\|0x05, addr, val_lo, val_hi]` — register access; the value is what the regbank
  *holds* after the operation, so a `REG_WRITE16` ack doubles as verification

`STOP_STREAMING` order matters: `SetStreamEnable(0)` → readback → only then flush `fifo0`,
so the flush drains a static backlog rather than racing a live 30 kSPS producer. If the
readback is non-zero the flush is skipped and logged loudly.

### Telemetry plane (`0xFFF4` notify → `0xDD 0x22` frame)

**A.7 step 2. Implemented 2026-09-04; builds clean on all three sides and is
desk-verified, but has not run on hardware yet** — the bridge's connection
sequence now writes a *fourth* CCCD, which is the part with a history of
fragility. Spec and open items: `docs/interfaces/stream-packet-format.md` §6.

A ~1 Hz frame carrying every loss counter plus an RTC time anchor, assembled in
two hops: the MCU fills bytes 0–29 and notifies on `0xFFF4`; the bridge appends
its own TX-ring truncation counters (bytes 30–37) and emits `0xDD 0x22`. The
bridge never synthesises one from its own counters alone — no `0xFFF4`
notification, no frame.

Counters are **cumulative since `START_STREAMING`** and are never reset by a
report, so a lost frame costs resolution rather than information. The point is
attribution: `dropped_packets` in the pc-app conflates a USB backlog with a
radio problem, and only the bridge can tell them apart.

| Field | Answers |
|---|---|
| `fifo0_overflow_samples` / `fifo0_high_water` | FPGA outran the transport — **not yet readable, see below** |
| `ring_truncated_samples` | MCU ring overflowed during a flow-off stall |
| `flow_off_count` / `stall_time_ms_total` | both halves of the stall duty cycle |
| `tx_ring_drop_bytes` / `tx_ring_drop_frames` | bridge USB backlog, *not* a radio problem |
| none of the above moved, but samples are missing | lost on air |

`flags` bit 0 `fpga_counters_valid` is `0` in this build and the two `fifo0_*`
fields read `0`: the RTL counter (A.7 step 1) does not exist yet, and
"cannot be read" must not look like "read as zero". The MCU switch is
`STREAM_TELEMETRY_FPGA_COUNTERS` in `stream_app.c`; turning it on needs that
switch plus the two regbank word addresses, and nothing else in the chain.

**Why the MCU may read the regbank at 1 Hz while streaming**, when every other
regbank access in the firmware is confined to the streaming-*stopped* branch:
the read is issued from exactly one call site — the top of `StreamSendTask`, at
a packet boundary, reads only, skipped during a flow-off. Full argument in the
spec's §6.6; do not add a second call site without reading it.

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
| `stream_app.h` / `stream_app.c` | Ring buffer (2048 pairs ≈ 68 ms at 30 kSps) used as a stall backlog, VTIMER-paced send task, 0xFFF1 command handler |
| `app_ble.c` | BLE event dispatcher; calls `STREAM_APP_OnCCCDWrite()` and `STREAM_APP_ResumeSending()` |

**STM32 streaming pipeline**:
```
VTIMER (StreamSendTimerCb, 2 ms safety fallback) → UTIL_SEQ task (StreamSendTask)
→ StreamAssemblePacket(): pop any backlog from the ring first,
  then pull the remaining pairs live via FPGA_SPI_ReadSamples()
→ STREAM_NotifyData() → aci_gatt_srv_notify on 0xFFF2
→ BLE_STACK_Tick() directly, looping until 0x88 (multi-packet per CI)
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

**FPGA sample ingestion** — a synchronous pull, not a DMA push. `StreamAssemblePacket()` calls `FPGA_SPI_ReadSamples()` (bit-banged SPI0 on APB0 pins — the SPI peripheral is unusable because the BLE radio gates APB1) from inside `StreamSendTask`, at BLE send cadence. There is no ISR path and no simulation fallback.

The ring buffer is a backlog absorber, not the normal path: it is empty in steady state, and fills only while `s_txFlowOff` holds the send loop back — `StreamIngestDuringStall()` then pulls one packet's worth (59 pairs) per ~2 ms tick. On the next send, the ring is drained first and only the shortfall is read live from the FPGA. Second line of defense behind it is the FPGA's own ~34 ms hardware FIFO (fifo0).

## Logcat Tags

| Tag | Class |
|---|---|
| `BleGattManager` | GATT lifecycle, MTU, PHY, packet drops |
| `BleManager` | scanning, connection, recording |
