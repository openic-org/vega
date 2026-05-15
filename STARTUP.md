# Startup & Pairing Sequence

This document defines the canonical power-on order and reconnection behaviour for
the three-component Vega system: **Kuntur MCU** (BLE peripheral), **WB09KE Bridge**
(BLE central → USB serial), and **PC app**.

---

## Components

| Component | Role | Firmware / code |
|---|---|---|
| Kuntur MCU (STM32WB09TEFX) | BLE peripheral — streams FPGA data | `kuntur-mcu/` |
| WB09KE Bridge (NUCLEO-WB09KE) | BLE central → USB CDC ACM bridge | `wb09ke-bridge/` |
| PC app | USB serial reader + display | `pc-app/` |

---

## Canonical startup order

Steps 1 and 2 are **order-independent** — the Bridge will keep scanning until the
Kuntur MCU appears. Steps 5 and 6 are **order-independent** with respect to the BLE
side — the PC app re-syncs on the first valid `0xAA 0x55` frame it sees.

```
1. Power on Kuntur MCU
   └─ 5 s HAL_Delay (SWD attach window) → prints "starting..." on USART1 115200
   └─ BLE advertising starts  name="Kuntur-Headstage"
      fast interval: 80–100 ms for 60 s
      LP interval:   after 60 s (Bridge still finds it — just slower)

2. Power on / reset WB09KE Bridge
   └─ Immediately starts passive scan on 1M PHY  window=500 ms / interval=500 ms
   └─ Finds "Kuntur-Headstage" in adv payload → aci_gap_create_connection (CI=7.5 ms)

3. Bridge performs BLE handshake (automatic, event-driven, ~1–2 s)
   └─ connect
   └─ MTU exchange → 247 (bridge initiates, Kuntur accepts)
   └─ MTU response → DLE request TxOctets=251 TxTime=2120
   └─ Symmetric DLE event (MaxTxOctets=251 both sides) → PHY 2M request
   └─ GATT discovery: all services → chars → descriptors
   └─ Write CCCD 0x0001 on characteristic 0xFFF2

4. Kuntur MCU detects CCCD write → STREAM_APP_OnCCCDWrite
   └─ Arms VTIMER at 2 ms period
   └─ StreamSendTask tight loop starts: FPGA_SPI_ReadSamples → STREAM_NotifyData
   └─ Bridge receives BLE notifications → forwards as 0xAA 0x55 frames over USB UART

5. Connect Bridge USB cable to PC (can be done at any time)

6. Open PC app → select COM port → click Connect
   └─ SerialReader re-syncs on first 0xAA 0x55 magic → data appears within 1 packet
```

---

## Reconnection behaviour

Both sides handle disconnection automatically — **no user action is needed** for
reconnection after any transient failure.

| Event | Kuntur MCU | WB09KE Bridge |
|---|---|---|
| Clean disconnect (remote user) | Resumes advertising immediately | Detects `HCI_DISCONNECTION_COMPLETE` → restarts scan |
| Link loss (supervision timeout 5 s) | Resumes advertising | Detects timeout → restarts scan |
| Bridge power-cycled | Keeps advertising; CCCD gets re-written on reconnect → streaming resumes | Restarts scan on boot |
| Kuntur power-cycled | Restarts advertising after 5 s | Detects timeout → scan → reconnects |

---

## DLE + PHY negotiation details

The LL parameter upgrade is **sequential** — sending both requests simultaneously
causes LL procedure collision (error 0x07). The Bridge firmware enforces the order:

```
connect
  └─ MTU exchange  (aci_gatt_clt_exchange_config)
       └─ MTU response  → DLE request  (hci_le_set_data_length_api 251/2120)
            └─ DATA_LENGTH_CHANGE symmetric (MaxTxOctets=251 both sides)
                 └─ PHY 2M request  (hci_le_set_phy TX=2M RX=2M)
```

If the peer responds to the PHY request with 1M (unsupported), the firmware
accepts 1M and continues — **no retry**. Streaming works at reduced throughput.

If the DLE event never reaches symmetric 251 (e.g. old Kuntur firmware), the
PHY task is never triggered, and streaming runs at 1M PHY with default DLE.

---

## PC app serial framing

The Bridge wraps every 244-byte BLE notification in a 4-byte header:

```
[0xAA][0x55][len_lo][len_hi][244 bytes of StreamDataPacket_t]
```

The PC app (`serial_reader.py`) searches for the `0xAA 0x55` magic at any point in
the byte stream — opening the port mid-packet or after a framing error is safe; the
reader will re-sync within at most one packet (248 bytes).

---

## Testing

### Validate a live session (headless)

```bash
cd pc-app
python test_validator.py --port /dev/ttyACM0
python test_validator.py --port /dev/ttyACM0 --duration 60 --max-drops 0
python test_validator.py --port /dev/ttyACM0 --verbose   # print each drop inline
```

Output columns: `Elapsed  pkt/s  SPS  drops/s  framing  ts_err`

Exit code 0 = PASS, 1 = FAIL (drops > `--max-drops` or serial error).

### Full test plan

See `log/2026-05-15.md` § "System architecture diagrams / testing plan" for the
complete test matrix (categories A–G).

---

## UART debug ports

Both MCUs print debug text on their USART1 at **115 200 baud 8N1**:

| Board | USB connector | ST-LINK UART |
|---|---|---|
| Kuntur MCU | CN1 (SWD) | PA1 TX |
| WB09KE Bridge | CN1 (ST-LINK) | integrated VCP |

Connect a terminal (e.g. `picocom -b 115200 /dev/ttyACM1`) to monitor the BLE
handshake log while the PC app reads from the Bridge data port (`/dev/ttyACM0`).
