# RHD2164 chip0 non-responsiveness — placement investigation

**Status: RESOLVED 2026-08-24.** Root cause: unconstrained FPGA placement of
the `spi1_rhd2164x2` block, which drifted to a worse location as design
complexity grew across builds — not a PCB signal-integrity issue, not a
timing-margin issue, not a functional/logic regression. Fixed by pinning
`spi1_rhd2164x2` (and `controller0`) to fixed physical regions via
`ldc_create_region`/`ldc_set_location` in `impl_1.pdc`. Verified by
restoring the *entire* original design, one block at a time, with placement
pinned — both chips stayed responsive throughout, confirmed via real
channel data (not just digital toggling) in the pc-app.

**Purpose.** Records the investigation and the several hypotheses tested
and ruled out along the way, so a future session (including future Claude,
which has no memory of this one) doesn't re-derive or re-test them from
scratch. Distinct from, but triggered by, the SPI1 timing-constraints work
in `fpga-timing-constraints.md` — that work fixed real STA setup/hold
violations on MISO/MOSI/CSB; *this* investigation is about why chip0
specifically never responded to any command at all, a functional bring-up
problem uncovered while hardware-verifying that fix.

---

## 1. Background

First observed 2026-08-11, during the A.1.1 verification ladder's bench
run (see PLAN.md Phase A.1.1, the "BENCH RESULTS 2026-08-11" block):
**chip0's MISO (`spi1_miso0`, pin G3/LVDS3P) read a stable `0xFFFF` on both
DDR halves, no spread across 64 frames.** Chip1 answered correctly on the
same shared `csb`/`sck`/`mosi` bus, so the FPGA's commands, clock, and
chip-select were all known-good — the fault was isolated to something
specific to chip0. Leading suspect at the time: a physically broken LVDS3
receive pair (comparator stuck at one rail). Recorded as "not a v1
blocker" (64 channels remain, v1 needs 2) but flagged as needing
resolution before any 128-channel claim.

Reopened 2026-08-24, after landing the SPI1 timing-constraints fix
(pipelining `rx_a_en`/`rx_b_en`/`csb` — `fpga-timing-constraints.md` §6):
chip0 was still unresponsive on the bench. The motivation shifted from
"close STA margins" to "actually bring chip0 alive."

---

## 2. Hypotheses tested and ruled out

### 2.1 SCK-MOSI dephasing, checked via oscilloscope (indirect)

Initial hypothesis: PCB trace-length differences between chip0 and chip1
cause SCK/MOSI to arrive skewed at chip0 specifically, so it never
correctly latches a command. Checked by routing `spi1_miso0`/`spi1_miso1`
through the FPGA to debug test points (`serial_lvds_tx`/`serial_lvds_rx`)
for scope viewing. Result: `spi1_miso0` reads a constant `1`, `spi1_miso1`
toggles normally — consistent with, but not able to *prove*, the skew
theory.

**Important limitation, identified during this check:** any signal routed
through an FPGA input pin to a test point has already passed through the
LVDS receiver's comparator, which converts a small differential swing into
a clean rail-to-rail digital level. Ringing, overshoot, and reflection
artifacts on the copper are erased by that conversion before they reach a
test point. This method can show *whether* a signal is toggling, but
cannot show *why* it isn't — it can't distinguish a skew problem from a
reflection problem from a stuck receiver. No direct (pre-comparator) probe
access was available on this board.

### 2.2 PCB multi-drop bus topology / reflections at chip0

Traced the actual routing in `kuntur144-nil.kicad_pcb` (the bottom board —
the RHD2164 chips are *not* on `kuntur144-ecl`, the FPGA/MCU board).
Findings, via net-to-pad text parsing (reliable) and an attempted
segment-length extraction (unreliable — see below):

- `SCLKp/m`, `MOSIp/m`, `CSbp/m` are each a **single shared net** touching
  four pads: the board-to-board connector (`J2`), chip0 (`U0`), chip1
  (`U1`), and a populated 100 Ω termination resistor (`R4`, `R5`, `R3`
  respectively) — a genuine multi-drop bus, not independent point-to-point
  routing to each chip. Matches the RHD2000 series datasheet's recommended
  100 Ω LVDS termination for CS/SCLK/MOSI.
- `MISO0p/m` and `MISO1p/m` are each a clean two-terminal net (`J2` + one
  chip only) — point-to-point, no shared termination, no stub.
- `U0` = chip0 confirmed directly (its `MISO0` net only touches `J2` and
  `U0`). `U1` = chip1. The two chips sit 16 mm apart, mirror-imaged
  (`U0` rotated -90°, `U1` rotated +90°).
- Topology confirmed (Manuel, visual inspection in KiCad) to be a T/star
  junction from `J2`: the termination resistor's branch uses the top
  copper layer, chip0's branch uses layer 3, chip1's branch uses layer 4.
  Measured length difference: chip1's branch is **2.5 mm longer** than
  chip0's; the termination resistor sits closer to chip0.

An automated attempt to extract precise routed trace lengths (Python
script parsing the KiCad S-expression file, building a placement + routing
graph) hit an unresolved ~5–6 mm systematic error in BGA pad position
calculation and was abandoned as unreliable — the qualitative topology
finding (multi-drop bus, chip0 vs chip1 asymmetric branch position) is
solid; the specific length numbers from that script are not and were
discarded in favor of Manuel's own visual measurement (2.5 mm) in KiCad.

**Magnitude check that undercut this hypothesis:** 2.5 mm of extra FR4
trace is roughly 15–20 ps of propagation delay (~6–8 ps/mm) — three orders
of magnitude smaller than the several nanoseconds of margin the SPI1
timing-constraints fix had already established (MOSI ~11 ns, CSB ~1.5 ns
at the time). Too small to explain total non-responsiveness via simple
propagation-delay skew. The *direction* of the topology (chip0 closer to
the source, termination resistor closer to chip0, chip1 on the longer
branch) also doesn't cleanly match the simple "near tap sees stub
reflections, far/terminated tap is clean" story once the exact T-junction
geometry (§2.2) is accounted for — depends on where the true electrical
end of each branch actually is, which wasn't resolved further because the
investigation moved on (§2.5 below made the whole SI-at-chip0 line of
reasoning moot).

### 2.3 Timing margin scaling (`TIMING_MARGIN_PCT`)

`impl_1.sdc`'s margin knob (see `fpga-timing-constraints.md` §1) tried at
2% — no change. Tried at 100% — produced an STA violation, which turned
out to be a **structural artifact of the SDC**, not a real finding: the
external RHD delay budgets (`miso_delay_max`=15 ns, etc.) are fixed
physical numbers that don't scale with the margin knob, only `clk`'s
*target* period does. At 100% margin, `clk`'s target period drops to
~11.2 ns — smaller than MISO's 15 ns external budget alone, making the
check structurally unsatisfiable regardless of routing quality. Crossover
point is `TIMING_MARGIN_PCT ≈ 50%` (`22.447 / 15.0 ≈ 1.5`); margin values
past that stop meaning anything about real routing headroom. Recorded here
so this doesn't get re-discovered and mistaken for a real result.

### 2.4 `DELAYA`/`DELAYB` output-delay primitives

Researched as a way to add a small, targeted, tunable delay to
`spi1_mosi` relative to `spi1_sck`, to compensate for a hypothesized
board-level skew specific to chip0. Reference:
`FPGA-TN-02097-2-0-CrossLink-NX-HighSpeed-IO-Interface.pdf`
(`~/Downloads` — **not** covered by the sysIO User Guide, which only
covers electrical buffer properties).

- Confirmed `DELAYA`/`DELAYB` work on **output** paths, not input-only as
  initially unclear: *"The DELAY block can be used to delay the input
  data ... OR to delay the output data from the ODDR, OREG or FPGA fabric
  to the output pin."* The delay resource is shared per-pin between input
  and output use, but `spi1_mosi` is output-only, so no conflict.
- `DELAYA`: dynamic. Port `A` (data in, from pin or output register),
  port `Z` (delayed data out, to pin or input register). Fine delay:
  `DEL_VALUE` 0–127 × 12.5 ps (~1.6 ns range), runtime-adjustable via
  `MOVE`/`DIRECTION`/`LOADN`. Optional coarse delay: `COARSE_DELAY_MODE`
  (`STATIC`/`DYNAMIC`) + `COARSE_DELAY` (`0NS`/`0P8NS`/`1P6NS`) — up to
  ~3.2 ns total combining fine + coarse.
- `DELAYB`: same port shape, static only (`DEL_VALUE`/`DEL_MODE`
  attributes at build time, no runtime control, no coarse option).
- `DEL_MODE="USER_DEFINED"` is the relevant mode for this use (the other
  modes — `SCLK_ZEROHOLD`, `ECLK_ALIGNED`, `DQS_*`, etc. — are for DDR
  memory interfacing).

**Not implemented** — the investigation moved to the clock-speed test
(§2.5) before this was tried, and turned out not to be needed. Kept here
as a verified reference (port list, attributes, actual instantiation
shape) in case a fine-grained output-delay correction is ever needed
again — this took real effort to track down (the primitive isn't in the
more obvious sysIO User Guide) and shouldn't need re-finding.

### 2.5 Clock speed / signal-settling time

Two tests, both decisive:

- `clk = clkin` directly (PLL bypassed, 32 MHz instead of 44.55 MHz) —
  chip0 still dead.
- `pll0` IP reconfigured to output 10 MHz instead of 44.55 MHz
  (`pll0.cfg`/`pll0.ldc`: `gui_clk_op_freq`/`CLKOP_FREQ_ACTUAL` changed to
  `10.0`) — chip0 still dead.

Slowing the design by more than 4× and still failing rules out any
timing-margin or signal-settling explanation — at 10 MHz, any board-level
skew or reflection ringing has an enormous amount of time to settle
within a bit period. Combined with Manuel's direct memory of chip0
working correctly at some earlier point, this also weighs against the
original physically-broken-pin hypothesis (a truly open/shorted receiver
wouldn't care about clock speed and would never have worked at all).
This result is what redirected the investigation from "signal integrity /
timing" toward "something functional changed" (§2.6), and ultimately
toward placement (§2.7).

### 2.6 Logic content / functional regression

Manuel stripped `kuntur_fpga.v` to a minimum: PLL bypassed (`clk=clkin`),
`spi1_rhd2164x2.start` tied permanently to `1'b1` (continuous back-to-back
transfers, no pacing FSM), `spi0`/`regbank`/`fifo`/`main_controller`/
`ch_sel`/`controller0` all removed, `spi1_miso0`/`spi1_miso1` routed
directly to debug test-point outputs. **Both chips responded in this
minimal configuration** — ruling out a fundamentally broken board or
`spi_master_rhd2164x2` interface, and isolating the bug to something in
the logic that had been stripped out.

Two specific candidate mechanisms were investigated and ruled out before
the pivot to placement:

- **`rhd2164_controller`'s pacing.** Traced the `start`/`done` handshake
  precisely (`components.v`, `rhd2164_controller`): `rhd_start` pulses one
  cycle (`op0b`/`op1b`), then the FSM waits ~4 more cycles
  (`op0d`→`op0a`→`op0b`) after seeing `rhd_done` before re-pulsing
  `start`. Combined with `spi_master_controller`'s own ~8-cycle
  `csbend0..csbend7` tail, the **full/paced design gives ~12 clk cycles of
  CS-high recovery time — *more* than the ~9 cycles the tied-high
  continuous-loop hack gives.** That's the opposite of what a
  `tCSOFF`-violation theory would predict, ruling against a pacing-gap
  explanation.
- **Configuration content, specifically `CALIBRATE`.** The RHD2000 series
  datasheet requires `CALIBRATE` be sent exactly once and states the chip
  ignores all other commands until calibration completes — an easy thing
  for sequencing to get subtly wrong per-chip. Found `RHD_CALIBRATE`
  (`intan.vh:40`) at config-table word 24 (`components.v:545`). Flagged as
  a candidate but never tested in isolation — superseded by the full
  incremental restoration (§3) passing with the real config table
  (including `CALIBRATE`) intact.

### 2.7 Unconstrained FPGA placement — CONFIRMED ROOT CAUSE

Manuel's hypothesis, from watching Radiant's floorplan view:
`spi1_rhd2164x2`'s physical placement on the die was never pinned, and
appeared to shift across builds as surrounding logic changed. Fix
mechanism: `ldc_create_group` / `ldc_create_region` / `ldc_set_location`
(Lattice app note FPGA-AN-02059, "Radiant Timing Constraints Methodology,"
§8.1–8.3) — physical (post-synthesis) constraints, so they belong in
`impl_1.pdc`, not `impl_1.sdc`. Generated via Radiant's Physical Designer
GUI (selecting the placed cells directly) rather than hand-typed, since
there was no reliable way to read exact site coordinates from a
screenshot or from the available text reports (`.mrp`/`.par` don't carry
per-instance placement; the real database is the binary `.udb`).

Landed in `impl_1.pdc`:

```
ldc_create_region -name macro_region_0 -anchor R20C66 -width 8 -height 8
ldc_set_location -region macro_region_0 [get_cells spi1_rhd2164x2]
ldc_create_region -name macro_region_1 -anchor R17C66 -width 8 -height 2
ldc_set_location -region macro_region_1 [get_cells controller0]
```

`controller0` (`rhd2164_controller`) was pinned too, once it was restored
in the incremental sequence below, adjacent to `spi1_rhd2164x2`'s region
— keeping the block that directly paces the RHD2164 link physically close
to it as the rest of the design was added back around them.

---

## 3. Verification: systematic incremental restoration

With placement pinned, the entire original design was restored one block
at a time, testing on hardware after each step — specifically to separate
"did pinning the placement fix it" from "was it actually one of the §2.6
logic-content hypotheses all along, and the placement pin is a red
herring." Order, every step confirmed both chips responding before moving
to the next:

1. **PLL restored to the real 44.55 MHz** (from the 10 MHz test config) —
   works. Rules out a clock-speed interaction with the new placement.
2. **`rhd2164_controller` (`controller0`)** — real `start`/`done` pacing
   restored — works. Empirically confirms §2.6's pacing-gap analysis.
3. **`regbank`** (the RAM, real config table content, including
   `CALIBRATE`) — works. Directly rules out the `CALIBRATE`/config-content
   hypothesis from §2.6.
4. **`ch_sel`** — works.
5. **`main_controller`, `fifo`, `dtx_mux_reg`** — works.
6. **`spi0`** (the MCU interface — the single largest remaining addition,
   and the one most likely to create real placement/routing pressure) —
   works.

Final state: the complete original design, `spi1_rhd2164x2` and
`controller0` pinned to fixed regions, both chips responding — confirmed
via **real channel data in the pc-app** (channels 42 and 88), not just
digital SPI toggling. Per the friendly-channel mapping established
2026-08-11 (PLAN.md A.1.1: friendly channels 0–63 = chip0, 64–127 =
chip1), channel 42 falls in chip0's range and channel 88 in chip1's —
genuine, distinct analog data flowing from both chips end-to-end.

---

## 4. Conclusion

Root cause: **unconstrained placement of `spi1_rhd2164x2`**, which
drifted to a worse location as surrounding design complexity grew across
builds — not a PCB signal-integrity issue, not a timing-margin issue, and
not a functional/logic regression. All of §2.1–2.6 were reasonable,
evidence-driven hypotheses given what was known at each point, and each
was cleanly ruled out by a concrete test rather than abandoned on a hunch.

**What's established:** pinning `spi1_rhd2164x2`'s (and `controller0`'s)
placement is necessary and sufficient to keep both chips working across
the full range of logic-content variation tested (§3). **What's not
established:** the exact physical mechanism by which a different,
unpinned placement specifically breaks chip0 and not chip1 — that would
need a routing-length/skew comparison between a known-bad and known-good
placement, which wasn't done (once the fix was confirmed, the priority
was verifying it holds, not fully explaining the physics).

---

## 5. Open items

- [ ] **Clean up `kuntur_fpga.v`'s exploratory scaffolding before
      committing.** The file currently has restored real logic and dead,
      commented-out "TESTING ONLY" remnants intermixed: an old
      `//assign clk = clkin;` bypass line left behind next to the real
      restored `ifdef SIM`/`pll0` structure, `//.start (1'b1)` and other
      commented-out overrides next to their restored real connections,
      and `serial_lvds_tx`/`serial_lvds_rx`/`cmd_is_00` still wired to the
      `spi1_miso0`/`spi1_miso1`/`fifo_full` debug taps used during this
      investigation rather than their original purpose. Decide whether to
      keep the debug taps (they're useful) or restore the original wiring
      before commit — either way, delete the dead commented-out code
      rather than leaving it as a trap for a future reader.
- [ ] **Not independently verified: a from-scratch synthesis.** All
      testing here started from an already-pinned, already-good placement
      and added logic incrementally on top of it. The region constraints
      should force the same outcome regardless of starting point, but a
      clean-room rebuild (delete `impl_1/` build products, resynthesize
      from source with the region constraints present from the start)
      would be good confirmation this isn't an artifact of incremental
      P&R reuse.
- [ ] **Not independently confirmed: whether other blocks need their own
      region constraints** for long-term robustness as the design keeps
      evolving, or whether pinning just `spi1_rhd2164x2` + `controller0`
      is sufficient. Worked for this specific sequence of additions;
      unverified against future, unrelated RTL growth elsewhere in the
      design.
- [ ] **`RHD_CALIBRATE`-specific isolated test was never actually run** —
      superseded by the full `regbank` restoration passing in §3. Low
      priority now that the config table as a whole is confirmed fine,
      noted for completeness only.
- [ ] Regbank FPGA area (large, ~4096 FFs from word-by-word async-reset
      initialisation forcing flip-flop inference instead of EBR) — noticed
      during this investigation's floorplan work, tracked separately in
      PLAN.md Phase B.1, deliberately deferred until after this
      investigation to avoid confounding the placement experiment.
