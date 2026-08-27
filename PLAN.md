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

### A.1.1 — Verification ladder, using the RHD2164's own known values

Decided 2026-08-07. "Connect the real data path" is not one step: between the
RHD2164 MISO pins and `fifo_din` there are several places where a value can be
real but wrong (MISO sampling timing, DDR A/B demux, the two-command pipeline
offset, slot→channel alignment). None of these is observable against a synthetic
ramp, and none needs an electrode or a signal generator to test — **the chip
supplies its own known values**, which is what separates this from A.3. A.3
starts where this ends: injected analog signals, characterisation, µV numbers.

Pipeline fact underpinning the whole ladder (RHD2000 series datasheet): each
command on MOSI returns its 16-bit result on MISO **two commands later**.

Known-value sources (RHD2164 datasheet unless noted):

| Source | Expected | Notes |
|---|---|---|
| Reg 59, MISO A/B marker | **53 (0x35) on MISO A, 58 (0x3A) on MISO B** | Purpose-built by Intan to confirm SPI signal integrity and tune MISO sampling timing. Asymmetric, so an A/B swap fails outright |
| Regs 40–44 | `I N T A N` = 0x49,0x4E,0x54,0x41,0x4E | Five distinct values in sequence; a wrong pipeline offset appears as rotated letters |
| Reg 63 / 62 / 61 | chip ID **4**, num amps **64**, unipolar **1** | Chip presence + identity, per chip |
| Channel 48 | VDD/2 via on-chip divider; `VDD = 0.0000748 × result` (≈44,100 @ 3.3 V) | First test of the actual **ADC**. Needs `RHD_VDD_SENSE_ENABLE` (`intan.vh:87`, currently `1'b0`). Aux/temp/supply sensors are on the **A module only** — the B result for a non-amplifier channel is meaningless per datasheet |

Ordered tasks, each with a numeric pass/fail.

> **Design settled 2026-08-11 — `docs/interfaces/fpga-diagnostic-access.md`.**
> Rungs (a)–(d) are specified there end to end: the RTL contract Manuel
> implements (§1), the generic **register console** that drives them (§2–§4),
> each rung as a register script with its expected values, RAM word addresses
> and a per-failure diagnosis table (§5), and the testbench work (§6). Decisions
> taken, all in that document's closing section: the rungs are driven by a
> console over the existing 0xFFF1/0xFFF3 control plane rather than an MCU
> build flag, so future rungs are scripts rather than reflashes; the `+2`
> pipeline offset moves into the RTL (see the superseded note above);
> `data_source_sel`'s reset default is **real data**, test pattern opt-in only.
>
> Two things that spec surfaced and this plan did not have:
> - **The testbench's RHD model cannot support any rung.** `rhd2164_model`
>   (`kuntur_tb.sv:403-488`) cycles two canned 4-word arrays; it does not decode
>   MOSI, has no register file, and has no response pipeline. A behavioural
>   `rhd2164_bfm` is a prerequisite for simulating (a)–(d) at all — §6.2.
> - **Rung (d)'s frame-boundary case is not bench-testable.** A whole-frame skew
>   between slot 32 and slot 0 is invisible to a static known value. It needs a
>   model whose responses vary per frame, i.e. simulation — §5.4, §6.3.
>
> Two open issues it raised: `` `RHD_2164_UNIBIAMP `` (`intan.vh:188`) is `8'd0`
> while the datasheet and this plan both say register 61 reads `1` — unused
> today, but about to become load-bearing; and `0x8000` is simultaneously the
> empty-FIFO sentinel and a legal full-negative-rail ADC sample once A.1.1e
> lands, so underrun statistics start counting saturated inputs.

> **BENCH RESULTS 2026-08-11 — first real neural-path data this project has
> ever streamed.** A.1.1e is confirmed working on hardware.
>
> - **A.1.1a — PASSED on chip1** (rung `L`, offset-independent: `READ(59)` in
>   all 33 slots, so no offset assumption can affect it). Sources 2/3 returned
>   `0x0035` / `0x003A` exactly — Intan's MISO A/B markers. That single result
>   establishes MISO sample timing, the DDR A/B split **and its polarity**,
>   `ch_sel`'s source mux, 33-slot command injection, the whole console path,
>   and that regbank word 229 really is selecting real RHD data.
>   **Rung (a) is subsumed by rung `L` and need not be run** — `L` tests the
>   same four sources with the same markers and, unlike (a), cannot be
>   confounded by a wrong slot offset.
> - **Slot offset = 3, confirmed** — see the note above. Rung `O` is likewise
>   redundant; the measurement fell out of the channel selector.
> - **Chip ID = 4 confirmed** (channel 66's constant). Part of rung (c).
> - **⚠ CHIP 0 IS NOT RESPONDING — half the array is dead.** Sources 0/1
>   (`spi1_miso0`, pin G3/LVDS3P) read a stable `0xFFFF` on both DDR halves —
>   all 64 collected frames identical, no spread. Confirmed independently via
>   the channel selector: friendly channels 0–63 are flat at ≈ −1 (`0xFFFF` as
>   `int16`), 64–127 carry signal. Both chips are populated.
>
>   **Isolated to the MISO path.** Both chips share `csb`/`sck`/`mosi` from one
>   `spi_master_rhd2164x2`, and chip1 answers correctly, so commands, clock and
>   chip-select are all proven good. The RTL and the constraints treat the two
>   pins identically — both `IO_TYPE=LVDS DIFFRESISTOR=100` in
>   `source/impl_1/impl_1.pdc` — so nothing in the design distinguishes them.
>   **Leading suspect: the physical LVDS3 pair.** An LVDS input compares P
>   against N; if LVDS3's N side is open or mis-biased while LVDS0's is fine,
>   the comparator sits at one rail permanently, which is exactly the stable
>   all-ones observed. To check: meter LVDS3P/N against LVDS0P/N at the FPGA,
>   and inspect chip0's MISO pin and its series/termination parts.
>
>   **Not a v1 blocker** — 64 channels remain and v1 needs 2 — but it is half
>   the array and must be resolved before any 128-channel claim. Tracked here
>   rather than in A.3 because it is an instrument defect, not a
>   characterisation task.
>
>   **RESOLVED 2026-08-24 — root cause was unconstrained FPGA placement, not
>   the LVDS3 pair.** Full investigation, hypotheses tested and ruled out
>   (PCB trace skew, multi-drop reflections, timing margin, clock speed,
>   `CALIBRATE`/config content), and the fix (pinning `spi1_rhd2164x2` and
>   `controller0` to fixed placement regions in `impl_1.pdc`):
>   `docs/interfaces/fpga-rhd2164-chip0-placement.md`. Verified by restoring
>   the entire original design with placement pinned — both chips now
>   confirmed responding with real channel data (channels 42 and 88) in the
>   pc-app, not just digital toggling. Open items (kuntur_fpga.v cleanup,
>   from-scratch synthesis re-verification) are in that spec's §5, not
>   repeated here.
>
> **Rungs (b), (c) and (d) then also PASSED, all on chip1** (2026-08-11):
>
> - **(b) pipeline offset — exact.** Slots 28–32 returned `I N T A N`
>   (`0x0049 0x004E 0x0054 0x0041 0x004E`) in slot order across three
>   configurations, including a repeat re-read of slot 28. Five distinct values
>   means a wrong offset would have shown as a rotation; there was none.
> - **(c) chip identity — exact.** Reg 63 = `0x0004` (RHD2164 ID), reg 62 =
>   `0x0040` (64 amplifiers), reg 61 = `0x0001` (unipolar — the value corrected
>   in `intan.vh` this session; the old `8'd0` would have been wrong).
>   **Chip 0's identity remains unknown** — it cannot be read until its MISO
>   path works, so we cannot presently confirm chip0 is even an RHD2164.
> - **(d) slot alignment — passed at the frame wrap.** Markers across slots 31,
>   32, 0, 1 read `I N T A`, each at its own `ch_cnt`. Reported as **"slot
>   alignment confirmed; frame-boundary phase not yet verified"** — a
>   whole-frame skew is invisible to a static value and needs T12 in
>   simulation (Phase B).
> - **(O) offset sweep — clean.** `0x0035` appeared at `ch_a = 2` and nowhere
>   else; all seven other probes read `0x0004`. Independent confirmation of
>   `SLOT_OFFSET = 3`.
>
> Rungs (b), (c) and (d) all ran against `PRIMARY_SRC = 2` (chip1) only.
> Rung (a) is the sole rung still probing all four sources, and it **aborted in
> its restore phase** (`word 63: no response after 3 retries`) after correctly
> reporting the chip0 failure — see the debug-print hazard below.
>
> **⚠ Operational hazard found and fixed: per-command debug prints.** Every
> 0xFFF1 command was emitting ~3 blocking `APP_DBG_MSG` lines. At 115200 that
> is ~15 ms of blocking UART per command, and USART1 is on **APB1, which the
> BLE radio gates** — the same hazard that forced FPGA SPI onto bit-banged
> APB0. Harmless at one line per operator click; a rung issues ~90 commands
> back to back. Symptom: a steady trickle of pc-app command timeouts (mostly
> recovered by retry) and one rung aborting mid-restore, which leaves the FPGA
> half-reconfigured. Fixed by gating the high-rate prints behind
> `STREAM_REG_CONSOLE_VERBOSE` (default 0) in `stream_app.c`; readback
> mismatches and malformed frames still print unconditionally. **Needs a
> firmware reflash to take effect** — built clean 2026-08-11.
>
> Remaining on the bench: re-run rung (a)'s restore after the reflash, and the
> A.2 re-test.

- [x] **A.1.1a — Link integrity & DDR demux.** `READ(59)`; expect 53 on `data_a*`,
      58 on `data_b*`, both chips. Proves MISO timing, DDR split, and that the four
      `ch_sel` inputs map to the right chip and half.
- [x] **A.1.1b — Pipeline offset.** `READ(40..44)` in consecutive slots; expect
      `INTAN` arriving two slots later. Pins the offset down numerically.
- [x] **A.1.1c — Chip identity.** `READ(63/62/61)` → 4 / 64 / 1, per chip. Also the
      FPGA-side half of B.6's `doctor`.
- [x] **A.1.1d — Slot→channel alignment.** `ch_sel` selects by timing `ch_cnt`
      against the SPI0 output stream, so the two-command offset must be accounted
      for in that alignment for `ch_a`/`ch_b` to mean the channel they name.
- [x] **A.1.1e — Connect `dout`** to `data0_synced`/`data1_synced`, **and do the
      A.1 structural fix in the same change.** ✅ **DONE AND CONFIRMED ON HARDWARE
      2026-08-11** — rungs (a)-(d) all pass on chip1, which is only possible with
      real RHD data reaching the FIFO. ← was **THE GATE FOR THIS LADDER**
      (promoted 2026-08-11, see below). Only meaningful once (d) holds.
      *Specified 2026-08-11, `fpga-diagnostic-access.md` §1.1:* test-pattern
      generation moves out of `ch_sel` into its own module and is muxed at the
      **top level**, selected by new regbank word **229** bits `[1:0]`
      (`0` = real RHD data = **reset default**, `1` = ramp). A runtime word, not
      a `` `define ``, because B.5's pre-session self-test and B.6's `doctor`
      must push a known pattern through the real path on an assembled device
      that will not be re-synthesised. Lands together with §1.2's two-counter
      offset, §1.3's `CONVERT(k)`-at-slot-`k` sampling-table defaults, and
      §1.4's deletions (`rhd2164_sampling_cmd0-3`, `regbank_addr0`,
      `ch_is_16`/`dout_en_16`) — one pass over `ch_sel`, not four.
- [ ] **A.1.1f — ADC path.** Enable VDD sense, convert channel 48 on module A,
      expect ≈44,100 at 3.3 V. First real analog value end to end.

**Status 2026-08-11 — the driver for (a)–(d) is built; the RTL it drives is
not.** Everything below the RTL line now exists and is tested as far as it can
be without hardware:

- [x] **Interface spec** — `docs/interfaces/fpga-diagnostic-access.md`, written
      before any code per working principle 5. Also updated
      `channel-selection-control-plane.md` (register table gains word 229,
      `ch_a[5:0]`'s meaning pinned, commands `0x04`/`0x05`, response types
      `0x04`/`0x05`, `rhd2164_sampling_cmd0-3` marked for deletion).
- [x] **MCU register console** — `FPGA_SPI_RegWrite16`/`RegRead16`/
      `SetSamplingSlot`/`SetDataSource`/`ReadDataSource` (`fpga_spi.c`/`.h`);
      0xFFF1 commands `0x04 REG_WRITE16` / `0x05 REG_READ16` with the same
      validate-stash-defer shape, stopped-stream precondition and
      `s_command_busy` guard as the existing three; `STREAM_NotifyRegAccess()`
      on 0xFFF3, `STREAM_RESPONSE_PAYLOAD_SIZE` 3 → 4. A write's ack carries
      the **readback**, so a scripted 33-word table rewrite is verified per
      word for free. Also collapsed `ReadStreamEnable` onto the shared
      `reg_read16` helper. **Builds clean for ARM, zero new warnings**
      (2026-08-11) — the only `fpga_spi.c` warnings are the pre-existing
      `%u`/`%lu` ones in `FPGA_SPI_DebugDumpPairs`, which this change did not
      touch.
- [x] **pc-app rung runner** — `pc-app/diagnostics.py`: rungs (a)–(d) as
      **data** (setup writes, observations with expected values, restore,
      per-rung diagnosis table) plus a generic ack-gated runner with
      `COMMAND_GAP_MS` pacing, retry-on-timeout, first-2-pair discard, and mode
      -not-single-sample measurement. Adding rung (f) is a table entry, not a
      code change — which is the "flags only" requirement, met more strongly
      than asked. Gated behind a collapsed **Diagnostics** panel in
      `main_window.py`.
- [x] **MCU console verified on the host** — `mcu-tests/`, added 2026-08-11.
      Compiles the **real** `Core/Src/fpga_spi.c` against stub HAL headers and a
      **pin-level model of the A.1.1g FPGA FSM**, so the bit-bang layer (bit
      order, 16-bit framing, NSS) is exercised too rather than trusted. 52
      checks: exact wire sequences for `RegWrite16`/`RegRead16`, the 16-bit
      staged-high-byte path with distinct non-zero high bytes, write→read round
      trip over all 256 words, `SetSamplingSlot` range rejection issuing **zero**
      transfers, all control words, `ReadSamples` pair integrity, friendly↔raw
      bijectivity, and — the load-bearing one — that **every public function
      leaves the FSM at its decode state**, which is exactly the 2026-08-11
      latent failure (a half-open POP pair eating `STOP_STREAMING`'s tag-1
      write, so streaming would never stop).
      **Mutation-tested**, because a suite that cannot fail is worthless:
      dropping the tag-2 transfer → 23 failures; dropping `RegRead16`'s NOP
      carrier → 1 failure; removing the slot range check → 4 failures. The
      middle one is instructive — `READ`+`READ` still returns correct *values*
      and is caught only by the wire-sequence assertion, which is why the suite
      asserts sequences and not just return values.
      **The firmware also builds clean for ARM** (2026-08-11): zero warnings
      from any of the changed code; the only `fpga_spi.c` warnings are the
      pre-existing `%u`/`%lu` ones in `FPGA_SPI_DebugDumpPairs`.
- [x] **Runner verified offline** — `pc-app/test_diagnostics.py`, against a
      fake reader implementing the spec's contract. All four rungs pass; a
      regbank value that disagrees with what was written aborts naming the
      word; two dropped commands retry and still complete; a broken B-side DDR
      demux fails rung (a) with `0x35/0x35`, matching its diagnosis table.
      Also pins the pc-app→bridge wire format for `0x04`/`0x05` against the
      spec's byte layout — including the little-endian value split, where a
      big-endian slip is silent because `0x95A5` arriving as `0xA595` still
      writes *something* — and asserts the slot→`ch_a` map stays injective and
      in range whatever `SLOT_OFFSET`/`FRAME_SLOTS` become.
- [x] **RTL — data-source mux + word 229** *(Manuel, 2026-08-11)*.
      `ch_sel.dout` now carries `{ch0, ch1}` latched from
      `data0_synced`/`data1_synced` — **A.1.1e's core connection, done**. The
      ramp moved to `kuntur_fpga.v`, muxed on `data_source_sel` (regbank word
      229, reset default `0` = real data), clocked by a new `dout_en_0` output
      from `ch_sel` so its timing is identical to the old in-`ch_sel` version.
- [x] **RTL — slot/response offset: no change needed** *(settled 2026-08-11)*.
      The `+3` is a mapping question, not a capacity one: with the original
      33-slot counter, `ch_a = v` observes slot `(v-3) mod 33`, a **bijection
      over all 33 slots**, so the ladder runs against today's counter. The
      offset lives in `pc-app/diagnostics.py` as `SLOT_OFFSET`/`FRAME_SLOTS`,
      applied centrally in `ch_code()`. A 36-slot variant was tried and
      reverted — it broke `ch_is_0_redge` (`cnt0` never returned to 0, so
      `fifo_wen` fired once at boot and never again) and would have cost ~8.3%
      of the sample rate even once fixed, while still leaving `ch_a = slot+3`.
      Making `ch_a` name the slot directly is deferred to Phase B as a clarity
      fix, where T11/T12 can verify it.
- [x] **RTL — sampling table needs no change** *(confirmed by Manuel,
      2026-08-11)*. Spec §1.3 previously demanded `CONVERT(k)` at slot `k`, on
      the reading that slots 2–31's thirty consecutive `CONVERT(63)` meant
      thirty conversions of channel 63. **Wrong — `C=63` means "cycle through
      successive amplifier channels"** (`intan.vh:24`, and the datasheet).
      Slot 0's `CONVERT(0)` and slot 1's `CONVERT(1)` anchor the chip's channel
      counter and the thirty `CONVERT(63)` walk it 2→31, so **slot `k` already
      converts channel `k`** — self-correcting too, since the anchor is
      re-asserted every frame. Requirement withdrawn; the table is deliberate
      and stays. Recorded prominently in the spec because thirty identical
      commands read like a copy-paste bug and will invite a "fix" that breaks
      it — the same trap as `stream_enable`'s reset default.
- [x] **RTL — nothing further needed for Phase A.** The §1.4 deletions moved to
      Phase B (see B.1), 2026-08-11: they are housekeeping, and re-synthesising
      before a bench session to remove dead wires trades a known-good bitstream
      for an unverified one with no test coverage behind it (Phase A has no
      simulation). Do them in Phase B alongside the testbench that can catch a
      slip.
- [ ] **Bench run** — fold into the same session as the A.2 re-test, per the
      sequencing note under A.2. **Phase A is bench-only** (decided
      2026-08-11); see B.1 for the simulation half.

**Response-delay offset is 3, not 2 — found 2026-08-11 while writing the RTL
change list, unconfirmed on hardware.** The RHD's own pipeline is 2 commands,
but `data_rx_*` are held registers loaded at the SPI master's `csbend1`
(`spi_controllers.v:1002-1007`, `sr_s2p` at `385-393`), and `rhd_done` is
asserted six clocks later in `idle` — so `rhd2164_controller` increments after
the load, and `ch_sel`'s `ch_is_a_redge` (first two clocks of the next slot)
sees the word loaded during the *previous* slot. One extra slot on top of the
RHD's two. This contradicts `components.v:627`'s *"Remember there is a delay of
2 SPI cycles"*. Never observable before now, because `dout` has always been the
ramp.

**The `ch_a`/`ch_b` reset defaults do not settle it** — checked 2026-08-11,
both readings are self-consistent, so they are not evidence either way:

| offset | `ch_a = {2'd2,6'd3}` | `ch_b = {2'd2,6'd2}` |
|---|---|---|
| 2 | slot 1 → channel 1 | slot 0 → channel 0 |
| 3 | slot 0 → channel 0 | slot 32 → `READ(63)` → constant 4 |

**CONFIRMED ON HARDWARE 2026-08-11 — the offset is 3.** Friendly channel 66
(source 2, index 2) reads a constant **4**: that is slot `(2-3) mod 33 = 32`,
the alternate-command placeholder holding `RHD_READ(63)`, whose answer is the
RHD2164 chip ID. Under an offset of 2 the same channel would have shown slot
0's live signal. Neighbouring channel 65 shows signal, as predicted. Measured
with the ordinary channel selector — no rung needed.

That single reading also confirms two other things for free: **the placeholder
slot 32 really is fetched and transmitted every frame** (A.1.4's claim, never
previously demonstrated on hardware), and **rung (c)'s chip-ID check, reg 63 =
4**.

`components.v:627`'s *"Remember there is a delay of 2 SPI cycles"* is therefore
wrong and should be corrected to 3 when the §1.4 housekeeping happens in Phase
B. The offset remains a single named constant (`SLOT_OFFSET` in
`pc-app/diagnostics.py`), so a future RTL change to the counter or the latch
timing is a one-line host edit.

**Ordering, revised 2026-08-11 — A.1.1e is the gate, not A.1.4.**

The original note here read *"A.1.4 comes first — (a), (b), (c) and (f) all need
a way to put an arbitrary command into the sampling cycle."* They do, and
**that way already exists**: A.1.1g made every RAM word writable at full 16-bit
width, and the 33rd sampling slot already fetches `ram[80]` and transmits it
every frame (see A.1.4 below for the trace). Command injection is a
`reg_write16(80, cmd)` from the MCU — no RTL work at all.

The binding constraint moved. **You can inject any command; you cannot see the
answer**, because `ch_sel` still discards `data0_synced`/`data1_synced` and
emits the ramp (`components.v:423-425`). So A.1.1e gates (a), (b), (c) and (f),
not A.1.4.

Reading the placeholder's result needs no new RTL either: the RHD returns a
command's value two commands later, so slot 32's answer lands at slot
`(32+2) mod 33 = 1`, i.e. `ch_a = {2'b00, 6'd1}`. The `ch_a` reset default
already carries the comment *"Remember there is a delay of 2 SPI cycles"*, so
this was anticipated.

> **Superseded 2026-08-11 — the offset moves into the RTL.** Making every
> caller of `ch_a` carry a mental `+2 mod 33` is the kind of correction-by-comment
> that working principle 1 exists to prevent. Manuel's fix: split
> `rhd2164_controller`'s `cnt0` into two counters incrementing in lockstep, with
> different start values — `cnt_cmd` (drives `rb_addr1`) starts at **2**,
> `ch_cnt` (drives `ch_sel`'s comparators) starts at **0**. Then
> `MISO(t) = ram[48 + ch_cnt(t)]` identically, so **`ch_a[5:0] = k` observes
> sampling slot `k`** for every `k` in 0–32, with no correction anywhere and no
> modulo adder in the comparator path. The placeholder slot's answer is read at
> `ch_a[5:0] = 32`, not `1`, and `components.v:623`'s "Remember there is a delay
> of 2 SPI cycles" comment is deleted along with the `{2'd2, 6'd3}` default it
> justified. Full derivation, first-frame artefact and frame-boundary caveat:
> `docs/interfaces/fpga-diagnostic-access.md` §1.2.

**Do A.1.1e together with the A.1 structural fix** (test-pattern generator
extracted into its own module, muxed at the top level behind a named signal).
Three reasons converge:

- The plan already argues the restructure "avoids touching `ch_sel` twice."
- A.1.1e **kills the testbench's `ChB - ChA == 1000` pairing invariant**, which
  only holds because `ch_sel` emits the ramp. A selectable test-pattern mode
  keeps that assertion alive; without it, A.1.1g-tb's T5 silently stops meaning
  anything and has to be rewritten against real data.
- The same mux is what lets `doctor` (B.6) and the B.5 pre-session self-test run
  a known pattern through the real path on a built device.

**Watch during (d):** 33 slots with a fixed 2-slot response delay means slots 31
and 32 have their answers land at slots 0 and 1 of the *next* frame — across the
`ch_is_0_redge` boundary that latches `data0_synced`. The placeholder slot sits
on the awkward side of that boundary, so it is the case most likely to expose an
off-by-one-frame in the alignment.

- [ ] **A.1.1g — Widen regbank access so any word is MCU-readable/writable at
      runtime.** *Status 2026-08-11: **RTL landed and now verified in
      simulation** (see A.1.1g-tb, 27/27 checks). The only remaining piece is
      the **MCU-side rewrite**, listed under "MCU-side impact" below — it is the
      blocking item, since the new bitstream cannot be flashed without it
      without breaking A.2's round-trip.*
      Decided 2026-08-07, originally framed as a prerequisite alongside A.1.4 —
      in the event it **subsumed** A.1.4's purpose entirely (uniform 16-bit
      access made the sampling table itself the command-injection mechanism).
      Two limits:
      `kuntur_fpga.v:122` hardcodes `regbank_addr0 = {2'b10, spi0_drx[13:8]}`,
      and since `addr0` feeds **both** the read and write paths this confines
      *both* to words 128–191 while the sampling slots sit at 64–96; and
      `kuntur_fpga.v:124` sets `regbank_din0 = {8'd0, spi0_drx[7:0]}`, so every
      write is 8-bit. A sampling slot holds a **full 16-bit** RHD command word,
      needing an 8-bit address *and* 16-bit data — 2+8+16 does not fit a 16-bit
      transfer, so indirection is forced, not preferred. Read *data* is already
      full-width (`dtx_mux_reg` passes `ram_din[15:0]`); only the read *address*
      is limited.

      **Uniform indirect access — a 3-transfer sequence with a redundant tag**
      (as-built, settled 2026-08-08). All MCU access to RAM goes through one
      mechanism, identical for every one of the 256 words.

      A `REG_WRITE` is a **three-transfer sequence**, tracked by the
      `main_controller` FSM (`op_write0`..`op_write6`). Each stage additionally
      requires the `addr` field to carry a matching **sequence tag**:

      | Transfer | `addr` tag | Effect |
      |---|---|---|
      | 1 | 1 | `addr_reg <= data[7:0]` |
      | 2 | 2 | `staged_h <= data[7:0]` |
      | 3 | 3 | `ram[addr_reg] <= {staged_h, data[7:0]}` |

      A `REG_READ` is **self-addressing**: it carries tag 1 and its own 8-bit
      address, loads `addr_reg` exactly as `REG_WRITE` transfer 1 does, and the
      value appears on the following transfer. So **tag 1 uniformly means "load
      address"** across both commands — one idiom, not two. Corrected 2026-08-10:
      as originally built the read ignored its address field and returned
      `ram[addr_reg]` from whatever the last *write* had left there, so a word
      could only be read by first writing it — the address register was never
      enabled on a read path (`regbank_port_en` was asserted only on the write
      branch of `op_decode1`). Found by Manuel, fixed same session.

      Reads do **not** auto-increment — repeated reads stay idempotent, and a
      `doctor` self-test simply sends the address it wants. There is no
      auto-increment on write either: the positional sequence restarts with an
      address load every time, so there would be nothing to exploit.

      **Transfer lengths — multi-transfer structure only where something forces
      it** (settled 2026-08-08, after finding that `NOP` and `REG_READ` were both
      built as mandatory 2-transfer pairs):

      | Command | Transfers | Why that length |
      |---|---|---|
      | `REG_WRITE` | 3 | Inherent — address, high byte, commit. Tag-checked at each stage |
      | `FIFO_POP` | 2 | Inherent — ChA then ChB. Second transfer must also be `POP`, so a broken pair fails loudly rather than half-consuming a FIFO entry |
      | `REG_READ` | 1 | Nothing to sequence — it carries tag 1 and its own address, and the value lands on whatever transfer follows |
      | `NOP` | 1 | Nothing to sequence |

      The bug this fixed: a 2-transfer `NOP` **swallowed the following transfer**
      — it was consumed by the sequence's wait state and never decoded. That made
      `NOP` unusable for its three natural jobs (padding, carrier to clock out a
      pending `REG_READ` value, and resync when the MCU is unsure of FSM state);
      sending NOPs to recover would have chewed through the commands after them.
      `REG_READ` as a mandatory pair had no equivalent justification — unlike
      `POP`, where the pair is real — and it forced a wasted `READ` as a carrier.

      Resulting invariant: **every transfer either starts a new command or is an
      identified part of a sequence, and no transfer is ever silently consumed.**
      All abort paths (three tag mismatches plus the `POP` pair check) land on
      `op_nop0`, one clock back to `op_decode0`, so an abort costs exactly the
      offending transfer. Combined with the tag checks this makes the protocol
      self-synchronising: send a `NOP` and you are at a known state, always.

      `addr_reg` and `staged_h` are **dedicated registers, not ram words** — a
      commit writes the target word and updates state on the same edge, which a
      single-write-port array cannot do if the pointer lives in it, and which
      would otherwise need a `ram[ram[N]]` two-level lookup plus a second 256-way
      write decoder. Only two registers are needed: transfer 3's low byte is
      consumed in the cycle it arrives, so it stores nothing.

      **Why positional rather than a pure port selector** (this reverses an
      earlier recorded decision): SPI0 is *already* a positional protocol — POP
      has always been two transfers, ChA then ChB. Making WRITE positional keeps
      one idiom across the interface instead of two. **Why the redundant tag
      anyway:** under bare positional, three consecutive writes look like three
      identical words on a logic analyzer and can only be interpreted if you know
      where the sequence started, and a transfer lost on the wire leaves the FSM
      parked mid-sequence where it silently absorbs the *next* unrelated transfer
      as the missing one. The tag makes traces self-describing and turns a desync
      into a detected abort (to `op_nop3`, like the existing `opcode_is_write`
      re-checks) rather than a silent misinterpretation. Cost is three
      comparators. Robustness and consistency were judged equally important, and
      the tag buys both.

      Rejected: a bare port-selector scheme with no sequencing (inconsistent with
      POP's existing positional shape); bare positional with no tag (silent
      desync, opaque traces); widening SPI0 to 32 bits (touches `spi_slave`,
      `main_controller`, `dtx_mux_reg`, the MCU bit-bang); a fifth opcode
      (`00/01/10/11` all in use as of A.2); keeping a directly-addressed window
      as a fast path (reaches only 64 words and earns nothing once indirection
      exists).

      **Side effect worth more than the feature: the ChA/ChB pairing hazard looks
      eliminated.** Previously `mcu_dtx_sel`/`mcu_dtx_en` were driven
      unconditionally on every transfer, so the ChA/ChB phase free-ran and any
      odd number of non-POP transfers shifted it — the origin of spec section
      1a's "register writes must always be an even-numbered batch" rule, and the
      suspected cause of the historical 32-bit FIFO channel-swap bug. In the
      rewritten FSM the phase is set explicitly per state: writes drive `2'd2`
      (SRAM), only `op_pop0`/`op_pop3` drive ChA/ChB. A write sequence can no
      longer disturb the pairing at all, which also makes the "pad to an even
      transfer count with a NOP" rule obsolete. **CONFIRMED in simulation
      2026-08-11** (see A.1.1g-tb): pairing held across a 3-transfer write, a
      read+NOP and a lone NOP, with ChA/ChB advancing 1→4 and the delta exactly
      1000 every time. The rule can now be deleted from the spec.

### A.1.1g-tb — T2 testbench work  ✅ **COMPLETE 2026-08-11**

Status 2026-08-11: `kuntur_tb.sv` (renamed from `.v`; SystemVerilog, `qrun.f`
updated) is now **self-checking** — 27 immediate assertions across T1–T7 with a
pass/fail summary and `$finish`, no waveform reading required. Full run passes,
2.25 ms sim, against a 4 ms timeout guard.

Structural changes: an `spi_xfer(word)` task that handshakes on `mcu_done`
instead of fixed delays (so there is no settle delay to re-tune when SPI timing
changes — note `wait()` not `@(negedge)`, since `mcu_done` falls *inside* the
start pulse and an edge-triggered wait blocks forever); `reg_write16` /
`reg_read16` / `fifo_pop_pair` wrappers; and command-encoding functions
replacing the hardcoded `data_mosi_*` parameters.

**Two results worth more than the pass line:**

- **The pairing claim is confirmed, non-vacuously.** ChA ran `0001,0002,0003,
  0004` with ChB exactly +1000 each pair — the counters *advance*, so the FIFO
  was genuinely non-empty and each pair consumed a fresh entry rather than
  passing on the underrun sentinel. Retires the even-batch rule,
  `FPGA_SPI_Init()`'s priming transfer, and the NOP padding.
- **A broken POP pair fails loudly, as designed.** ChA jumped `0004 → 0006`: the
  lone POP fired `fifo_ren` at `op_decode1`, popped entry `0005`, delivered its
  ChA, then aborted when the partner was not a POP — so entry 5's ChB was never
  clocked out. One entry lost, no phase slip afterwards. This is the closest
  thing yet to a direct test for the historical 32-bit FIFO channel-swap bug.

*Simulator note:* this design does not simulate under iverilog — time stops
advancing at t=60 ns, right as `rhd_start` first pulses. Questa runs it
correctly, so it is an iverilog artifact, not an RTL fault. Leading suspect is
`rhd2164_controller` (`components.v:879`), whose hand-written sensitivity list
`always@(current_state or rhd_done or cnt0_is_max)` drives `rhd_dtx_sel` →
`max` → `cnt0_is_max`, back into its own list. It should settle since
`rhd_dtx_sel` is a pure function of `current_state`, but `always@(*)` would
remove the question. Consequence for now: **testbench work cannot be
self-verified outside Questa** — Claude proposes, Manuel runs. This is not
accepted as permanent: see the B.1 item *"Make the RTL simulate under an
open-source simulator"*, which treats it as a contributability and CI blocker
in the same class as B.6's licensed-toolchain problem, not a convenience.

- [x] **Exercise the 16-bit write path.** Both write sequences currently stage
      `8'd0` as the high byte, so the commit `{staged_h, data[7:0]}` is
      indistinguishable from the old 8-bit write. **This test would still pass
      with review-bug #2 present** (the `regbank_port_sel` width truncation that
      left `staged_h` permanently unwritten). Widening writes to 16 bits *is* the
      feature and nothing currently proves it works. Best case: write a full RHD
      command word into a sampling-table slot (48–95), where 16-bit words are the
      actual motivation, and read it back.
      *Done:* T2 writes `0x95A5` to word 48 and `0x3C5A` to 49 — both non-zero
      high bytes, so a `staged_h` never written reads `0x00A5` and one stuck at
      `0x95` reads `0x955A`. Both pass; a third read re-checks 48 after writing
      49 to catch a commit to the wrong address.
- [x] **The pairing claim** — unverifiable by reading source, and the current
      stimulus cannot expose it because it is grouped by opcode (six POPs, *then*
      writes, *then* reads). The hazard only appears with register traffic
      **between** POP pairs. Needs `POP,POP → WRITE×3 → POP,POP → READ,NOP →
      POP,POP`, where three writes is deliberately odd — exactly the case the
      even-batch rule existed to prevent. Two preconditions for it to mean
      anything: the FIFO must be non-empty (the current POPs fire ~12 µs after
      reset), and ChA/ChB must be distinguishable.
      *Correction, found while writing the test:* the RHD model's canned
      `0xe7xx`/`0x81xx` **never reach the FIFO** — `ch_sel` computes
      `data0_synced`/`data1_synced` and then discards them, assigning
      `dout = {cnt0, cnt0+1000}` (the A.1 ramp, `components.v:423-425`). That is
      better for this test, not worse: the pair invariant becomes the numeric
      `ChB - ChA == 1000`, with a phase slip flipping it to −1000 (=64536), and
      `0x8000/0x8000` accepted separately as the underrun sentinel. **This test
      must be revisited when A.1.1e connects the real data path** — the ramp
      invariant it asserts on will no longer hold.
      Confirming it retires three MCU-side workarounds at once: the even-batch
      rule, `FPGA_SPI_Init()`'s priming transfer, and the NOP padding, and it is
      the closest thing to a direct test for the historical 32-bit FIFO
      channel-swap bug.
- [x] **Read-path settling** — was the hygiene check; became load-bearing once
      the read started loading its own address (2026-08-10), since `addr_reg` is
      now written one to two clocks before use rather than transfers earlier.
      `addr_reg` is written in the port-register always block while
      `dout0 <= ram[addr_reg]` reads it in another; confirm MISO carries the
      value for the address just loaded, not the previous one. The `op_read0` →
      `op_read1` split exists precisely for this.
      *Done:* T3 reads 48→49→48 back to back, then reads 49 immediately after a
      write to 50 — the case where `addr_reg` was last left pointing elsewhere,
      which is the 2026-08-10 regression class.
- [x] **Abort paths — currently untested.** The tag comparators are the new
      safety mechanism and nothing exercises them. Minimum: a bad tag at each of
      the three write stages (e.g. `WRITE t1 → WRITE t3`, which must abort to
      `op_nop0` and leave the target word untouched), and a `POP` not followed by
      a `POP`.
      *Done:* T6 covers all three write-tag mismatches against a known `0xCAFE`
      target plus a write that must still work afterwards; T7 covers the broken
      POP pair and confirms a `NOP` does not swallow the following transfer.
- [x] **Collapse the stimulus into a `spi_xfer(word)` task.** The
      `#12000/#300/#600` triple now appears 15×; the interleaved pairing sequence
      above is a three-line edit with a task and a rewrite without one.
- [x] **Housekeeping:** delete the dead old-protocol parameters `data_mosi_a` /
      `data_mosi_b`; restore the field structure in `data_mosi_write_b3`
      (`{2'd2,6'd4}` documents the encoding, flat `8'h84` hides it).
      *Done:* all `data_mosi_*` parameters replaced by `cmd_wr_addr/high/low`,
      `cmd_read`, `cmd_wr_tag` encoding functions, so no literal hides a field.
- [ ] **Optional — tags on `FIFO_POP`.** POP still ignores its address field.
      The trace-readability argument that justified the write tags (and was
      accepted for `READ`) applies equally; tags 1/2 on the two POP transfers
      would make a logic-analyzer capture fully self-describing.



      Consequences: all 256 words are equally reachable, so `ch_a`, `ch_b` and
      `stream_enable` stop being privileged and are written like any other word.
      `regbank_addr0 = {2'b11, spi0_drx[13:8]}` and `ram`'s `addr0` port are now
      **vestigial** — the array address is `addr_reg` — and should be deleted
      before they mislead someone into thinking direct addressing survives.
      `RB_CTRL_BASE` survives as a **map convention** (where the control
      registers happen to live), not as a decode boundary. `rb_addr1` and the RHD
      command fetch are untouched.

      Cost: a register write is 3 transfers, a read 2. `SET_CHANNELS` goes from 2
      transfers to 6 — irrelevant on a paused-stream reconfiguration path.

      **MCU-side impact (Claude, once the RTL lands):** `FPGA_SPI_SetChannels`,
      `SetStreamEnable`, `ReadStreamEnable` and `ReadChannels` all rewrite
      against the new scheme, plus `docs/interfaces/channel-selection-control-plane.md`
      sections 1 and 1a. This **is** a wire-protocol change — it does not
      preserve the existing MCU offsets — so it cannot lag the RTL without
      breaking A.2's round-trip. **A.2 must then be re-tested end to end on the
      bench** (see the note at the head of A.2): its 2026-08-06 verification was
      against the old protocol and does not carry over.

      **Memory map, rearranged in the same change** (decided 2026-08-07). The
      old layout wasted address space because `rb_addr1 = {1'b0, rhd_dtx_sel,
      cnt0}` built its config/sampling mux out of bit concatenation, forcing each
      table to a 64-word aligned region regardless of use (config used 34 of
      0–63, sampling 33 of 64–127). Replaced by base+offset — costs a small
      adder, timing impact accepted as negligible:

      | Region | Words | Used | Spare |
      |---|---|---|---|
      | RHD config table | 0–47 | 34 | 14 |
      | RHD sampling table | 48–95 | 33 | 15 |
      | Free | 96–191 | — | 96 |
      | Control registers | 192–255 | `ch_a` 196, `ch_b` 197, `stream_enable` 228 | — |

      **Headroom rationale:** 48 words per table is not a round number for its
      own sake. The RHD2164 datasheet recommends reserving **three** alternate-
      command slots and this design reduced that to one (+2 to restore); the
      non-amplifier channels are auxin1–3, VDD (ch 48) and temperature (ch 49),
      five more if ever sampled in-cycle. 32+3+5 = 40, so 48 leaves real margin.
      Keeping 96–191 free is a deliberate choice for future needs even at the
      cost of RAM. Sizes stay **parametric** so the map can be retuned later.

      **Single-source the map.** `cfg_max`/`sampling_max` live in
      `rhd2164_controller`, the bases in the top-level address computation, and
      the reset defaults as ~256 hardcoded `ram[8'dN] <=` literals in `ram`.
      Moving a table means renumbering those literals by hand with no compiler
      help — precisely the drift working principle 1 exists to prevent. Put the
      map in `intan.vh` (already the shared-constants home) as
      `RB_CONFIG_BASE`/`RB_CONFIG_ALLOC`/`RB_SAMPLING_BASE`/`RB_SAMPLING_ALLOC`/
      `RB_CTRL_BASE` and derive all three consumers from it. Collapse the
      filler-zero runs into generate loops so the real entries are visible.

      **Latent bug to fix while in there:** `components.v:496` declares
      `reg [DATA_WIDTH-1:0] ram [0:(2**8)-1]` — hardcoded `2**8` despite
      `ADDR_WIDTH` being a parameter. Harmless today because both are 8, which is
      why it will survive until it doesn't. Should be `2**ADDR_WIDTH`.

      **Confirmed 2026-08-24 (Manuel, floorplan observation during the chip0
      placement-pinning investigation — see the FPGA timing constraints
      spec's §7/open items for that investigation's own status): the regbank
      is using a lot of FPGA area.** Consistent with the hypothesis above —
      word-by-word initialisation under an asynchronous reset forces
      flip-flop inference rather than EBR, so 256×16 is ~4096 FFs of fabric,
      not free block RAM.

      **Quantified 2026-08-26**, from the per-macro area reports generated
      as a byproduct of the item-4 placement-region work
      (`regbank_macro/kuntur_fpga_impl_1.arearep`): `regbank` alone uses
      **4147 of the whole design's 4657 register bits — 89% of the
      design's flip-flop usage, 30% of the entire device's register
      capacity** — plus 2720 of 2752 `WIDEFN9` wide-fanin LUTs (the
      256-deep read-address muxing for `dout0`/`dout1`). `4147 ≈
      256 × 16 + addr_reg/staged_h` confirms the array really is 256
      individual flip-flop words, not EBR. The device already uses real
      EBR elsewhere (`PDPSC16K` × 8, almost certainly `fifo0`) — this is
      specific to how `ram` (`components.v:457`) is coded, not a device
      limitation.

      **Root cause, precisely — corrects the "split by purpose" framing
      below.** The area driver is not memory *size*, it's that every one
      of 256 words gets an explicit `if (!rstb) ram[N] <= <distinct
      value>;` (`components.v:516-700`). EBR has no way to async-reset 256
      words to 256 different nonzero values combinationally in one edge —
      its only power-on mechanism is bitstream-loaded INIT content, and
      any reset it supports is a synchronous clear to one shared value.
      Splitting into three memories by purpose, as originally proposed,
      would **not** fix most of this: 67 of the 256 words (34 config + 33
      sampling) carry live, distinct default values and would need the
      *same* per-word async-reset pattern in any split, in three smaller
      boxes instead of one. Splitting cleanly helps only the **control**
      region (192–255): just ~6 of those 64 words are actually live
      (`ch_a`, `ch_b`, `stream_enable`, `data_source_sel`, plus the 4 dead
      `rhd2164_sampling_cmd0-3` words A.1.4 already flags for deletion) —
      those become plain named registers, near-zero cost. Separately, 112
      words (96–191, 240–255) are reserved-for-future-use padding, reset
      to 0, and are *currently* costing real flip-flops (~1792 of the
      4096 bits) for storing nothing.

      **Decided 2026-08-26 (Manuel): move to EBR for the config/sampling
      tables.** Checked first whether anything depends on a bare `rstb`
      pulse (no bitstream reprogram) restoring the RHD config/sampling
      table to defaults — answer: not today, but Phase B's planned
      `doctor`/self-recovery capability (B.5/B.6) was going to want
      *something* like it. Resolved by choosing a better mechanism for
      that, not by keeping the expensive one: restoring known-good
      defaults becomes a **firmware-issued sequence of `REG_WRITE`s**
      over the existing runtime-writable regbank interface (already fully
      supported end-to-end by A.1.1g's uniform indirect write path — no
      new RTL needed for this), rather than an implicit side effect of a
      shared hardware reset pin that also resets everything else in the
      design. This fits the regbank's existing "dumb, uniform, rewritable
      at runtime" philosophy (A.1.1g's "writes are left unrestricted"
      decision) better than an RTL-side reset trick would, and gives
      `doctor` an explicit, host-driven remedy action instead of an
      implicit one. **New tracked item, Phase B (B.5/B.6):** MCU-side
      "restore regbank defaults" helper — a table of the known-good
      config/sampling words pushed via existing `REG_WRITE` sequencing —
      as part of the `doctor`/pre-session self-test machinery. *(Claude,
      once B.5/B.6 work starts.)*

      **DONE 2026-08-26** — landed directly as "the real fix" (`kuntur`
      `2021971`), skipping the cheap-padding-only intermediate step:
      - [x] Restructured `ram`'s config+sampling+free region (words 0–191)
            to use an `initial` block (bitstream-configuration-time power-on
            values) instead of active per-word `if (!rstb)` assignment, so
            it can synthesize as EBR. `ch_a`/`ch_b`/`stream_enable`/
            `data_source_sel` pulled out into small dedicated registers with
            their own unchanged async reset — required, not optional: those
            four are read combinationally every cycle by `ch_sel` and a hard
            EBR primitive has no combinational output for a fixed address.
      - [ ] `rhd2164_sampling_cmd0-3` deletion (A.1.4, words 192–195) —
            deliberately **not** done in this pass, since it needs
            `kuntur_fpga.v` port-list changes and that file was mid-edit for
            the item-4 placement work below at the time. Still tracked there.

      **Measured post-synthesis (Manuel, 2026-08-26)** —
      `regbank_macro/kuntur_fpga_impl_1.arearep`: **4147 → 35 register bits
      (30% → 0.253% of the device)**, now backed by 2 real `PDPSC16K` EBR
      blocks (was 0). Whole-design register usage: **4657 → 545 bits (33.7%
      → 3.9% of the device)**; the 256-deep read-address `WIDEFN9` wide-mux
      LUTs collapsed **2752 → 32**. **STA clean** (Manuel). One small,
      expected residual: `DPR16X4 × 16` (small LUT-based distributed RAM,
      not registers) appears in the same report — almost certainly the
      dead `rhd2164_sampling_cmd0-3` combinational taps forcing a small side
      copy of the table, since LSE doesn't optimize across the module
      boundary those ports sit on. Resolves itself once the A.1.4 deletion
      above lands; harmless in the meantime (no register cost).

      Not yet exercised on the bench — functional confirmation of
      `SET_CHANNELS`/channel selection round-trip (matching A.2) against
      this rewrite is still open.

      **Writes are left unrestricted** — no RTL write-protection on any word.
      Both the sampling table and the RHD config table are legitimately
      rewritable, so there is no clean read-only set to protect, and partial
      protection would give a false sense of safety. Keeping the regbank dumb and
      uniform is the deliberate choice. See the related B.5 known-open item on the
      absence of genuine read-only identity registers.

      Unlocks running this ladder as a `doctor`-style self-test on a built device
      (B.5 pre-session self-test / B.6 `doctor`), not only in simulation.
- [ ] **T3.3 Remove debug hijacks from product paths** — `serial_lvds_tx = spi0_csb`
      and `serial_lvds_rx` **declared as an output** (`kuntur_fpga.v:36-37`), which
      must be undone before bidirectional tunnel work · `assign cmd_is_00 = fifo_full`
      · `mode` hardwired `2'b00` with `mode1_*`/`mode2_*`/`mode3_*` declared and
      unwired · delete `old.v`.
- [x] **Guard the sim-only PLL bypass with `` `ifdef SIM ``** — raised 2026-08-10,
      **done 2026-08-11** (Manuel). Simulating used to require commenting out the
      `pll0` instance and enabling `assign clk = clkin` (`kuntur_fpga.v:101`) by
      hand, left in the working tree — one `git add -A` from becoming the
      bitstream, and a build with it would silently run the whole design at
      `clkin`. Both arms are now behind `` `ifdef SIM `` (bypass) / `` `else ``
      (`pll0`), with `+define+SIM` on `qrun.f`'s `lib1` makelib line only. The
      file is committable as-is, with no manual edit before or after a sim run —
      elimination rather than a rule to remember. Same hijack class as T3.3,
      which remains open.

      *Loose end, not blocking:* `qrun.f` also compiles `kuntur_fpga.v` a second
      time into `dutLib` **without** `+define+SIM`, so that copy carries the real
      `pll0`. Harmless today — `kuntur_tb.sv` `` `include ``s the design, so the
      whole thing lands in `lib1` and the run log confirms `lib1.kuntur_fpga` is
      what elaborates. But it leaves a duplicate module definition whose two
      copies now differ in their clock source, and if resolution ever picked
      `dutLib` the sim would instantiate a Lattice PLL primitive instead of the
      bypass. Either drop the `dutLib` makelib line or give it the same define.
- [x] **SPI0 opcode decode, 4-way** — landed 2026-08-06 with A.2.
      `main_controller` now decodes all four: `00` FIFO pop, `01` regbank write,
      `10` regbank read (new read path to the TX mux), `11` NOP. The paired
      MCU-side fix landed with it — `FPGA_STREAM_CMD` `0xA5A5` → `0x2525`, so a
      streaming FIFO pop no longer carries the `10` opcode by accident. Verified
      on hardware via the A.2 readback round-trip.
- [ ] **A.1.4 — Sampling-cycle placeholder command slot.** **Rewritten
      2026-08-11: mostly already done, and demoted from "enabler, do this
      first" to a small cleanup that gates nothing.** Fold the remnant into
      A.1.1e.

      The sampling counter's extra state beyond the 32 real per-module channels
      (33 states; `RB_SAMPLING_MAX = 6'd32` in `intan.vh` — the plan previously
      cited `components.v:855, sampling_max = 6'd32`, which predates the
      single-sourced map) is an intentional placeholder for an alternate
      RHD2164 command instead of a channel conversion. The datasheet recommends
      reserving 3 such slots; this design reduces that to 1.

      **It is already wired.** Verified by reading the RTL 2026-08-11:

      ```
      cnt0 = 32  →  rb_addr1 = RB_SAMPLING_BASE + 32 = ram[80]
                 →  regbank_dout1  →  rhd_dtx  →  spi1 MOSI
      ```

      `rb_addr1 = (rhd_dtx_sel) ? (RB_SAMPLING_BASE + cnt0) : (RB_CONFIG_BASE +
      cnt0)` already spans the full 0–32 range, and `ram[80]` is initialised to
      `RHD_READ(6'd63)` — a chip-ID read — labelled *"RHD2164 Sampling: cmd0"*
      (`components.v:600`). The slot fetches and transmits that command **every
      frame, today**. There is no consumer to wire.

      **A.1.1g deleted the reason for `rhd2164_sampling_cmd0-3`.** Those
      registers exist because the sampling table used to be unreachable and
      writes were 8-bit, so a full 16-bit RHD command needed a dedicated side
      channel. Now `ram[80]` is directly writable at full width. The four
      registers are **dead-end wires** — assigned from `ram`
      (`components.v:486-489`, words 192–195), routed to the top level,
      connected to nothing; `kuntur_fpga.v:76` declares only `cmd0-2`, so
      `cmd3` is not even connected at instantiation.

      What actually remains:

      - [ ] Confirm slot 32 → `ram[80]` → MOSI in simulation. The testbench
            already runs the sampling cycle; this is an assertion, not new
            stimulus.
      - [ ] **Delete `rhd2164_sampling_cmd0-3`** — module ports, top-level
            wires, and the `regbank` (renamed from `ram`, 2026-08-26 — see
            B.3) assigns. Frees words 192–195. Do it before someone wires
            something to them believing they are the intended path.
            **Now unblocked and worth prioritizing**: `kuntur_fpga.v` is
            no longer mid-edit for the item-4 placement work that
            deferred this during the 2026-08-26 session, and the
            `DPR16X4 × 16` residual noted in `regbank_macro`'s arearep
            (a small LUT-based side copy of the table, forced by these
            dead ports still being wired to top-level output) should
            disappear once this lands.
      - [ ] MCU helper `FPGA_SPI_SetSamplingCmd(uint16_t cmd)` →
            `reg_write16(80, cmd)`. One line on top of the A.1.1g rewrite.

      Address-space consequence: words 192–195 return to the free pool, and the
      *sampling table itself* is the runtime command-injection mechanism. The
      A.3 impedance-check DAC use case (`RHD_ZCHECK_DAC/SEL/EN`) is served the
      same way — write the command word into the placeholder slot — so no
      reserved address block is needed for it either.

      See `docs/interfaces/channel-selection-control-plane.md` section 1; that
      spec's register table still lists `rhd2164_sampling_cmd0-3` as reserved
      and must be updated when the wires are deleted.

*Already verified correct:* RHD init sequence — chip-ID read, regs 0–21,
`RHD_CALIBRATE`, then nine dummy reads as the datasheet requires.

## A.2 — Minimum control plane  *(Claude: MCU + app; Manuel: RTL side)*  — ✅ **COMPLETE, hardware-verified 2026-08-06**

Enough to choose which two channels to record — without it the animal test is stuck
with a hardcoded pair. Polished UI is Phase B.

- **Design:** `docs/interfaces/channel-selection-control-plane.md` — all three hops,
  plus sections 5.x for the STOP/SET/START sequencing and why it ended up that way.
- **Bring-up narrative — every bug, in the order it was found:** `log/2026-08-06.md`.

Final shape: `SET_CHANNELS` requires the stream to be explicitly stopped first, so
none of its SPI0/notify work ever interleaves with live streaming. One operator click
runs `STOP_STREAMING → SET_CHANNELS → readback verify → START_STREAMING`, each step
gated on a real MCU-confirmed ack rather than a settle timer. Three earlier attempts
to interleave the work with the live stream each failed differently; the fix was to
remove the need to interleave at all.

- [x] **Interface spec written before implementation** (2026-08-05) — covers all
      three hops. Surfaced a scope gap the original plan bullets missed: the pc-app
      cannot reach 0xFFF1 directly and must relay through the bridge, so this needed
      new bridge firmware, not just MCU + app.
- [x] **RTL** *(Manuel)* — `ch_a`/`ch_b` regbank endpoint · 4-way SPI0 opcode decode
      (`00` FIFO pop, `01` reg write, `10` reg read, `11` NOP) · `stream_enable` gate
      (regbank word **228** — was word 164 before the A.1.1g memory-map
      rearrangement, bit 0) ANDed directly into `fifo_wen` in `ch_sel`, reset
      default `1`.
- [x] **MCU** — 0xFFF1 handler for `SET_CHANNELS`/`STOP_STREAMING`/`START_STREAMING`,
      all SPI0 work deferred off the BLE event-handler callback ·
      `FPGA_SPI_{SetChannels,ReadChannels,SetStreamEnable,ReadStreamEnable}` ·
      0xFFF3 type-prefixed command-response notify, backed by an actual SPI0 readback
      rather than "the write call didn't error" · `s_command_busy` reentrancy guard
      making one STOP/SET/START cycle atomic with respect to the next · streaming
      dummy TX word `0xA5A5` → `0x2525`, so a FIFO pop can't decode as a reg read.
      **Rewritten 2026-08-11 for A.1.1g** (`fpga_spi.c`/`.h`, spec §1/§1a/§4.1):
      tagged 3-transfer writes to RAM words 196/197/228, self-addressing reads,
      `FPGA_SPI_Init()`'s priming transfer and all NOP padding deleted.
      **Builds clean** (2026-08-11, `Debug/make all` with the STM32CubeIDE
      toolchain — see CLAUDE.md; the earlier "no ARM toolchain available"
      caveat was wrong, the compiler was simply not on `PATH`). Still untested
      on hardware.
- [x] **Bridge** — UART command relay (`0xCC 0x33`) and response relay (`0xEE 0x11`) ·
      USART1 overrun-error flag now checked and cleared every ISR entry, with a log
      line. An uncleared ORE latched RXNE off permanently, silently killing command
      reception for the rest of the session.
- [x] **pc-app** — channel selector and ack-driven Apply orchestration, with
      verified/mismatch/timeout feedback · `COMMAND_GAP_MS` and `APPLY_COOLDOWN_MS`
      rate limiting.
- [x] **Host-side verification, no hardware** — channel encode/decode bijectivity over
      all 128 channels, SPI word bit-fields, pc-app→bridge wire framing over a real
      pty loopback, and the bridge RX parser fed the actual bytes captured from that
      loopback. All by compiling the real extracted source, not a reimplementation.
- [x] **Full round-trip verified on real hardware** — pc-app Apply → bridge relay →
      BLE 0xFFF1 → MCU → SPI0 `REG_WRITE` → RTL → SPI0 `REG_READ` → 0xFFF3 notify →
      bridge relay → "✓ Verified" in the pc-app, values matching exactly. Confirmed at
      the source on the MCU debug UART, not inferred from the UI. Supersedes the
      separate checks previously listed here for bridge 0xFFF1 handle discovery,
      `aci_gatt_clt_write_without_resp` status, and logic-analyzer inspection of the
      SPI0 waveform — all four hops are demonstrably working end to end.
- [x] **Reliability tested under repeat use** — single-click and moderate-repeat-click
      solid; the earlier rapid-click MCU crash/reset loop no longer reproduces after
      ack-driven sequencing plus rate limiting.
- [x] **Diagnostic scaffolding reverted** — bridge trace back off by default, pc-app
      debug prints removed. The fixes stay; the noise used to find them doesn't.

> **⚠ A.2 must be re-tested once A.1 lands.** A.1.1g changes the SPI0 wire
> protocol underneath this feature: register access becomes a tagged
> 3-transfer sequence, `REG_READ` becomes a single self-addressing transfer
> carrying tag 1 whose value lands on the *following* transfer, and
> `ch_a`/`ch_b` move from offsets 4/5 to RAM words 196/197. Every MCU helper
> A.2 depends on (`FPGA_SPI_SetChannels`, `SetStreamEnable`,
> `ReadStreamEnable`, `ReadChannels`) is rewritten as a result. The
> hardware-verified result above was obtained against the *old* protocol, so
> **"complete" here means complete-as-of-2026-08-06, not still-verified.**
> The full STOP → SET_CHANNELS → readback → START round-trip needs re-running
> on the bench after the new bitstream and firmware are flashed together —
> including the repeat-click reliability pass, since the transfer counts and
> FSM timing both change.
>
> **Sequencing, settled 2026-08-11.** "Update A.2, then continue A.1" is a false
> split: the A.2 helper rewrite **is** the A.1.1g MCU-side work — one change,
> not two. What actually gates what:
> - The moment a bitstream containing A.1.1g is flashed **for any reason**, the
>   MCU speaks the old protocol and A.2 is broken. So the firmware cannot lag
>   the bitstream by even one bench session.
> - The A.1.1 ladder needs a readout path for its numeric pass/fail. Rungs
>   (a)–(c) are *technically* observable on a logic analyzer at the RHD MISO
>   pins with no MCU involvement, but (d)–(f) and any repeatable check need the
>   FIFO→MCU→pc-app path — i.e. the rewritten helpers.
>
> Therefore: **do the MCU rewrite before any A.1.1 bench work**, and fold the
> A.2 re-test into the same bench session that starts the ladder rather than
> spending a separate one on it. Desk work that needs no bench and can run in
> parallel beforehand: the MCU helpers + spec §1/§1a/§4.1 (Claude, **done
> 2026-08-11**) and **A.1.1e + the A.1 structural fix** (Manuel) — the latter
> having replaced A.1.4 as the ladder's gate, see A.1.1's ordering note.
>
> **Latent failure found while doing the rewrite, 2026-08-11 — worth recording
> because it would have been misdiagnosed.** `FPGA_SPI_ReadSamples()` used to
> issue `2n` transfers and rely on a one-off priming transfer in
> `FPGA_SPI_Init()`, which left the running transfer count permanently odd —
> i.e. **every call ended with a `FIFO_POP` pair half-open**, dangling into
> whatever command came next. Harmless while nothing checked. Under the A.1.1g
> FSM, a POP whose partner is not a POP aborts *and consumes the offending
> transfer*, so `STOP_STREAMING`'s tag-1 write would have been silently eaten;
> tags 2 and 3 would then each abort on their own tag check, and **streaming
> would never stop** — presenting as the pc-app's existing "no confirmation
> received" timeout, indistinguishable from the known USART-overrun limitation.
> Fixed by making `ReadSamples()` self-contained: `2n+1` transfers with a
> trailing `NOP` carrier, no priming, no dangling pair. Costs ~5 µs per BLE
> packet (1 transfer in 119 at 59 pairs). `StreamFlushFpgaFifo()` was batched
> at 32 pairs per call to keep the amortised cost at ~2.03 transfers/pair
> rather than 3. **This changes the 30 kSPS hot path, whose NOP margins are
> empirically tuned — validate on the bench** (`FPGA_SPI_DebugDumpPairs(32,
> 1000)` over UART gives DUP/SKP/OFF directly; any `OFF` means the pairing
> offset is wrong).

**Known limitation, accepted** — not blocking Phase A:

- A command lost to a USART overrun has **no retry**. The pc-app times out and
  honestly reports failure, streaming keeps running, nothing gets stuck — but the
  operator has to notice and re-click. `COMMAND_GAP_MS = 15` cut the rate from
  ~2-in-8 cycles to roughly 1-in-many; it did not eliminate it.

Two lower-priority items surfaced by this work are tracked under B.5 known-open
issues rather than here: the bridge UART TX ring-buffer silent drop, and the
pc-app's inability to distinguish a busy-rejection from any other timeout.

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

> **Status 2026-08-27 (Sonnet session, same day as the handoff):**
> A.6.1/A.6.2/A.6.3 **done and verified** (A.6.2's DECISION 1 confirmed by
> Manuel — 0.195/37.4/74.8 µV per LSB, `pc-app/rhd2164_units.py`). A.6.4
> single-sourced (`packet_parser.is_fifo_underrun`) but its DECISION 2 is
> still open and its empirical measurement is blocked — no real (non-ramp)
> recording exists anywhere on this machine yet. **A.6.5's spec is fully
> agreed** (`docs/interfaces/recording-format.md`) after real back-and-forth
> that changed the design materially — see that spec and the updated B.5
> "SPS overshoot" item for what changed and why — but **implementation is
> still deliberately not started**: it needs both today's bench session
> (the connect flow and `csv_recorder.py` it touches) and Manuel's
> in-progress PLL retune/oscilloscope verification (the sidecar's
> `sample_rate` figure depends on the result) to close out first. Work
> done on branch `session-2026-08-27-a6`, per the working constraint below
> — not yet merged.
>
> **Handed to Sonnet 2026-08-27.** Scoped and sequenced by Opus in the same
> session; the intent is that this section is executable without re-deriving
> anything from the rest of the plan. Read this whole section before starting
> — the ordering exists because two items have a decision in front of them,
> and the traps below are the reason this was written out rather than just
> assigned.
>
> **Working constraint — the pc-app is the bench instrument, and there is a
> bench session on 2026-08-27.** `main_window.py`, `serial_reader.py` and
> `diagnostics.py` are all on the bench path (A.2 round-trip re-test + the
> A.1.1 ladder runner). Work on a branch; do **not** restructure the command
> or diagnostics path; keep every change additive and revertible until the
> bench session has run. A.6.1 is the sole exception — it is a strict
> robustness fix on that path and is safe to land first.
>
> **Three decisions gate parts of this work. None may be assumed.** They are
> called out inline as **DECISION** below. If Manuel has not answered one,
> do every other item and leave that one stated — do not pick a plausible
> value and proceed, because two of the three end up in published numbers.

### A.6.1 — Fix `serial_reader.py` crash on `num_pairs=0`  *(no decision, do first)*  ✅ **DONE 2026-08-27**

- [x] Found 2026-08-06 while testing the A.2 readback feature. The monotonicity
      clamp indexes the sample array unconditionally in the resync loop:
      `serial_reader.py:214` (`packet.timestamps_us[0]`) and `:221`
      (`packet.timestamps_us[-1]`). A header-only or malformed packet (empty
      sample array — `parse()` returns a valid `ParsedPacket` with
      `num_pairs = 0`, it does not reject it) raises `IndexError` and kills the
      reader thread. Never triggered by real firmware (always 59 pairs), but the
      parser should not crash on a malformed frame it cannot control.
      Fix in the reader, not by making `parse()` return `None` — a zero-pair
      packet is still a real packet whose `seq_num` must feed drop detection, and
      discarding it would corrupt the sequence-gap count.
      **Fixed:** guarded the whole monotonicity-clamp block on
      `len(packet.timestamps_us) > 0`; `_last_ts_us` is deliberately left
      unchanged on an empty packet rather than advanced to a fabricated value.
      **Verified two ways, not just read-through:** (1) mutation check — the
      exact pre-fix `IndexError` at `serial_reader.py:214` reproduces on demand
      by stashing the fix; (2) a real pty-loopback regression test,
      `pc-app/test_serial_reader.py`, drives the actual `SerialReader.run()`
      thread with real wire-framed packets (not a call into `parse()` directly,
      since the bug was in the reader's indexing, not the parser) — one case
      sandwiches a zero-pair frame between two real ones, one puts it first
      (before `_last_ts_us` is ever set). Signal-driven with a watchdog timeout
      rather than fixed sleeps after an earlier version proved flaky against
      real QThread scheduling. 5/5 clean runs; fails deterministically against
      the unfixed code. `QT_QPA_PLATFORM=offscreen python3 test_serial_reader.py`.

### A.6.2 — Display in physical units (µV)  *(DECISION 1 in front of it)*  ✅ **DONE 2026-08-27**

- [x] **Plotting raw int16 is not acceptable for a neural recorder.**
      `graph_widget.py:_build_ui` currently sets
      `plot.setLabel("left", "Signal", units="LSB")`; that axis must read µV.

      **DECISION 1 — the µV/LSB constant must come from the RHD2164 datasheet
      and be confirmed by Manuel. Do not take it from a model's recollection,
      and do not copy it from an Intan software package.** It is the scale
      factor under every amplitude number this instrument will ever publish;
      a wrong value is invisible on screen and silently wrong in a methods
      section. Working principle 3 applies directly. There is no RHD2164
      datasheet in either repo — ask Manuel for the number *and* the page.
      **Resolved 2026-08-27.** Located on Manuel's machine
      (`~/Downloads/Intan_RHD2000_series_datasheet.pdf` — the RHD2164-specific
      datasheet has no Electrical Characteristics table of its own, confirmed
      by search). Read the rendered page image directly, not `pdftotext` — the
      2026-08-24 session found `pdftotext` mis-tabling numeric values in this
      document family. Page 6, symbol `V_LSB`, three rows, all confirmed by
      Manuel and all now sourced in `pc-app/rhd2164_units.py`:
      **`AMPLIFIER_UV_PER_LSB = 0.195`** µV (referred to amplifier input — what
      CH0/CH1 are in normal operation), `AUX_ADC_UV_PER_LSB = 37.4` µV, and
      `SUPPLY_SENSE_UV_PER_LSB = 74.8` µV. The last cross-checks exactly
      against A.1.1f's independently-derived `VDD = 0.0000748 × result` note
      (0.0000748 V = 74.8 µV) — two independent sources agreeing.

      Two configuration facts already verified in the RTL, both load-bearing
      for this conversion (`kuntur` `source/impl_1/afe/rhd2164/rhd2164_defs.vh`):
      - **`RHD_TWOSCMP = 1'b1` (line 112)** — the chip is configured to emit
        **two's complement**, so interpreting the wire value as signed `int16`
        (which the whole pc-app already does) is correct, and `0x8000` really is
        the full-negative rail rather than mid-scale. Confirm this still holds
        before trusting the sign convention; if `RHD_TWOSCMP` ever goes to `0`
        the format becomes offset binary and every sample in the app is
        misinterpreted by 32768 counts.
      - **`RHD_DSPEN = 1'b0` (line 114)** — the on-chip DSP offset-removal
        high-pass filter is **disabled**. The signal therefore carries the
        amplifier's DC offset; a channel at rest will not sit near zero. This
        is why A.6.3 is a real task and not a cosmetic one.

      Keep the conversion in exactly one place with the constant named and its
      datasheet source cited in a comment. It is needed by the graph, by the
      sidecar (A.6.5) and by `analyze_recording.py`; three copies is how the
      sentinel rule below became wrong in three files at once.
      **Wired into `graph_widget.py`:** axis relabelled "Amplitude"/µV,
      `enableAutoSIPrefix(False)` on the left axis (values are already in µV;
      pyqtgraph's SI-prefix autoscaling assumes `units=` names a base unit and
      would otherwise re-prefix an already-scaled value), `_refresh()` now
      plots `counts_to_uv(ch0)`/`counts_to_uv(ch1)`. Verified end to end
      offscreen through the real widget, not just the conversion function in
      isolation: 1000 raw counts → 195.0 µV on the actual plotted curve data,
      underrun filtering still correct on the converted values.

### A.6.3 — Sensible amplitude ranges / autoscale  *(depends on A.6.2)*  ✅ **DONE 2026-08-27**

- [x] Do this **after** the µV conversion, not before — the ranges are only
      meaningful in physical units. Spikes are ~50–500 µV, LFP ~mV.
      Note the consequence of `RHD_DSPEN = 0` above: raw DC offset may be
      large compared to the signal, so a naive full-range autoscale will
      flatten the neural content against its own baseline. Whatever is done
      here, the graph must not silently hide saturation — a rail-to-rail
      channel and a quiet channel must look different.
      **Resolved 2026-08-27.** `enableAutoRange(axis="y")` was already enabled
      (pre-existing), and per-window min/max autorange is the correct strategy
      here — it tracks the *visible* signal's actual range rather than a fixed
      full-ADC-span display, which is exactly what avoids the DSPEN=0 DC-offset
      flattening risk. The only change needed was operating on physical (µV)
      values instead of raw counts, which A.6.2 already did. Verified through
      the real widget (forced layout + `updateAutoRange()`, since an
      offscreen/unshown widget never gets the resize event that normally
      triggers it): a flat/railed +32767-count channel settles at a
      non-degenerate range centred on the true rail (~6389–6390 µV, matching
      32767 × 0.195 µV); a single-sample window doesn't produce `NaN`; and a
      synthetic ~200 µV-std spike-scale signal settles the axis on roughly
      [-930, +765] µV — tracking the actual signal, not the ±6390 µV full ADC
      span. No saturation-highlight UI was added beyond this — that's a
      Phase-B polish decision (PLAN.md already scopes "polished UI is Phase
      B" elsewhere in A.2), not implied by this bullet's literal ask.

### A.6.4 — Underrun sentinel against real (non-ramp) data  *(DECISION 2)*

- [ ] The current rule — count an underrun only when **both** channels read
      `0x8000` — is implemented three times over:
      `packet_parser.py:25,73` · `graph_widget.py:62-65` ·
      `analyze_recording.py:23,54`. All three carry the same comment justifying
      it from the **ramp** test pattern (`ch1 = ch0 + 1000`, so ch0 alone can
      legitimately hit `-32768` while ch1 reads `-31768`).

      **That justification expired when A.1.1e connected real data (2026-08-11).**
      With real RHD2164 samples the two channels are independent, so:
      *both channels can legitimately rail simultaneously* (a genuinely saturated
      pair reads as an underrun and is silently dropped from the display), and
      *a real underrun is indistinguishable from that*. PLAN.md's A.1.1 spec note
      predicted exactly this: "`0x8000` is simultaneously the empty-FIFO sentinel
      and a legal full-negative-rail ADC sample once A.1.1e lands, so underrun
      statistics start counting saturated inputs."

      **DECISION 2 — this is a protocol question, not a pc-app question, and it
      belongs to Manuel.** The honest options, in rough order of cost:
      *(a)* accept the ambiguity and document it (cheapest, but the 1.7% underrun
      figure in B.5 stays uninterpretable against real signals);
      *(b)* have the FPGA/MCU carry underrun as out-of-band metadata — a count or
      a flag in the packet header — rather than in-band in the sample values,
      which is the only option that actually resolves it;
      *(c)* pick a sentinel that is not a reachable ADC code (there isn't one in
      a full-scale 16-bit two's-complement range, so this mostly doesn't work).
      Option (b) is an interface change touching RTL, MCU and the packet format,
      so it is a Phase-B-shaped decision surfacing in Phase A — flag it, do not
      start it.

      **What Sonnet should do now, without the decision:** do not change the rule.
      Instead make it *single-sourced* (import the one definition from
      `packet_parser.py` into the other two rather than restating it) so that
      whichever way the decision goes, it changes in one place. That is B.3's
      "single-source the underrun sentinel rule" item, and doing it here costs
      almost nothing and removes the tri-copy trap. Then verify empirically
      against a real (non-ramp) recording what the sentinel rate actually looks
      like now, and report the number — that measurement is what makes the
      decision above answerable.
      **Single-sourcing done 2026-08-27.** New `packet_parser.is_fifo_underrun(ch0,
      ch1)`, documented with both the rule and its known post-A.1.1e limitation
      inline so the ambiguity travels with the code, not just this plan.
      `graph_widget.py` and `analyze_recording.py` both now call it instead of
      restating the boolean-and; confirmed no other copy exists anywhere in
      `pc-app/` (`grep`'d for `32768`/`0x8000` across every `.py` file — the only
      other hits are diagnostic-message strings, not logic).
      **The empirical measurement could not be done** — checked every recording
      in `pc-app/recordings/` plus `~/Downloads/vega_*.csv`: all dated
      2026-07-24 through 2026-08-03, which predates A.1.1e (2026-08-11) by at
      least a week. There is no real (non-ramp) recording anywhere on this
      machine yet. DECISION 2 is still fully open; the first real recording
      from today's bench session (or any future one) is what unblocks this
      measurement — report the sentinel rate against whichever recording comes
      out of it first.

### A.6.5 — Recording metadata sidecar  *(DECISION 3 — spec first)*

- [ ] Minimum content: sample rate, gain / µV-per-LSB, channel map, filter
      settings, firmware + bitstream versions.

      **DECISION 3 — this is a new cross-boundary interface (the recording
      format), so per working principle 5 and the standing project rule it needs
      a spec in `docs/interfaces/` written before the implementation.** Write
      `docs/interfaces/recording-format.md` and get it agreed before touching
      `csv_recorder.py`. It should cover the sidecar's format, its filename
      relationship to the `.csv`, every field with units and provenance, and —
      explicitly — a **format version field**, whose absence B.2 already flags as
      blocking safe evolution once the format is public.

      **Trap, verified 2026-08-27 — there are two different sample-rate constants
      in this app and they disagree.** `packet_parser.py:22` has
      `SAMPLE_RATE_HZ = 30_000` (used to stamp per-sample timestamps) while
      `main_window.py:26` has `DELIVERED_SPS = 5_000` (used to size the graph
      buffer and window). These measure different things — sampled rate vs.
      currently-delivered rate — and both are arguably "the sample rate" to a
      naive reader. The sidecar must record the right one, say which it is, and
      ideally record both with distinct names. Also note B.5's open item that
      measured SPS overshoots to ~30,700–31,900 against the FPGA's nominal
      30,000, so the nominal figure is not a measurement and must not be written
      into a sidecar field that implies it was one.

      Firmware/bitstream versions are **not currently obtainable** — B.5's
      known-open list records that the FPGA regbank has no read-only identity
      registers and there is no version handshake (B.6). Do not invent a value or
      leave a field silently blank: spec the field, and have the writer record an
      explicit "unknown" until B.6 supplies it.

      **Spec fully agreed 2026-08-27** (`docs/interfaces/recording-format.md`)
      after a real design discussion with Manuel, not a rubber-stamp — three
      of his four objections changed the design materially:
      - **Filter settings, firmware/bitstream version must come from the
        actual hardware, not "unknown" placeholders.** Checked what's really
        available: RHD2164 filter registers (regs 4, 8–11, 12–13) are
        readable *today*, no new RTL/firmware, via the same `RHD_READ(n)`
        mechanism A.1.1 already proved on hardware — read once at connect
        (not per-recording) and cached, generalizing the same
        provenance-tagged pattern `channels` needed anyway (§2.1).
        Firmware/bitstream version genuinely aren't obtainable yet — tracked
        as new Phase B work against the existing B.5/B.6 items rather than
        left open-ended.
      - **`sample_rate` — the biggest change.** The original "nominal
        constant + measured_sps" design was wrong on two counts: the
        "nominal 30,000" framing itself doesn't match any real measurement
        on this project (see B.5's "SPS overshoot" item, reframed the same
        day), and `row_count/duration` wouldn't have revealed FIFO-underrun
        data loss anyway, since underrun samples are written as sentinel
        rows, not omitted. Replaced with the actual FPGA-derived rate
        (cycle-counted from RTL — see B.5), and reshaped `sample_rate` into
        a config-named object so a future per-mode lookup table (multi-
        channel modes, PLAN.md's roadmap) is additive, not a schema break.
      - **CSV needs its own version**, not just the JSON sidecar — a leading
        `# vega-recording-format-version: 1` comment line, versioned
        independently of the sidecar's `format_version` since the two
        schemas can change independently. Existing readers need dynamic
        `skiprows` detection so every pre-A.6.5 recording still parses.

      **Found while writing the spec, not previously tracked anywhere:**
      `main_window.py` has no persisted "last-verified" channel state.
      `_on_channels_readback` compares against `_pending_channels` to drive the
      `✓ Verified` UI label, then discards it — the only durable channel state
      is the spinbox value (what the operator last *typed*, not what was last
      *confirmed on the FPGA*), and `_btn_rec` enables purely on `connected`,
      independent of channel-apply state. The spec (§2.1) requires persisting
      that state, with a `provenance` field (`verified_readback` /
      `unverified_requested` / `unknown`) so the sidecar says which case it
      is rather than presenting an unverified value with false confidence.

      **Implementation still deliberately not started** — two independent
      reasons, both from Manuel 2026-08-27: the pc-app is on today's
      bench-session path (`main_window.py`'s connect flow and
      `csv_recorder.py` both need touching), and `sample_rate`'s exact
      figure depends on his in-progress PLL retune + oscilloscope
      verification (B.5). Starting now would mean redoing it once the PLL
      changes. Wait for both to close out.

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

- [ ] **RTL testbench coverage.** Recorded 2026-08-08 as a deliberate deferral,
      not an oversight: the Phase A testbenches (`kuntur_tb.v`) check basic
      functional behaviour only — they are bring-up aids, driven and read as
      waveforms, with no self-checking assertions and no coverage goal. That is
      the right trade while bench time is the constraint and the RTL is still
      moving. Phase B needs the other thing: self-checking testbenches with
      pass/fail output, coverage of the SPI0 command FSM's abort and desync
      paths (which is where A.1.1g's tag checks live and where a regression
      would be silent), an RHD2164 model that implements the two-command
      pipeline and the ROM registers rather than four canned values, a check
      that the pipelined `csb` (`docs/interfaces/fpga-timing-constraints.md`
      §6/§7 — landed 2026-08-24, only checked by STA so far, not simulation)
      asserts/deasserts on the same state-relative timing as before the
      pipelining, and these wired into the CI checks below so a red run
      blocks a merge.
- [x] **FPGA timing constraints + structural fix.** Raised 2026-08-11
      (Manuel's question). Spec: `docs/interfaces/fpga-timing-constraints.md`.
      **Status 2026-08-24: constraints landed, real violation found and
      root-caused (RHD2164 MISO capture path), fixed by pipelining
      `rx_a_en`/`rx_b_en` and (once that tightened `spi1_csb` to
      near-zero margin) `csb` too. Setup and hold both clean, 0 endpoints,
      0.000 ns negative slack, all corners, both before (spec §5.5) and
      after (spec §9) the chip0-placement fix landed. Manuel's simulation
      pass confirmed A.1.1's `SLOT_OFFSET = 3` slot-to-channel mapping held
      through the `rx_a_en`/`rx_b_en` pipelining.**
      **Update 2026-08-24, after the placement fix (spec §9.2): CSB's
      margin against the 1.5 ns board/cable *estimate* narrowed** — it
      moved from +1.563 ns to +1.462 ns (0°C) when the constraint set was
      re-run on the placement-pinned, fully-restored design. Still
      passing, still a small change (~0.1 ns), plausibly routing noise
      from the two newly-pinned regions. Two things worth being precise
      about here (Manuel, 2026-08-24): the 1.5 ns itself is an *estimate*,
      never a measurement (spec §3), so this isn't "CSB fell below a known
      real number" — the assumed number just got less headroom under it.
      And the `rx_a_en`/`rx_b_en`/`csb` pipelining fix bought structural
      margin against PCB delay by moving SPI1's outputs off combinational
      logic onto a direct register-to-pad path — that margin holds
      regardless of what the real board delay turns out to be. The other
      three signals (MISO×2, MOSI) all *improved* with pinning (spec
      §9.2).
      **Deliberate sequencing deviation:** the plan's original note said do
      the RTL fix *with* Phase B work, not before the remaining Phase A
      bench items, since it changes the bitstream the A.1.1 ladder was
      verified against. Manuel's call 2026-08-24: doing both together
      anyway ("we need to change the bitstream anyway"), rather than
      leaving a known-marginal RTL path in place through the rest of
      Phase A. Open (spec §7): a simulation check on the `csb` pipelining
      specifically (the `rx_a_en`/`rx_b_en` one already got that check,
      now folded into the RTL testbench coverage item above); re-running
      the A.1.1 bench ladder against the new bitstream. The board/cable
      delay estimates (1.5 ns) are staying as-is — resolving PCB delay at
      this timescale needs an oscilloscope sampling in the 10s of GSa/s,
      not equipment on hand, so this is an equipment ceiling rather than a
      priority call — but CSB's narrowed margin against that estimate
      (spec §9.2) is worth keeping in mind if real board numbers ever do
      become available.
- [x] **`spi0` and `rstb` false-path exceptions — landed 2026-08-26.**
      Both are asynchronous-exception cases, not missing clocks: `spi0`
      is architecturally async to `clk` (no sck-domain logic anywhere —
      `edge_detector` 2-flop synchronizer + one-cycle-late capture), so
      the fix is `set_false_path -from`/`-to` on its four ports, not
      `set_input_delay`; `rstb` is a single global async reset with no
      release synchronizer (~2747 endpoints), so `set_false_path -from`
      documents the exception but is a risk acceptance, not a fix — the
      robust version needs an RTL `rstb_sync` release synchronizer,
      tracked separately below. Full derivation:
      `docs/interfaces/fpga-timing-constraints.md` §10. Confirmed active
      in the 2026-08-26 STA run — constraint coverage rose from 92.19%
      to 96.4491%, matching exactly what closing this gap should do.
- [ ] **FPGA timing constraints — still-remaining pins.** Spec:
      `docs/interfaces/fpga-timing-constraints.md` §7, §10. SPI1
      (MISO/MOSI/CSB) and now `spi0`/`rstb` (above) are constrained.
      Still genuinely unconstrained, expected rather than a gap:
      `serial_lvds_tx`/`serial_lvds_rx`/`cmd_is_00` (uHDMI tunnel /
      debug, not yet built out — confirmed via the 2026-08-26 STA run's
      unconstrained-ports listing, alongside `spi2_miso0`/RHS2116).
      **New, not yet designed:** the `rstb_sync` release synchronizer
      that would make `rstb`'s false-path exception a real fix instead
      of a risk acceptance — this is real, tracked follow-up RTL work,
      not something the false-path exception substitutes for.

- [ ] **A.1.1 verification ladder — the simulation half.** Moved here from
      Phase A, 2026-08-11 (Manuel's call: Phase A is bench-only). Specified in
      `docs/interfaces/fpga-diagnostic-access.md` §6:
      - a behavioural **`rhd2164_bfm`** replacing `rhd2164_model`, which cycles
        two canned 4-word arrays and therefore cannot support *any* rung — it
        does not decode MOSI, has no register file, and has no response
        pipeline (§6.2);
      - assertions **T8–T14** (§6.3), of which **T12 is the one that carries
        weight**: the frame-boundary phase check for rung (d2), which no bench
        test can perform because a static known value that is one frame stale
        is the same value. Until T12 runs, rung (d)'s frame-boundary case is
        untested, not passed;
      - **T13** — that `data_source_sel` (word 229) actually selects, and that
        its reset default really is real-data;
      - the two-line fix to existing **T5**, whose `ChB - ChA == 1000`
        invariant holds only in test-pattern mode and which therefore starts
        failing the moment an A.1.1e bitstream exists. Expected, not a
        regression.
- [ ] **Make the RTL simulate under an open-source simulator.** Raised
      2026-08-11 and **not optional** — every item in the two bullets above
      depends on it. Today the design simulates only in QuestaSim: under iverilog
      (`-g2012`, compiles clean) time stops advancing at t=60 ns, right as
      `rhd_start` first pulses, and a bare probe with no testbench logic at all
      reproduces it. Three consequences, in increasing order of cost:
      1. **CI cannot run the testbenches.** "Wired into the CI checks below so
         a red run blocks a merge" is unimplementable on a licensed,
         GUI-oriented simulator. The self-checking testbench built in A.1.1g-tb
         is exactly the artifact CI should be running, and cannot.
      2. **Contributors cannot run them either.** This is the *same* barrier as
         the licensed Lattice tooling in B.6 — a contributor who cannot
         simulate cannot safely change RTL, so RTL contribution is closed to
         everyone without a Questa seat. B.6 calls the toolchain blocker "the
         worst OOBE blocker"; this is its twin and belongs in the same fix.
      3. **Claude cannot self-verify RTL work.** Testbench changes must be
         proposed blind and run by Manuel, which spends the scarce resource
         (bench/human time) on something a machine should catch.

      Approach, cheapest first: **root-cause the iverilog stall** — leading
      suspect is `rhd2164_controller` (`components.v:879`), whose hand-written
      sensitivity list `always@(current_state or rhd_done or cnt0_is_max)`
      drives `rhd_dtx_sel` → `max` → `cnt0_is_max`, feeding back into its own
      list. It *should* settle, since `rhd_dtx_sel` is a pure function of
      `current_state`, but `always@(*)` removes the question and is the right
      fix regardless of whether it is the culprit. Audit every hand-written
      sensitivity list in `components.v` / `spi_controllers.v` the same way.
      If that does not do it, evaluate **Verilator** (`--timing` handles the
      `#` delays in the testbenches; async-reset-in-sensitivity-list style is
      supported) as the CI simulator, keeping Questa as the waveform-debug
      tool rather than the gate. Either way the outcome required is: **a
      `make sim` that any contributor can run with no licensed software, and
      that CI runs on every push.**

      Note this is genuinely a *design* constraint, not just tooling: an RTL
      style that only one simulator accepts is a portability defect in the
      same class as relying on undefined behaviour. Fixing it improves the RTL.
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

- [x] **Split RTL — done 2026-08-26.** `components.v`/`spi_controllers.v`/
      `intan.vh` (three grab-bag files) split into `source/impl_1/`
      `common/` (`edge_detector`, `shift_registers`, `spi_slave`
      +`spi_slave_controller`, `spi_master`+`spi_master_controller_std`,
      `fifo`) · `afe/rhd2164/` (`rhd2164_controller`,
      `spi_master_rhd2164x2`+`spi_master_controller`, `rhd2164_defs.vh`)
      · `app/` (`ch_sel`, `main_controller`, `dtx_mux_reg`,
      `test_pattern_gen`, `fifo_din_mux`, `regbank` — renamed from `ram`,
      `regbank_map.vh`) · `tb/` (`kuntur_tb.sv`, `rhd2164_model` split
      into its own file). Layering decided by checked macro/coupling
      usage per module, not by guessing — e.g. `spi_master_rhd2164x2`
      lives in `afe/` not `common/` despite being structurally generic
      SPI, because its dual `rx_a_en`/`rx_b_en` capture path exists
      specifically for the RHD2164's DDR output; `regbank` lives in
      `app/` not `common/` because its `initial` block hardcodes the
      actual RHD2164 command sequence. Each file `` `include``s its own
      macro dependencies (guarded), rather than one top-level
      include-order chain. Deleted along the way: `old.v` (fully dead)
      and `spi_master_rhd2164` (the unused single-chip SPI master
      variant — confirmed zero references anywhere, including the
      testbench). Verified via full resynthesis: identical area/timing
      to before the move (see A.1.1g's regbank entry and the
      parametrization item below for the numbers). `kuntur` `af50765`,
      `09d81f1`, `5c1f24f`. See `log/2026-08-26.md`.
- [ ] **Decouple the AFE.** `ch_sel`'s ports (`data_a0/b0/a1/b1`) are shaped by "two
      RHD2164s with two outputs each" — AFE topology has leaked into application
      logic. Define a generic `{channel, sample, valid}` source. **Not done by
      the 2026-08-26 file split** — that moved `ch_sel` into `app/` (correctly,
      since it's still coupled) but didn't change its ports; this decoupling is
      still open.
- [x] **Parametrization review — done 2026-08-26.** Checked every module in
      the reorganized tree for whether its `parameter`s (or lack of them)
      were a good design choice — found four with false generality, two
      of them real bugs: `ch_sel`'s `n` didn't actually resize `ch0`/`ch1`
      (hardcoded `[15:0]`, silently mismatching `dout`'s `[2*n-1:0]` for
      any `n != 16`); `spi_master`/`spi_master_rhd2164x2`'s `n`/`m` didn't
      resize their FSMs (`spi_master_controller`/`_std` hand-unroll
      exactly 16 SCK states regardless of the parameter — real data
      corruption risk if ever overridden); `regbank`'s `DATA_WIDTH`/
      `ADDR_WIDTH` looked free but are pinned by unparametrized protocol
      assumptions in `main_controller.v`/`dtx_mux_reg.v`. Fixed all four
      by converting to `localparam` (kept in the `#(...)` header only
      because Verilog needs the value declared there before the port
      widths that use it) rather than rewriting the timing-critical,
      hardware-verified `spi_master_rhd2164x2` FSM to genuinely scale —
      that risked disturbing `fpga-timing-constraints.md`'s cycle-exact
      csb/rx_a_en/rx_b_en analysis for no present benefit. Deleted `m`
      (confirmed unused in both spi_master variants) and the now-illegal
      `#(...)` overrides at every instantiation site — all were restating
      the existing default anyway. Verified via full resynthesis + STA
      (twice — once via direct CLI, once by Manuel): area and timing
      identical to before every fix, 0 negative-slack endpoints all
      corners, constraint coverage 96.4491%. `kuntur` `20523a8`,
      `21a2f34`. See `log/2026-08-26.md`.
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
- [ ] **SPS overshoot — reframed 2026-08-27, in progress.** Raised while
      designing A.6.5's `sample_rate` sidecar field
      (`docs/interfaces/recording-format.md` §3). Cycle-counted the
      current RTL rather than relying on the measured-overshoot framing:
      `spi_master_rhd2164x2.v` (42 cycles/SPI1 transaction) +
      `rhd2164_controller.v`'s outer loop (+4 cycles) = 46 `clk`
      cycles/sampling slot × 33 slots/frame = 1,518 cycles/frame; at
      `clk = 44.549 MHz` (`pll0.ldc`, PLL `×71 ÷51` off 32 MHz `clkin`)
      that's 34.074 µs/frame → **≈29,348 SPS per channel, not 30,000** —
      a real ~2.2% shortfall from the PLL's clock choice, not a
      measurement artifact. Cross-validates to within 0.1% against
      2026-08-03's measured *production* (FPGA ground-truth) rate of
      29,350–29,390 SPS. The every-above-30,000 figures on record
      (05-04, 05-15, this item's own "~30,700–31,900") are all
      **delivered/BLE packet-rate** measurements (`pkt/s × 59`), a
      different quantity from production rate — working hypothesis, not
      yet confirmed, is that "overshoot" was a packet-rate-arithmetic
      artifact of bursty delivery rather than the chip genuinely
      producing samples faster than its own SPI clock permits.
      **Manuel, 2026-08-27: agrees with the derivation.** Next: (1)
      independent oscilloscope verification — output `spi1_csb` as a
      test signal and measure the real period directly; (2) adjust the
      PLL to actually hit 30,000 SPS, then re-verify; (3) once re-flashed,
      a fresh full-stream BLE-throughput measurement to confirm delivery
      still keeps up with the corrected (now genuinely 30,000) production
      rate — the 2026-08-03 result (506.0 pps × 59 ≈ 29,854 SPS
      delivered, matching the *old* ~29,348 production rate almost
      exactly) doesn't by itself prove BLE has headroom for the new,
      slightly higher target.
- [ ] **Bridge UART TX ring-buffer silent drop** — noticed 2026-08-06 while
      diagnosing the RX overrun; not yet confirmed to actually occur.
      `VEGA_UART_Write()` drops bytes that don't fit when the ring is full
      (`if (next == s_tail) break;`) with no log. That buffer carries continuous
      30 kSPS sample data *and* command responses, so a readback or ack could
      plausibly be dropped on the outgoing side even when every upstream hop
      worked. Instrument it if the residual A.2 "unsuccessful" rate turns out
      not to be fully explained by RX overruns.
- [ ] **FPGA regbank has no read-only registers** — raised 2026-08-07 while
      deciding A.1.1g. Every regbank word is writable and nothing identifies the
      device: there is no bitstream version, no fixed marker to validate SPI0 link
      integrity, no capability bits. The RHD2164 shows how useful this is — its
      Reg 59 A/B marker, Regs 40–44 `INTAN`, Reg 60 die revision, Reg 62 amp count
      and Reg 63 chip ID are exactly what the whole A.1.1 verification ladder is
      built on, and the FPGA offers no equivalent. Wanted: a small read-only block
      (bitstream version/ID, a fixed SPI0-link marker, capability bits) mirroring
      that pattern. **Phase B** — feeds B.6's `doctor` ("FPGA bitstream ✓ v1.2.0")
      and B.6's version/name handshake, and belongs in B.2's FPGA register-map
      interface spec. Not blocking A.1; A.1.1g deliberately ships with writes
      unrestricted.
      **Also needed by A.6.5** (confirmed with Manuel 2026-08-27): the recording
      metadata sidecar's `bitstream_version` field reads `"unknown"` until this
      lands — a hand-maintained version constant in a new read-only regbank
      word, same `initial`-block mechanism as the 2026-08-26 EBR rewrite. Checked
      2026-08-27 whether Lattice's `USERCODE` field could substitute instead:
      no — it's currently unused (`impl_1.xcf:33`,
      `VerifyUsercode value="FALSE"`) and is a JTAG-programmer feature in any
      case, not reachable over the SPI0 path the MCU actually uses.
- [ ] **pc-app can't distinguish a busy-rejection from any other timeout** — the
      MCU rejects (and logs) commands arriving while `s_command_busy` is held, but
      the pc-app only ever sees "no response within 2 s" and reports the same
      message for a rejection, a dropped command, and a disconnected bridge. Safe,
      just vaguer than it could be. Needs a rejection response on 0xFFF3 rather
      than silence, so the UI can say which one happened.
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
      **Also needed by A.6.5** (confirmed with Manuel 2026-08-27): the recording
      metadata sidecar's `firmware_version` field reads `"unknown"` until this
      exists. Checked 2026-08-27: no version constant is compiled into the MCU
      firmware anywhere (`grep`'d `App/*.c`/`.h` for `VERSION`/`__DATE__`/UID —
      nothing), and no existing command can fetch one. Needs a version constant
      plus a way to carry it back — piggyback on an existing 0xFFF3 response, or
      a new command.

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
