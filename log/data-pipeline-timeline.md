# RHD2164 → pc-app: Full Delivery Timeline

End-to-end sequence for one group of samples from the Intan RHD2164 headstage
ADC to a plotted/recorded point in the PC app, with every place BLE's
asynchronous, non-deterministic behavior can perturb an otherwise fully
deterministic (clock-driven) pipeline called out explicitly. Companion to
`ble-transmission-summary.md` (BLE specifics) and `2026-07-30.md` (how this
session's findings were derived). Firmware-side stages describe
`kuntur-mcu` + `kuntur_fpga` as they exist as of 2026-07-30 — Verilog stages
are read-only observations (Verilog is the user's domain per project
convention, not edited by the assistant).

---

## Sequence diagram

```mermaid
sequenceDiagram
    participant RHD as RHD2164 ADC
    participant FPGA as FPGA (rhd2164_controller + fifo0)
    participant MCU as STM32WB0 MCU (fpga_spi.c + stream_app.c)
    participant BLE as BLE Radio / Link Layer (closed stack)
    participant WB09 as WB09KE Bridge (BLE central, USB CDC)
    participant PC as pc-app (SerialReader → GraphWidget/CsvRecorder)

    RHD->>FPGA: SPI sample burst (deterministic, clocked)
    FPGA->>FPGA: rhd2164_controller decodes channels,\nch_sel muxes, writes {ch0,ch1} pair\ninto fifo0 (1024x32, ~34ms depth)
    Note over FPGA: FIFO is the shock absorber between the FPGA's own\nsample clock and the MCU's on-demand SPI polling.

    loop every StreamSendTask invocation
        MCU->>FPGA: bit-banged SPI read, 59 pairs\n(NSS low, 59x{ch0,ch1} words, NSS high)
        alt FIFO has <59 pairs ready
            FPGA-->>MCU: underrun sentinel (0x8000) for missing pairs
        else FIFO has data
            FPGA-->>MCU: real {ch0,ch1} words
        end
        MCU->>MCU: assemble StreamDataPacket_t\n(timestamp_s/sub_s, seq_num, 59 pairs)
        MCU->>BLE: aci_gatt_srv_notify() — enqueue into TX mblock pool
        alt pool has room
            BLE-->>MCU: BLE_STATUS_SUCCESS
            MCU->>MCU: seq_num++, BLE_STACK_Tick(), loop immediately
        else pool full (0x88)
            BLE-->>MCU: BLE_STATUS_INSUFFICIENT_RESOURCES
            Note over MCU,BLE: ★ INTERRUPT POINT 1 — TX flow-off.<br/>Packet buffered into ring (fixed 2026-07-30);<br/>s_txFlowOff=1; MCU returns to scheduler.
        end
    end

    Note over BLE: ★ INTERRUPT POINT 2 — Connection Interval gating.<br/>Queued packets can only actually leave the radio<br/>at CI boundaries, N-per-CI depending on DLE/PHY budget.
    Note over BLE: ★ INTERRUPT POINT 3 — Link-layer retransmission.<br/>RF interference/noise → LL ARQ retries within a CI,<br/>consuming that CI's packet budget invisibly to the app.
    Note over BLE: ★ INTERRUPT POINT 4 — TX pool refill timing.<br/>ACI_GATT_TX_POOL_AVAILABLE_VSEVT_CODE fires whenever<br/>the closed stack decides enough has drained — not app-observable,<br/>not app-controllable (2026-07-30 measured 4.5-22ms typical).

    BLE->>MCU: ACI_GATT_TX_POOL_AVAILABLE_VSEVT_CODE\n(dispatched via BLE_STACK_Tick() or async HCI task)
    MCU->>MCU: STREAM_APP_ResumeSending()\ns_txFlowOff=0, UTIL_SEQ_SetTask(send task)
    Note over MCU: ★ INTERRUPT POINT 5 (hypothesis, unconfirmed) —<br/>possible second transition bug when ring-buffer<br/>backlog fully drains back to live FPGA reads,<br/>~46ms after resume. Next session's first task.

    BLE->>WB09: air interface, GATT notification\n(2M PHY, up to 244B payload/packet)
    Note over WB09: ★ INTERRUPT POINT 6 — WB09KE is itself a second<br/>BLE stack instance (central role) with its own<br/>connection-event timing and possible reconnect/<br/>re-pairing behavior, independent of the peripheral side.
    WB09->>WB09: BLE central stack receives notification,\nre-frames as 0xAA 0x55 + len + 244B payload
    WB09->>PC: USB CDC ACM serial stream
    Note over WB09,PC: ★ INTERRUPT POINT 7 — USB CDC ACM is itself a\nseparately-scheduled, buffered transport (host USB\npolling interval, OS driver latency) — not synchronous\nwith the BLE air interface that fed it.

    PC->>PC: SerialReader (QThread) — re-sync on 0xAA 0x55 magic,\nparse header + 59 pairs
    PC->>PC: GraphWidget — circular buffer, 30fps plot\nCsvRecorder — timestamp_us,ch0,ch1,seq_num
```

---

## Stage-by-stage detail

### 1. RHD2164 → FPGA (deterministic)

The RHD2164 is sampled via its own SPI interface, decoded by
`rhd2164_controller` in `spi_controllers.v`, channel-muxed by `ch_sel`, and
written as a `{ch0, ch1}` pair into `fifo0` (`kuntur_fpga.v:178-181`,
`DATA_WIDTH=32, ADDR_WIDTH=10` → 1024 entries ≈ **~34 ms of buffering at
30,000 pairs/s**). This entire stage is clock-driven and has no dependency on
BLE — it runs whether or not a phone/bridge is even connected. `fifo0` is the
shock absorber that makes everything downstream tolerant of the MCU not
polling for a while.

### 2. FPGA → MCU (on-demand, MCU-paced)

`FPGA_SPI_ReadSamples()` (`fpga_spi.c`) bit-bangs a 59-pair SPI read on
dedicated APB0 GPIO pins (`SCK=PB3, MISO=PA8, MOSI=PA11, NSS=PA9` — chosen
specifically because APB0 is never gated by the BLE radio, unlike APB1). If
the FIFO has fewer than 59 pairs ready when polled, the FPGA returns the
underrun sentinel `0x8000` for the missing entries (handled downstream — see
§6) rather than blocking. This stage happens once per `StreamSendTask`
invocation — its cadence is set by how fast the *send* side (§3) is able to
loop, not by a fixed timer, in the non-stalled case.

### 3. MCU: packet assembly and the tight send loop

`StreamSendTask()` builds a `StreamDataPacket_t` (8-byte header + 59 pairs) and
calls `STREAM_NotifyData()`. On success it loops immediately (calling
`BLE_STACK_Tick()` directly, bypassing the `UTIL_SEQ` scheduler — see
`ble-transmission-summary.md` §3 for why). This is the last fully
BLE-independent stage — everything past this point is subject to the radio.

### 4. ★ Interrupt point 1 — TX flow-off (well understood, largely fixed)

`aci_gatt_srv_notify()` can return `0x88` (pool full) at any point,
unpredictably, depending on how fast the link has been draining packets over
the air. This was the dominant source of data loss investigated all session
(`2026-07-30.md`) — as of the fix in §7.1 of that log, a stalled packet is
preserved (pushed into the MCU-side ring buffer) rather than discarded, but the
*stall itself* — 4.5 ms to 22 ms typical/observed — is still real and
unavoidable from the app side.

### 5. ★ Interrupt point 2 — Connection interval gating

Even when the TX pool has room, a queued packet physically cannot leave the
radio until the next connection event. How many packets can go out per CI
depends on CI length, PHY (2M active), and DLE payload size — all negotiated
at connect time (see `diagrams-kuntur-mcu.md`, Diagram 1). This bounds the
*sustained* throughput ceiling independent of the TX pool size — raising
`CFG_BLE_MBLOCK_COUNT_MARGIN` (§7 of `ble-transmission-summary.md`) changes how
often flow-off triggers, not this ceiling.

### 6. ★ Interrupt point 3 — Link-layer retransmission (not directly observed this session)

BLE's link layer retransmits packets lost to RF interference within the same
connection event, consuming that CI's packet budget invisibly to application
code — the app has no visibility into whether a given CI's packets went out
clean or needed retries. Raised early in the investigation as a candidate
explanation for anomalies (interference from CMOS-level debug signals brought
out to test pads was specifically discussed as a hypothesis) but not
conclusively measured either way this session — flagged as a standing unknown,
distinct from the TX-pool mechanism that was measured.

### 7. ★ Interrupt point 4 — TX pool refill timing (measured, not controllable)

`ACI_GATT_TX_POOL_AVAILABLE_VSEVT_CODE` fires whenever the closed-source stack
decides enough of the pool has drained — confirmed via oscilloscope
(`2026-07-30.md` §1) to correspond to no observable app-side delay (the CPU
sleeps/wakes normally the whole time); the stall duration is purely a function
of this internal BLE stack timing. Measured range this session: 4.5–8.5 ms
typical, 21.75 ms observed outlier.

### 8. ★ Interrupt point 5 — hypothesized second transition (open, next session)

Not yet confirmed. `2026-07-30.md` §7.3 Category B: a cluster of residual SKPs
sits at a consistent +46 ms offset after flow-off resume, distinct from the
already-fixed entry-transition bug. Leading hypothesis is a second
assembled-then-discarded failure mode at the point the ring buffer's backlog
fully drains back to live FPGA reads. First task of the next session.

### 9. Radio → WB09KE bridge

The peripheral's notification crosses the air interface to the WB09KE NUCLEO
board, which is itself running a **second, independent BLE stack instance** in
the *central* role (see `project_wb09ke_bridge.md` memory). It re-frames each
244-byte GATT payload as `0xAA 0x55 + uint16 length + 244-byte payload` and
writes it out over USB CDC ACM.

### 10. ★ Interrupt point 6 — bridge-side BLE central timing (not investigated this session)

The WB09KE's central-role connection-event handling, buffering, and any
reconnect/re-pairing behavior are a separate BLE stack instance with its own
internal timing, not something this session's peripheral-side investigation
covered. If residual, uncorrelated loss is ever found downstream of the fixes
in this session, this is a candidate location that hasn't been ruled in or out.

### 11. ★ Interrupt point 7 — USB CDC ACM transport

USB is itself a separately-scheduled, host-polled, OS-buffered transport,
asynchronous with respect to the BLE air interface that fed it. `SerialReader`
(pc-app, `QThread`) re-syncs on the `0xAA 0x55` magic bytes and parses the
framed payload — the resync logic exists specifically because this boundary
is not guaranteed to preserve message framing under all conditions (port
open/close races were fixed in an earlier session — `serial_reader: fix
stop/run race on port close`).

### 12. pc-app: final delivery

`GraphWidget` maintains a circular numpy buffer for the live 30 fps plot;
`CsvRecorder` writes `timestamp_us,ch0,ch1,seq_num` rows. `seq_num` gaps here
indicate genuine BLE-level packet loss (a packet that never arrived at all,
distinct from the SKP mechanism investigated this session, which is a
*within-packet sample count* discontinuity — see `ble-transmission-summary.md`
§5 for why seq_num-gap detection is structurally blind to the flow_off bug that
was root-caused this session).

---

## Underrun sentinel (§2, not itself a BLE interrupt, but interacts with one)

Independent of BLE: when the FPGA's `fifo0` is queried faster than the RHD2164
pipeline fills it, the sentinel `0x8000` passes through the whole pipeline
in-band (`csv_recorder.py` and `analyze_recording.py` both handle it explicitly
— see `log/2026-07-27.md` §2). Underrun rate observed 2026-07-30: ~0.9% of
samples. **Newly found this session** (`2026-07-30.md` §7.3, Category A): 98%
of the small `+2`-magnitude residual SKPs occur within 200 µs of an underrun
row, recurring at a suspiciously regular ~2.2 s period — an open question
handed to next session, not yet linked to any of the BLE interrupt points
above (rate is constant regardless of BLE flow-off fix state).
