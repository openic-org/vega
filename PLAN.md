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

**Operating modes (agreed 2026-09-03, full table in
`docs/interfaces/stream-packet-format.md` §5.3):** every mode shares one
aggregate budget and one packet rate (474.6–476.7 pkt/s, a 0.45% spread),
so `μ_low` measured once covers all of them. `mode_id` 0 stays reserved
for *unknown*; modes are numbered **1–10**. **Mode 1 alone is needed for
the animal test; Modes 1–5 for public release; 6–10 are future versions.**

| Mode | N | F | k | SPS/ch | bits | needed for |
|---|---|---|---|---|---|---|
| **1** | 2 | 28k | 1 | **28,000** | 16 | **animal test** |
| 2 | 4 | 28k | 2 | 14,000 | 16 | public release |
| 3 | 8 | 28k | 4 | 7,000 | 16 | public release |
| 4 | 16 | 28k | 8 | 3,500 | 16 | public release |
| 5 | 32 | 28k | 16 | 1,750 | 16 | public release |
| 6 | 3 | 25k | 1 | 25,000 | 12 | future |
| 7 | 6 | 25k | 2 | 12,500 | 12 | future |
| 8 | 12 | 25k | 4 | 6,250 | 12 | future |
| 9 | 72 | 25k | 24 | 1,041.67 | 12 | future |
| 10 | 128 | — | — | spike times only | — | future, needs spike-detection RTL |

**Two frame rates, and no third clock anywhere in the system.** The
16-bit family runs off F = 28,000 (`clk` = 42.504 MHz, A.7 step 3a) with a
power-of-two decimation counter, k = 1…16; the 12-bit family off
F = 25,000 (`clk` = 37.95 MHz — an *exact* PLL solution, already specified
as the A.4 wired-mode bring-up rate). Because the RHD2164 pair converts
all 128 channels every frame, **k must be an integer** or samples are
non-uniformly spaced; that constraint plus the aggregate budget is what
picks these two rates. The 16-bit family extends free to 64 ch @ 875 SPS
and 128 ch @ 437.5 SPS.

Modes 3–5 are **corrected** from the first proposal (7,500 / 3,750 /
1,875): those sat at a 60,000 aggregate — the pre-A.7 budget — giving
`m` = −1.78%, numerically the same ρ > 1 failure A.7 step 3a just fixed.
Runtime switching between the two families needs the spare PLL (1 of 2
used) and the DCS (0 of 1 used); Modes 1–5 all share F = 28,000, so no
switching is needed until Mode 6.

**Out (documented explicitly as unsupported):**

- Stimulation (RHS2116 / `stim16ch`) — later version
- Android app — archived
- Coin-cell operation — later; likely a different operating mode
- >2 channel modes (4ch@15k, 8ch@7.5k, …) — roadmap; architecture must not preclude
- **Transparent SPI bridge to the Intan controller** (Intan as sole SPI master,
  Kuntur relaying the RHD2164 bus over LVDS) — **roadmap, deferred 2026-09-03 on
  scope grounds, not technical ones.** It is feasible: one master means no bus
  contention, and the round trip (~0.3–0.7 µs) fits inside the RHD2164's
  2-command pipeline budget (~1.3 µs). But it belongs to a *different product
  configuration* — a wired-only headstage with no wireless mode. Building it
  here would mean creating a second architecture in order to verify the first.
  Manuel: *"It is definitely worth doing but not as part of this project: it
  adds complexity for a goal that is different than the verification that it
  needs to be."* Full consequence analysis in
  `docs/interfaces/lvds-tunnel.md` §2.1 Case B — notably that it would make
  cable loss fatal to the wireless recording and put commands on a path too
  tight for a store-and-forward CRC.
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

| ID | Milestone | Status |
|---|---|---|
| **A1** | Real RHD2164 signal on the bench, end-to-end to the pc-app (injected) | **DONE 2026-08-31.** Full A.1.1 ladder (`L`,`O`,`a`,`b`,`c`,`d`,`f`) passed clean on real hardware, including `A.1.1f`'s VDD/2 analog reading (≈3.27 V @ 3.3V rail). See A.1.1's closing note and the 2026-08-31 critical-path entries below for the (unrelated) chip0 regression this bench session also had to work through first. |
| **A2** | Dual-path validated — Kuntur wireless and Intan controller agree, bench | Blocked on A.4 RTL and A.3 (injection rig). **A.4's spec is complete and all its desk-side gates closed 2026-09-03** — the boards have arrived, the pinout is resolved both ends, and the remaining work is RTL and a pigtail. |
| **A3** | **In-vivo animal recording** | |

### Current critical path — ordered, 2026-09-04

Sections below are not in execution order (A.6 and A.7 run parallel to
A.3–A.5). This is the order that actually matters:

0. **chip0's intermittency — characterise it before trusting any other
   bench result.** *(Manuel, bench — see A.1.2)* **Newly first, 2026-09-04.**
   chip0 failed twice on a cold board and then recovered untouched hours
   later; the failure drifts over hours and is not latched at boot. Until
   the pass rate and its driver are known, **no bench result on this board
   can be scored**, because a change that "fixes" chip0 is
   indistinguishable from a warm board — which is how three previous root
   causes came to be confirmed by a single pass each. Cheapest-decisive
   first: reproduce with freeze spray, then halve `clk` while cold to
   separate hold from setup, then pass rate versus temperature. Nothing
   here needs a scope. **This gates item 1's validation, not item 1's
   execution** — the reflash can proceed, but its result cannot be
   believed until this is characterised.
1. **One FPGA rebuild + reflash, carrying two committed-but-unapplied
   changes.** *(Manuel, bench)* Both are specified, committed and
   verified on paper; neither is on hardware. They are gated on the same
   session, so do them together and validate both at once:
   - **PLL retune to `CLKOP` = 42.504 MHz** → λ = 28,000.01 SPS/ch
     (A.7 step 3a). Today's shipped 30,000 puts ρ = 1.018 and discards
     **1.78% of every sample, silently**, after ~12 s of streaming.
   - **fH 20 kHz → 7.5 kHz** (`kuntur` `6563edc`). fH sat at the chip
     maximum, whose Nyquist is 40 kSPS — **every recording this project
     has made was aliased**.
   - ~~Fold in the **`324a21c` re-confirmation** carried since
     2026-08-31~~ — **superseded 2026-09-04.** This was framed as
     settling whether `324a21c`'s bitstream is good. A.1.2 shows the
     question was malformed: `324a21c`'s bitstream both failed and worked
     on the same day with nothing changed, so no single ladder run can
     settle it, and neither could the ones that produced the conflicting
     records. Re-confirmation is now item 0's job, and any `kuntur` `main`
     fast-forward waits on it.
   - **Caution on the PLL retune** *(added 2026-09-04)*: it was expected
     to help chip0 by relaxing SCK from 22.770 to 21.252 MHz. If A.1.2's
     failure turns out to be hold-type, that expectation is wrong and
     frequency-independent — do not read a chip0 pass after the retune as
     evidence the retune helped.
2. **A.7 step 1 — `fifo0` overflow counter + high-water mark as read-only
   regbank words.** *(Manuel, RTL)* **Now the highest-value single item
   in the plan.** A.7 step 3a set λ from measurement, but *cannot confirm
   it*: FPGA-side overflow is invisible downstream, because discarded
   samples never appear and real analog data gives no way to spot the
   gap. This counter is the only thing that can turn "we believe it is
   lossless" into evidence — which is exactly what a one-shot animal
   recording needs. Smallest change in the plan, largest information
   gain. Also retires T3.3's `cmd_is_00 = fifo_full` debug hijack.
3. **A.7 step 2 — telemetry frame end to end.** ✅ **Code complete
   2026-09-04** *(Claude: MCU + bridge + pc-app)* — `0xFFF4`
   characteristic, bridge discovery + fourth CCCD, `0xDD 0x22`
   re-framing, `serial_reader.py` decode, pc-app attribution panel, plus
   the MCU's `ring_truncated_samples` and `stall_time_ms_total`. Both
   firmwares build clean; desk tests pass. **What remains is bench
   bring-up, and it folds into item 1's session:** the bridge connection
   sequence now writes a fourth CCCD and nothing desk-side can exercise
   it. Bring it up against an already-streaming headstage so a telemetry
   failure is unambiguous. Until item 2's RTL lands, every frame carries
   `fpga_counters_valid = 0` by design — *absent*, not *clean*.
4. **A.4 RTL — fully unblocked, nothing desk-side gates it.**
   `docs/interfaces/lvds-tunnel.md` is complete on both ends of the cable;
   O1 and O2 are closed. Order per its §12: `.pdc` `IO_TYPE=LVDS` + PAR
   margin check (also O3's cheapest checkpoint) → pigtail → physical layer
   alone at 85.008 Mbps → `SAMPLE` frames + CRC → link-loss behaviour →
   emulator → Intan controller = **A2**. *(Manuel RTL both ends; Claude
   available for O2a and the companion diagnostics console, O8.)*
5. **A.3 attenuation network** — independent of everything above, and the
   noise-floor headline number cannot be measured without it. *(Manuel)*
6. A.4 RTL (both ends) → A.3 dual-endpoint capture → **A2** → **A3**.

**Closed 2026-09-03 and no longer on the critical path:** A.4's interface
spec (item 5 of the 2026-08-31 list), its open items O1 and O2, A.5 (now
discharged by construction — see below), and A.7 step 3's measurement
half.

**REOPENED 2026-09-04 — chip0 is intermittent, and all three of its
previous root causes are unsupported. See A.1.2 below.** This is now the
most serious open item in Phase A: it is an experiment-integrity risk,
not a bench annoyance, and it invalidates the evidence behind three
closures. The standing rule still applies to any deskew attempt — (a) add
any constraint alongside `mregion0`-`mregion7`, never by removing them,
and (b) measure rather than guess a phase — but the first task is no
longer a fix, it is a **measurement of the failure's own behaviour**.

**Repo state.** `vega` `main` is current. **`kuntur` is on
`session-2026-08-31-checkpoint` (now `7e1f8a5`), not `main`** — `main`
remains deliberately parked at `e2bac25` until the SCK/MOSI question is
settled, so today's fH change was merged to the checkpoint branch rather
than fast-forwarding `main`. Three harmless comment-only commits sit on
old `main`, safe to fast-forward onto whenever.

**Live external gate: NONE, as of 2026-09-04.** A.0's animal-protocol
amendment — carried since 2026-08-05 and the last item on the plan whose
timing the project did not control — **closed: no amendment is needed.**
Every remaining Phase A item is internal bench, RTL or desk work.

**Schedule risk, CLOSED 2026-09-02:** the LIFCL-40-EVN and IAM FMC
breakout **have arrived**, and as of 2026-09-03 nothing desk-side gates
A.4 RTL — see item 4.

**A documentation-structure weakness worth fixing (B.1).** Three times on
2026-09-03 a figure that had been correct for months quietly stopped
being correct, all descending from λ: the 60,000 aggregate in the mode
proposal (which would have reintroduced ρ > 1 in Modes 3–5), the
120,000 B/s / 512 pkt/s pair in `stream-packet-format.md` §3's header
budget, and the 19.9 h `sample_index` wrap. None were flagged by
anything, because nothing links a derived figure back to its input. Mark
derived numbers with their source (e.g. *"= f(λ)"*) so a future λ change
has a greppable blast radius.

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
      a new device — communicated to collaborator 2026-08-05. **CLOSED
      2026-09-04: no amendment is needed** (collaborator's determination,
      relayed by Manuel). This was the plan's only live external gate and
      the only Phase A item whose schedule was outside the project's
      control; A2/A3 are now gated purely on internal work.
      *(The determination's reasoning is not recorded here — worth capturing
      one line of it if the collaborator stated one, since "no amendment
      needed" is the kind of finding a reviewer may later ask the basis
      for.)*

## A.1 — Make the signal real  → **A1**  *(Manuel, RTL)*

- [x] **The FPGA has never sent neural data.** ✅ **DONE 2026-08-11**, discharged
      by A.1.1e below — rungs (a)–(d) pass on chip1, which is only possible with
      real RHD data reaching the FIFO. Re-confirmed on hardware 2026-08-27 after
      the chip0 placement fix: both friendly 42 (chip0) and 88 (chip1) streaming
      real, varying data. *(Checkbox was stale until 2026-08-28.)* Original text:
      In `ch_sel` (`components.v`),
      `data0_synced`/`data1_synced` are computed from the RHD2164s and then
      discarded: `assign dout = {ch0, ch1}` where `ch0 = cnt0` (ramp),
      `ch1 = cnt0 + 1000`. The real path is commented out. **Every metric in the
      entire SKP/throughput investigation measured a synthetic ramp** — the
      transport is well validated, the instrument is not.
- [x] **Fix structurally, not tactically.** ✅ **DONE 2026-08-11** in the same pass
      as A.1.1e, as specified. Test-pattern generation lives in its own module
      (`test_pattern_gen0`) and is muxed at the **top level**, selected by regbank
      word **229** bits `[1:0]` — `0` = real RHD data = reset default, `1` = ramp.
      A runtime word rather than a `` `define ``, so B.5's pre-session self-test
      and B.6's `doctor` can push a known pattern through the real path on an
      assembled device that will not be re-synthesised. *(Checkbox was stale until
      2026-08-28.)* Original intent: extract test-pattern generation into its own
      module; mux at the top level behind an obvious named signal, so "am I
      streaming real data?" is answerable from the top file. The bug existed
      *because* test pattern and real path shared a module with no visible mux.

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
- [x] **A.1.1f — ADC path.** Enable VDD sense, convert channel 48 on module A,
      expect ≈44,100 at 3.3 V. First real analog value end to end.
      **Implemented 2026-08-31** (`pc-app/diagnostics.py` `RUNG_F`,
      spec `fpga-diagnostic-access.md` §5.6) — no RTL change needed after
      all: `RHD_VDD_SENSE_ENABLE` only reaches the chip via `WRITE(1,
      RHD_REG1)`, which since A.1.1g is an ordinary regbank word, so it is
      set the same command-injection way rungs (a)-(d) already inject
      `READ`s. Offline-verified against a `FakeReader` extended to model
      `WRITE`'s echo response. **Bench-verified 2026-08-31**: WRITE(1) echo
      exact (`0xFF42`/`0x0004` chip-ID companion), analog reading
      `0xAACF` = 43,727 → `VDD = 0.0000748 × 43,727 ≈ 3.27 V` against a
      3.3 V rail — real, sane, first analog value this project has ever
      streamed end to end.

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
- [x] **Bench run** — **done 2026-08-31**: full ladder (`L`,`O`,`a`,`b`,`c`,`d`,`f`)
      run against real hardware, all passed. Ran on the `session-2026-08-31-checkpoint`
      branch (`kuntur` `e89671d`) after reverting a same-day chip0/SCK-MOSI
      regression — see the critical-path entry above and the new
      "2026-08-31 checkpoint revert" note near B.5. **Phase A is bench-only**
      (decided 2026-08-11); see B.1 for the simulation half.

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

- [x] **A.1.1g — Widen regbank access so any word is MCU-readable/writable at
      runtime.** ✅ **DONE, hardware-verified 2026-08-27.** *(Checkbox was stale
      until 2026-08-28.)* RTL landed and verified in simulation 2026-08-11
      (A.1.1g-tb, 27/27 checks); the MCU-side rewrite (`fpga_spi.c`, tagged
      3-transfer writes, self-addressing reads) built clean the same day, and was
      confirmed on hardware 2026-08-27 — post-reflash round trip
      `STOP_STREAMING` → `SET_CHANNELS(42,88)` → exact readback →
      `REG_READ16(196)`/`REG_READ16(197)` both returning exactly what was written
      → `START_STREAMING`, all acked. *Historical status 2026-08-11: RTL landed
      and verified in simulation; the MCU-side rewrite under "MCU-side impact"
      below was the blocking item, since the new bitstream could not be flashed
      without it without breaking A.2's round-trip.*
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
      - [x] `rhd2164_sampling_cmd0-3` deletion (A.1.4, words 192–195) —
            deliberately **not** done in this pass, since it needs
            `kuntur_fpga.v` port-list changes and that file was mid-edit for
            the item-4 placement work below at the time.
            ✅ **Landed 2026-08-27** (`kuntur` `e89671d`), bundled into the
            PLL-retune resynthesis as planned; confirmed by the area report
            (SLICE/LUT 645/641 → 595/543, `DPR16X4 × 16` residual gone) and
            zero remaining references in `kuntur_fpga.v`. *(Checkbox was stale
            until 2026-08-28.)*

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
      - [x] **Delete `rhd2164_sampling_cmd0-3`** — module ports, top-level
            wires, and the `regbank` (renamed from `ram`, 2026-08-26 — see
            B.3) assigns. Frees words 192–195.
            **Done, 2026-08-27** (landed in the same pass as the chip0
            placement fix, `kuntur` `e89671d`) — confirmed zero
            references left in `kuntur_fpga.v` (only an explanatory
            comment survives in `regbank.v`), and the `DPR16X4 × 16`
            residual noted in every area report since 2026-08-26 is
            gone from the fresh `arearep`.
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

### A.1.2 — chip0 is intermittent on a timescale of hours  *(Manuel, bench — REOPENED 2026-09-04)*

**The single most serious open item in Phase A.** Not because a channel
is missing today, but because it means **the project cannot currently
tell whether chip0 works**, and a one-shot animal recording could come
back with one channel of two and no indication anything was wrong.

#### What was observed, 2026-09-04

1. Loaded the previously-committed bitstream (`324a21c`,
   SHA-256 `7a5418d6…`). chip0 gave **all `0xFFFF`** — the signature
   Manuel recognises as the SCK/MOSI timing failure. chip1 fine.
2. Rebuilt from source and reflashed. Same result, minutes later.
3. System left powered and **completely untouched** for several hours
   (meetings, lunch). On return, **both chips responding.** No power
   cycle, no reconfiguration, no command.
4. Manuel: this is not new — a bitstream that had been working has failed
   on a later reload before, **on occasions spanning days and weeks.**

#### What follows, and what does not

**Established by (1)–(3) alone**, without relying on any earlier
recollection:

- The failure is **not deterministic in the bitstream.** Two different
  bitstreams failed and one of them later worked untouched.
- It is **not latched at initialisation.** Step 3 recovered with no
  re-init of any kind, which refutes the "all-or-nothing per boot" reading
  the same day's earlier evidence had supported.
- It **drifts on a timescale of hours** in a powered, idle system.

**Hypothesis, well-supported but not yet measured: temperature.** The only
variable known to change over hours of idle powered operation is the
board warming. It matches Manuel's own independent impression that cold
and warm days differ. *Not established:* there are no logged temperatures,
and the diurnal "evening warm / morning cold" story that appeared briefly
in this session's discussion was an over-reading of a figure of speech
and has been withdrawn. The direction — warm works, cold fails — rests on
step 3 plus that impression, and wants confirming before anything is
built on it.

#### This invalidates three closures

chip0 has been root-caused three times, and **every one was confirmed by a
single pass**: unconstrained placement (2026-08-24), the SCK/MOSI
regression (2026-08-31, closed by reverting to passthrough), and this
session's initial suspicion of `324a21c`'s `clk90`/PLL retune.

On a system that is intermittent over hours, a single pass is not evidence
of a fix — it is one sample from a process that produces passes and
failures regardless of what was changed. Worse, the debugging loop had a
**systematic bias toward false confirmation**: change RTL on a cold board
in the morning → observe failure → debug for hours while the board warms
→ observe the "fix" working. That sequence manufactures a convincing
causal story for whatever happened to be changed that day.

Point (4) sharpens this: if the phenomenon spans weeks, it was present
before, during and after all three episodes — exactly what would be
expected if none of them addressed it.

**Consequence for the record:** `324a21c`'s commit message ("Bench-verified:
both chips responding") and PLAN.md's note that its re-confirmation was
still outstanding were **never in conflict.** They are two honest reports
of two different boots. The contradiction was the evidence talking, and it
was read as a bookkeeping error.

#### Correction to a claim made earlier the same day

Slowing the clock was proposed here as likely to help chip0, on the
grounds that λ = 28,000's `clk` = 42.504 MHz gives SCK = 21.252 MHz
against the failing build's 22.770 MHz (SCK = `clk`/2 exactly — the SPI
controller is a hand-unrolled FSM with two `clk` states per SCK half
period, no divider).

**If the temperature direction is warm-works / cold-fails, that reasoning
is probably wrong.** Colder silicon is faster, so a failure that appears
as delays *shorten* is a **hold** violation, and hold violations are
frequency-independent: stretching the period does not change how long
data remains valid after an edge. If this is hold, 42.504 MHz will not
help, and neither would 20 MHz.

It also means 2026-08-31's four-phase deskew sweep may have been pushing
the right signal in the wrong direction — the remedy for hold is *more*
delay on MOSI relative to SCK, not less.

#### The next work is measurement, not a fix

Ordered cheapest-decisive first. None of it needs a scope.

- [ ] **Reproduce on demand with freeze spray.** If cold is the trigger,
      this converts an intermittent ghost into a debuggable fault — which
      is the single thing that has been missing from every previous
      attempt. Chill chip0 and its SCK/MOSI traces and expect dropout.
      **Everything below is far cheaper once this works.**
- [ ] **Halve `clk` while cold.** Not a 5% trim — half. If chip0 still
      fails, the failure is hold-type and frequency is permanently off the
      table as a remedy. If it recovers, it is setup after all. One PLL
      change, and it discriminates cleanly between the two families of fix.
- [ ] **Pass rate versus temperature.** Ten cold power cycles with ambient
      logged, then ten warm. This is the margin measurement the standing
      rule has been asking for, obtainable without the 10s-of-GSa/s scope
      that blocked the 2026-08-24 measurement.
- [ ] **Re-examine the three closures** against whatever the above shows.
      `docs/interfaces/fpga-rhd2164-chip0-placement.md` and
      `fpga-timing-constraints.md` both record ruled-out hypotheses that
      were ruled out *by single observations* and may need re-testing.

#### Consequences elsewhere

- **Animal test protocol.** A cold start in a surgical suite can yield a
  one-shot recording with one channel of two. Until this is closed, a
  warm-up-and-verify step before the subject is anaesthetised is
  **mandatory**, and it belongs in A.0's checklist rather than in
  somebody's memory.
- **Pre-session self-test** (B.5, "boot/startup process hardening") is
  promoted from nice-to-have: it must be **re-runnable at session start**,
  not boot-only, because the state changes while powered.
- **Every past bench result on this board is weaker than recorded**,
  including any that happened to be taken while chip0 was healthy. The
  22.8-minute recording behind λ = 28,000 is not invalidated — μ and λ are
  transport measurements, independent of which RHD channels are live — but
  results that depended on *both* chips responding should be re-checked
  against the temperature question before being relied on.

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

- [x] **Interface spec, written before implementation** — framing, clocking,
      link-loss detection, latency budget, **CRC**. ✅ **DRAFTED 2026-09-02**:
      `docs/interfaces/lvds-tunnel.md`. Every physical-layer number in it is
      read out of the shipped PCB (`kuntur144-ecl.kicad_pcb`,
      `kuntur144-omnetics.kicad_pcb`) and a real Radiant build
      (`kuntur_fpga_impl_1.pad`/`.mrp`), not from datasheet recollection.
      Headline findings:
      - **Only two differential pairs reach the uHDMI** — `FPGA_LVDS1`
        (G9/F9 = `PB18A/B`) and `FPGA_LVDS2` (E9/E8 = `PB16A/B`). HDMI's
        third pair (`D0±`, J1 pads 9/11) is present on the connector but
        **unrouted on this board**. So there is no spare clock pair: one
        pair per direction, each self-timed, and the receiver recovers
        timing from the data. Every framing/coding decision follows from
        this one fact.
      - Both pairs are **bottom-bank (bank 5)**, and true `LVDS_OUT` there
        is *demonstrated* rather than inferred — `spi2_csb` (G5, `PB30A`)
        and `spi2_sck` (F7, `PB26A`) already build as `LVDS_OUT` with
        `DIFFDRIVE:3.5` on this exact device, package and speed grade.
      - **The TX/RX pair assignment must swap.** G9/F9 is the primary-clock
        input pair (`PCLKT5_0`/`PCLKC5_0`); today's `TEST ONLY` passthrough
        puts TX on it and RX on the pair that has no clock capability —
        backwards. Costs nothing (the pigtail is hand-made, so no PCB
        change), but must happen **before the pigtail is soldered**.
      - Resource headroom confirmed: **1 of 2 PLLs free**, 0 of 102
        IDDR/ODDR primitives used, 4% logic — but **PIOs at 31/39**, going
        to 33/39 once both pairs are promoted to differential.
      - Rate: 128 ch × 29,999.97 SPS × 16 bit = **61.44 Mbit/s**; with
        framing and CRC-32, 64.32 Mbit/s; 8b/10b → 80.4 Mbit/s minimum
        line rate. Recommended `clk`/2 = **227.7 Mbps** (759 symbol slots
        per sampling frame exactly, 35% utilisation), `clk`/3 as fallback.
        `clk`/4 is disqualified structurally: 1518 = 2·3·11·23, so it
        cannot give a whole number of symbol slots per frame.
      - The 29,999.97 Hz frame rate is re-derived here independently
        (45,539,955 / 1518 clk, where 1518 = 33 slots × 46 clk) and agrees
        exactly with A.6.5's recorded `sample_rate.channel_hz`.
- [ ] Kuntur-side serialiser/deserialiser — unblocked (boards arrived).
      **Spec item O2 resolved 2026-09-02** against the installed Radiant
      2025.2.1 LIFCL primitive library: `ODDRX5`/`IDDRX5` are **hardened
      10:1** gearing (`D0..D9`, `SCLK` = `ECLK`/5), so one 8b/10b symbol
      maps to exactly one word and one `SCLK` cycle — no fabric gearbox,
      no 8→10 rate conversion. `IDDRX5.ALIGNWD` does comma alignment as a
      hardware barrel shift. The line rate lands on **exact integer
      dividers off `pll0`'s existing VCO** (`FVCO` = 1593.898438 MHz):
      `clk` = /35, `ECLK` = /21 (75.8999256 MHz, DDR → 151.799851 Mbps),
      `SCLK` = /105 (15.1799851 MHz) — a 3:5:1 ratio, all legal against
      the PLL IP's own `PARAM_RANGE` (`O_DIV` ≤ 128, `FVCO` 800–1600,
      `FOUT_F` ≤ 800), using two of `pll0`'s four spare outputs. So the
      second PLL stays free and there is **no clock-domain crossing**
      between the sampling and tunnel domains.
      **Superseded 2026-09-03 by decision 4** — see below. The rate
      question (227.7 → 151.8 Mbps, argued on switching noise beside a
      µV-scale AFE) is moot: with the line code gone the link runs at
      **91.08 Mbps**, `ECLK` = `clk` itself, and 10:1 gearing is replaced
      by `ODDRX4`'s 8:1, one byte per word. Remaining gate is O1 only.
- [ ] Companion FPGA RTL: deserialise, reassemble SPI, drive the Intan controller

## A.5 — RHD2164 bus arbitration  *(joint design)*  — ✅ **DISCHARGED BY CONSTRUCTION 2026-09-02**

Two masters want the AFE. If the Intan controller reconfigures gain/bandwidth
mid-session, **the BLE recording silently changes meaning and the file has no record
of it.**

**Resolved by A.4's ownership decision (Manuel, 2026-09-02), not by building
an arbiter.** The Intan controller is a *visualiser of the data the Kuntur
FPGA gets*; Kuntur owns AFE configuration exclusively and replicates its real
register state downstream, so the Intan controller's reads return live truth
rather than an echo of its own writes. See `docs/interfaces/lvds-tunnel.md`
§2.3, §4.4, §9.

- [x] Explicit ownership model — Kuntur owns, always, unconditionally. There
      is no arbiter, no handover, and no mode in which ownership is ambiguous,
      because there is no path at all from the Intan controller to the RHD2164
      registers. Writes from the Intan host are absorbed with a
      datasheet-correct ack (so its protocol never stalls), not applied, and
      reported upstream as `HOST_EVENT` frames.
- [ ] Live RHD2164 register state captured into the recording metadata — the
      `CONFIG` frame's contents are exactly this; feed the same source into
      A.6.5's sidecar `filter_settings.registers` for wired sessions. One
      source of truth, three consumers (Intan reads, sidecar, telemetry).
- [ ] **Runbook consequence** (spec open item O6): the operator configures via
      Vega, **not** via the Intan software. A `READ` after a host `WRITE`
      returns Kuntur's real value, not the written one — intended, and the
      whole point, but it looks like a fault to anyone who does not know.
      Must be written into the bench procedure and the animal-test runbook,
      not discovered on the day.

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

> **Update, 2026-08-28/29: A.6.5 implemented and merged to `main`** — see
> that section below for what changed from this spec and `log/2026-08-28.md`
> (third session) / `log/2026-08-29.md` for the full narrative. The
> "implementation is still deliberately not started" line above is stale;
> left in place as the historical record of why it waited. **A.6.4's
> DECISION 2 remains the one open item in this section** — still blocked on
> an empirical sentinel-rate measurement against real (non-ramp) data.

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

- [x] **RESOLVED 2026-08-28** — see DECISION 2 at the end of this item. The
      single-sourcing was done 2026-08-27; the decision landed 2026-08-28 as
      out-of-band loss accounting, which retires the rule rather than fixing it.
      The remaining code change (deleting `is_fifo_underrun()` and both callers)
      is `stream-packet-format.md` §9 **step 5**, and stays in Phase B with the
      rest of the v1 format work — A.7 steps 1–3 do not depend on it.
      *Original text:* the current rule — count an underrun only when **both**
      channels read `0x8000` — is implemented three times over:
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

      **DECISION 2 resolved 2026-08-28 — option (b), out-of-band metadata.**
      `docs/interfaces/stream-packet-format.md` §7. The v1 packet header carries an
      absolute `sample_index`, so loss is detected structurally
      (`gap = sample_index − (prev_index + prev_payload_samples)`) and gives the
      exact count and position of every missing sample; attribution — producer-side
      `fifo0` overflow vs. MCU ring truncation vs. bridge USB backlog vs. genuine
      air loss — comes from differencing the §6 telemetry counters across the gap.
      **The `0x8000` sentinel is retired entirely** and becomes an ordinary ADC
      code, which is what makes the ambiguity go away rather than merely documenting
      it. Consequences: `packet_parser.is_fifo_underrun()` and both its callers are
      deleted (B.3's "single-source the underrun sentinel rule" closes as
      resolved-by-removal — the 2026-08-27 single-sourcing did its job, which was to
      make this a one-place change); and the blocked empirical measurement above
      becomes **moot**, since `fifo0_overflow_samples` answers directly the question
      the sentinel rate was a proxy for. Implementation follows the spec's §9 order,
      not this item.

### A.6.5 — Recording metadata sidecar  *(DECISION 3 — spec first)*  — ✅ **DONE 2026-08-28, bench-verified 2026-08-31**

- [x] Minimum content: sample rate, gain / µV-per-LSB, channel map, filter
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

      **Both gates cleared — unblocked as of 2026-08-28.** The bench session
      ran 2026-08-27 and the PLL retune landed the same day
      (`CLKOP_FREQ_ACTUAL = 45.539955 MHz`). Two additions from that day and
      the next, neither a reason to wait: the sidecar gains a `mode_id` field
      (`stream-packet-format.md` §3.2, additive), and `sample_rate` will take
      one more *value* update after A.7 step 3 sets λ — which is exactly the
      change the config-named-object design was chosen to absorb without a
      schema break. Do not write `30,000` into it; A.7 step 3 is expected to
      land λ below that deliberately.

      **Implemented 2026-08-28 (Claude).** `csv_recorder.py` writes the
      two-pass atomic sidecar (`start()`/`stop()`) and the versioned CSV
      header; `analyze_recording.py` gained dynamic `skiprows` detection
      so every pre-A.6.5 recording still parses unchanged. `channels`
      provenance now persists through the existing Apply/readback flow
      (the gap this section found while writing the spec, above) — no new
      command needed. `filter_settings` ended up **not** read
      automatically at connect as originally specced: reading it
      unavoidably touches `REG_CH_A` transiently (the only path any RHD
      SPI response takes back to the host), so Manuel's call was a
      dedicated operator-triggered **"Get Settings" button**
      (`diagnostics.FilterSettingsReader`) instead — same STOP/act/
      restore/START shape as Apply. `firmware_version`/`bitstream_version`
      write literally `"unknown"`, per this section's own instruction not
      to infer a value from git state. Full narrative: `log/2026-08-28.md`
      (third session). Both interface specs updated to as-built.
      **Bench-verified 2026-08-31**: a 22.8-minute recording produced a
      correct sidecar (`ch_a`/`ch_b` verified-readback, `duration_sec`,
      `rows_written` all right), and Get Settings separately confirmed
      working (after the bridge UART fix below — it hung twice before
      that) with "7 registers read." Not yet done in the *same* recording
      — Get Settings needs to run before Start to land `filter_settings`
      in the sidecar rather than staying `null`/`unknown` — small,
      mechanical, do next time.

## A.7 — Loss accounting & rate margin  *(moved into Phase A 2026-08-28)*

**Spec:** `docs/interfaces/stream-packet-format.md` (AGREED 2026-08-28), §9
steps 1–3. **History and the investigation that produced it:** B.5's
"mblock margin + FPGA FIFO sizing", "FIFO/ring occupancy telemetry" and
"Bridge TX-ring truncation telemetry" items, which retain the narrative and
now point here for scheduling. Not duplicated.

**Why this is Phase A and not Phase B.** The headstage drops samples
silently and unquantifiably today: `fifo.v:58` discards writes when `fifo0`
is full with no counter and no latched flag, and since the 2026-08-27 PLL
retune put production above delivery (ρ ≥ 1), that path is *active*, not
theoretical. A recording made at the animal test under those conditions
cannot be shown to be complete. The animal test is a one-shot external
commitment with an anaesthetised subject and a collaborator's protocol
behind it — there is no second run to fix an uninterpretable dataset.
Steps 1–3 are cheap, non-breaking, and turn "we believe it is lossless"
into a number.

Steps 4–6 (the breaking v1 wire format) stay in Phase B: they are genuinely
deferrable past the animal test, and step 4 additionally gates on B.6's
version handshake.

- [ ] **Step 1 — make loss visible.** *(Manuel, RTL)* Saturating overflow
      counter and high-water mark in `fifo`, exposed as **read-only regbank
      words**; MCU reads them over the existing `REG_READ16` path that
      A.1.1g already generalised — no new mechanism, just a counter and two
      words. Smallest change in the whole plan, largest information gain.
      Two things fold into it:
      - It is the first real use case for B.5's tracked *"FPGA regbank has
        no read-only registers"* item, which should be built as this rather
        than separately.
      - **T3.3's `cmd_is_00 = fifo_full` debug hijack is superseded by it**
        (`kuntur_fpga.v:118`), so that cleanup wants doing in the same pass
        rather than as a separate carried-over item.
- [x] **Step 2 — make loss measurable.** ✅ **Implemented 2026-09-04,
      desk-verified, not yet on hardware.** *(Claude: MCU + bridge + pc-app)*
      The telemetry frame end to end: new `0xFFF4` notify characteristic in
      `stream.c`'s service definition, the bridge's connection sequence
      extended to discover it and write its CCCD, bridge re-framing to
      `0xDD 0x22` with its own TX-ring counters appended, `serial_reader.py`
      decode, pc-app status line. Plus two new MCU counters —
      `ring_truncated_samples` (`stream_app.c:1098-1103` and `:826-835` both
      clamp their push and silently discard the remainder) and
      `stall_time_ms_total`, which with the existing `s_flowoff_total` gives
      both halves of the stall duty cycle.
      Retires one of the three causes currently conflated in
      `dropped_packets` on its own merit, independent of step 3.
      - **Built:** MCU `0xFFF4` characteristic + byte-wise serialiser +
        1 Hz `StreamTelemetryPoll()` + the two new counters; bridge
        discovery, fourth CCCD and `0xDD 0x22` re-framing; pc-app
        `telemetry.py`, three-way frame dispatch in `serial_reader.py`,
        and an attribution column in the Debug Info panel. Both firmwares
        compile clean with no new warnings; `test_telemetry.py` covers
        §6.2's byte offsets, the dispatch through a real `SerialReader`
        thread, forward-compatibility with a longer future frame, and the
        loss-differencing arithmetic across a far-end counter reset.
      - **Two spec gaps closed while building** (both now in the spec):
        §6.2's `reserved` byte became `flags` bit 0
        `fpga_counters_valid`, because "the FPGA counter cannot be read"
        and "the FPGA counter reads zero" were indistinguishable and the
        first is what is true until step 1 lands; and §6.6 now argues why
        a 1 Hz regbank read mid-stream is safe from one specific call
        site, which the agreed text had walked past — every other regbank
        access in the firmware is confined to streaming being stopped.
      - **One spec correction:** §6.5 named two MCU discard sites. Only
        the `flow_off:` one is; the others clamp their FPGA *read*, so a
        short read leaves the remainder in `fifo0` and loses nothing.
      - **Still needs the bench** — the riskiest part is unchanged and
        untestable at the desk: the bridge connection sequence now writes
        a *fourth* CCCD. Bring it up against an already-streaming
        headstage so a telemetry failure is unambiguous. Also worth
        measuring there: the 1 Hz notify's real cost on packet rate
        (argued negligible, ~60 µs/s, but `μ` was measured without it).
- [x] **Step 3a — μ measured, λ set.** ✅ **2026-09-03.** Done *ahead of*
      steps 1–2 rather than after them, because the existing 22.8-minute
      recording turned out to measure both rates at once: the MCU always
      sends a full 59-pair packet (padding with the `0x8000` sentinel), so
      delivered rows ÷ duration = **μ** and rows−underruns ÷ duration =
      **λ**. See `docs/interfaces/stream-packet-format.md` §1.5.
      - **μ = 499.420 pkt/s (29,465.8 SPS)** mean, 499.00 at p1, over
        682,351 packets with **zero `seq_num` gaps**. The 2026-05-15
        figure of 512 pkt/s is **superseded and was 2.5% optimistic**.
      - λ recovered as **29,348.04 SPS**, reproducing the spec's stated
        pre-retune figure exactly — an independent check on the method.
      - **The shipped 30,000 SPS puts ρ = 1.018.** `fifo0` saturates in
        **7.7 s** (11.5 s including the MCU ring) and then discards
        **1.78% of every sample, silently and uncounted**, forever.
      - **Worst stall is ~116 ms, not the ~22 ms** B.5/§1.2 assume — five
        such events in 22.8 min, 60 s minimum spacing. Buffers survive it,
        but at 1.8× margin rather than ~9×. Stall duty cycle **0.316%**.
      - **λ = 28,000 SPS/ch chosen** (Manuel — *"we should work with the
        highest data rate"*). `m` = 5.23%, **16.6×** the stall duty cycle;
        a 116 ms stall recovers in 2.2 s against 60 s observed spacing.
        Preferred over 28,500 because μ is a *bench* number and in vivo it
        can only get worse (tissue absorbs 2.4 GHz, surgical-suite RF,
        antenna orientation, retransmissions): 28,000 tolerates μ being
        5.2% worse, 28,500 only 3.4%. **PLL: set `CLKOP` target to
        42.504 MHz** (= 28,000 × 1518 `clk`/frame), expected
        42.5040118 MHz → 28,000.01 SPS, +0.28 ppm.
        *(Manuel, RTL — not yet applied.)*
      - **25,000 SPS as a wired-mode bring-up step**, not the target: it
        lands exactly on an Intan-selectable rate (`clk` = 37.95 MHz,
        +0.00 ppm), collapsing A.4 §9.5's systematic offset to crystal
        tolerance so the first dual-path work has no rate artifact to
        confuse a link bug with. Production stays 28,000, where the Intan
        side sees 6.67% and A2's comparison needs resampling.
- [x] **fH lowered 20 kHz → 7.5 kHz.** ✅ **2026-09-03**, applied to
      `rhd2164_defs.vh` (`RH1 22/0`, `RH2 23/0` — the datasheet's literal
      7.5 kHz row). Found while choosing λ: fH was at the chip's
      **maximum**, whose Nyquist is 40 kSPS, so at any rate this project
      has ever used the 14–20 kHz band folded straight back into the
      signal — and the RHD's 3rd-order Butterworth rolls off only *above*
      fH, leaving that band essentially passband. **Every recording this
      project has made was aliased.** At 28 kSPS, Nyquist (14 kHz) now
      sits well above the corner. Not a noise fix — the datasheet says
      `vni` varies < 15% with bandwidth — so A.3's noise-floor number
      should not be expected to move much. **Needs an FPGA rebuild +
      reflash**; do it in the same rebuild as the PLL retune above.
- [x] ~~`RL_DAC1/2/3 = 35/17/0` match no datasheet row~~ — **FALSE ALARM,
      retracted 2026-09-03.** 35/17/0 is the datasheet's literal
      **fL = 0.50 Hz** row (p.26); the flag came from a table extraction
      that truncated below 1.5 Hz. fL is unchanged and correct.
      - **Does not establish losslessness.** FPGA overflow is invisible
        downstream, so step 1's counter is still required to *confirm*
        what this analysis merely *sets*.
- [ ] **Step 3b — confirm, once steps 1–2 land.** *(Joint)* `μ_low` from a direct
      re-measurement of the MCU packet-rate ceiling — the cheapest way to
      separate an mblock-margin question from a per-packet-cost regression,
      and the thing the 2026-05-15 figure of 512 pkt/s can no longer answer.
      Stall duty cycle from `flow_off_count` / `stall_time_ms_total`. Then
      set λ and `m` per the spec's §1.3 invariant (`λ_aggregate < μ_low`,
      `m` ≥ the stall duty cycle) and re-tune the PLL to the chosen λ.
      **Expect λ to land below 30,000 SPS/ch, and that is the intended
      outcome** — 30,000 is a target, not a requirement, and A.6.5's sidecar
      records the real rate either way. Also confirm here whether `μ` is
      genuinely payload-size-independent (spec §10, non-blocking).
- [ ] **Consequence for A.6.5:** `sample_rate` needs one value update after
      step 3. Not a reason to delay the sidecar — the config-named-object
      design agreed 2026-08-27 was chosen precisely to absorb this without a
      schema break.

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
      nRF52840 bridge · **`fifo0` depth** (CLAUDE.md and `log/2026-08-28.md` both say
      "~34 ms"; it was deepened 1024→4096 frames on 2026-07-31, so it is ~137 ms —
      `stream_app.c:226-229` and `kuntur_fpga.v:246` `ADDR_WIDTH=12` are correct,
      found 2026-08-28 while writing `stream-packet-format.md` §1.2; this one
      matters because it feeds every buffer-sizing argument).
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

- [ ] **Interface specs** (the A.4 tunnel spec is the first) — ~~BLE packet format~~
      (**AGREED 2026-08-28**, `docs/interfaces/stream-packet-format.md`, not yet
      implemented) · 0xFFF1 command protocol · bridge UART wire format
      (**add CRC** — promoted 2026-08-28: the stream-packet spec rejected a
      per-packet *header* CRC as the wrong layer, since BLE already CRCs and
      retransmits the headstage→bridge hop, and named this item as the right place
      instead. The UART hop carries a length but no integrity check, so a corrupted
      length desynchronizes until the next magic pair; the fix is a frame-level CRC
      over header **and** payload, emitted by the bridge) · FPGA register
      map · RHD2164 configuration contract · recording format + metadata ·
      **protocol version field**, absent today, without which the format cannot
      evolve safely once public — *satisfied for the wire format* by the v1 header
      plus B.6's version handshake (`stream-packet-format.md` §8.2)
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
      same bug. **Done 2026-08-27** (`packet_parser.is_fifo_underrun()`), and
      **closes as resolved-by-removal** once the v1 packet format lands: A.6.4's
      DECISION 2 retires the `0x8000` sentinel entirely
      (`docs/interfaces/stream-packet-format.md` §7), so the single definition and
      both its callers are deleted. The single-sourcing did exactly the job it was
      done for — making this a one-place change.
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
      real underruns, never investigated. **Becomes directly measurable 2026-08-28**:
      the figure is a *read-side* sentinel count, which is a proxy for the quantity
      actually wanted; `fifo0_overflow_samples`
      (`docs/interfaces/stream-packet-format.md` §6.4) counts the write-side drop
      directly. Re-derive the number from that counter rather than investigating the
      old one — and note the old figure is uninterpretable against real data anyway,
      per A.6.4.

      **New data point, 2026-08-31**: a 22.8-minute real-signal recording
      (`vega_20260831_123301.csv`, 40,258,709 samples, 5 Hz injected +
      floating-channel hum, pre-PLL-retune rate ~29,466 SPS) measured
      **0.4% underrun** (160,837 samples) — directly confirmed as genuine
      FIFO-empty events, not analog saturation misread as the sentinel:
      `ch0==-32768`, `ch1==-32768`, and both-together counts are all
      *exactly* 160,837, an exact 1:1:1 correspondence across 40M+ rows
      that rules out two independent real channels coincidentally railing
      at the same value. Spread fairly evenly through the whole recording
      (flat ~0.4-0.5% band), not one big event. Zero packet-level loss the
      same recording (`seq_num`: 0 resync points, 0 packets lost) — the
      loss is specifically FIFO-side, not transport-side. Feeds directly
      into A.7's rate-margin work: even at the *lower*, pre-retune target
      rate, where historically (2026-08-27) delivery "comfortably matched
      or exceeded production," there's a real non-zero baseline loss —
      worth having before A.7 step 3 picks λ and m.
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
      **Manuel, 2026-08-27: agrees with the derivation.**

      **Bench session started 2026-08-27 — sequencing decided (Manuel):**
      the FPGA needs reflashing regardless, so do the oscilloscope check
      and the PLL retune in the same pass rather than verify-then-
      re-verify. Order: (1) oscilloscope — output `spi1_csb` as a test
      signal, measure the real period directly, against the *current*
      (pre-retune) bitstream, to check the RTL cycle-count derivation
      above before spending a resynthesis on it; (2) PLL retune to
      actually hit 30,000 SPS; (3) **A.1.4's dead-port cleanup bundled
      in** — deleting `rhd2164_sampling_cmd0-3` needs its own
      `kuntur_fpga.v` port-list edit, and since that file is already
      being resynthesized for the PLL change, doing both in one pass
      avoids a second resynthesis cycle; (4) one resynthesis + reflash;
      (5) full functional round-trip verification against the new
      bitstream (the regbank EBR rewrite, RTL reorg, and parametrization
      fixes from 2026-08-26 have *also* never been bench-verified — this
      is that check too, not a separate pass); (6) re-check `spi1_csb`'s
      period on the scope against the retuned rate; (7) a fresh full-
      stream recording to confirm BLE keeps up with the corrected rate —
      the 2026-08-03 result (506.0 pps × 59 ≈ 29,854 SPS delivered,
      matching the *old* ~29,348 production rate almost exactly) doesn't
      by itself prove BLE has headroom for the new, slightly higher
      target. That recording is also the first real (non-ramp) data
      since A.1.1e (2026-08-11) — unblocks A.6.4's DECISION 2 sentinel-
      rate measurement as a side effect.

      **Flagged, not blocking today's FPGA work:** the MCU firmware has
      not been reflashed since 2026-08-11 (Manuel, 2026-08-27) — the
      A.1.1g protocol rewrite (`fpga_spi.c`, tagged 3-transfer writes,
      self-addressing reads) built clean that day but PLAN.md's A.2
      status has said "still untested on hardware" ever since, and no
      session log between then and now records flashing it. Step (5)'s
      round-trip verification needs the MCU actually running that
      firmware — worth confirming what's currently flashed before
      relying on the register console, since a stale MCU speaking the
      pre-A.1.1g protocol against the new regbank would fail in a way
      that could be mistaken for an FPGA-side regression.
      **Checked 2026-08-27, before the reflash:** MCU responded correctly
      to `REG_READ16` (word 196) with a well-formed reply — confirms the
      MCU is running A.1.1g-era firmware, not the pre-2026-08-11 protocol,
      so no flash needed there. (`SET_CHANNELS`'s readback mismatched at
      that point — expected, the FPGA regbank layout it was checked
      against was still pre-reflash.)

      **Step (1), oscilloscope — done, 2026-08-27 (Manuel):** `spi1_csb`
      period measured directly: **1.03 µs**. Matches the RTL-derived
      figure above (46 cycles × 22.447 ns = 1032.57 ns) to within 0.25%
      — well inside oscilloscope rounding. Cycle count confirmed correct
      by independent hardware measurement, against the pre-retune
      bitstream as planned.

      **Steps (2)-(4), PLL retune + A.1.4 cleanup + resynthesis +
      reflash — done, 2026-08-27 (Manuel).** Exact new PLL value and its
      own oscilloscope re-verification not yet reported here.

      **Step (5), round-trip verification — partially done, 2026-08-27.**
      Checked post-reflash: `STOP_STREAMING` → `SET_CHANNELS(5,6)` →
      readback `(5,6)` (exact match) → `REG_READ16(196)`/`REG_READ16(197)`
      both read back exactly what was written → `START_STREAMING` — full
      SPI0/regbank protocol round-trip clean. **But real-data path check
      surfaced a likely regression**, unrelated to the protocol round
      trip: friendly channel 42 (chip0's range, 0–63) read a flat `-1`
      (`0xFFFF`), zero variance over 745 packets; friendly channel 88
      (chip1's range, 64–127) showed real, varying data
      (std ≈ 13,232). **This is the exact signature of the dead-chip0-
      MISO bug** root-caused and fixed 2026-08-24 (unconstrained
      placement of `spi1_rhd2164x2`/`controller0`,
      `fpga-rhd2164-chip0-placement.md`) — same symptom, same channel
      range, and 42/88 are the identical pair that session used to
      confirm the fix. **Confirmed by Manuel, 2026-08-27: a real
      regression, same root cause class as before — placement, not
      logic.**

      **Corrected by Manuel mid-investigation: the actual broken signals
      are MOSI/SCK, not MISO.** The MISO-side analysis below (pad
      distance, `rxsr_a0`/`rxsr_b0`'s extra `LUT4`) was a red herring —
      recorded here for completeness since it's still-true data about the
      MISO path, but it is **not** the cause of this regression.

      **Fix approach, isolated on a stripped-down bring-up build**
      (`kuntur_fpga.v` with everything but `spi1_rhd2164x2` commented
      out, `start` tied high, `impl_1.sdc` entirely commented out except
      the original stray 100 MHz `clkin` line — a deliberate "both chips
      respond" electrical-only check with zero timing constraints
      active). **Both chips confirmed responding on this build.** Old
      placement approach: one coarse region (`mr0`, anchor R20C56, 9×8)
      pinning the whole `spi1_rhd2164x2` macro — anchored near
      `spi1_miso1`'s pad (`PB56`), nowhere near the MOSI/SCK/CSB pad
      cluster (`spi1_csb`=`PB70`, `spi1_sck`=`PB68`, `spi1_mosi`=`PB64`).
      New approach: `impl_1.pdc` now names every individual FF in
      `spi_master_controller0` (the FSM driving MOSI/SCK/CSB) via
      `ldc_create_group`, pinned to a small `region0` (anchor R20C69D,
      4×6) — anchored *at* the pad cluster instead. **Verified placement
      footprint** (GUI, Manuel, cross-checked against the subset
      independently recovered from `.twr`'s path listings — consistent,
      no conflicts): rows R21–23, full A–D at columns C70–71, plus two
      single-slice extensions at R21C71D and R22C72D. Tight and compact,
      essentially sitting on top of the pads it drives.

      **Found while verifying the group's cell list: a fragile
      constraint, independent of the chip0 bug itself.**
      `ldc_create_group`'s cell list includes
      `spi1_rhd2164x2/spi_master_controller0/i6_1_lut`, which **does not
      exist in the current netlist** —
      `WARNING <1026001> - impl_1.pdc (41): No cell matched
      'spi1_rhd2164x2/spi_master_controller0/i6_1_lut'.`
      (`kuntur_fpga_impl_1.mrp:142`, `automake.log:1902`). Radiant warns
      and silently drops the cell from the group rather than failing the
      build — confirmed via the GUI instance count (52, not the 53 the
      `.pdc` list implies) and cross-checked against
      `kuntur_fpga_impl_1.mrp:215`'s unrelated `Block
      spi1_rhd2164x2/rxsr_a0/i6_1_lut was optimized away` (a
      *different*, coincidentally-same-named LUT, under `rxsr_a0` not
      `spi_master_controller0`). `i1_3_lut`/`i1_4_lut`/
      `i1_4_lut_adj_1-6` are the same *class* of name — LSE's own
      auto-generated numbering, not anything named in the RTL — and
      happened to still resolve this run, but carry the identical risk:
      nothing guarantees these survive a future resynthesis unchanged.
      **This is the concrete answer to "how do we make this constrained
      or verified"**: an enumerated list of synthesis-auto-named cells is
      a constraint that degrades silently (a log warning, easy to miss,
      not a build failure) rather than loudly.

      **Root framing, worked out with Manuel 2026-08-27:** `spi1_mosi`/
      `spi1_sck`/`spi1_csb` are shared — one FPGA pad each, fanning out
      on the PCB to *both* RHD2164 chips (`spi_master_rhd2164x2.v`: a
      single `mosi`/`sck`/`csb` port each, only `miso`/`miso1` are
      per-chip). FPGA-internal placement can't differentially compensate
      chip0 vs. chip1 for a shared signal — both see the same edge at
      the same instant off the pad. What tight placement actually does
      is minimize the FPGA-internal share of the fixed total period,
      leaving more of it for the external PCB share — and since chip0's
      and chip1's traces are presumably different lengths, whichever is
      longer has less slack to begin with, which is why one chip fails
      while the other doesn't (both bugs today, and A.1.1's original
      2026-08-11 finding, are all this same shape). `impl_1.sdc`'s
      MOSI/CSB `set_output_delay -max` uses a uniform, never-measured
      1.5 ns board/cable placeholder (the file says so directly) as if
      both traces were equal — tight placement has been standing in for
      an honest bound on that real, likely-asymmetric external delay.

      **Decided, 2026-08-27 (Manuel): cannot be measured with equipment
      on hand** — resolving trace-length asymmetry at this timescale
      needs sub-1 ns resolution (a GHz-bandwidth oscilloscope) *and*
      physical probe access to the relevant pads, neither available.
      Sharpens the existing 2026-08-24 "equipment ceiling" note in
      `fpga-timing-constraints.md` rather than replacing it. **Decision:
      fix the placement constraint instead** — pin `spi_master_controller0`
      as a whole instance/region (`ldc_set_location -region region0
      [get_cells spi1_rhd2164x2/spi_master_controller0]`, RTL-stable
      hierarchical name, not synthesis-auto-named leaf cells), matching
      how `spi1_rhd2164x2` itself was pinned before — rather than the
      current enumerated-cell-list `ldc_create_group`. **In progress.**
      Still open, separate from this: an automated check for "No cell
      matched" warnings post-PAR generally (B.1's enforcement-ratchet
      philosophy — few, fast, reliable checks), so any future case of
      this class fails loudly instead of silently.

      **Next, per Manuel:** re-add the blocks removed for this isolation
      test (`regbank`, `ch_sel0`, `controller0`, `controller1`/
      `main_controller`, `fifo0`, `muxreg0_spi0`, `test_pattern_gen0`,
      `fifo_din_mux0`, `spi0`), re-enable `impl_1.sdc`'s commented-out
      constraints (all of it — clocks, MISO/MOSI/CSB delays, the
      `spi1_mosi` hold multicycle exception, `spi0`/`rstb` false-paths),
      then decide the group-vs-region question above before the next
      resynthesis. Device left in a safe streaming state (channels 42/88
      selected) from the earlier round-trip test, before this isolation
      build replaced it.

      **RESOLVED, 2026-08-27 (Manuel).** Went further than the single
      `spi_master_controller0` fix discussed above — restored the
      **whole-design** whole-instance placement scheme from the
      2026-08-26 "item-4" work (all `ldc_set_location -region <name>
      [get_cells <RTL-instance-name>]`, no enumerated leaf-cell lists
      anywhere), described as "the latest design we got working":

      | Region | Anchor | W×H | Cell |
      |---|---|---|---|
      | `mregion0` | R20C38 | 10×5 | `spi1_rhd2164x2` (MISO capture *and* the MOSI/SCK/CSB-driving FSM together) |
      | `mregion1` | R20C48 | 6×5 | `ch_sel0` |
      | `mregion2` | R8C42 | 22×5 | `fifo0` |
      | `mregion3` | R8C34 | 8×5 | `regbank0` |
      | `mregion4` | R13C39 | 3×4 | `controller0` |
      | `mregion5` | R13C52 | 2×6 | `fifo_din_mux0` |
      | `mregion6` | R4C38 | 4×4 | `controller1` |
      | `mregion7` | R4C42 | 5×4 | `spi0` |

      A.1.4's dead-port cleanup (`rhd2164_sampling_cmd0-3`) also landed
      in this same pass. **Full verification, all four legs:**

      - **Placement — confirmed via `.twr`.** All of `spi1_rhd2164x2`'s
        sub-instances (both `rxsr_a0`/`rxsr_b0`/`rxsr_a1`/`rxsr_b1` MISO
        capture *and* `spi_master_controller0`'s `csb_reg`) landed
        together in one compact cluster, **R21–24 × C42–47**, inside the
        declared `mregion0` (R20–24 × C38–47) — unlike every placement
        tried earlier today, MISO and MOSI/SCK/CSB logic are now
        co-located rather than split across the die.
      - **Timing — clean.** `1.3 Overall Summary`: **0 endpoints, 0.000 ns
        total negative slack on all 3 corners** (setup 85°C/0°C, hold
        m/0°C). Constraint coverage 98.1954%. Worst `spi1_sck`-related
        margins 1.270 ns / 1.953 ns (both comfortably positive). Only 2
        design warnings, both the known/expected `spi2_miso0`
        (disabled RHS2116) ones — **zero** placement/cell-matching
        warnings, confirming the RTL-stable-name approach has no
        equivalent to today's earlier `i6_1_lut` fragility.
      - **Area — improved vs. the 2026-08-26 baseline.**
        `SLICE 595/6912 (9%)`, `LUT 543/13824 (4%)`, `REG 545/13824 (4%)`,
        `EBR 10/24 (42%)` — SLICE/LUT dropped from 645/641 (register
        count unchanged, as expected), consistent with A.1.4 actually
        landing this time: confirmed zero `rhd2164_sampling_cmd` references
        in `kuntur_fpga.v` (only an explanatory comment survives in
        `regbank.v`), and the `DPR16X4` residual noted in every area
        report since 2026-08-26 is **gone**.
      - **Functional round-trip — clean, on real hardware.**
        `STOP_STREAMING` → `SET_CHANNELS(42,88)` → readback `(42,88)`
        (exact match) → `START_STREAMING`, all acked. Both friendly
        channel 42 (chip0) and 88 (chip1) streaming real, varying data
        (std ≈ 10,889 and ≈ 10,754 respectively — not flat, not stuck) —
        matches what Manuel sees directly in the pc-app's own
        visualization for both chips.

      **Still open, tracked separately:** an automated check for "No
      cell matched"-class warnings post-PAR, so a future case of this
      failure shape (any project, any cell) fails loudly rather than
      silently (B.1 enforcement-ratchet philosophy). Both repos have a
      full day of uncommitted work sitting in the tree — worth a
      checkpoint commit before anything else changes.
- [x] **`SET_CHANNELS` has always selected the wrong physical RHD2164
      channel — found 2026-08-29, compensated in pc-app, firmware still
      wrong.** **Bench-verified 2026-08-31**: `ChA=3`/`ChB=4` (the wire
      values `physical_to_wire()` computes for physical channels 0/1)
      showed a clean known 5 Hz injected signal on physical channel 0 and
      60 Hz floating-input hum on physical channel 1 — the dynamic
      channel-title UI correctly labelled them "Channel 0"/"Channel 1".
      Confirms the fix with a real known signal, not just the wire-capture
      print. Run on `kuntur` `e89671d` (the 2026-08-31 checkpoint, see
      below), so this also stands as an independent reconfirmation that
      checkpoint's hardware health. `docs/interfaces/channel-selection-control-plane.md` §1a's
      friendly-index formula (written 2026-08-05) and its verbatim
      firmware implementation (`FPGA_SPI_ChannelToRaw()`,
      `fpga_spi.c:325-328`) apply **zero** correction — but A.1.1e later
      confirmed on hardware (2026-08-11) that the RHD2164's response
      pipeline needs a `+3` slot correction (`SLOT_OFFSET`,
      `pc-app/diagnostics.py`). The two facts were never reconciled:
      every `SET_CHANNELS` call this project has ever made has captured
      physical channel `(n − 3) mod 32`, not `n`. New development the
      same session that surfaced this: **both chips now respond**
      (the 2026-08-27 chip0-placement fix above), which is what turned
      this from a 64-channel question into a full 128-channel one.

      Compensated in `pc-app/channel_mapping.py`, per explicit decision
      to fix in pc-app rather than firmware — cross-checked against both
      `diagnostics.py`'s hardware-confirmed `ch_code()` and a verbatim
      copy of the real firmware formula (`test_channel_mapping.py`), not
      just its own internal consistency. **4 of 128 channels (one per
      32-channel module — friendly 29/61/93/125) are structurally
      unreachable via `SET_CHANNELS` at all**, corrected or not — the
      friendly encoding can never produce the raw code they need (it
      always clears the bit that code depends on) — and go through a new
      direct `REG_WRITE16` fallback (`RawChannelSetter`) instead.

      Full derivation: `docs/interfaces/channel-selection-control-plane.md`
      §1a-addendum; narrative: `log/2026-08-29.md`. A firmware fix to
      `FPGA_SPI_ChannelToRaw()` remains the more complete answer (closes
      the 4-channel dead zone entirely, one code path instead of two);
      noted as Phase B cleanup, not chased this session by explicit
      choice.

      **Scope, corrected 2026-08-31 (Manuel):** the bench session verifies
      that the pc-app **sends the correct command** — not that an RHD2164
      channel's output is "correct," which would need assuming the chip
      itself works and having selective per-channel access, neither of
      which this bug is about. Two consequences:
      - Current PCB only exposes physical channels 0 and 1 (chip0 module
        A), one at a time. `physical_to_wire()` gives friendly wire values
        3 and 4 respectively — checked at the bench by reading the
        command, per "Verification method" below, not by inspecting the
        analog signal.
      - **The 4-channel raw path (29/61/93/125) needs no bench/hardware
        session at all under this framing, and is off the checklist
        entirely** — not deferred, just verified somewhere else in the
        chain already. `test_channel_mapping.py` reads
        `physical_to_wire()`/`physical_to_raw()`'s output for all 128
        channels including these 4, offline, cross-checked against both
        `diagnostics.ch_code()` and a verbatim copy of the real firmware
        formula. That already proves the pc-app computes (and would send)
        the correct raw `REG_WRITE16` values — hardware adds nothing to
        that claim, since there is no physical channel to check it
        against anyway.

      **Verification method, 2026-08-31:** since this is a pure pc-app
      software fix, Manuel proposed confirming it by capturing the actual
      command bytes rather than (or in addition to) reading the analog
      signal. Checked against source: the WB09KE bridge is a **transparent
      relay** (`vega_bridge_app.c`'s `vega_bridge_relay_command()` — "no
      interpretation of the payload beyond framing"), so whatever leaves
      the pc-app on the wire is byte-for-byte what reaches the kuntur-mcu's
      0xFFF1. Capturing on the *bridge* side instead would mean enabling
      `DT_INFO_MSG`/`CFG_DEBUG_APP_TRACE`, which — per the 2026-08-28
      finding above — shares USART1 with the live command/data stream and
      is a known, deliberately-unfixed corruption risk; not worth enabling
      just to watch a value the pc-app already knows. Added a console print
      at the Apply send site (`main_window.py:_apply_channels_send_set`)
      showing physical→wire mapping and the literal outbound frame bytes,
      so the value can be read directly against `channel_mapping.py`'s
      arithmetic. Paired with the existing FPGA regbank readback
      (`_on_channels_readback`'s "✓ Verified" / "✗ Mismatch"), which already
      round-trips through the real kuntur-mcu regbank — between the two,
      no bridge instrumentation is needed to confirm the fix end to end.
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
      **New evidence, 2026-08-27 — the PLL retune exposed exactly this
      margin.** After retuning the PLL to hit true 30,000 SPS production
      (`impl_1.sdc`'s `clk` period corrected to 21.9587393093 ns,
      `CLKOP_FREQ_ACTUAL = 45.539955 MHz`, STA clean — 0 violations, all
      3 corners, worst `spi1_sck` margin now **0.915 ns**, tighter than
      anything else recorded this investigation but still passing),
      measured *delivered* rate over a real 10 s capture came in at
      **29,482.9 SPS — 1.7% below the new 30,000 target**, versus
      comfortably matching/exceeding the *old* ~29,348 production rate
      before the retune (2026-08-03's post-mblock-fix result, and this
      session's own earlier checks, both ~29,500–29,850). **Underrun
      measured 0%** — consistent with production now *exceeding*
      delivery rather than the reverse: the FPGA's 4096-pair ring buffer
      fills instead of draining (at the ~517 pair/s deficit implied
      here, full in ~8 s, inside the capture window), and excess
      samples are most likely silently dropped on the write side, which
      does **not** produce the `0x8000` underrun sentinel the read side
      already watches for. Different failure mode than the one the
      2026-08-03 mblock-margin fix targeted, and the sharper `spi1_sck`
      timing margin above narrows headroom on the production side at
      the same time. **Not yet root-caused or fixed** — this is the
      concrete measurement this tracked item has been waiting for, not
      a resolution. Two real captures per channel pair are on record
      (chA=3/chB=121, plus earlier 42/88), both from live `pc-app`
      sessions, neither saved as a CSV recording.

      **Reframed 2026-08-28 — this is a margin problem, not a depth
      problem, and the work moved to Phase A (A.7).** This item retains the
      investigation history; **A.7 holds the actionable steps** and is where
      scheduling lives. See `docs/interfaces/stream-packet-format.md` §1,
      which supersedes the framing above. The retune moved the system across
      ρ = 1: delivery (499.7 pkt/s) fell below production (508.5 pkt/s)
      with underrun at 0%, meaning `fifo0` accumulates rather than
      drains. Buffer depth is *not* the constraint — real depth is
      ~205 ms headstage (`fifo0` 137 ms + MCU ring 68 ms), ~10× the
      worst measured stall. The constraint is that margin `m` sets the
      *drain rate*: at today's ~0.69%, recovery from one 22 ms stall
      takes 3.1 s, so stalls arriving more often than that accumulate
      backlog regardless of depth. **This item cannot be closed by
      tuning; it closes by measuring `μ_low` and the stall duty cycle
      (spec §9 steps 1–3) and then setting λ.** Note also that the
      per-mode framing in this item's own title is no longer needed:
      under the v1 packet format the packet rate is mode-independent
      (spec §5), so one tuning result covers every future mode.
- [ ] Reduced sample rate as a reliability lever — characterise empirically
- [ ] **FIFO/ring occupancy telemetry — now specified and on the critical path.**
      MCU ring watch written but `STREAM_DIAG_RING_WATCH=0`, never flashed; FPGA
      FIFO occupancy needs new RTL.
      **Specified 2026-08-28** in `docs/interfaces/stream-packet-format.md`
      §6.4–6.5, promoted from "tracked but unbuilt" to **steps 1–2 of that
      spec's implementation order** — nothing downstream can be tuned until it
      exists, because `m` cannot be chosen without the stall duty cycle — and
      **moved into Phase A as A.7 steps 1–2** the same day. This item retains
      the source findings; A.7 holds the schedule.
      Two findings from reading the source to write it:
      - `fifo.v:58` is `else if (wen && !full)` — on full the write is silently
        discarded, with no counter and no latched flag (`fifo_full` reaches only
        `cmd_is_00`, itself T3.3's debug hijack). **This is the single
        uncontrolled loss point in the headstage**, and its invisibility is why
        the 2026-08-27 deficit had to be inferred from delivered-rate arithmetic.
        Fix: a saturating overflow counter + high-water mark exposed as
        **read-only regbank words** — the first real use case for the tracked
        "FPGA regbank has no read-only registers" item below, which should be
        built as this rather than separately.
      - `stream_app.c:1098-1103` (the `flow_off:` path) and `:826-835` clamp their
        push to whatever ring room remains and silently discard the remainder.
        Only reachable when the ring is already full, but real and uncounted.
      Also needs `stall_time_ms_total` alongside the existing `s_flowoff_total`:
      together they give both halves of the stall duty cycle, which is the number
      nobody currently has. Backpressure elsewhere in the headstage is already
      correct — a full MCU ring stops `StreamIngestDuringStall`, pushing pressure
      back onto `fifo0` rather than dropping — so no other counter is needed.
- [ ] **Bridge TX-ring truncation telemetry — counters done 2026-08-28, reporting
      path still open.** `VEGA_UART_Write()` drops the remainder of a write when the
      4096-byte ring is full, which puts a *truncated* frame on the wire. The pc-app
      resynchronises on the next magic pair and books it as a missing packet —
      indistinguishable from a packet lost on air, so a USB-side backlog and a radio
      problem read identically in `dropped_packets`. The bridge is the only place
      that can tell them apart.

      **Done:** `s_drop_bytes` / `s_drop_frames` in `wb09ke-bridge/STM32_BLE/App/
      vega_uart.c`, incremented under a short critical section on the drop path only
      (that function is reachable from ISR context whenever `CFG_DEBUG_APP_TRACE` is
      on, and the M0+ has no atomic read-modify-write). Read via
      `VEGA_UART_GetDropStats()`. +40 B flash, +8 B RAM.

      **Open — and blocked on a spec, not on code.** Nothing reports them. The debug
      console is a no-op by default and deliberately so (it shares the wire with the
      data stream), and `VEGA_UART_GetDropStats()` is currently collected away by
      `--gc-sections` because nothing calls it, so today the counters are SWD-only.
      Surfacing them means a new bridge→PC frame type — a cross-boundary interface,
      which gets a spec in `docs/interfaces/` first. Proposed shape: a `0xDD 0x22`
      telemetry frame carrying both counters on a slow cadence, decoded by
      `serial_reader.py` alongside the existing `0xAA 0x55` data and `0xEE 0x11`
      response frames, and surfaced in the pc-app's status line next to the drop
      figure it currently cannot qualify. Same argument as A.6.4's DECISION 2: loss
      that is reported out of band can be attributed; loss inferred from the data
      stream cannot.

      **Specified 2026-08-28, widened, and moved into Phase A as A.7 step 2** —
      `docs/interfaces/stream-packet-format.md` §6. The `0xDD 0x22` shape above is
      kept but is **no longer bridge-specific**: it carries every counter in the
      chain (FPGA `fifo0` overflow, MCU ring truncation and stall time, bridge TX
      drops) *and* the RTC time anchor, because A.6.4's out-of-band loss report and
      the v1 header's removal of per-packet timestamps both need exactly this frame.
      Three frame types doing one job is the outcome that was worth avoiding.
      Path: FPGA counters → MCU over the existing `REG_READ16` regbank path → host
      over a **new `0xFFF4` notify characteristic** → bridge appends its own
      counters and emits `0xDD 0x22`. Counters are **cumulative since
      `START_STREAMING`**, so a lost telemetry frame costs resolution, not
      information.
      **`0xFFF4` decided 2026-08-28 (Manuel), changed from the spec's original
      proposal** of reusing `0xFFF3` with an unsolicited high-bit opcode. `0xFFF3`'s
      contract is request/response, so unsolicited traffic on it would have been
      safe only by convention — the same "correct by assumption, not by
      construction" shape as the bridge's single-producer TX ring found the same
      day. A characteristic handle is enforced by GATT instead. Accepted cost: the
      bridge's connection sequence gains a fourth discovery + CCCD write, in a
      sequence with a history of fragility — but it fails loudly (no telemetry)
      rather than silently misrouting a command response.
- [ ] **Bridge TX ring is single-producer by assumption, not by construction.**
      `vega_uart.c` documents itself as single-producer/main-context-only, and
      `VEGA_UART_Write()` relies on that: it caches `s_head`, fills slots, and commits
      the new head at the end. That is safe with one producer and unsafe with two.

      There *is* a second producer, latent: `USART1_IRQHandler`'s ORE branch calls
      `DT_INFO_MSG` → `printf` → `__io_putchar` → `VEGA_UART_Write`, from ISR context.
      It is inert today only because `CFG_DEBUG_APP_TRACE` is `0`. Turn tracing on and
      an ISR write landing mid-frame reads the same uncommitted `s_head`, overwrites
      bytes the interrupted call had already placed, and commits a head the
      interrupted call then overwrites in turn — so the frame on the wire is
      *corrupted*, not merely delayed, and the debug character is swallowed into it.
      `printf` emitting one byte per `__io_putchar` call narrows the window but does
      not close it.

      The trap is the shape of it: the configuration you would enable to diagnose a
      streaming problem is the one that can corrupt the stream, and the corruption
      looks like a framing error rather than like a tracing bug. Cheapest honest fix
      is a critical section around the head cache/commit in `VEGA_UART_Write()` — the
      same guard the truncation counters above already use, widened to the write
      itself; measure it on the hot path first, since unlike the counters this one
      runs per frame rather than per drop. Alternative: give ISR-context tracing its
      own single-byte path that touches only a reserved slot. Not urgent while the
      flag is `0`; worth fixing before anyone debugs with it.
- [x] **kuntur chip0/SCK-MOSI board-level regression — found 2026-08-31, real
      root cause identified, closed for now without a working fix.** Bench
      session started with chip0 unresponsive again on reload of the (then-
      uncommitted) pre-retune bitstream. Traced, with a detour through a
      `TIMING_MARGIN_RATIO` period-scaling experiment (see below) and a
      `set_clock_uncertainty` margin attempt, to the real cause:
      **`spi1_sck`/`spi1_mosi`/`spi1_csb` are a single FPGA pad each,
      fanning out on the board to *both* RHD2164 chips — a shared,
      multi-drop bus. If the physical trace length from the FPGA to chip0
      differs from the trace to chip1, one chip's setup/hold margin is
      worse than the other's, and nothing FPGA-internal can differentially
      compensate a shared signal.**

      A same-day fix attempt (deliberate MOSI deskew via a new placement
      region, `region0`/`group0`) made things *worse*: it required removing
      the whole-design placement pinning (`mregion0`-`mregion7`), which
      reintroduced the exact regression class `e89671d` (2026-08-27) exists
      to fix — the diagnostics ladder went flat/wrong on every rung
      regardless of slot or chip, and the baseline signal degraded too.
      Reverted to the checkpoint rather than continue mid-regression — see
      the checkpoint note immediately below.

      **Lesson, load-bearing, not optional**: `mregion0`-`mregion7` has now
      been the fix for this exact failure class twice (2026-08-24,
      2026-08-27) and the cause of a third regression when removed
      (2026-08-31). Any future SCK/MOSI deskew attempt must add its
      constraint **alongside** `mregion0`-`mregion7`, never by removing
      them.

      **Second attempt, same day, on top of the checkpoint (not the
      region-pinning-removed state): a real deskew via a phase-shifted PLL
      clock.** Added `clk90` (PLL `CLKOS`, +90° from `clk` — 5.4897 ns at
      the retuned 45.539955 MHz) and re-launched `spi1_mosi` off a new
      `mosi_reg` clocked by `clk90`, with `spi1_sck` itself registered
      (`sck_reg`, mirroring `csb_reg`'s existing 2026-08-24 pattern,
      previously combinational). **STA fully verified this structurally**
      — 0 negative slack all 3 corners, 98.2% coverage, `spi1_mosi`'s own
      margin *improved* to 4.939 ns (real, traced through `Source Clock:
      clk90` → `Destination Clock: spi1_sck` in the `.twr`, not assumed) —
      confirming the phase direction was at least not actively harmful.
      **Did not work on real hardware anyway.** Tried four `mosi_reg`
      clock relationships (`clk`, `clk90`, `negedge clk`, `negedge clk90`)
      — none got both chips responding. Root cause of the miss: 90° was
      picked from a rough ns estimate of the needed deskew, never a
      measurement of the actual board trace-length asymmetry — STA proving
      the *internal* timing is clean says nothing about whether 90° is the
      right *amount* of deskew for an unmeasured physical asymmetry.
      Two paths for whoever revisits this: (a) check whether this PLL
      block supports Lattice's Dynamic Phase Shift, which would allow a
      live phase sweep on real hardware without a resynthesize-reflash
      cycle per attempt; (b) failing that, a systematic discrete-phase
      sweep (0°, 45°, 90°, ... bracketing the full range) via resynthesis.

      **Closed for now (Manuel's call)**: reverted `sck_reg`/`mosi_reg` to
      plain passthrough assigns rather than deleting the infrastructure —
      `clk90`, the PLL routing, and the register declarations all stay in
      the RTL (commented out where they'd conflict), so a future attempt,
      ideally informed by an actual board measurement, doesn't have to
      redo the PLL/RTL plumbing from scratch. Bench-confirmed both chips
      responding again on this exact build. Committed `kuntur` `324a21c`
      on `session-2026-08-31-checkpoint`, pushed.

      **2026-08-31 checkpoint state — what's where.** `kuntur` is on
      branch `session-2026-08-31-checkpoint`, now at `324a21c` (one commit
      ahead of `e89671d`) — **not** on `main`, which still sits untouched
      at `e2bac25`; held there deliberately (not fast-forwarded) until this
      whole SCK/MOSI question is fully settled. `vega` moved forward to
      `main` normally (nothing there caused or was affected by the
      regression).
      - **Safe to fast-forward onto the checkpoint whenever, zero risk,
        still not done**: the three 2026-08-28 comment-only commits sitting
        on old `main` ahead of `e89671d` (`ec8b8d6` bus-label AHB fix,
        `834b888` dead enum removal, `5d50981` `fifo0` sizing comment fix)
        — all confirmed comment/dead-code-only, rebuilds byte-identical at
        173,348 B text each time.
      - **Real, wanted, and now actually committed** (was the gap this
        whole revert originally surfaced): the 2026-08-27 PLL retune
        (44.55→45.54 MHz, exact 30,000 SPS) — verified on hardware that
        day but never committed until `324a21c` landed it for real, three
        sessions of drift closed. One real mistake happened along the way
        before that: Claude briefly "corrected" `impl_1.sdc`'s `clk` period
        back to the stale *pre*-retune 44.55 MHz value, on the wrong belief
        the retuned figure was stale; Manuel caught and fixed it before it
        went anywhere.
      - **Correctly abandoned, not "lost"**: the *first* SCK/MOSI attempt
        (`region0`/`group0`, the removed `mregion` pins, the
        `TIMING_MARGIN_RATIO`/`CLK_SETUP_MARGIN_NS` margin experiments) —
        caused the regression, not blindly redoable as-is. The *second*
        attempt (`clk90`, the two new registers) is kept as real,
        STA-verified-but-hardware-unproven infrastructure, per the
        "closed for now" note above — a different disposition from the
        first attempt, worth keeping distinct.
      Today's bench work (full A.1.1 ladder pass, A.1.1f VDD confirmation,
      the offset-fix confirmation, the 22.8-min recording) ran against
      `e89671d` before `324a21c` landed — so it validates the checkpoint
      lineage generally, not the exact retuned+clk90-infrastructure build
      specifically. Worth a quick re-confirmation (ladder + a short
      recording) before fully trusting `324a21c` as the new baseline to
      fast-forward `main` to.
- [x] **Bridge command-frame parser desyncs on a USART1 overrun — found and
      fixed 2026-08-31.** A different mechanism from the single-producer
      item above (this one is unconditional, not gated behind
      `CFG_DEBUG_APP_TRACE`), found chasing a real bench symptom: two
      diagnostics-ladder rungs and one Get Settings run corrupted a
      `REG_WRITE16`'s staged high byte on the FPGA regbank (`0xCC`
      appearing where it shouldn't — the first byte of `CMD_MAGIC`), and
      Get Settings twice hung hard enough to need a bridge reset.

      Root cause: the 2026-08-06 USART1 ORE fix only clears the overrun
      flag so RX doesn't die *permanently* — it never told
      `VEGA_UART_RxByte()`'s command-frame parser that the byte which
      triggered the overrun was lost. An ORE mid-payload leaves the parser
      misaligned with what the pc-app actually sent, with no way to detect
      it, so the *next* frame's `0xCC 0x33` magic gets consumed as payload
      data instead of recognized as a new frame — exactly how a
      `REG_WRITE16`'s staged high byte ends up as `0xCC`.

      Fixed (`wb09ke-bridge`, commit `0836caf`): `VEGA_UART_RxReset()`
      resets the parser to `RX_IDLE`, called from the ORE handler right
      after clearing the overrun; plus a 5 ms RX timeout backstop inside
      `VEGA_UART_RxByte()` itself for any other desync source (at 2 Mbaud
      a real frame's byte gap is ~5 µs, so this never trips on legitimate
      traffic, and it's ~1000x shorter than the pc-app's ~2000 ms
      `ACK_TIMEOUT_MS` retry gap, so a retry now always finds the parser
      at `RX_IDLE`). Bench-verified: rung `L` and Get Settings both
      re-run afterward with multiple retries firing on the still-lossy
      transport, all recovering cleanly — no corrupted writes, no hangs.
      **Does not reduce how often USART1 drops a byte** (still the
      2026-08-06 ISR-priority cause, unaddressed), only how cleanly
      recovery happens when it does — the retry *frequency* is still
      elevated and is its own, separate, lower-priority item if it's ever
      worth chasing.
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
      **Promoted 2026-08-28 from nice-to-have to a prerequisite**
      (`docs/interfaces/stream-packet-format.md` §8.2): the v1 packet format is a
      breaking wire change, and v0/v1 cannot coexist on `0xFFF2` without a
      discriminator. The handshake is the clean one — the pc-app learns the
      protocol version at connect and selects a parser. A byte-7 sniff
      (`num_pairs`=59 in v0 vs. `reserved`=0 in v1) works as an interim fallback but
      is fragile and breaks if §10.1's header CRC claims that byte. Schedule fact:
      this now gates step 4 of that spec's implementation order.
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

**Decided 2026-08-28 — the rate architecture** (Manuel, after working the
producer/transport model through; spec: `docs/interfaces/stream-packet-format.md`):

- **Lossless-by-margin (option A).** Production rate is set *below* measured
  transport capacity — `λ_aggregate < μ_low`, with margin `m` ≥ the stall duty
  cycle — and v1 claims zero sample loss for a stated duration at a stated rate.
  The alternative considered and rejected was "loss-accounted": run at the full
  nominal rate and report every loss. Rejected because a complete recording is
  worth more to every downstream analysis than a round sample-rate number, and
  because **30,000 SPS is a target, not a requirement** — A.6.5's sidecar records
  the actual rate either way.
- **Build the loss-accounting machinery anyway.** The counters that would have
  reported loss under option B are the same counters that *prove* option A's
  claim, and they are the only way to size `fifo0` and pick `m` on evidence.
- **Buffer depth and rate margin are two parameters, not one.** Depth sets how
  long a stall is survived (`B ≥ λ × T_stall_max`); margin sets how long recovery
  takes (`T_recover = T_stall / m`). Depth is already adequate (~205 ms headstage
  vs. a ~22 ms worst measured stall); margin is ~0.69% and is what fails. This is
  why the 2026-08-03 mblock fix does not apply a second time — that was a
  variance fix for a variance problem, and this is a mean-rate problem.
- **Store-and-forward through multi-second outages is foreclosed for v1** — it
  needs ~120 kB/s of headstage buffering the WB09's 64 KB cannot provide. It is a
  headstage-storage feature, not a tuning parameter. Margin is therefore the only
  free lever, which is what makes the invariant above an invariant.
- **Packet rate must not depend on channel count** (Manuel's argument, correct —
  and it followed from a proposal already on the table). A packet carrying an
  absolute stream position no longer needs whole-frame packing, so payload is
  always full and `packets/s = aggregate_bytes/s ÷ 236` in *every* mode. This
  retracts the "8ch@7.5k is infeasible at 60 kSPS aggregate" finding raised the
  same day: under the v1 format it costs exactly the same 508.5 pkt/s as 2ch@30k.
  Larger payoff: **B.4 characterisation no longer multiplies by the number of
  modes** — `μ_low` measured once applies to all of them.

**Spec AGREED 2026-08-28** (`docs/interfaces/stream-packet-format.md`), with four
further decisions taken in the agreement pass: **no header CRC** (wrong layer —
BLE already protects that hop; the bridge UART frame CRC in B.2 is the right
place); **telemetry gets its own `0xFFF4` characteristic** rather than riding
`0xFFF3` unsolicited; **`mode_id` changes require streaming stopped**, matching
`SET_CHANNELS`; **`sample_index` stays `uint32`**, accepting a 19.9 h wrap with a
modular-comparison requirement on receivers. Two non-blocking questions remain
(`T_fill_max` per mode, needed only before the first low-rate mode; and whether
`μ` is truly payload-size-independent, to be confirmed during step 3's
measurement). **Implementation is unblocked and follows the spec's §9 order** —
`fifo0` counter, then telemetry, then measure, then the format.

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
