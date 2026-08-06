# Kuntur / Vega — Delivery Plan

**Goal:** ship an open-source neural recording system — hardware, firmware, RTL,
and application — that is clean, robust, reliable, and genuinely usable by
engineers, scientists, and researchers.

Assembled 2026-08-04. Restructured into **Phase A** (road to the animal test) and
**Phase B** (road to public v1) once the animal-test date became the schedule anchor.

---

## V1 scope

**In:**

- Kuntur headstage: **2 runtime-selectable channels** of 128 available (2× RHD2164),
  **30 kSPS/channel**, 16-bit
- **Wireless mode** — BLE → WB09KE bridge → USB → Vega PC app; live view + recording
- **Wired mode** — RHD2164 SPI tunnelled bidirectionally over LVDS/uHDMI to a
  **companion FPGA** feeding the **Intan controller**, with simultaneous BLE
  streaming. **Required for Kuntur to be usable — cannot be deferred.**
- Battery powered (battery bank)
- Subjects: animals first; human research (IRB) subsequently
- Deliverable: **open hardware + firmware + software**

**Out (documented explicitly as unsupported):**

- Stimulation (RHS2116 / `stim16ch`) — later version
- Android app — archived
- Coin-cell operation — later; likely a different operating mode
- >2 channel modes (4ch@15k, 8ch@7.5k, …) — roadmap; architecture must not preclude
- **Multiple simultaneous Kuntur devices in the pc-app** — roadmap; discuss when it
  comes up. Raised 2026-08-05 during the A.2 command-relay spec work: likely one
  WB09KE bridge per device (own USB serial port each), not one bridge multiplexing
  several BLE links — matches the isolation argument above (BLE buys **per-headstage**
  galvanic isolation, so one device ↔ one isolated wireless link is the natural
  unit, not a shared bridge). If so, needs **no protocol change** — magic bytes
  identify frame *type* (data vs. command), not *device*; the OS-level serial port
  already disambiguates which physical device a byte stream belongs to. Only the
  multiplexed-single-bridge alternative would need a device/connection-ID field
  added inside existing frames — architecture must not preclude either path.

**Fixed constraint:** BLE carries a ~60 kSPS aggregate 16-bit budget. Future modes
trade channel count against per-channel rate within it. This is deliberate —
**BLE buys galvanic isolation in wireless mode**, the core safety argument.

## Hardware inventory

Five PCBs, all in scope for the open-hardware release:

| Board | Role |
|---|---|
| `kuntur144-nil` | Bottom: 2× RHD2164 (`rec64ch`) **+ RHS2116** (`stim16ch`) |
| `kuntur144-ecl` | Top: FPGA (`LIFCL-17-8UWG72C`) + STM32WB09 MCU |
| `kuntur144-omnetics` | Adapter: bottom board → cables → Intan controller |
| `kuntur144-prog`, `-prog-adapter` | Programming |

Bottom and top connect via a 24-pin Molex. **RHS2116 is physically present on the
bottom board** — must be explicitly unpowered/disabled, in writing, before any
subject contact.

## Team & ownership

**Manuel** (PhD EE, full-time): hardware, PCB, analog/mixed-signal, FPGA RTL, all
bring-up and bench work. **Claude**: PC-app, firmware, tooling, docs. Firmware
debugging is joint.

**The constraint is bench time, not code.** Every hardware iteration requires Manuel
present. Optimise for fewer, higher-information hardware sessions — the argument for
building the injection rig and automated compare tooling early.

**Structural risk:** the boundary between owners is exactly where this project's bugs
concentrate (FPGA↔MCU SPI, MCU↔app protocol). Interface specs are the coordination
mechanism between us, not paperwork.

**Claude's limitations, planned around:** no session continuity except memory files
(which drifted from reality — the repo must become the memory); will assert wrong
things about hardware state unless verified against source each time; cannot run,
observe, or measure hardware. Long-running work is checkpointed in files.

**Bus factor is 1 and it is the human.** This raises the return on contributability
and knowledge-transfer work — external contributors are the only path to scale.

---

# PHASE A — Road to the animal test

**Target: September, flexible to October.** Requires the wired path.

## Why the wired path is worth the effort

Not merely a surgical feature. **The Intan controller is a trusted, already-validated
reference instrument**, and the wired path is the only way to compare against it
simultaneously on the same electrodes: one signal, one AFE, two independent readouts
(LVDS→Intan controller, BLE→pc-app). Sample-for-sample agreement is calibration
against an established instrument — what makes a datasheet number defensible.
Without it, the wireless path is validated only against itself.

## De-risking ladder

| Rung | Setup | Validates | Status |
|---|---|---|---|
| 1 | Bottom board + omnetics + Intan controller | Electrodes, surgical workflow, bottom board | **Works today** |
| 2 | Bench: injected signal, both paths simultaneously | Full Kuntur stack vs. reference | Phase A |
| 3 | In-vivo: full Kuntur, both paths | The product | **A3** |

Rung 1 is the insurance policy: if the companion FPGA slips, the animal test still
happens with placement done the existing way and Kuntur used for wireless recording
only. That loses the simultaneous reference comparison, not the test.

## Milestones

| ID | Milestone |
|---|---|
| **A1** | Real RHD2164 signal on the bench, end-to-end to the pc-app (injected) |
| **A2** | Dual-path validated — Kuntur wireless and Intan controller agree, bench |
| **A3** | **In-vivo animal recording** |

## A.0 — Start this week (pure lead time / minutes of work)

- [x] **Procure the companion FPGA dev kit.** Decided 2026-08-05: **Lattice
      LIFCL-40-EVN** (`LIFCL-40-9BG400C`, board silkscreen `LIFCL-40-EVN REV B`) +
      **IAM Electronic FMC LPC Breakout Board** (passive, ~€145, exposes all LA
      differential pairs at 1.27 mm pitch). Ordered: LIFCL-40-EVN via Mouser,
      breakout board directly via IAM Electronic.
      - Corrected assumption from the original criteria: this board has **no HDMI
        connector**. CrossLink-NX Family Datasheet Table 2.13 confirms true
        differential **LVDS output exists only on the Bottom I/O bank**
        (Top/Left/Right support only emulated `LVDSE`/`SUBLVDSE`). On this eval
        board, only the **FMC LPC connector** is wired to Bottom-bank balls — the
        D-PHY1 header/camera connector instead hit the separate hardened
        MIPI-D-PHY hard IP block (CSI-2/DSI only, not usable as generic LVDS).
        So FMC LPC + a breakout is the only viable path on this board, not a
        convenience choice.
      - Ruled out the Exostiv "HDMI to FMC" module: it routes HDMI's TMDS lanes to
        the FMC gigabit-transceiver pins (`TXDP/TXDN/RXDP/RXDN_FMC`), which this
        eval board's own connector table lists as unrouted (LIFCL-40 ball `—`) —
        would plug in but connect to nothing.
      - Plan: wire the handful of needed LA pairs from the breakout board to a
        hand-made uHDMI pigtail for the tunnel link (A.4).
      - Vendor check on IAM Electronic GmbH (Leipzig, DE, founded 2017): active
        DigiKey Preferred Supplier, positive Tindie reviews (~170-196 orders
        across their FMC line), 11 FMC modules currently for sale with 2025-dated
        updates. No red flags.
- [x] **T1.1 live risks** — `CFG_BONDING_MODE=0` committed (`0c7a612`, was
      uncommitted with committed value `1`, which would've blocked BLE on a fresh
      clone). `STREAM_DIAG_POST_DRAIN_WATCH=1` (`stream_app.c:165`) reviewed and
      left at `1` — still useful while A.1/A.2 touch `stream_app.c`.
- [x] **Verify `RHD_REG13`** (`intan.vh:149`) — confirmed the 7-bit concatenation
      bug and fixed: now `{RHD_ADC_AUX3_EN, RHD_RL_DAC3, RHD_RL_DAC2}` (8 bits),
      matching RHD2000 reg 13 `[7] aux3_en, [6] RL_DAC3, [5:0] RL_DAC2`.
      Committed `e07b696` on `fpga-fifo-sentinel`.
- [x] Confirm RHS2116 is unpopulated or provably disabled on the test hardware —
      populated and powered (board wiring requires it), but FPGA SPI to it was
      undriven/absent from the design (undefined idle state). Fixed: `spi2_csb`
      tied high (deselected), `spi2_sck`/`spi2_mosi0` tied low — chip can never
      latch a command. Committed `4f0e31d` on `fpga-fifo-sentinel`.
- [x] Confirm whether the collaborator's animal protocol needs an amendment to admit
      a new device — communicated to collaborator 2026-08-05, amendment in progress.
      Revisit 2026-09-05.

## A.1 — Make the signal real  → **A1**  *(Manuel, RTL)*

- [ ] **The FPGA has never sent neural data.** In `ch_sel` (`components.v`),
      `data0_synced`/`data1_synced` are computed from the RHD2164s and then
      discarded: `assign dout = {ch0, ch1}` where `ch0 = cnt0` (ramp),
      `ch1 = cnt0 + 1000`. The real path is commented out. **Every metric in the
      entire SKP/throughput investigation measured a synthetic ramp** — the
      transport is well validated, the instrument is not.
- [ ] **Fix structurally, not tactically.** Extract test-pattern generation into its
      own module; mux at the top level behind an obvious named signal, so "am I
      streaming real data?" is answerable from the top file. The bug exists *because*
      test pattern and real path share a module with no visible mux. Doing the
      restructure now avoids touching `ch_sel` twice.
- [ ] **T3.3 Remove debug hijacks from product paths** — `serial_lvds_tx = spi0_csb`
      and `serial_lvds_rx` **declared as an output** (`kuntur_fpga.v:36-37`), which
      must be undone before bidirectional tunnel work · `assign cmd_is_00 = fifo_full`
      · `mode` hardwired `2'b00` with `mode1_*`/`mode2_*`/`mode3_*` declared and
      unwired · delete `old.v`.
- [ ] **SPI0 opcode decode, 4-way** (from A.2 control-plane spec review,
      2026-08-05) — `main_controller` currently only distinguishes `opcode==01`
      from everything else. Needs explicit decode: `00`=FIFO pop (existing),
      `01`=regbank write (existing), `10`=regbank read (new — no path from
      `regbank_dout0` to the TX mux exists yet), `11`=NOP (new — no side
      effects). **Must land together with** the MCU-side fix to
      `FPGA_SPI_ReadSamples()`'s dummy TX word (`FPGA_STREAM_CMD = 0xA5A5`
      currently has top bits `10` by accident — would misread every streaming
      transfer as a register read once `10` means something). See
      `docs/interfaces/channel-selection-control-plane.md` section 1.
- [ ] **Wire the sampling-cycle placeholder command slot** — confirmed
      2026-08-05: the sampling counter's extra state beyond the 32 real
      per-module channels (`components.v:855`, `sampling_max = 6'd32`, giving
      33 total states) is an intentional placeholder for an alternate RHD2164
      command (e.g. chip-ID or temperature-sensor read) instead of a channel
      conversion — datasheet recommends reserving 3 such slots, reduced to 1
      here. Not yet wired to a consumer; `rhd2164_sampling_cmd0-3`
      (`components.v:419-437`, regbank addr 128-131) are the likely
      MCU-writable home for the command word(s) once this is implemented. See
      `docs/interfaces/channel-selection-control-plane.md` section 1.

*Already verified correct:* RHD init sequence — chip-ID read, regs 0–21,
`RHD_CALIBRATE`, then nine dummy reads as the datasheet requires.

## A.2 — Minimum control plane  *(Claude: MCU + app; Manuel: RTL side)*

Enough to choose which two channels to record — without it the animal test is stuck
with a hardcoded pair. Polished UI is Phase B.

- [x] FPGA endpoint exists — `ch_a`/`ch_b` driven from regbank, writable via `spi0`
- [x] **Interface spec finalized** — `docs/interfaces/channel-selection-control-plane.md`,
      covers all 3 hops (FPGA regbank SPI write, BLE 0xFFF1 command, bridge UART
      relay), all open questions resolved 2026-08-05. Surfaced a scope gap the
      plan bullets below didn't call out: the pc-app doesn't reach 0xFFF1
      directly, it must relay through the WB09KE bridge — new bridge firmware,
      not just MCU + app. Ready for implementation; RTL follow-ups tracked in A.1
      are non-blocking (`REG_WRITE` alone is sufficient for `SET_CHANNELS`).
Implemented 2026-08-06, all four pieces below. **Not marking these done** —
none has run on real hardware yet, and per this plan's own rule (requirements
≠ specifications), code that compiles is not a verified feature. What's
actually been checked vs. what still needs Manuel's bench:

**Verified so far (host-only, no hardware involved):**
- `FPGA_SPI_ChannelToRaw()` — bijectivity over all 128 channels + exact
  module-block encoding, by compiling the actual extracted source (not a
  reimplementation) natively and running it against a hand-derived oracle.
- `FPGA_SPI_SetChannels()` word encoding — confirmed opcode/addr/data bit
  fields and the even-transfer-count (2) pairing invariant, same method.
- pc-app → bridge wire framing — `SerialReader.send_set_channels()` driven
  over a real pty loopback (`socat`), captured actual bytes on the wire:
  `cc 33 03 01 <ch_a> <ch_b>`, matches spec exactly. Also confirmed
  disconnected/out-of-range calls write nothing.
- Bridge RX parser (`VEGA_UART_RxByte()`) — compiled the actual extracted
  source natively and fed it the *real* bytes captured from the pc-app test
  above; correctly reconstructs the SET_CHANNELS payload. Also covered:
  debug-console ASCII passes through untouched when no command frame is
  present, back-to-back frames each dispatch separately, oversized/zero-length
  frames are discarded without desyncing the next frame.
- All host tests + the extraction diffs proving no drift from the real source
  live in the scratchpad from that session — not committed (throwaway
  verification, not product code).

**Bench results, 2026-08-06 — RTL opcode decode landed, full chain tested live:**

- [x] Build + flash both firmwares — kuntur-mcu (headless `Debug/makefile`)
      and wb09ke-bridge (`make`, `STM32_Programmer_CLI` SWD flash, CLI now
      works for this board — reverses the earlier GUI-only finding, see
      `memory/feedback_wb09ke_flash.md`). Both zero-error builds.
- [x] **Full SET_CHANNELS round-trip verified on real hardware, first try:**
      script → bridge relay → BLE write 0xFFF1 → MCU handler → SPI0
      `REG_WRITE` → **Manuel's new RTL 4-way opcode decode** → SPI0
      `REG_READ`/`NOP` → readback conversion → BLE notify 0xFFF3 → bridge
      relay → received back as the exact requested `(ch_a, ch_b)`. Confirms
      the RTL's `REG_READ` latency matches the 1-transfer-deep pipeline
      assumption in `FPGA_SPI_ReadChannels()` (spec section 4.1) — validated
      against the real bitstream, not just the earlier host-side model.
      Also confirms `BLE_GATT_SRV_OP_MODIFIED_EVT_ENABLE_FLAG` does fire the
      0xFFF1 attribute-modified event on this stack build.
- [x] **Found and fixed a real MCU-hang bug**, same session: repeated
      back-to-back `SET_CHANNELS` calls hung the Kuntur MCU hard enough to
      need a physical reset (SWD connect itself failed — `DEV_CONNECT_ERR` —
      not just the debug UART going quiet). Root cause: `FPGA_SPI_SetChannels()`
      + `FPGA_SPI_ReadChannels()` (6 blocking SPI0 transfers) ran synchronously
      *inline inside the BLE GATT event-handler callback*
      (`STREAM_APP_OnCommandWrite`) — the same "inline work on the hot BLE
      path" hazard already flagged elsewhere in this plan (B.3). Fixed by
      deferring the SPI0 work to a new cooperative-scheduler task
      (`CFG_TASK_SET_CHANNELS_ID` / `SetChannelsTask()`), mirroring the
      pattern `StreamSendTask` already uses — the event-handler callback now
      only validates, stashes the request, and schedules the task. Rebuilt
      clean, reflashed; not yet re-tested against the hang scenario
      specifically (needs repeated-call testing to confirm the fix holds).
- [x] **Root cause fully identified and fixed, 2026-08-06.** Two failed
      intermediate attempts before landing on the fix (both left as comments
      in `stream_app.c` for the next person who touches this): (1) a
      standalone `UTIL_SEQ` task got scheduled correctly but mysteriously
      never ran — root cause not identified, would need hardware tracing;
      (2) checking a pending-flag at the *top* of `StreamSendTask()` also
      never fired, because that function's packet-send loop is
      `while(1) { ...; continue; }`, returning only on flow-off — on a
      healthy link it never returns to the top again, so the check was
      correct in principle but placed in code that doesn't run. **Actual
      fix:** check the flag *inside* the per-packet loop (after
      `BLE_STACK_Tick()`), so it's evaluated every packet cycle regardless
      of how long the loop has been spinning. Confirmed via the real pc-app
      (not scripts): SET_CHANNELS → bridge → BLE → MCU → SPI0 write → RTL →
      SPI0 readback → notify → bridge relay → pc-app shows "✓ Verified",
      values matched exactly. Streaming confirmed healthy throughout and
      after (8KB/1.5s, normal rate, no hang). **Confirmed at the source**,
      not just inferred from the pc-app UI: debug UART shows
      `SetChannelsTask running, ch_a=32 ch_b=65` — the exact line that never
      appeared in either failed attempt — followed by a normal, expected,
      self-recovering `flow-off #1` on the regular 0xFFF2 stream (already
      handled by `STREAM_APP_ResumeSending()`, not a new problem).
- [x] **Repeated-call test done, found a second hang, fixed.** 6-7 rapid
      Apply clicks hung the MCU again — same silent-everything signature as
      the original bug, just needing several repetitions instead of one.
      Root cause: each `SET_CHANNELS` execution added 6 SPI0 transfers + a
      second BLE notify *on top of* that iteration's normal ~118-transfer
      streaming work (124 total, 2 notifies) — survivable once, not safe
      repeated back-to-back. **Manuel's fix idea, implemented:** when a
      channel-change is pending, skip that iteration's normal packet
      work entirely rather than adding to it — one skipped ~2 ms frame of
      streamed samples (acceptable: deliberate channel change, not data
      loss) in exchange for keeping every iteration's SPI0/BLE workload
      bounded to roughly its usual size. Combined with a 300 ms debounce
      (`HAL_GetTick()`-based, wraparound-safe) so actual executions can
      never land closer together than that regardless of click rate.
      Rebuilt clean, zero errors/warnings.
- [x] **Third hang found under the debounced-in-loop build.** Survived 5
      clean back-to-back executions (each with the full debug-log sequence)
      but still eventually hung — debug UART and 0xFFF2 stream both went
      silent, `STM32_Programmer_CLI -c port=SWD ... -hardRst` itself failed
      with `DEV_CONNECT_ERR` (not just quiet — the debug port was
      unreachable), and `tio` showed the ST-LINK's own USB VCP cycling
      disconnect/reconnect with a `SET_CHANNELS` debug print truncated
      mid-transmission. Working theory (Manuel's, after ruling out a power/
      brown-out explanation — SPI0 already runs constantly across hour-long
      tests without issue, so a few extra transfers shouldn't tip a supply
      margin): a `SET_CHANNELS` execution landing at the same moment as some
      *other* BLE stack event (not specifically flow-off) may be corrupting
      or bypassing the debounce/pending-flag guards, since those only
      throttle *our* timing, not whatever internal state the closed-source
      BLE stack library is in when `aci_gatt_srv_notify()` gets called.
- [x] **Redesigned rather than patched further, 2026-08-06 — full details in
      `docs/interfaces/channel-selection-control-plane.md` section 5.**
      Rather than keep searching for a safe moment to interleave
      `SET_CHANNELS`'s SPI0/notify work with live streaming (three attempts,
      three failure modes), removed the need to interleave at all:
      `SET_CHANNELS` now requires the stream to already be explicitly
      stopped. New opcodes `0x02 STOP_STREAMING` / `0x03 START_STREAMING` on
      0xFFF1. Samples generated while stopped are **discarded, not
      buffered** — Manuel's call: they're pre-switch data nobody wants once
      channels change, and buffering them would feed into an already-open,
      uninvestigated FPGA-FIFO chronic-backlog question (`fifo_full`
      asserting on a timescale the deepened 4096-pair FIFO shouldn't allow —
      see `stream_app.c` `STREAM_DIAG_FIFO_FULL_WATCH` section) rather than
      helping it. `START_STREAMING` flushes the FIFO via the existing
      empty-FIFO sentinel (`0x8000`) before resuming, guaranteeing the first
      sample streamed after resuming is genuinely post-switch. MCU-side, the
      streaming hot loop reverts to its original shape (just one added cheap
      boolean check for prompt `STOP_STREAMING` pickup); all the SPI0/notify
      work now lives in a branch that only runs while stopped, reliably
      revisited every ~2 ms via the same VTIMER fallback flow-off recovery
      already depends on — the debounce timer from the previous attempt is
      gone, replaced by natural spacing from explicit multi-command
      sequencing. pc-app's Apply button orchestrates
      STOP → SET_CHANNELS → (readback or timeout) → START as one
      operator-facing click. Rebuilt clean, zero errors, zero new warnings.
      **Tested 2026-08-06:** single click → verified, clean. Repeated rapid
      clicks → worked cleanly 3 full cycles (debug log shows complete
      STOP→SET→flush→START sequences each time), then hung again on/after a
      4th attempt.
- [x] **Found a real, numeric bug in the flush itself while investigating
      the above** — every single flush hit its safety cap
      (`FPGA_FIFO_MAX_PAIRS`, was 4096) and gave up, `4097` pairs discarded
      every time, never once finding the true empty-FIFO sentinel. Root
      cause: the cap was set to the FIFO's raw depth, not accounting for the
      FPGA continuing to ingest real samples at 30 kSPS *throughout* the
      flush — draining a saturated 4096-pair FIFO to genuine empty against
      that continuous refill needs ~5850 pops (measured ~10us/pair pop rate
      vs. 30k/s fill rate), not 4096. Fixed: cap raised to 16384 (~2.8x
      margin, still only ~164ms worst case). Rebuilt clean. **Not yet
      re-tested** — unknown whether this was also the hang's cause, or
      whether Manuel's "colliding with some other BLE event" theory is a
      separate, still-open issue underneath it. Next bench pass will tell.
- [x] **Tested with the raised cap, 2026-08-06: still hit the cap every
      time (`16385` discarded, every flush) — and found the real bug while
      reading the log closely.** A new `STOP_STREAMING`+`SET_CHANNELS` cycle's
      debug prints appeared *interleaved inside* a still-running previous
      flush's own prints — only possible because `StreamFlushFpgaFifo()`
      calls `BLE_STACK_Tick()` internally (to avoid one long blocking
      stretch), and that nested tick can process a brand-new incoming GATT
      write while the outer flush call hasn't returned yet. The shared
      pending-state (`s_streaming_stopped`, `s_set_channels_pending`,
      `s_pending_ch_a/b`) had no protection against a new command
      overwriting it mid-use by the in-progress one — this is Manuel's
      "guards get bypassed by the interruption" theory, concretely
      confirmed. Exact failure mode matched what was observed in the
      pc-app: a `SET_CHANNELS` arriving mid-flush gets silently orphaned
      (flag set, but streaming resumes before anything checks it again,
      and the normal tight loop doesn't poll that flag) — permanent
      "no response" for that specific click, while the next click (once the
      MCU wasn't mid-flush) worked normally. **Fixed:** new
      `s_command_busy` flag, set for the duration of
      `SetChannelsTask()`/`StreamFlushFpgaFifo()`; `STREAM_APP_OnCommandWrite()`
      now rejects (logged, not applied) any command that arrives while
      busy. Makes one full STOP/SET/START cycle atomic with respect to the
      next — a too-early re-click now fails safely (rejected, pc-app times
      out) instead of corrupting shared state. Rebuilt clean. **Not yet
      re-tested.** Known follow-up, not blocking: the pc-app doesn't yet
      distinguish "rejected because still busy" from any other timeout in
      its UI — acceptable for now, worth a clearer message later.
- [x] **Root cause of the flush never terminating, fixed at the source
      (Manuel's proposal), 2026-08-06.** Raising the safety cap to 16384
      changed nothing — still hit the cap every time. Manuel's question
      ("isn't it easier to send STOP/START down to the FPGA?") was the
      right call: the MCU-side flush was racing a continuous 30 kSPS
      producer it could never reliably outrun (confirmed independently —
      not a bad rate estimate, `BLE_STACK_Tick()`'s own documented
      occasional 10-22 ms stalls, called periodically during the flush,
      could let backlog grow faster than the flush caught up). **RTL fix**
      (Manuel, `components.v`): new regbank register addr 36, bit 0
      `stream_enable`, gates `fifo_wen` directly in `ch_sel`
      (`fifo_wen <= dout_en_0 & stream_enable`). One real bug caught before
      flashing: the first version defaulted this to `0` (disabled) on
      reset, which would have silently killed streaming on every FPGA
      reset/reprogram until the MCU explicitly enabled it — corrected to
      default `1`. **MCU side:** `FPGA_SPI_SetStreamEnable()` added to
      `fpga_spi.c`; the flush moved from `START_STREAMING` to
      `STOP_STREAMING` (disable ingestion, *then* flush a now-static
      backlog — ~41ms worst case, not an open-ended race); `START_STREAMING`
      no longer flushes at all. Full design in
      `docs/interfaces/channel-selection-control-plane.md` section 5.3.
- [x] **Second bug found and fixed in the same investigation: command
      reentrancy.** While reading the bench log closely to understand why
      the flush never terminated, found something more serious: a new
      `STOP_STREAMING`+`SET_CHANNELS` cycle's debug prints appeared
      *interleaved inside* a still-running previous flush's own prints.
      `StreamFlushFpgaFifo()`'s periodic `BLE_STACK_Tick()` calls (needed to
      avoid one long blocking stretch) let a new GATT write get processed
      while the outer flush call hadn't returned yet — nothing protected
      the shared pending-state against a new command overwriting it mid-use.
      This exactly explained an earlier symptom: the pc-app intermittently
      showing "no response" for a `SET_CHANNELS` that had been silently
      orphaned this way. **Fixed:** `s_command_busy` flag, set for the
      duration of any SPI0-touching operation; `STREAM_APP_OnCommandWrite()`
      now rejects any command that arrives while busy, making one full
      STOP/SET/START cycle atomic. Section 5.5.
      Both fixes rebuilt clean, zero errors/warnings.
- [x] **Tested with the FPGA-side gate + reentrancy fix, 2026-08-06: major
      improvement, confirmed at the source.** Flush counts dropped from
      always-16385 (always hitting the cap) to 246-292 pairs — the
      empty-FIFO sentinel is now actually being found, not given up on.
      ~10 clean full STOP→SET_CHANNELS→START cycles confirmed in the debug
      log, each complete, ending in a normal self-recovering flow-off.
      Single-click and moderate-rate use is solid.
- [x] **Rapid-click stress test still eventually broke it — but this time
      as a repeating crash/reset loop, not a single hang.** `tio`'s own
      device connection cycled disconnect/reconnect roughly every
      1.0-1.7s for ~15+ cycles (consistent ~1.000-1.001s reconnect gap =
      tio's own poll interval catching the USB device actually
      disappearing and reappearing — i.e. the MCU genuinely resetting
      repeatedly, not freezing once). Prints were truncated mid-transmission,
      consistent with a real reset interrupting output, not a deadlock.
      **Decision (Manuel): scope as a known limitation for now, not chased
      further today** — real animal-test usage is occasional channel
      selection, not rapid button-mashing, and the single/moderate-click
      case is solid. **Did fix the actual software bug that let a human
      sustain a high enough rate to trigger it**: `START_STREAMING` is
      fire-and-forget (no MCU confirmation), so the Apply button was
      re-enabling the instant the bytes were sent — no cooldown enforced
      after a cycle actually completed. A human clicking at a normal pace
      could sustain close to 1 cycle/second, matching the observed crash-loop
      period almost exactly. Added `APPLY_COOLDOWN_MS = 1000` in
      `main_window.py` — enforced pause after `START_STREAMING` is sent,
      before the button re-enables, making that rate physically impossible
      to sustain regardless of how fast someone clicks. Rebuilt clean.
      Working theory, unconfirmed: rapidly toggling `stream_enable` on/off
      many times in quick succession is a different electrical stress
      pattern than the continuous steady-state SPI0 traffic that's already
      proven fine across hour-long tests (switching transients at each
      on/off edge vs. sustained load) — worth a scope check on the supply
      rail during a rapid-click burst if this becomes worth chasing later.
      **Re-tested and confirmed 2026-08-06, same session**: after the full
      ack-driven redesign (section 5.6) plus `COMMAND_GAP_MS` and the bridge
      ORE fix all landed, Manuel sustained multiple rapid-click bursts —
      button stayed inactive through each full cycle (Verified mark lands
      *before* the button re-enables, confirming the ack-driven sequencing
      is genuinely gating the button, not just racing it), no crash/reset
      loop, live streaming continued throughout. The rate-limiting mitigation
      holds under real rapid-click load. Root electrical cause remains
      un-investigated by deliberate scope decision — not blocking, since the
      trigger condition (sustained ~1 click/s) is no longer reachable through
      the UI at all.
- [ ] Logic-analyzer or scope confirmation of the SPI0 waveform itself —
      still open, lower priority now that the functional round-trip works.
- [ ] Confirm bridge discovery finds the 0xFFF1 value handle — bridge debug
      trace should show `Found 0xFFF1 value handle: 0x....` after connecting.
- [ ] End-to-end: pc-app "Apply" button → bridge relay → MCU log line. This is
      the first point where all four pieces are exercised together.
- [ ] `aci_gatt_clt_write_without_resp` is the correct client-side call for a
      write-without-response characteristic per the vendor API docs, but
      hasn't been exercised against this stack build — confirm no unexpected
      status code on the bridge's debug trace.

**Readback verification (spec section 4, added 2026-08-06)** — closes the
loop so `SET_CHANNELS` can be confirmed *in the pc-app UI*, without waiting
for A.1's full `ch_sel` restructure. Only needs the opcode-decode subset of
A.1 (`REG_READ`/`NOP`), not the ramp→real-data rewrite. New: `0xFFF3` notify
characteristic (MCU), automatic readback after every successful
`SET_CHANNELS`, bridge relay with a third magic (`0xEE 0x11`), pc-app
verified/mismatch/timeout indicator next to Apply. Full design in the spec's
new section 4. Same "implemented, not hardware-verified" status as above:

- Host-verified: `FPGA_SPI_ReadChannels()`'s 4-transfer sequence and
  `FPGA_SPI_RawToChannel()` (exact inverse of `ChannelToRaw`, confirmed over
  all 128 values) against a modeled regbank+pipeline — models the spec's
  *assumed* RTL behavior, not the real RTL, which doesn't exist yet. pc-app
  parsing of the new `0xEE 0x11` response frame, interleaved with normal data
  frames, verified over a real pty loopback the same way as the command path.
- Still needs the RTL opcode decode (A.1) before it can produce anything but
  a timeout — that's the expected state until then, not a bug to chase.
- **Found and fixed a stack buffer overflow in the test harness itself**
  (not the product code) while building the first version of this
  verification — `gcc -fstack-protector-all` caught it immediately. Kept as a
  reminder that the tests need scrutiny too, not just the code under test.
- **Found a pre-existing, unrelated latent bug while building the pc-app
  test**: `serial_reader.py`'s monotonicity clamp does
  `packet.timestamps_us[-1]` unconditionally, which crashes the reader thread
  on a `num_pairs=0` packet (empty array). Not triggered by any code touched
  this session — real packets always carry 59 pairs — but a real crash risk
  if a header-only/malformed packet ever reaches the parser. Not fixed here
  (out of scope for A.2); tracked as a new bullet under A.6.

**Real MCU-confirmed acks for STOP_STREAMING/START_STREAMING (spec section
5.6, added 2026-08-06)** — after admitting the previous fix
(`APPLY_COOLDOWN_MS`) only ever *guessed* the MCU had finished each step via
a fixed timer, not confirmed it, replaced both fixed settle delays with real
acks. 0xFFF3 extended with a type-prefix byte (shared with the existing
`SET_CHANNELS` readback — `0x01`/`0x02`/`0x03` mirror the command opcodes so
a response self-identifies what it's answering); `success` is backed by an
actual SPI0 readback of `stream_enable` after the write, not just "the write
call didn't error." MCU rebuilt clean (zero errors) after this change.
`main_window.py`'s Apply sequence now waits on `stop_streaming_ack`/
`start_streaming_ack` signals (2 s timeout fallback, same pattern as the
existing readback verify timeout) instead of `STOP_STREAMING_SETTLE_MS`/
`START_STREAMING_SETTLE_MS`; `APPLY_COOLDOWN_MS` kept as-is, now applied
*after* the start ack/timeout resolves rather than as the only gate. Not yet
hardware-tested — needs an MCU reflash (bridge unchanged, no reflash needed
there) and a live Apply-button pass to confirm acks actually arrive and the
crash-loop mitigation still holds.

**Bridge command-relay silently dying mid-session (found + fixed 2026-08-06,
bench testing)** — after the ack mechanism above shipped, repeated Apply
clicks over one session showed clicks 1-2 fully succeed (confirmed via new
`[pc-app] sent:`/`[bridge] cmd relay: wrote...` logs on both ends) and then
click 3's commands vanish completely: pc-app sends all 3 bytes locally, but
*zero* bridge-side log output for any of them — not even the "not ready"
rejection path, meaning `vega_bridge_relay_command()` was never even
invoked. Root cause: `stm32wb0x_it.c`'s `USART1_IRQHandler` never checked or
cleared the USART overrun-error (ORE) flag. Per the STM32 USART reference
manual, once ORE latches, RXNE stops being set for new data until ORE is
explicitly cleared — one overrun (plausible at 2 Mbaud if the BLE radio's
own higher-priority ISR delays servicing a byte past its ~5 µs window, e.g.
right as 30 kSPS streaming resumes) silently and *permanently* kills command
reception for the rest of the session, with no log output anywhere in the
existing code. This required first enabling the bridge's debug trace
(`CFG_DEBUG_APP_TRACE`, previously off — same UART as the data stream, so
`DT_INFO_MSG` was unconditionally silenced too) and adding relay
success/connect/disconnect logging, plus having the pc-app print every send
attempt to its own terminal (`serial_reader.py`), to even see this — the
symptom was completely invisible before that. Fix: check+clear
`LL_USART_IsActiveFlag_ORE`/`LL_USART_ClearFlag_ORE` every ISR entry, with a
log line so a future overrun is visible instead of silent. Bridge rebuilt
and reflashed (`STM32_Programmer_CLI` over SWD — no GUI needed).

**Confirmed live, 2026-08-06 (same session)** — root cause verified exactly
as diagnosed: after reflashing, 6 consecutive Apply cycles succeeded, then
the bridge logged `USART1: RX overrun (ORE) cleared` mid-`SET_CHANNELS`, and
recovery was immediate — `START_STREAMING` sent right after relayed and
applied normally, vs. the pre-fix behavior of killing the rest of the
session. So the fix converts a fatal, permanent, unrecoverable failure into
a survivable, self-healing, single-command loss. Residual gap: that single
command can still be lost with no retry — the pc-app's existing verify-
timeout fallback catches it safely (streaming still resumes correctly; the
UI honestly reports the command as unsuccessful rather than falsely
claiming success — improved wording for this 2026-08-06, see below), so
nothing gets stuck, but the requested channel change doesn't happen and the
operator has to notice and re-click.

Two overruns in one session both landed specifically on `SET_CHANNELS`, not
`STOP_STREAMING` or `START_STREAMING` — suspected reason: the ack-driven
design (section 5.6) sends the next command the instant an ack arrives, with
zero deliberate gap; `SET_CHANNELS` is sent immediately upon receiving the
`STOP_STREAMING` ack, which lands it right as the bridge is still busy
processing/relaying that same ack's GATT notification event — a natural
collision window. Mitigation (not a full fix — the ORE fix above is what
actually prevents fatal failure): `COMMAND_GAP_MS = 15` in `main_window.py`,
a small deliberate delay between receiving an ack and sending the next
command, to reduce how often this specific collision happens. Also updated
the pc-app's timeout-path messaging (`_on_stop_ack_timeout`,
`_on_verify_timeout`, `_on_start_ack_timeout`) from a vague/stale "no
response (RTL readback not available yet?)" to an explicit "✗ ... unsuccessful
— no confirmation received", since a timeout now more often means a real
dropped command than a missing RTL feature.

**Confirmed live, 2026-08-06 (same session)** — many clicks in a row, only
one hit the overrun (down from 2-in-~8 before `COMMAND_GAP_MS`), degraded
exactly as designed (honest "unsuccessful" message, streaming stayed live,
zero stuck state), and the very next click cleanly verified. Single-click
and moderate-repeat-click reliability now considered solid. Remaining open
item under A.2: the rapid-click crash-loop retest (`APPLY_COOLDOWN_MS`
mitigation from earlier this session), not yet re-attempted.

## A.3 — Signal injection & validation rig  → toward **A2**

Two tiers. The chip's own impedance-check DAC (regs 5–7: `RHD_ZCHECK_DAC`,
`RHD_ZCHECK_SEL`, `RHD_ZCHECK_EN`) injects into a selected channel with **no external
hardware** — use it for automated checks. An external generator/AWG covers
characterisation.

| Stimulus | Answers |
|---|---|
| **Shorted input** | **Noise floor µV RMS** — headline spec; no generator involved |
| DC / step | Offset, saturation, settling, DSP offset removal |
| Sine, known amplitude | Gain accuracy, THD, channel identity |
| Sine sweep | Frequency response — would catch the REG13 bug |
| Two-tone | Linearity, intermodulation |
| Different signal per channel | Channel mapping, crosstalk |
| Arbitrary neural waveform from file | Realistic end-to-end fidelity |

- [ ] **Attenuation network** — spikes are ~50–500 µV, LFP ~mV; generators output
      volts. Needs a 1:1000+ divider whose own thermal noise and pickup are
      understood, or the test runs 1000× hot and masks noise and saturation.
- [ ] **Capture at both endpoints simultaneously and compare** — the direct test of
      the A.5 arbitration problem, and the reference comparison that justifies the
      wired path.
- [ ] **Regression, not bring-up** — known input means correlation/RMS error against
      the source becomes a numeric pass/fail feeding verification evidence.
- [ ] **Latency for free** — a step or spike yields end-to-end latency at both
      endpoints (safety-relevant for surgical use, currently unmeasured).

## A.4 — LVDS tunnel  *(joint spec; Manuel RTL both ends)*

```
RHD2164 ×2 → Kuntur FPGA ├─→ ch_sel → FIFO → MCU → BLE → bridge → pc-app
                         └─→ LVDS ser/des ⇄ uHDMI ⇄ companion FPGA → SPI → Intan controller
```

- [ ] **Interface spec, written before implementation** — framing, clocking,
      link-loss detection, latency budget, **CRC**. A corrupted RHD2164 *command*
      during surgery silently changes what the operator sees. This is where the
      interface-spec discipline starts: two documents, not seven.
- [ ] Kuntur-side serialiser/deserialiser
- [ ] Companion FPGA RTL: deserialise, reassemble SPI, drive the Intan controller

## A.5 — RHD2164 bus arbitration  *(joint design)*

Two masters want the AFE. If the Intan controller reconfigures gain/bandwidth
mid-session, **the BLE recording silently changes meaning and the file has no record
of it.**

- [ ] Explicit ownership model
- [ ] Live RHD2164 register state captured into the recording metadata

## A.6 — pc-app readiness for real signals  *(Claude)*

- [ ] **Display in physical units (µV), not raw ADC counts** — requires the RHD2164
      gain/LSB conversion; plotting raw int16 is not acceptable for a neural recorder
- [ ] Sensible amplitude ranges/autoscale for neural signals
- [ ] Verify the underrun-sentinel path behaves against real (non-ramp) data
- [ ] Recording metadata sidecar — minimum: sample rate, gain, channel map, filter
      settings, firmware/bitstream versions
- [ ] **Fix `serial_reader.py` crash on `num_pairs=0`** — found 2026-08-06
      while testing the A.2 readback feature. The monotonicity clamp does
      `packet.timestamps_us[-1]` unconditionally in the resync loop; a
      header-only or malformed packet (empty sample array) raises
      `IndexError` and kills the reader thread. Never triggered by real
      firmware (always 59 pairs), but the parser shouldn't crash on a
      malformed frame it can't control.

---

# PHASE B — Road to public v1

Begins after A3. Ordering within Phase B is dependency-driven, not fixed.

## B.1 — Foundation & repository

- [ ] **Ground truth audit** — every documented constant against source. Known-false
      today: active stream mode (`CLAUDE.md` says `LENOVO_SMOOTH`, actual
      `WB09KE_HF`) · device names (`Kuntur-N/-S/-A` vs. actual `"Kuntur-Headstage"`)
      · `NORDIC_HF` "not implemented" · PA10→TP5 · `CFG_LPM_SUPPORTED` (memory says
      `0`, code is `1` at `app_conf.h:415`) · `project_fpga_spi_status.md`
      self-flagged untrustworthy · `serial_reader.py:2` still describes the removed
      nRF52840 bridge.
- [ ] **New monorepo, fresh start — named `kuntur`.** Kuntur is the system; Vega is
      the app component within it. Two things to resolve first:
  - **Name collision:** `ssh://git@openic.org:2222/headstages/kuntur.git` already
    holds the name. Rename it (e.g. `kuntur-archive`) when archiving so the new
    repo can take it cleanly.
  - **Host it on GitHub.** The old `kuntur` is on self-hosted Forgejo, `vega` on
    GitHub. For a project whose goal is community adoption, GitHub is where this
    audience already is (Open Ephys, SpikeInterface, Intan tooling) — self-hosting
    costs discoverability, drive-by contribution, and issue-tracker familiarity.
    Keep self-hosted repos for the *private* hardware-revision and research-data
    repos if preferred.
  - Corrected docs and restructured code go *into the new repo*, not into the old
    ones — otherwise the work is done twice. Move research data out (146 bench
      CSVs, 55 scope traces, 53 stall logs, 4.7 GB untracked recordings) to a private
      research repo. Archive `kuntur` and `vega` read-only; tag final commits; record
      the mapping (bisect cannot cross the boundary). Carry `log/` over deliberately.
      Private repos for unreleased hardware revisions and pre-publication data —
      **release by copying files into a fresh public commit, never merging private
      history in.**

```
<product>/
├── hardware/          5 PCBs: schematics, BOM, gerbers
├── fpga/              rtl/{common,afe/rhd2164,app}, companion/, constraints, build
├── firmware/          kuntur-mcu/, wb09ke-bridge/
├── software/vega-pc/
├── docs/              requirements, interfaces, architecture, safety, datasheet, decisions
└── tools/             analysis, validators
```

- [ ] **Enforcement, ratcheted from commit one.** Prefer **elimination over
      detection**: generate as-built doc sections from source; single-source domain
      logic. Five checks, each justified by a bug that already cost time —
      constant/doc drift (the falsehoods above) · domain-logic unit tests (underrun
      sentinel, ramp unwrap → Category A) · protocol golden fixtures · build all
      targets · secrets + committed artifacts (prerequisite for going public).
      Baseline file that may only shrink; branch protection; CODEOWNERS on
      `docs/interfaces/`; `import-linter`; RTL lint forbidding `app/`→`afe/`.

> Few, fast, reliable checks. A flaky check is worse than none — it teaches bypass.

## B.2 — Specifications & requirements

**Structured, safety-ready from day one.** Permanent IDs, verification method per
requirement, requirement→test traceability in CI, verification *evidence* retained.

- [ ] **Interface specs** (the A.4 tunnel spec is the first) — BLE packet format ·
      0xFFF1 command protocol · bridge UART wire format (**add CRC**) · FPGA register
      map · RHD2164 configuration contract · recording format + metadata ·
      **protocol version field**, absent today, without which the format cannot
      evolve safely once public
- [ ] System requirements — including the lossless claim stated testably (duration +
      RF envelope)
- [ ] Subsystem requirements — MCU, FPGA, bridge, pc-app, companion FPGA
- [ ] **Hazard analysis** — root of the safety requirement tree; prerequisite, not a
      byproduct
- [ ] **ADRs** — why BLE despite the ceiling (isolation), the 60 kSPS budget,
      mblock=200, LPM setting. Stops the community re-litigating settled decisions.
- [ ] **Test equipment specification** (`docs/test-equipment.md`) — written as a
      *specification, not an inventory*: required capability so a replicator can
      substitute, then what we used. Sections: required to reproduce validation ·
      required for development · **DIY fixtures** (µV attenuator, harness, cabling,
      with schematics) · **calibration status**. Check calibration dates early —
      out-of-cal instruments are a lead-time item.
- [ ] **Datasheet — generated last, from verification evidence**

> **Requirements ≠ specifications.** Requirements are what we demand (writable now).
> Specifications are what we measurably achieve. Researchers cite these numbers in
> methods sections — never publish aspirational values as measured ones.

## B.3 — Architecture for contributability

Design the **seams**; file layout follows.

- [ ] Split RTL: `common/` (ram, fifo, spi, edge_detector) · `afe/rhd2164/` · `app/`.
      `components.v` is ~1,100 lines holding nine modules across all three tiers.
- [ ] **Decouple the AFE.** `ch_sel`'s ports (`data_a0/b0/a1/b1`) are shaped by "two
      RHD2164s with two outputs each" — AFE topology has leaked into application
      logic. Define a generic `{channel, sample, valid}` source.
- [ ] **Transport abstraction in firmware.** `stream_app.c` (1,023 lines) is welded to
      BLE while v1 needs the same stream over LVDS.
- [ ] Move `STREAM_DIAG_*` behind a hook interface — inline diagnostics on the hot
      path caused two documented regressions (`fifo_full` EXTI storm, post-drain
      print flood).
- [ ] **Single-source the underrun sentinel rule** — triplicated across
      `analyze_recording.py`, `packet_parser.py`, `graph_widget.py`; all three had the
      same bug.
- [ ] Restructure pc-app — 14 flat files mixing product app, analysis tools, one-off
      investigation plots, and a test harness in one namespace.
- [ ] **Committed extension points** (few, versioned): AFE driver · transport · data
      sink · analysis plugins · **FPGA user block** (a defined insertion point in the
      sample stream for researcher processing — something this audience cannot get
      from closed systems).

## B.4 — Characterisation & instrument validation  *(produces every datasheet number)*

- [ ] Noise floor, µV RMS input-referred — **currently unknown**
- [ ] Gain/amplitude accuracy against injected known signals
- [ ] Frequency response and RHD2164 filter configuration
- [ ] Electrode impedance measurement (RHD2164 supports it; standard QC workflow)
- [ ] **Timing integrity** — timestamps are RTC-derived at 1 ms resolution with a
      *monotonicity clamp*. A clamp hides the error instead of bounding it. Needs a
      measured spec: uniform at 30 kSPS ± X ppm, inter-sample jitter < Y µs.

## B.5 — Power, safety & reliability

- [ ] **Charging interlock — safety blocker.** A charger plugged in *is* a mains path;
      connecting it during a session destroys the isolation guarantee. Prevent
      physically, not just in documentation.
- [ ] Battery safety (overcurrent, thermal, enclosure); runtime as a published spec;
      analog performance across the discharge curve; low-battery cutoff **before**
      specs degrade
- [ ] **Battery telemetry — verified absent** (no `battery`/`VBAT`/`ADC_Init`/`PVD`
      in the MCU). A session that silently degrades or dies is the undefined
      behaviour the reliability framing objects to.
- [ ] Coin-cell power budget — likely infeasible at continuous 30 kSPS (current
      delivery, not just capacity); probably a different mode
- [ ] **Isolation is per-mode, not architectural.** Wireless+battery is galvanically
      isolated; wired mode has a conductive path to a mains-referenced system. The
      datasheet must state this per mode.
- [ ] Research-use-only labelling · risk documentation for IRB submissions ·
      RHS2116 documented as unpopulated/unsupported
- [ ] **Link quality gating** — define "good BLE connection" quantitatively (RSSI,
      retransmission rate, flow-off frequency, `BLE_STACK_Tick()` block duration)
      with thresholds · pre-session self-test (**same machinery as `doctor`, B.6 —
      build once**) · defined degraded-link policy: pause/flag the recording, alert
      the user, discard-vs-buffer. Auto-reconnect ≠ no data lost ≠ user informed.
- [ ] **Soak & regression infrastructure** — hardware-in-the-loop runner, scheduled
      soak, results archived as verification evidence. The reliability claim cannot
      be defended against regression otherwise.

### Known-open technical issues

- [ ] **1.7% FPGA FIFO underrun rate** (1,924,235 / 111,946,128 on the hour soak) —
      real underruns, never investigated
- [ ] **SPS overshoot** — measured ~30,700–31,900 vs. the FPGA's 30,000; unresolved
- [x] **WB09KE bridge RAM at 100%** — RESOLVED 2026-08-05, was a measurement
      artifact, not real exhaustion. Linker script (`stm32ble-test/client/STM32CubeIDE/STM32WB09KEVX_FLASH.ld`,
      referenced via `wb09ke-bridge/Makefile:161`) sets `_Min_Heap_Size=0x0` and
      places `.stack` at a fixed address anchored to RAM's top, independent of
      where `.heap` ends. Actual claimed sections (`.data`+`.bss`+`.bss.blueRAM`
      +`.noinit`/`dyn_alloc_a`+`.stack`) total ~21.5 KB of 64 KB (~33%); the
      "100%" figure almost certainly came from `(highest address − RAM start)/
      RAM size`, which hits 100% simply because the stack sits at RAM's very
      top — even though ~43 KB between `.noinit` and `.stack` is genuinely
      unclaimed (confirmed no `malloc`/`calloc`/`realloc`/`free` anywhere in the
      bridge firmware, so the zero-sized heap isn't a problem). Bridge feature
      work (A.2's command relay) can proceed.
- [ ] **mblock margin + FPGA FIFO sizing as one joint tuning project.** *Permanently
      valuable, not v1-specific — the fixed ~60 kSPS budget means every future mode
      inherits it.*
- [ ] Reduced sample rate as a reliability lever — characterise empirically
- [ ] FIFO/ring occupancy telemetry — MCU ring watch written but
      `STREAM_DIAG_RING_WATCH=0`, never flashed; FPGA FIFO occupancy needs new RTL
- [ ] **ST support ticket** — `BLE_STACK_Tick()` ~10–22 ms block. Evidence assembled
      in `project_st_support_ticket_ble_stack.md`; never filed. External response
      time — file early.

## B.6 — Usability & release

**Engineering a guide cannot substitute for:**

- [ ] **Prebuilt, version-matched release artifacts** (MCU `.hex`, bridge `.hex`,
      both bitstreams, one tagged bundle) — **biggest single lever.** Today a user
      must install STM32CubeIDE + ARM GCC + licensed Lattice tooling.
- [ ] **Spike: open FPGA toolchain (`prjoxide` + `nextpnr-nexus`).** Kuntur is
      `LIFCL-17`, a Nexus-family part with open-toolchain support. If it covers this
      design, contributors build **both** bitstreams with zero licensed tooling —
      killing the worst OOBE blocker. Cheap to evaluate; another reason to keep the
      companion FPGA in the same family. *Investigate, don't assume.*
- [ ] **Fix WB09KE CLI flashing** — currently GUI-only with repeated RESET presses.
      Cannot appear in a product quickstart. A boot-strap/option-byte cause is
      plausible given the PA10 experience.
- [ ] **PA10 external pull-down** — reframed: not a determinism nicety but *"the board
      appears dead for five seconds on every power-up."* Blocked on re-identifying
      the real PA10 net — the TP5 trace was wrong (TP5 is PB1).
- [ ] **Version/name handshake** replacing the bare `"Kuntur-Headstage"` string match
      (`app_ble.c:582`) — a mismatched pair must report *"bridge v1.2 cannot talk to
      headstage v0.9"*, not scan forever in silence.

**First-run path:** pinned dependencies/lockfile/`pyproject.toml` (currently `>=`
only) · serial port auto-detect (`serial_reader.py` already imports `list_ports`) ·
permissions guidance (`dialout`), Windows drivers · a `flash` tool covering all
targets from the release bundle.

**`doctor` — the highest-value usability feature.** Walks the chain, reports each
link with a *specific remedy*:

```
USB serial port      ✓  /dev/ttyACM0
Port permissions     ✗  not in 'dialout' → sudo usermod -aG dialout $USER
Bridge firmware      ✓  v1.2.0
BLE link             ✓  Kuntur-Headstage, RSSI -52 dBm
Headstage firmware   ✓  v1.2.0 (matched)
FPGA bitstream       ✓  v1.2.0
AFE (RHD2164)        ✗  no response — check headstage ribbon cable
```

Same subsystem as the B.5 pre-session self-test. Also: live connection-chain status
in the app, not only at setup.

**Quickstart & OOBE:**

- [ ] Quickstart **executed by CI** in a clean container — documentation that isn't
      run, rots
- [ ] **Time-to-first-signal as a tracked requirement:** a new user with assembled
      hardware and no prior toolchain reaches a live signal within **15 minutes**.
      *Verification: demonstration — timed clean-machine run, every release.*
- [ ] **Surgical mode is the deliberate exception** — mandatory, non-skippable
      pre-session verification (channel mapping, link health, latency) is a safety
      feature, not friction. Frictionless setup; deliberate clinical arming.
- [ ] `examples/` and a "hello world" contribution path

**Release:** LICENSE, CONTRIBUTING, CHANGELOG, versioning scheme. Gate: all checks
green · every v1 requirement traced to a passing test · current (not stale) soak
evidence · timed OOBE run completed · datasheet regenerated from verification
results. Then the public flip.

## B.7 — Human IRB

Collaborator's protocol, monthly cadence, existing relationship, Kuntur already
mentioned. **Defer the documentation, not the design** — isolation architecture, the
charging interlock, and fault behaviour must be decided in Phase A/B.1 because
retrofitting safety architecture is far more expensive than designing for it.

---

## Decisions log

All four opening questions resolved 2026-08-04:

- **Product name:** `kuntur` — the system. Vega is the app component within it.
- **Team:** Manuel (full-time, hardware/RTL/bench) + Claude (FW/SW/tooling/docs).
- **Companion FPGA:** COTS dev kit, not a custom board — no fab lead time.
- **IRB:** collaborator's protocol, monthly cadence, relationship established, Kuntur
  already mentioned. Animal test first, so human IRB is not a Phase A gate.
- **Wired surgical mode:** required for Kuntur to be usable; cannot be deferred.
- **Schedule anchor:** animal test, September, flexible to October.

Still to confirm (not blocking): whether the collaborator's animal protocol needs an
amendment; RHS2116 unpopulated/disabled on test hardware; calibration status of
instruments feeding datasheet numbers.

---

## Working principles

1. **Eliminate over detect** — generated docs and single-sourced logic cannot drift.
2. **Ratchet, don't gate** — baseline known violations; the count may only shrink.
3. **Requirements ≠ specifications** — never publish aspirational numbers as measured.
4. **Intent vs. as-built** — separate documents. Conflating them is the root cause of
   the current documentation drift.
5. **Interface specs outrank subsystem specs** — every expensive bug lived at a boundary.
6. **CI is the reviewer** on a two-person team. Never merging red *is* the enforcement.
7. **Phase A adds code to a repo we know is structurally wrong.** Accepted
   deliberately: the animal test is an external commitment and wins. The specific
   foundation work Phase A *does* need — the LVDS interface spec, and fixing `ch_sel`
   structurally rather than tactically — is the part that cannot be skipped anyway.
