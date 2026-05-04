# Vega — Real-Time ADC Visualisation System

Vega streams 30 000 samples per second from a **STM32WB09KE** ("Kuntur") MCU over Bluetooth Low Energy and displays both channels live.  Two front-ends are provided: an Android tablet app and a Linux/macOS/Windows desktop app.

---

## Hardware

| Component | Part | Role |
|---|---|---|
| Sensor node | NUCLEO-WB09KE (Kuntur firmware) | BLE peripheral — samples ADC, encodes & notifies |
| BLE-to-USB bridge | NUCLEO-WB09KE (bridge firmware) | BLE central — forwards notify packets over UART |
| Host PC | Any | Runs the PyQt6 desktop app |
| Android tablet | Lenovo TB305FU (API 31+) | Runs the Android app (BLE direct, no bridge needed) |

The bridge exposes a standard ST-LINK Virtual COM Port at 2 Mbaud.  No custom driver is required.

---

## Repository Layout

```
vega/
├── android-app/        Kotlin + Jetpack Compose Android app
├── pc-app/             PyQt6 desktop app (Linux / macOS / Windows)
├── wb09ke-bridge/      NUCLEO-WB09KE BLE-to-UART bridge firmware
├── log/                Session logs
├── CLAUDE.md           Developer notes for Claude Code
├── BLE_CONFIGURATION.md  BLE packet format reference
├── LICENSE
└── README.md           ← you are here
```

The Kuntur MCU firmware lives in a separate repository:
`/data/projects/kuntur/kuntur144/mcu/kuntur-mcu`

---

## Quick Start

### Android app

Requirements: Android Studio Iguana or later, Android SDK 34, device with API ≥ 31, USB debugging on.

```bash
cd android-app
./gradlew assembleDebug        # build
./gradlew installDebug         # install on connected device
```

1. Open the app and grant Bluetooth permissions.
2. Tap **Scan** — the Kuntur device appears as `Kuntur-N`.
3. Tap it to connect.  Live waveforms appear immediately.
4. Tap **Record** to save a CSV to the device Downloads folder.

### PC app

Requirements: Python ≥ 3.11, PyQt6, pyqtgraph, pyserial, numpy.

```bash
cd pc-app
pip install -r requirements.txt
python main.py
```

1. Flash the bridge firmware (`wb09ke-bridge/`) to a NUCLEO-WB09KE and connect it via USB.
2. Power on the Kuntur node.
3. In the app, select `/dev/ttyACM1` (2 000 000 baud) and click **Connect**.
4. Live waveforms appear.  Click **Record** to save a CSV.

Device assignment with both boards connected:

| Port | Device |
|---|---|
| `/dev/ttyACM0` | Kuntur NUCLEO ST-LINK VCP — debug UART at 115 200 baud |
| `/dev/ttyACM1` | WB09KE bridge ST-LINK VCP — data stream at 2 000 000 baud |

### Bridge firmware

```bash
cd wb09ke-bridge
make                  # build
make flash            # flash via SWD (requires STM32CubeProgrammer in PATH)
```

### Kuntur MCU firmware

```bash
# Build (STM32CubeIDE toolchain must be on PATH)
make -C /data/projects/kuntur/kuntur144/mcu/kuntur-mcu/Debug all

# Flash
STM32_Programmer_CLI -c port=SWD sn=<serial> \
  -w Debug/kuntur-mcu.elf -v -rst
```

---

## BLE Protocol

- **PHY**: 2M
- **ATT MTU**: 247 (244-byte payload)
- **Data length extension**: 251 bytes both directions
- **Connection interval**: 7.5 ms → ~4 packets per CI → **30 000 SPS**
- **Service**: `0xFFF0`
- **Notify characteristic**: `0xFFF2`

Each notify packet carries an 8-byte header followed by up to 59 interleaved `int16` CH0/CH1 sample pairs:

| Bytes | Field | Description |
|---|---|---|
| 0–3 | `timestamp_s` | `uint32` — whole seconds (H×3600 + M×60 + S) |
| 4–5 | `timestamp_sub_s` | `uint16` — (32767 − SSR) × 32000 / 32768 |
| 6 | `seq_num` | `uint8` — rolling 0–255, for drop detection |
| 7 | `num_pairs` | `uint8` — number of CH0/CH1 pairs that follow |
| 8+ | samples | interleaved `int16` ch0, ch1, ch0, ch1, … |

Timestamp decode: `base_us = timestamp_s × 1_000_000 + timestamp_sub_s × 1000 / 32`

---

## CSV Recording Format

```
timestamp_us,ch0,ch1
1234567890,512,1024
...
```

One row per sample at the full ADC rate (~178 KB/s at 30 kSPS × 2 channels).  Files are named `vega_YYYYMMDD_HHmmss.csv`.

---

## Plot Tools (`pc-app/`)

Two helper modules are included for offline analysis:

- **`plot_palette.py`** — dark-theme color constants and three matplotlib helpers (`fig_defaults`, `apply_dark_axes`, `dark_legend`).
- **`plot_template.py`** — parametric 5-panel analysis template (full waveform, zoom, Δt histogram, gap timeline, statistics).  Edit the `── CONFIGURE ──` block at the top for your CSV file, then run `python plot_template.py`.

---

## Stream Modes

Three modes are available.  Both the STM32 firmware and the Android app constant must be changed together when switching:

| Mode | STM32 `STREAM_ACTIVE_MODE` | Android `DELIVERED_SPS` | Device name | Result |
|---|---|---|---|---|
| `STREAM_MODE_LENOVO_SMOOTH` | 2 | 4 000 | `Kuntur-S` | ~4 000 SPS, smooth |
| `STREAM_MODE_ANDROID_BLE` | 0 | 7 725 | `Kuntur-A` | ~7 725 SPS |
| `STREAM_MODE_NORDIC_HF` | 1 | 30 000 | `Kuntur-N` | 30 000 SPS |

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).
