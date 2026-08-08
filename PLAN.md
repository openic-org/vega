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

Ordered tasks, each with a numeric pass/fail:

- [ ] **A.1.1a — Link integrity & DDR demux.** `READ(59)`; expect 53 on `data_a*`,
      58 on `data_b*`, both chips. Proves MISO timing, DDR split, and that the four
      `ch_sel` inputs map to the right chip and half.
- [ ] **A.1.1b — Pipeline offset.** `READ(40..44)` in consecutive slots; expect
      `INTAN` arriving two slots later. Pins the offset down numerically.
- [ ] **A.1.1c — Chip identity.** `READ(63/62/61)` → 4 / 64 / 1, per chip. Also the
      FPGA-side half of B.6's `doctor`.
- [ ] **A.1.1d — Slot→channel alignment.** `ch_sel` selects by timing `ch_cnt`
      against the SPI0 output stream, so the two-command offset must be accounted
      for in that alignment for `ch_a`/`ch_b` to mean the channel they name.
- [ ] **A.1.1e — Connect `dout`** to `data0_synced`/`data1_synced`. Only meaningful
      once (d) holds.
- [ ] **A.1.1f — ADC path.** Enable VDD sense, convert channel 48 on module A,
      expect ≈44,100 at 3.3 V. First real analog value end to end.

**A.1.4 (placeholder command slot) comes first** — (a), (b), (c) and (f) all need a
way to put an arbitrary command into the sampling cycle, which is exactly what that
33rd slot is for. It is the enabler for this ladder, not a side task.

- [ ] **A.1.1g — Widen regbank access so any word is MCU-readable/writable at
      runtime.** Decided 2026-08-07, prerequisite alongside A.1.4. Two limits:
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

      A `REG_READ` ignores its address field and returns `ram[addr_reg]`. It does
      **not** auto-increment — repeated reads stay idempotent, and a `doctor`
      self-test can simply send the address it wants. There is no auto-increment
      on write either: the positional sequence restarts with an address load
      every time, so there would be nothing to exploit.

      **Transfer lengths — multi-transfer structure only where something forces
      it** (settled 2026-08-08, after finding that `NOP` and `REG_READ` were both
      built as mandatory 2-transfer pairs):

      | Command | Transfers | Why that length |
      |---|---|---|
      | `REG_WRITE` | 3 | Inherent — address, high byte, commit. Tag-checked at each stage |
      | `FIFO_POP` | 2 | Inherent — ChA then ChB. Second transfer must also be `POP`, so a broken pair fails loudly rather than half-consuming a FIFO entry |
      | `REG_READ` | 1 | Nothing to sequence; the value lands on whatever transfer follows |
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
      transfer count with a NOP" rule obsolete. **Not yet confirmed in
      simulation** — verify before deleting the rule from the spec.

      **Two assertions the T2 testbench should carry**, both of which are
      unverifiable by reading the source:

      1. **The pairing claim — the valuable one.** Interleave a `REG_WRITE`
         sequence and a `REG_READ` between `FIFO_POP` pairs and assert ch0/ch1
         come back unswapped. Confirming this retires three workarounds on the
         MCU side at once: the even-batch rule, `FPGA_SPI_Init()`'s priming
         transfer, and the NOP padding. It is also the closest thing to a direct
         test for the historical 32-bit FIFO channel-swap bug.
      2. **Read-path settling.** `addr_reg` is written in the port-register
         always block while `dout0 <= ram[addr_reg]` reads it in another; confirm
         the value presented on MISO is the one for the address just loaded, not
         the previous one.

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

      **Worth checking before compacting further:** the regbank is initialised
      word-by-word under an asynchronous reset, which forces flip-flop inference
      rather than EBR — if so, 256×16 is ~4096 FFs of fabric and unused words are
      not free. Confirm against the utilization report. If it did infer block
      RAM, the holes cost nothing and the argument is purely clarity. A follow-on
      option, deferred: split into three memories sized to purpose (config,
      sampling, control), which matches how they are actually used — config
      written once at boot and read sequentially, sampling read every frame,
      control random-access driving combinational taps. They share one RAM out of
      convenience, not behaviour.

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
- [x] **SPI0 opcode decode, 4-way** — landed 2026-08-06 with A.2.
      `main_controller` now decodes all four: `00` FIFO pop, `01` regbank write,
      `10` regbank read (new read path to the TX mux), `11` NOP. The paired
      MCU-side fix landed with it — `FPGA_STREAM_CMD` `0xA5A5` → `0x2525`, so a
      streaming FIFO pop no longer carries the `10` opcode by accident. Verified
      on hardware via the A.2 readback round-trip.
- [ ] **Wire the sampling-cycle placeholder command slot** — **do this first; it
      is the enabler for the A.1.1 verification ladder above.** Confirmed
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
      (regbank word 164, bit 0) ANDed directly into `fifo_wen` in `ch_sel`, reset
      default `1`.
- [x] **MCU** — 0xFFF1 handler for `SET_CHANNELS`/`STOP_STREAMING`/`START_STREAMING`,
      all SPI0 work deferred off the BLE event-handler callback ·
      `FPGA_SPI_{SetChannels,ReadChannels,SetStreamEnable,ReadStreamEnable}` ·
      0xFFF3 type-prefixed command-response notify, backed by an actual SPI0 readback
      rather than "the write call didn't error" · `s_command_busy` reentrancy guard
      making one STOP/SET/START cycle atomic with respect to the next · streaming
      dummy TX word `0xA5A5` → `0x2525`, so a FIFO pop can't decode as a reg read.
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
> 3-transfer sequence, `REG_READ` no longer carries an address, and
> `ch_a`/`ch_b` move from offsets 4/5 to RAM words 196/197. Every MCU helper
> A.2 depends on (`FPGA_SPI_SetChannels`, `SetStreamEnable`,
> `ReadStreamEnable`, `ReadChannels`) is rewritten as a result. The
> hardware-verified result above was obtained against the *old* protocol, so
> **"complete" here means complete-as-of-2026-08-06, not still-verified.**
> The full STOP → SET_CHANNELS → readback → START round-trip needs re-running
> on the bench after the new bitstream and firmware are flashed together —
> including the repeat-click reliability pass, since the transfer counts and
> FSM timing both change.

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

- [ ] **RTL testbench coverage.** Recorded 2026-08-08 as a deliberate deferral,
      not an oversight: the Phase A testbenches (`kuntur_tb.v`) check basic
      functional behaviour only — they are bring-up aids, driven and read as
      waveforms, with no self-checking assertions and no coverage goal. That is
      the right trade while bench time is the constraint and the RTL is still
      moving. Phase B needs the other thing: self-checking testbenches with
      pass/fail output, coverage of the SPI0 command FSM's abort and desync
      paths (which is where A.1.1g's tag checks live and where a regression
      would be silent), an RHD2164 model that implements the two-command
      pipeline and the ROM registers rather than four canned values, and these
      wired into the CI checks below so a red run blocks a merge.
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
