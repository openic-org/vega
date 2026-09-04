# FPGA timing constraints — RHD2164 SPI1 link — interface spec

> ⚠️ **UNDER REVIEW, 2026-09-04.** This document's conclusion was
> confirmed by a **single hardware pass**. On 2026-09-04 chip0 was shown
> to be **intermittent over a timescale of hours** — it failed twice on a
> cold board, then recovered with no power cycle, no reflash and no
> command (PLAN.md A.1.2). On a system that behaves that way a single
> pass cannot distinguish a fix from a lucky boot, and the debugging loop
> that produced this document had a systematic bias toward false
> confirmation: change RTL on a cold board, observe failure, debug for
> hours while it warms, observe the "fix" working.
>
> **Read the ruled-out hypotheses here with that in mind** — several were
> ruled out by single observations and may need re-testing. The root
> cause recorded below is *unsupported*, not *disproven*; it may still be
> right, but the evidence for it does not currently establish that.


**Status: CONSTRAINTS + STRUCTURAL FIX LANDED AND VERIFIED, 2026-08-24.**
Constraints written and iterated against actual Radiant STA output (not
just derived by hand). First run found a real, small setup violation on
the MISO capture path, root-caused to §2's round-trip budget. Manuel
pipelined `rx_a_en`/`rx_b_en` (§6) — fixed MISO/hold, but tightened
`spi1_csb` to near-zero margin as a side effect (§5.4). Pipelined `csb`
itself the same way — **all four SPI1 signals (MISO/MOSI/CSB) now carry
>1.5 ns of setup margin, setup and hold both clean (0 endpoints, 0.000 ns
negative slack, all corners) — see §5.5.** Manuel's simulation pass
confirmed the pipelining didn't shift A.1.1's `SLOT_OFFSET = 3`
slot-to-channel mapping. Remaining open item (§7): a simulation check on
the `csb` pipelining specifically (the `rx_a_en`/`rx_b_en` one already
got that check). Board/cable trace numbers were deliberately left at the
1.5 ns placeholder — no equipment to measure at that resolution, and not
load-bearing now (§7). **This spec covers SPI1 only** — the rest of the
design (`spi0`, async reset recovery/removal, `serial_lvds_tx`/
`cmd_is_00`) remains unconstrained; tracked as a separate PLAN.md Phase
B.1 item, "FPGA timing constraints — remaining pins."

**Purpose.** `source/impl_1/impl_1.sdc` (Radiant pre-synthesis constraints)
and `source/impl_1/impl_1.pdc` (physical/placement constraints) had no real
timing intent behind them before this — no `create_clock` at all, and a
`set_clock_uncertainty` line referencing a clock that was never created.
Every path in the design, including the RHD2164 MISO/MOSI/CSB SPI timing,
closed on whatever the router happened to do. This spec is the record of
what was added, why each number is what it is, and what it found —
written so the next person (including future Claude, which has no session
memory) doesn't have to re-derive the clock topology or re-discover the
Radiant syntax gotchas from scratch.

Board/cable delay is an **estimate** (1.5 ns, §3), not a measurement —
resolving PCB delay at this timescale needs an oscilloscope sampling in
the 10s of GSa/s, not equipment on hand, so this is an equipment ceiling
rather than a priority call. Independent of that estimate's accuracy, the
`rx_a_en`/`rx_b_en`/`csb` pipelining fix (§6) moved SPI1's outputs off
combinational logic onto a direct register-to-pad path, which buys
structural margin against PCB delay regardless of what the real number
turns out to be (§9.2).

Companion: `PLAN.md` Phase B.1 (pointer only, no content duplicated there
per working principle — see the memory note on this).

Files touched, both in the `kuntur` repo:
`kuntur144/fpga/kuntur_fpga/source/impl_1/impl_1.sdc` (all timing
constraints) and `.../impl_1.pdc` (physical constraints; cleaned of two
stale `lvdsp`/`lvdsp2` lines that referenced ports no longer in
`kuntur_fpga.v`, otherwise untouched — Radiant classifies `.sdc` as
"Pre-Synthesis Constraints" and `.pdc` as "Physical Constraints" per
`kuntur_fpga.rdf`, and timing intent belongs in the former).

---

## 1. Clock topology

| Clock | Period | Frequency | How declared |
|---|---|---|---|
| `clkin` | 31.25 ns | 32 MHz | `create_clock` on the port. From the STM32WB0 MCO3/PB14. |
| `clk` | 22.447 ns | 44.55 MHz | `create_clock` directly on the net (see below), not `create_generated_clock` from `clkin` |
| `spi1_sck` | 44.893 ns | 22.275 MHz | `create_generated_clock -divide_by 2 -source [get_nets clk]` on the port |

**Why `clk` is a direct `create_clock`, not a generated clock off
`clkin`.** `clk` is `pll0`'s `CLKOP` output (`pll0/pll0.cfg`:
`gui_clk_op_freq 44.55`; `pll0/constraints/pll0.ldc`:
`CLKOP_FREQ_ACTUAL 44.550000`). The PLL is fractional-N (`FRAC_N_EN=1`,
44.55/32 is not an integer ratio), so `create_generated_clock
-multiply_by/-divide_by` off `clkin` can't express the relationship
exactly. Constraining `CLKOP` directly is what Lattice's own IP constraint
templates do for fractional-N PLLs. `clkin` fans out only to the PLL
primitive — no user logic is clocked directly by it — so there is no
register-to-register path between the `clkin` and `clk` domains for
Radiant to check, and no clock-group statement is needed between them.

Radiant does emit a warning on this: `WARNING "70009502" - The preferred
point for defining clocks is top level ports and driver pins. Pad delays
will not be taken into consideration if clocks are defined on nets.` This
hasn't produced wrong numbers in practice (there's no pad between the PLL
and the `clk` net), but switching to constraining the PLL's `CLKOP` pin
directly (visible in path traces as
`mypll.lscc_pll_inst.gen_no_refclk_mon.u_PLL.PLL_inst/CLKOP`) would silence
it cleanly if it ever matters. Not done yet.

**`spi1_sck` is decoded combinationally**, not driven by a toggle flop —
`spi_master_controller`'s FSM (`spi_controllers.v`) drives `sck=1` during
`sckNb` states and `sck=0` during `sckNd` states, one `clk` cycle each, for
as long as a burst is shifting. `-divide_by 2` is an *assertion* about the
FSM, not something Radiant can derive: it holds during the shift states,
which is the only time it needs to.

**Margin knob — `TIMING_MARGIN_PCT`, top of `impl_1.sdc`, default 0.**
Found empirically (Manuel, pre-2026-08-24): tightening `clkin`'s
constraint alone — before any of the below existed — made a `tMOSI`-margin
problem go away, even with no explicit constraint on `spi1_mosi` at all.
`clkin` fans out only to the PLL, so the only way that works is if Radiant
derives `clk`'s STA timing from `clkin`'s constraint using the PLL's real
configured ratio; tightening the input proportionally tightens `clk`,
which tightens every `clk`-domain path system-wide. `TIMING_MARGIN_PCT`
scales both `clkin`'s and `clk`'s declared periods together by the same
factor, reproducing that mechanism deliberately. **It only buys margin on
the FPGA-internal portion of the round trip** (§2's `sck` decode, capture-
flop setup, MOSI clock-to-out) — it does not touch the external, physical
part of the budget (RHD `t_co`, `tMOSI`, or the board/cable delays in §3),
which are fixed by the chip and the PCB, not by synthesis effort. Leave at
0 for any run meant to answer "does this actually work at the real
frequency" — that's the whole point of this constraint set. Use it to
guardband a *chosen* structural fix (§6) afterward, not as a substitute
for picking one.

---

## 2. Round-trip budget

The capture flops (`sr_s2p` in `spi_controllers.v`) are clocked by `clk`,
not by `sck`, and the FSM samples MISO on the very next `clk` edge after
each `sck` edge. So the entire round trip —

```
T_sck_out (FPGA sck generation + pad)
  + T_pcb_out (FPGA -> RHD)
  + T_co_RHD (RHD's internal SCLK-to-MISO delay)
  + T_pcb_in (RHD -> FPGA)
  + T_route_in (FPGA input pad + routing to the capture flop)
  + T_setup
```

— must fit inside **one `clk` period, 22.447 ns**. This is tight by
construction (see §5 for what the real STA numbers say), and is the
structural reason this whole exercise exists: PLAN.md flagged this
round-trip as "the most likely root of the margin-sensitive behaviour
recorded throughout the SKP investigation" before any constraint existed
to check it.

MOSI and CSB have the analogous, DDR/multi-edge relationships worked out
in §4.

---

## 3. RHD2164 datasheet timing (verified against source PDFs)

`/data/projects/iris-128/iris-128s/pcb/datasheets/`:
`Intan_RHD2000_series_datasheet.pdf` p.15, "SPI BUS TIMING
SPECIFICATIONS" table (`T_A = 25C, V_DD = 3.3V`):

| Symbol | Parameter | Min | Max | Notes |
|---|---|---|---|---|
| `tSCLK` | SCLK period | 40 ns | — | max SCLK freq 25 MHz |
| `tSCLKH`/`tSCLKL` | SCLK pulse width high/low | 20 ns | — | |
| `tCS1` | CS low to SCLK high setup | 20 ns | — | |
| `tCS2` | SCLK low to CS high setup | 20 ns | — | |
| `tCSOFF` | CS high duration | 154 ns | — | |
| `tMOSI` | MOSI data valid to SCLK high setup | 10 ns | — | verified directly against the datasheet image, not just extracted text — see the correction note below |
| `tMISO` | SCLK or CS falling edge to MISO data valid | — | 12 ns | |
| `tCYCLE` | total cycle time between ADC samples | 950 ns | — | |

**`tMOSI` correction, 2026-08-24.** A value of 10.4 ns was recalled from
memory during this work and didn't match what the datasheet actually
shows — pulled the page as an image to check directly (not just
`pdftotext`, which can silently misplace numbers in tabular layouts): it's
**10 ns flat**, no separate max. Recorded here specifically so a future
session doesn't re-introduce 10.4 ns from the same faulty memory.

Device is **LIFCL-17-8UWG72C** (CrossLink-NX, speed grade 8), so
`DELAYA`, `IDDRX1F`, and phase-shifted PLL outputs are all available if
needed for §6.

**Board/cable delay placeholders — NOT yet extracted from real trace
lengths or a bench measurement.** `pcb_sck_ns`, `pcb_mosi_ns`,
`pcb_miso_ns`, `pcb_csb_ns` are all set to `1.5` (ns, one-way) in
`impl_1.sdc`. The link runs over uHDMI (`kuntur144-omnetics`). §5.3 shows
exactly how much this placeholder currently matters — replace with a real
number (trace length from the PDC route report, or a bench measurement of
the cable) before trusting reported slack on the margin-sensitive paths.
A wrong constraint here still reports a clean STA run, which is why this
is flagged explicitly rather than left implicit.

**Deliberately conservative choice, kept consistent across MISO/MOSI/CSB:**
none of the per-signal board-delay placeholders are netted against each
other (e.g. `T_pcb_mosi - T_pcb_sck`), even where the algebra would allow
it if trace lengths were assumed matched. Since trace-length matching
between `sck` and the other SPI1 signals hasn't been verified, assuming
zero net skew and treating each leg additively is the safer of the two
readings — it doesn't rely on an assumption that could be wrong in either
direction.

---

## 4. MISO / MOSI / CSB constraints

All in `impl_1.sdc`. RTL line references are to
`kuntur144/fpga/kuntur_fpga/source/impl_1/`.

### 4.1 MISO (input delay)

RHD2164's MISO is DDR (RHD2164 datasheet p.9): A data launched off SCLK's
rising edge, B off the falling edge. A rising-edge-only constraint would
leave the B half of every sample unconstrained, so both edges are
constrained:

```
set_input_delay -clock spi1_sck -max 15 [get_ports {spi1_miso0 spi1_miso1}]
set_input_delay -clock spi1_sck -min 3  [get_ports {spi1_miso0 spi1_miso1}]
set_input_delay -clock spi1_sck -clock_fall -add_delay -max 15 [get_ports {spi1_miso0 spi1_miso1}]
set_input_delay -clock spi1_sck -clock_fall -add_delay -min 3  [get_ports {spi1_miso0 spi1_miso1}]
```

`15 = pcb_sck_ns(1.5) + tMISO_max(12.0) + pcb_miso_ns(1.5)`. `3 =
pcb_sck_ns(1.5) + 0(no published tMISO min) + pcb_miso_ns(1.5)`.

### 4.2 MOSI (output delay)

`sr_p2s`'s shift register (`spi_controllers.v`) updates on the `clk` edge
that also drives `sck`'s combinational output from 1 to 0 (`tx_en` fires
in the same FSM state, `sckNb`, as `rx_a_en`) — MOSI's new bit becomes
valid coincident with `sck`'s **falling** edge, matching the datasheet's
own timing diagram ("Data should change on the falling edge of SCLK",
p.15). The RHD then samples MOSI on `sck`'s next **rising** edge, one
`spi1_sck` half-period later.

```
set_output_delay -clock spi1_sck -max 11.5 [get_ports spi1_mosi]
set_output_delay -clock spi1_sck -min 1.5  [get_ports spi1_mosi]
```

`11.5 = pcb_mosi_ns(1.5) + tMOSI(10.0)`. `1.5 = pcb_mosi_ns` alone (no
published MOSI hold spec).

**No `-clock_fall` here — this was a real bug, found and fixed
2026-08-24.** For `set_output_delay`, the named clock/edge means "the edge
the *external device* uses to **capture**" — the opposite convention from
`set_input_delay`, where it means "the edge the external device uses to
**launch**". The RHD captures MOSI on `sck`'s rising edge, so the
constraint uses `spi1_sck`'s default (rising) reference. An earlier
version used `-clock_fall`, telling the tool the RHD captures on the
*falling* edge instead — wrong, and it inflated reported slack to ~12 ns
by checking against a deadline a full `spi1_sck` period too late. Caught
because Radiant's own path report showed `Destination Clock: spi1_sck
(F)`, which didn't match the intended relationship once checked against
the datasheet's own statement that RHD2000 samples MOSI on the rising
edge.

**Hold false-violation, found and fixed 2026-08-24.** With the max/min
above (and no exception), the first real STA run showed `spi1_mosi`
failing hold by -0.769 ns. Diagnosis: `clk` (fast) launches, `spi1_sck`
(2x slower, `-divide_by 2`) captures. Setup already finds the correct edge
(one full `spi1_sck` period after launch — the intended relationship, no
exception needed). SDC's hold default is different: absent a multicycle
exception, it checks against the destination-clock edge immediately
preceding the setup edge, which for a 2:1 related clock is a full
`spi1_sck` period too early — an edge that has no physical meaning here,
since MOSI only ever changes in lockstep with `sck`'s own toggling and
could never actually be sampled that early. Confirmed numerically: the
failing path's destination-clock arrival was 4.178 ns; adding one
`spi1_sck` period (44.893 ns) lands at ≈49.1 ns, matching the setup path's
reference-edge ballpark. Fixed with:

```
set_multicycle_path 1 -hold -end -from [get_clocks clk] -to [get_ports spi1_mosi]
```

Re-run confirmed it: **hold errors dropped to 0 endpoints, 0.000 ns total
negative slack**, and `spi1_mosi` no longer appears anywhere in the hold
report at all (not even near the worst-10 list) — a clean removal of the
artifact, not a marginal fix.

**Radiant `set_multicycle_path` syntax note** (Lattice app note
FPGA-AN-02059-1.5, "Radiant Timing Constraints Methodology", §3.3.4, p.21
— at `/data/nextcloud/OpenIC-Docs/Projects/OIC2603-Kuntur-EdgeComputing/datasheets/`).
The doc's own two worked examples disagree on where the bare `ncycles`
argument sits (`-from [...] 2` vs `2 -from [...] -to [...]`), so Radiant's
parser accepts it in either position — but there is **no bare trailing
object list** the way `set_input_delay`/`set_output_delay` have every
object must sit under `-from`/`-to`/`-through`. The first attempt at this
constraint left `[get_ports spi1_mosi]` bare at the end with no flag,
which Radiant rejected. Fixed by moving `spi1_mosi` under `-to` (valid per
the doc's Table 3.14: `-to` accepts clocks, ports, pins, or cells).
`-start`/`-end` semantics aren't demonstrated anywhere in the app note
with a worked `-hold` example — `-end` (count cycles from the destination/
capturing clock, standard Synopsys SDC convention) is the best-supported
inference, not something confirmed against a worked example. If a future
re-run shows the reference edge landing somewhere other than ≈49 ns, this
flag is the next thing to question.

### 4.3 CSB (output delay, two independent single-sided checks)

`csb` is combinational in `spi_master_controller`: defaults high, and
every active state (`op0` through `sck15d`) explicitly drives it low;
`csbend0`..`csbend7` don't re-drive it, so it reverts to default (high)
starting at `csbend0`. Traced through the FSM: `csb` falls the same `clk`
edge the FSM leaves `idle` (entering `op0`); `sck`'s first rising edge
follows exactly 2 `clk` cycles later (`op0` -> `op1` -> `sck0b`). `csb`
rises the same `clk` edge `sck`'s *last* falling edge happens (leaving
`sck15d`, entering `csbend0`).

```
set_output_delay -clock spi1_sck -max 21.5 [get_ports spi1_csb]
set_output_delay -clock spi1_sck -clock_fall -min 21.5 -add_delay [get_ports spi1_csb]
```

- **Falling edge** (`tCS1`, "CS low to SCLK high setup", 20 ns min):
  setup-type, checked against `spi1_sck`'s rising edge (default, no
  `-clock_fall`) — csb must be low before that edge. `21.5 =
  pcb_csb_ns(1.5) + tCS1(20.0)`. No published max and no meaningful hold-
  type pairing (csb falling earlier is harmless), so `-max` only.
- **Rising edge** (`tCS2`, "SCLK low to CS high setup", 20 ns min):
  hold-type, checked against `spi1_sck`'s **falling** edge (the true
  last-sck-edge reference for this check) — csb must stay low a minimum
  time after that edge. `21.5 = pcb_csb_ns(1.5) + tCS2(20.0)`. `-min`
  only.
- **Not modeled: `tCSOFF`** ("CS high duration", 154 ns min) — bounds the
  minimum time between the end of one transaction and the start of the
  next, which isn't a two-signal edge relationship `set_output_delay` can
  express. It's a protocol/firmware-pacing requirement on how soon
  `start` may re-assert after `csb` rises, not something Radiant STA
  checks here.

Both values land on 21.5 ns because `tCS1 == tCS2 == 20.0` in the
datasheet — coincidence of the spec, not a modeling shortcut.

---

## 5. Results — 2026-08-24 run (`TIMING_MARGIN_PCT = 0`)

Full constraint set from §4, all four signals (MISO/MOSI/CSB) constrained,
multicycle hold exception in place.

### 5.1 Overall

| Check | Corner | Errors | Total negative slack |
|---|---|---|---|
| Setup | 85°C | 2 endpoints | -0.113 ns |
| Setup | 0°C | 2 endpoints | -0.092 ns |
| Hold | 0°C (fast/min corner, "m") | 0 endpoints | 0.000 ns |

Coverage: 89.76%. Remaining unconstrained (not in scope for this pass):
`spi0` (MCU-facing SPI, separate link) entirely unconstrained · `rstb`
recovery/removal (2747 endpoints, all async-reset `LSR` pins) ·
`serial_lvds_tx`/`cmd_is_00` (uHDMI tunnel / debug, not yet built out).

### 5.2 The two failing setup endpoints (85°C corner)

Both on **MISO0** — the DDR A and B capture flops for the same physical
pad:

| Endpoint | Slack (85°C) | Slack (0°C) |
|---|---|---|
| `rxsr_b0` (MISO0, B channel) | **-0.084 ns** | -0.073 ns |
| `rxsr_a0` (MISO0, A channel) | **-0.028 ns** | -0.018 ns |
| `rxsr_a1`/`rxsr_b1` (MISO1, both channels) | +0.269 / +0.270 ns (pass) | +0.277 / +0.278 ns (pass) |
| `spi1_csb` | +0.427 ns (pass) | +0.309 ns (pass) |

### 5.3 Breakdown — is this the PCB placeholder, or something else?

Decomposed from the Radiant path report, 85°C corner, worst path
(`rxsr_b0`):

| Segment | Value | Source |
|---|---|---|
| `sck` generation (2 LUTs, `LUT4_77`->`LUT4_76`) + pad | 7.723 ns | FPGA-internal, fixed by RTL |
| External budget (`set_input_delay -max`) | **15.000 ns** | = 1.5 (PCB, sck) + 12.0 (RHD `t_co`, datasheet) + 1.5 (PCB, miso) |
| Input pad (LVDS) | 0.467 ns | FPGA-internal |
| Routing, pad -> flop | 1.068 ns | FPGA-internal, placement-dependent |
| **Total arrival** | **24.258 ns** | |
| Available (`clk` period + clk network - uncertainty + setup) | 24.173 ns | 22.446 + 1.819 - 0.125 + 0.033 |
| **Slack** | **-0.084 ns** | |

`rxsr_a0` is the same breakdown with a 1.012 ns routing leg instead of
1.068 ns (24.202 ns arrival, same 24.173 ns available). MISO1's passing
endpoints share the *identical* 7.723 ns `sck`-generation cost and 15.000
ns external budget — the only difference is a 0.714 ns routing leg
(MISO1's pad sits closer to its capture flops). That's pure floorplanning,
unrelated to the PCB/cable assumption.

**Sensitivity.** Every 1 ns added to *either* `pcb_sck_ns` or
`pcb_miso_ns` subtracts 1 ns of slack directly (additive in the external-
budget term):

- Real board/cable delay ≈ **0 ns each way** instead of 1.5: slack →
  **+2.9 ns**, comfortably passing.
- Real board/cable delay ≈ **3 ns each way** instead of 1.5: slack →
  **-3.1 ns**, a real failure.

**Conclusion.** The current -0.084 ns violation (≈80 ps) is small next to
the ±1.5 ns of uncertainty already sitting in the placeholder — getting
the real trace/cable numbers is very likely to flip this specific result
to a pass. But margin is thin even in the *best case*: at 0 ns PCB delay,
slack is only +2.9 ns out of a 22.4 ns period, because **~34% of the whole
budget (7.723 ns) is consumed by `sck`'s own combinational generation
delay before the signal even leaves the chip** — not a PCB question at
all. That's exactly the structural issue PLAN.md flagged (`sck` decoded
through LUTs, not a clean toggle flop), and real board data resolving §5.2
does not make it go away.

### 5.4 Re-run after §6's structural fix (Manuel, 2026-08-24)

Same constraint set, same `TIMING_MARGIN_PCT = 0`, after implementing §6
option 2 (pipeline `rx_a_en`/`rx_b_en` — see §6 for the RTL change).

| Check | Corner | Errors | Total negative slack |
|---|---|---|---|
| Setup | 85°C | 0 endpoints | 0.000 ns |
| Setup | 0°C | 0 endpoints | 0.000 ns |
| Hold | 0°C ("m" corner) | 0 endpoints | 0.000 ns |

The previously-failing endpoints now have real margin, not a knife-edge
pass:

| Endpoint | Slack (85°C) | Slack (0°C) |
|---|---|---|
| `rxsr_a1` (MISO1) | +2.192 ns | +2.178 ns |
| `rxsr_b1` (MISO1) | +2.209 ns | +2.195 ns |
| `rxsr_a0` (MISO0) | +2.227 ns | +2.213 ns |
| `rxsr_b0` (MISO0) | +2.448 ns | +2.432 ns |
| `spi1_mosi` | +10.820 ns | +10.780 ns |
| **`spi1_csb`** | **+0.052 ns** | **+0.008 ns** |

The improvement (+2.3 to +2.5 ns on the MISO paths) is larger than "one
extra `clk` cycle of capture delay" alone predicts, because it's two
effects stacked: the intended one (capture happens later, more settling
time) plus a favorable side effect — `sck`'s own generation got faster
too. Its source-clock insertion delay dropped from 4.404 ns to 2.840 ns
(85°C), because `sck`'s decode now routes through the new
`rx_b_en_reg`-adjacent register stage instead of the old two-level
`LUT4_77`->`LUT4_76` combinational chain (see §6's RTL diff description).

**Watch item at the time, now resolved (§5.5): `spi1_csb` was the
tightest path in the design here — +0.008 ns at 0°C, essentially
noise-level.** It was comfortably positive before this change (+0.427/
+0.309 ns). The same pipelining that fixed MISO tightened CSB too, since
CSB's destination-clock path shares the same `rx_b_en`-adjacent registers
in its route.

### 5.5 Re-run after pipelining `csb` itself (Manuel, 2026-08-24)

Same constraint set, `TIMING_MARGIN_PCT = 0`. `csb` itself pipelined the
same way as `rx_a_en`/`rx_b_en` (§6) — its own generation, not just the
shared `sck`/enable timing.

| Endpoint | Slack (85°C) | Slack (0°C) |
|---|---|---|
| **`spi1_csb`** | **+1.581 ns** | **+1.563 ns** |
| `rxsr_a1` (MISO1) | +2.442 ns | +2.428 ns |
| `rxsr_b1` (MISO1) | +2.507 ns | +2.493 ns |
| `rxsr_a0`/`rxsr_b0` (MISO0) | +2.733 ns | +2.717 ns |
| `spi1_mosi` | +11.019 ns | +10.998 ns |

Setup and hold both stay clean (0 endpoints, 0.000 ns negative slack, all
corners). CSB's own path now runs `csb_reg.ff_inst` (register) ->
`spi1_csb_c` (net) -> pad — a direct ~1.5 ns chain, replacing the old
3-LUT combinational decode (~3.4 ns). That ~1.9 ns reduction in CSB's own
generation delay more than offset the ~1.3 ns the earlier `rx_a_en`/
`rx_b_en` pipelining had cost CSB (§5.4), netting real margin instead of
a knife-edge pass. **All four SPI1 signals (MISO/MOSI/CSB) now have >1.5
ns of margin at TIMING_MARGIN_PCT=0** — the tightest path in the design
is CSB at +1.563 ns, comfortably clear of the placeholder board/cable
uncertainty (§3) rather than sitting inside it.

---

## 6. Structural fix — chosen and implemented (Manuel, 2026-08-24)

Constraints identify the problem; they don't fix it on their own. Four
options were on the table, cheapest/most-robust first — the other three
are kept here for the record, in case they're needed again (e.g. if real
board data reopens the CSB margin flagged in §5.4):

- **Slow `sck` to two `clk` cycles per phase.** Costs sample rate;
  rejected specifically because Manuel didn't want to reduce the data
  rate.
- **Pipeline `rx_a_en`/`rx_b_en`** (and, once it turned out to need it,
  `csb`) **so the capture/output edges move one `clk` later**, keeping
  `sck` fast. **Chosen.** Confirmed the failures were specifically
  `rxsr_a0`/`rxsr_b0` (MISO0's DDR A/B capture flops) before picking this
  — the enables are shared across both chips (`rx_a_en`/`rx_b_en` come
  from one `spi_master_controller` driving all four `sr_s2p` instances),
  so the fix applies uniformly rather than being targeted per-channel.
- **`DELAYA` static input delay** on the MISO pins — fine tuning only, not
  used.
- **PLL phase-shifted output clocking the receive side** — most correct,
  most work, not used; this design didn't need it once the pipeline fix
  closed the margin with room to spare (§5.4).

**RTL change** (`kuntur144/fpga/kuntur_fpga/source/impl_1/spi_controllers.v`,
`spi_master_controller`): the module's `rx_a_en`/`rx_b_en` **outputs**
were renamed to `rx_a_en_reg`/`rx_b_en_reg`, fed by new registers:

```verilog
reg rx_a_en, rx_b_en;   // combinational, same case-statement logic as before

always@(negedge rstb or posedge clk)
    if (!rstb) begin
        rx_a_en_reg <= 1'b0;
        rx_b_en_reg <= 1'b0;
    end
    else begin
        rx_a_en_reg <= rx_a_en;
        rx_b_en_reg <= rx_b_en;
    end
```

The combinational `rx_a_en`/`rx_b_en` assignments inside the FSM's case
statement moved **one state earlier** than before (e.g. `rx_a_en` now
asserts in `op1`, where previously nothing drove it, instead of in
`sck0b`) — so after the one-cycle register delay, `rx_a_en_reg` lands on
the *same* state-relative `clk` edge the old unpiped `rx_a_en` did. Net
read: `sr_s2p`'s capture timing relative to the FSM's own state numbering
is unchanged, so A.1.1's `SLOT_OFFSET = 3` finding should still hold —
this was inference from reading the diff at the time; **confirmed by
Manuel's simulation pass, 2026-08-24 — slot/channel mapping unchanged.**

**Follow-up RTL change, same session: `csb` pipelined the same way.**
§5.4's re-run left `spi1_csb` at +0.052/+0.008 ns — technically passing
but tight enough that it was likely to fail once real board/cable numbers
replaced the placeholder (§5.4's watch item). Rather than add an extra
FSM state (the other option on the table for this specific problem —
rejected in favor of keeping one consistent pipelining idiom across
`rx_a_en`/`rx_b_en`/`csb`), `csb`'s own output was pipelined identically:

```verilog
reg rx_a_en, rx_b_en, csb;   // combinational

always@(negedge rstb or posedge clk)
    if (!rstb) begin
        rx_a_en_reg <= 1'b0;
        rx_b_en_reg <= 1'b0;
        csb_reg <= 1'b0;
    end
    else begin
        rx_a_en_reg <= rx_a_en;
        rx_b_en_reg <= rx_b_en;
        csb_reg <= csb;
    end
```

Combinational `csb`'s falling-edge assignment moved from `op0` into
`idle` (asserted when `start=1`, one state earlier), and its last
assertion (at the state transitioning into `csbend0`) was dropped — the
same shift-and-drop pattern as `rx_a_en`/`rx_b_en`. Results: §5.5. Device
(LIFCL-17-8UWG72C, speed grade 8) supports all four original options if
any of this needs revisiting.

---

## 7. Open items

- [x] **Manuel's simulation pass** on the pipelined `rx_a_en`/`rx_b_en`
      RTL (§6) — confirmed 2026-08-24: channel/slot mapping (A.1.1's
      `SLOT_OFFSET = 3`) unchanged.
- [x] **Decided against, 2026-08-24 (Manuel): real board/cable
      trace-length numbers.** `pcb_sck_ns`/`pcb_mosi_ns`/`pcb_miso_ns`/
      `pcb_csb_ns` stay at the 1.5 ns estimate permanently — resolving
      board delay at this timescale needs an oscilloscope sampling in the
      10s of GSa/s, which isn't equipment on hand, so this is an equipment
      ceiling rather than a priority call. Independent of whether 1.5 ns
      is accurate, the `rx_a_en`/`rx_b_en`/`csb` pipelining fix (§6) moved
      SPI1's outputs off combinational logic and onto a direct
      register-to-pad path, buying structural margin against PCB delay
      that holds regardless of the real number (§9.2). §5.3's sensitivity
      analysis stands as documentation of the placeholder's impact, not as
      an open question. §9.2 (2026-08-24, after placement pinning): CSB's
      margin against the 1.5 ns estimate narrowed to +1.46 ns — still
      passing, worth watching, not evidence the estimate itself was wrong.
- [ ] A bench/simulation check specifically on the pipelined `csb` (§6,
      §5.5's follow-up fix) — the same class of confirmation the
      `rx_a_en`/`rx_b_en` simulation pass just gave `SLOT_OFFSET`, not yet
      done for `csb`'s own shifted assertion window. Tracked in PLAN.md's
      Phase B.1 "RTL testbench coverage" item, folded in alongside the
      other self-checking-testbench work rather than as a standalone
      pass.
- [ ] `spi0` (MCU-facing SPI) has no timing constraints at all — separate
      link, separate exercise, not started. Tracked in PLAN.md's Phase B.1
      as "FPGA timing constraints — remaining pins."
- [ ] Async reset (`rstb`) recovery/removal timing — 2747 unconstrained
      endpoints, not evaluated. Same PLAN.md item as `spi0` above.
- [ ] Consider constraining `clk` on the PLL's `CLKOP` pin instead of the
      `clk` net, to silence Radiant's warning 70009502 cleanly (low
      priority — no evidence it's produced a wrong number so far).
- [x] Restore the full constraint set (real `clkin`@31.25 ns, `spi1_sck`
      generated clock, MISO/MOSI/CSB delays, multicycle exception) on top
      of the placement-pinned design from
      `fpga-rhd2164-chip0-placement.md`, and re-run §5's checks — done
      2026-08-24, results and a real finding in §9.

---

## 8. Post-placement-fix baseline — `clkin`-only constraint (Manuel, 2026-08-24)

Deliberate, acknowledged-as-incomplete STA run requested as a guideline to
compare against if the full restoration (open item above) produces
surprises. Design state: the chip0-placement fix is in
(`macro_region_0`/`macro_region_1` pinning `spi1_rhd2164x2` and
`controller0` — `fpga-rhd2164-chip0-placement.md`), and the full original
RTL is restored (both chips confirmed live, channels 42 and 88 in the
pc-app). `impl_1.sdc` itself is untouched from where §4-§7 left it: only
the stray leftover clock is active —

```
create_generated_clock -name {clk} -source [get_pins {mypll/lscc_pll_inst/gen_no_refclk_mon.u_PLL.PLL_inst/REFCK}] -multiply_by 71 -divide_by 51 [get_pins {mypll/lscc_pll_inst/gen_no_refclk_mon.u_PLL.PLL_inst/CLKOP}]
create_clock -name {clkin} -period 10 [get_ports clkin]
```

— i.e. `clkin` at the wrong 100 MHz (should be ~32 MHz / 31.25 ns), and
none of `spi1_sck`/MISO/MOSI/CSB/multicycle from §4 present. Constraint
coverage: 92.11%.

### 8.1 Headline result

Setup (both corners, 8_High-Performance_1.0V) and hold (`m` corner):
**0 endpoints, 0.000 ns negative slack.** Clean across the board.

### 8.2 Read this number with a correction factor — `clk`'s target is 3.15x too fast here

`clk` is generated from `REFCK` (which tracks `clkin`) via `-multiply_by
71 -divide_by 51`. With the stray `clkin` at 100 MHz, that makes `clk`'s
**target** period 7.183 ns (139.2 MHz) — not the real 44.55 MHz (22.44 ns)
the design actually runs at. The ratio is fixed in the SDC; only
`clkin`'s value is wrong, so it drags `clk`'s target along with it, 3.15x
too fast (139.2 MHz vs the real 44.55 MHz).

**This makes the setup check in §8.1 strictly harder than reality, not
easier.** The worst setup path found — `controller0/cnt0__i2` →
`regbank/dout1_i14` (a 5-logic-level, 79%-route address-decode path into
the config regbank; unrelated to SPI1) — passed with +0.346 ns slack at
85°C / +0.552 ns at 0°C against the artificially tight 7.182 ns
constraint. Once `clkin` is restored to its real ~31.25 ns period, that
same path's setup budget grows to ~22.4 ns — roughly 15 ns of additional
headroom on top of what's already a clean pass. **No setup risk expected
anywhere in the design from the restoration itself; this path is not
worth re-checking as a priority.**

### 8.3 The number that *does* carry forward unchanged: hold on the RHD2164 DDR receive path

Hold checks a fixed same-edge minimum delay — they don't scale with the
clock period, so unlike §8.2's setup numbers, these are representative of
the real restored/pinned design as-is. Every reported hold path is
internal (register-to-register within `rxsr_a0`/`rxsr_a1`/`rxsr_b0` in
`spi1_rhd2164x2`, and the equivalent in `spi0/rxsr`) — the same DDR
shift-register capture logic the `rx_a_en`/`rx_b_en` pipelining fix (§6)
targeted, not the SPI1 pad-to-pad paths themselves (those aren't checked
here since MISO/MOSI/CSB have no I/O delay constraints active in this
baseline). Every one of the ten worst hold paths reports **the same
+0.143 ns slack** — small, but consistently positive and structurally
identical (single register hop, `REG_DEL` 0.142 ns against a 0.080 ns
hold requirement). **This is the number to watch**: if the full
constraint restoration or any future placement change erodes it, it'll
show up here first, on this same set of internal DDR capture paths.

### 8.4 Unconstrained scope (expected, not a new problem)

`spi0_sck`/`spi0_mosi`/`spi0_csb`/`spi1_miso0`/`spi1_miso1`/`spi2_miso0`/
`cmd_is_00`/`serial_lvds_rx`/`serial_lvds_tx`/`rstb` all report as
unconstrained I/O — expected, since no `set_input_delay`/
`set_output_delay`/generated clock exists yet for any of them in this
deliberately-partial baseline. `spi1_rhd2164x2/txsr` and
`spi1_rhd2164x2/spi_master_controller0/csb_reg` show as unconstrained
start points for the same reason — their fan-out (the SPI1 output pads)
has no downstream timing model without §4's constraints re-enabled.

---

## 9. Full constraint set restored on the placement-pinned design (Manuel, 2026-08-24)

The real `clkin` (31.25 ns), `spi1_sck` generated clock, MISO/MOSI/CSB
delays, `set_clock_uncertainty`, and the multicycle exception (§4) are
all back in `impl_1.sdc`, on top of the chip0-placement fix and full RTL
restoration (`fpga-rhd2164-chip0-placement.md`). This is the first STA
run against that combination.

### 9.1 Headline result

Setup (both corners) and hold (`m` corner): **0 endpoints, 0.000 ns
negative slack.** §8.2's prediction held — the `controller0`→`regbank`
family of paths that were the tightest thing in the §8 baseline (+0.346 ns
under the artificially fast 139 MHz target) now sit at **+10.9 to +11.4 ns**
against the real 22.447 ns `clk` period. No setup risk anywhere in the
design.

### 9.2 SPI1 margins vs. §5.5 (same fixes, no placement pinning)

| Endpoint | §5.5 (pre-pinning) | §9 (pinned + restored) | Change |
|---|---|---|---|
| **`spi1_csb`** | +1.581 / +1.563 ns | **+1.464 / +1.462 ns** | **−0.12 / −0.10 ns** |
| `rxsr_a1` (MISO1) | +2.442 / +2.428 ns | +3.126 / +3.132 ns | +0.68 / +0.70 ns |
| `rxsr_b1` (MISO1) | +2.507 / +2.493 ns | +3.334 / +3.338 ns | +0.83 / +0.85 ns |
| `rxsr_a0` (MISO0) | +2.733 / +2.717 ns | +3.263 / +3.268 ns | +0.53 / +0.55 ns |
| `rxsr_b0` (MISO0) | +2.733 / +2.717 ns | +3.471 / +3.474 ns | +0.74 / +0.76 ns |
| `spi1_mosi` | +11.019 / +10.998 ns | +11.210 / +11.204 ns | +0.19 / +0.21 ns |

All four MISO paths and MOSI **improved** with placement pinning — plausibly
tighter/more direct routing now that `spi1_rhd2164x2` and `controller0`
have fixed locations instead of whatever P&R picked incrementally before.

**CSB is the one signal that got worse, and it's now the tightest path in
the whole SPI1 link at +1.46 ns — below the 1.5 ns `pcb_csb_ns` value in
§3.** Two corrections to how that number should be read, per Manuel
2026-08-24:

- **The 1.5 ns is an *estimate*, not a measurement** — §3 already flags it
  as "NOT yet extracted from real trace lengths or a bench measurement."
  So "CSB dropped below 1.5 ns" isn't "CSB dropped below a known real
  number" — it's "the margin against an *assumed* number got thinner."
  Nothing about the real PCB delay is any better or worse understood than
  it was before this run.
- **Why no real measurement is planned: it's an equipment ceiling, not a
  priority call.** Resolving a board delay at this timescale needs an
  oscilloscope sampling in the 10s of GSa/s — not equipment on hand. This
  isn't "not worth measuring yet," it's "can't measure it here."
- **The `rx_a_en`/`rx_b_en`/`csb` pipelining fix (§6) helps regardless of
  what the real PCB delay turns out to be.** It moved output generation
  off combinational logic and onto a direct register-to-pad path, which
  is what bought CSB's slack back from near-zero (§5.4→§5.5) in the first
  place. That structural margin exists independent of the 1.5 ns
  estimate's accuracy — even if the real board delay is somewhat larger
  than assumed, the design has more room to absorb it now than it did
  before the fix.

Net: still a real, small (~0.1 ns) regression from placement pinning worth
tracking, and CSB is the signal to watch first if anything shifts again —
but it's not evidence the 1.5 ns budget has been "used up" by something
concrete, since that number was never measured to begin with. See the
updated PLAN.md B.1 entry.

### 9.3 Hold margins dropped sharply — expected, traced to `set_clock_uncertainty`

The ten worst hold paths in this run range **0.012–0.018 ns** — far
tighter than §8.3's uniform +0.143 ns on the same class of internal DDR
capture paths. This is not a placement regression: `impl_1.sdc` now
carries `set_clock_uncertainty -setup -hold 0.125 [get_clocks clk]`,
which wasn't active in §8's baseline. Each hold report's `Uncertainty`
line shows the full 0.125 ns added directly against the requirement
(e.g. Path 1: `0.887 → 1.012`), and 0.143 − 0.125 = 0.018 ns — matching
the reported slack on most of the ten paths almost exactly (two paths,
`regbank/ram[9][15]` and `regbank/ram[191][2]`, come in slightly tighter
at 0.012/0.016 ns due to a smaller common-path-skew cancellation, −0.023 ns
vs. the more typical −0.040 ns). **The constraint is doing exactly what
it's supposed to do** — 0.125 ns is the uncertainty budget the design is
meant to absorb, and every path still clears it with margin to spare, just
thinner margin than the unconstrained §8 baseline showed. Still 0 hold
errors. Worth knowing this is normal before anyone sees a sub-0.02 ns
number and assumes something broke.

### 9.4 Scope check

Constraint coverage 92.19% (vs. 92.11% in §8) — negligible change, as
expected; `spi0`, `rstb`, `serial_lvds_tx`/`serial_lvds_rx`, `cmd_is_00`
remain unconstrained exactly as tracked in §7's open items, nothing new
here.

---

## 10. `spi0` and `rstb` — asynchronous exceptions, drafted 2026-08-26

Both ports are architecturally different from SPI1, so "constrain them"
does not mean "give them a clock" — it means declaring them as explicit,
justified exceptions instead of leaving them as silent unconstrained I/O.
Drafted here for Manuel to add to `impl_1.sdc` and verify in Radiant
(same division of labour as §4-§9: the constraint text and rationale are
worked out here, the actual entry into the tool and STA re-run happen on
the bench). Not yet added to `impl_1.sdc` as of this writing — Manuel is
mid-edit on that file for the item-4 placement-region work (macros for
`regbank`/`ch_sel0`/`controller1`/`fifo0`/`spi0`, extending the
`macro_region_0`/`macro_region_1` pinning from
`fpga-rhd2164-chip0-placement.md` to more blocks), so this section stays
text-only here until that's clear of the file.

### 10.1 `spi0` — genuinely asynchronous, not a second clock domain

`spi_slave` (`spi_controllers.v:250`) does not use `spi0_sck` as a clock
anywhere. `spi0_csb` and `spi0_sck` both go through `edge_detector`
(`spi_controllers.v:334`) — a plain 2-flop `clk`-domain synchronizer — and
`spi_slave_controller`'s FSM reacts only to the synchronized
`csb_redge`/`csb_fedge`/`sck_redge`/`sck_fedge` pulses, never the raw
pins. `spi0_mosi` is shifted into `sr_s2p` (`rx_en`) exactly one `clk`
cycle after `sck_redge` fires — i.e. deliberately mid-bit-period, the same
margin strategy a real sck-domain shift register would use, except the
"domain" here is `clk` throughout and `csb`/`sck`/`mosi` are ordinary
asynchronous data inputs to it. `spi0_miso` is driven purely from `clk`-domain
logic (`sr_p2s`) with no defined relationship to when the far end (the
STM32WB0, bit-banging GPIOs per `fpga_spi.c`) samples it.

There is no clock-edge relationship to declare on either side, so
`set_input_delay`/`set_output_delay` (SPI1's tool) doesn't apply here —
the correct STA statement is that these paths are exempt from
clock-relative timing checks by design:

```tcl
set_false_path -from [get_ports {spi0_csb spi0_sck spi0_mosi}]
set_false_path -to   [get_ports spi0_miso]
```

This is not "we didn't get to it" — it's the standard treatment for an
interface whose safety comes from the RTL's synchronizer plus the
one-cycle-late capture, not from any clock relationship Radiant could
check. It also converts `spi0` from silently-unconstrained I/O
(§8.4/§9.4) into an explicit, justified exception, which is what closes
PLAN.md B.1's "`spi0` ... not started" item — "fully constrained" for an
asynchronous interface means documented exceptions, not a fabricated
clock.

**What this does NOT verify**, and STA cannot: whether `fpga_spi.c`'s
bit-bang gap between SCK edges leaves enough margin for `edge_detector`'s
2-clk synchronizer delay plus the 1-clk capture delay. That is a
firmware/protocol timing budget, invisible to a false-pathed interface by
definition, and its only evidence is empirical — A.2's full round-trip and
the whole A.1.1 ladder already run correctly on the bench at the
firmware's current bit-bang rate. If that rate is ever increased
significantly, this margin should be re-examined on its own terms, not by
looking for it in an STA report that has been told not to check it.

### 10.2 `rstb` — false-pathed by necessity, not fixed

`rstb` drives `negedge rstb` directly in every sequential `always` block
across the design (~2747 endpoints, PLAN.md B.1). Assertion needs no
timing check by construction — that is what an asynchronous reset is for.
Removal/recovery is the real question: whether `rstb`'s rising edge lands
far enough from a `clk` edge that every flop in the design exits reset on
a consistent cycle. This design has never synchronized that — every
module takes the raw `rstb` pin as its async reset directly; there is no
2-flop release-synchronizer anywhere generating an internal `rstb_sync`.

```tcl
set_false_path -from [get_ports rstb]
```

This is standard practice for a single global reset asserted for an
extended period at power-up rather than toggled during normal operation,
and it is the only way to make Radiant's coverage report honest about
this signal — but it is a **documented risk acceptance, not a fix**: it
tells Radiant not to check recovery/removal timing, it does not make a
borderline-timed release safe. A flop or two exiting reset one cycle later
than its neighbours, on an unlucky release edge, is exactly the kind of
one-time, power-up-only glitch that would be extremely hard to catch on
the bench (indistinguishable from any other early-boot flakiness) and
easy to dismiss if it were ever seen. The robust fix — synchronizing
`rstb`'s deassertion in RTL and distributing `rstb_sync` in place of the
raw pin everywhere — is real, tracked follow-up work (RTL change,
Manuel's queue), not something this SDC exception substitutes for.

### 10.3 Net effect on coverage

Once both are added, `spi0`/`rstb` move from "unconstrained" to
"explicitly excepted" in Radiant's report — expect constraint coverage to
rise from 92.19% (§9.4), though `serial_lvds_tx`/`serial_lvds_rx`/
`cmd_is_00` remain genuinely open (the uHDMI tunnel isn't built yet) and
should still show as unconstrained after this change, not disappear.
