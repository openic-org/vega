# BLE Transmission — Consolidated Findings

Everything learned about the BLE transmission path during the SKP investigation
(culminating 2026-07-30, see `2026-07-30.md` for the chronological version).
Topic-organized, not chronological. Scope: the STM32WB0 "Kuntur" peripheral's
notify path only (`kuntur-mcu/STM32_BLE/App/stream_app.c` and `app_ble.c`) —
the WB09KE bridge and pc-app sides are covered by
`data-pipeline-timeline.md`.

---

## 1. Protocol facts (reference — see also root `CLAUDE.md`)

- Service `0xFFF0`, notify characteristic `0xFFF2` (STM32→phone/bridge),
  write characteristic `0xFFF1` (reserved).
- `ATT_MTU = 247` (`CFG_BLE_ATT_MTU_MAX`, `app_conf.h:141`) — DLE already maxed.
- 2M PHY (`RCC`-independent radio clock, 32 MHz HSE).
- Packet: 8-byte header (`timestamp_s`, `timestamp_sub_s`, `seq_num`,
  `num_pairs`) + 236-byte payload (59 pairs × int16 ch0/ch1) = 244 bytes,
  fits the 247-byte MTU.
- `STREAM_PAIRS_PER_PACKET = 59` — fixed, not adaptive.
- Target rate 30,000 SPS/channel ⇒ ~508 packets/s ⇒ one packet every ~1.97 ms
  of real time, when the link can sustain it.

---

## 2. TX flow control — the central mechanism of this whole investigation

`STREAM_NotifyData()` → `aci_gatt_srv_notify()`. Two outcomes:

- `BLE_STATUS_SUCCESS` — packet queued into the controller's TX mblock pool.
- `BLE_STATUS_INSUFFICIENT_RESOURCES` (**0x88**) — pool full. App sets
  `s_txFlowOff = 1U` and stops sending.

Recovery is **entirely asynchronous and outside application control**:
`ACI_GATT_TX_POOL_AVAILABLE_VSEVT_CODE` fires once the controller has drained
enough of the pool over the air, dispatched to `app_ble.c`'s
`SVCCTL_App_Notification` switch, which calls `STREAM_APP_ResumeSending()`
(`stream_app.c`) — clears `s_txFlowOff` and re-triggers the send task via
`UTIL_SEQ_SetTask(CFG_TASK_STREAM_SEND_ID, ...)`.

**Pool size** is set by `CFG_BLE_MBLOCKS_COUNT` (`app_conf.h:312`):
```c
#define CFG_BLE_MBLOCKS_COUNT (BLE_STACK_MBLOCKS_CALC(CFG_BLE_ATT_MTU_MAX,
                                CFG_BLE_NUM_RADIO_TASKS, CFG_BLE_NUM_EATT_CHANNELS)
                                + CFG_BLE_MBLOCK_COUNT_MARGIN)
```
`CFG_BLE_MBLOCK_COUNT_MARGIN = 54` (`app_conf.h:179`) is the only tunable
headroom — this is the direct knob for "how big a burst before the first 0x88."
It doesn't raise the sustained throughput ceiling (that's set by how fast the
controller can actually drain packets over the air, i.e. link capacity), it only
changes how often the app hits the wall for a given average rate.

### 2.1 Why the app hits 0x88 at all, structurally

`StreamSendTask`'s steady-state loop (`stream_app.c`) intentionally sends as
fast as `BLE_STACK_Tick()` allows, in a tight `while(1)`, until the pool is
exhausted — this is deliberate, not a bug (see §3). So flow-off isn't a rare
error condition; it's the expected, regular backpressure signal from pushing the
link at its ceiling. Measured stall counts: 67–103 flow-off events per
~100–116 s recording (roughly one every 1–1.5 s).

### 2.2 Measured stall durations

From the UART debug log (`APP_DBG_MSG` in `STREAM_APP_ResumeSending()`, prints
when `stall_us > 3000`):

- Typical: 4.4–8.5 ms (dominant range across all 2026-07-30 recordings).
- Outlier: 21.75 ms, precisely measured via oscilloscope in `scope_15`
  (see §3 of `2026-07-30.md`) — the longest directly observed, though the UART
  log's `s_longest_stall_us` running-max variable shows `22446250 us` (22.4 s)
  printed in every "LONG STALL" line in the 2026-07-30 recordings. **This is a
  known cosmetic bug**: `s_longest_stall_us` is never reset on reconnect, so
  it's carrying a stale value from a much earlier session/connection. Not the
  real worst-case for the sessions in question — not fixed yet, low priority.

### 2.3 What the oscilloscope proved about *why* stalls take as long as they do

Full detail in `2026-07-30.md` §1. Summary: during a stall, the CPU is not
stuck anywhere — it sleeps/wakes on its completely ordinary ~2.04 ms cadence
(driven by the periodic VTIMER fallback, `STREAM_SEND_PERIOD_MS`), waiting for
`ACI_GATT_TX_POOL_AVAILABLE_VSEVT_CODE`. That event's timing is internal to the
closed-source BLE stack (link-layer packet draining over the air, governed by
connection interval and how much data the controller can push per connection
event) — **not observable or fixable from application code.** This was
confirmed by two independent negative angles: (a) direct GPIO instrumentation of
`UTIL_LPM_EnterLowPower()` entry/exit (PA0 marker) showed 15 short sleep
episodes during one 21.75 ms stall, not one continuous stuck call; (b) wiring up
the previously-dead `CFG_LPM_FPGA_SPI` low-power-manager requester ID changed
nothing about stall duration.

---

## 3. Why the send loop is a tight synchronous `while(1)`, not scheduler-driven

This shaped every fix decision this session. `stream_app.c`'s own header
documents a "Phase 1" experiment: an earlier architecture that scheduled sends
through `UTIL_SEQ` (with its `__WFE()` sleep) could not sustain 30k SPS. The
fix was rewriting the send path as one synchronous loop that calls
`BLE_STACK_Tick()` directly after each successful notify, bypassing the
scheduler's sleep entirely:

```c
while (1) {
    FPGA_SPI_ReadSamples(...) / StreamAssemblePacket(...)
    STREAM_NotifyData(...)
    if (0x88) goto flow_off;
    BLE_STACK_Tick();   // pump HCI → LL directly, no UTIL_SEQ round-trip
}
```

**Consequence for this session's fixes:** any change that reintroduces a
separately-scheduled task for ingestion (as originally proposed) risks
regressing this. Every fix implemented was deliberately confined to either (a)
code that only runs *during* an already-stalled period (zero cost when not
stalled), or (b) a single extra branch/comparison in the hot path (see
`2026-07-30.md` §3, §7.1).

---

## 4. `BLE_STACK_Tick()` semantics — load-bearing for the diagnostic in §5

From `ble_stack.h`'s doc comment (closed-source stack, header-only visibility):

> *"The BLE Stack Tick function has to be executed to process incoming Link
> Layer packets and to process Host Layers procedures. **All stack callbacks
> are called by this function.**"*

This means `BLE_STACK_Tick()` synchronously dispatches vendor events —
including `ACI_GATT_TX_POOL_AVAILABLE_VSEVT_CODE` → `STREAM_APP_ResumeSending()`
— from wherever it's called, without needing `UTIL_SEQ_Run()` to reach a
separate cooperative task. This was the key fact that made the Round 3
gap-free-polling diagnostic safe to spin without deadlocking the scheduler (see
`2026-07-30.md` §6) — confirmed *before* implementing it, not discovered by
trial and error.

There's also a `BLE_STACK_TickNoEvents()` variant (processes Host layers
*without* calling `BLE_STACK_Event()`, safe from interrupt context) — not used
this session, noted for future reference if a truly-non-blocking tick is ever
needed from an ISR.

---

## 5. Two negative results that ruled out capacity and cadence as the cause

Both are important precisely because they were disproven — they closed off
entire classes of explanation and pointed at the real bug (`2026-07-30.md` §7):

1. **Bounded per-tick ring-buffer ingest during stalls** (poll once per ~2 ms
   fallback tick into an 8 KB / 2048-pair MCU-side buffer, stacked on the
   FPGA's own ~34 ms hardware FIFO): **no change** in SKP/stall ratio
   (1.687 baseline → 1.727). Ruled out: buffer capacity was never the
   constraint — actual stalls (4.5–22 ms) were far shorter than the ~100 ms
   combined margin.
2. **Gap-free continuous polling during stalls** (spin with zero idle gaps,
   relying on `BLE_STACK_Tick()` semantics from §4 to stay deadlock-safe):
   **also no change**, if anything slightly worse (1.826). Ruled out: it's not
   a resume-after-idle artifact triggered by polling-cadence interruption
   either.

The real bug was in code neither experiment touched — the transition *into*
flow-off itself, where an already-FPGA-read packet was discarded rather than
buffered (fixed, see `2026-07-30.md` §7.1). After the fix: SKP/stall dropped to
0.718, a ~58% reduction, and the dominant ~59-sample (one packet) jump
signature nearly disappeared (down to a single occurrence out of 74 residual
SKPs).

---

## 6. Residual BLE-correlated timing (open, handed to next session)

One of the two remaining SKP categories (`2026-07-30.md` §7.3, "Category B")
shows a strikingly consistent **+46.0 to +46.2 ms offset after a flow-off
resume** — a second, distinct transition, not colocated with resume like the
fixed bug. Not yet root-caused. Leading hypothesis is app-side (the
ring-buffer-backlog-drained transition in `StreamAssemblePacket()`), but if
that's ruled out next session, the remaining candidate is a second, slower BLE
resource distinct from the TX mblock pool that also gates resumption at a
~46 ms cadence — that would be a second closed-stack-internal timing constraint,
same flavor as §2.3 but a different resource. Not confirmed either way yet.

---

## 7. Levers available for future flow-off frequency reduction (not yet applied)

Deferred deliberately (§2.4 in `2026-07-30.md`) — recorded here for reference
when it's picked back up:

- **`CFG_BLE_MBLOCK_COUNT_MARGIN`** (currently 54, `app_conf.h:179`) — raise for
  bigger bursts before the first 0x88. RAM cost, same 64 KB budget as the ring
  buffer competes for.
- **Pacing** `STREAM_NotifyData()` calls to track real per-CI airtime instead of
  firing flat-out — trades against the throughput headroom §3 was built for.
- **Link capacity**: DLE/MTU already maxed; multi-packet-per-CI burst pipeline
  already active; a shorter connection interval (if the WB09KE bridge, acting
  as BLE central, isn't already requesting the tightest one) would raise the
  ceiling itself rather than just changing how bursts hit it.
