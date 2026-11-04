# SPI1 MOSI eye scan (task #6a): interface spec

**Status: SPEC ONLY, written 2026-11-04. Nothing here is implemented.**
Decisions D1–D7 agreed with Manuel (`log/2026-11-04.md`). Schedule:
PLAN.md R1, task #6a, after #6 (the 25k/28k clocks) and before #6b.

**Lane split:**

| Part | Owner |
|---|---|
| §3 RTL (MOSI launch path, phase stepper, checker, regbank words) | Manuel |
| §6 testbench | Claude |
| §5 scan script and bench procedure | Claude |
| Bench runs | Manuel + Claude |

**Goal.** Find, once per clock rate, a MOSI launch timing at which both
RHD2164s take every command correctly with margin on both sides, and
build it into the operating bitstreams. Board, cable and chips are
fixed, so the answer is deterministic and needs finding only once.

## 1. Why, and the hypothesis under test

chip0 sometimes gives all `FFFF` while chip1 works (PLAN.md A.1.2). The
08-31 attempt moved MOSI by a fixed 90° to land in an open eye by chance;
it did not work, and it measured nothing.

**Hypothesis (Manuel, D7), written before the first run.** chip0 and
chip1 have different MOSI/SCK windows at the chip, from different PCB
paths and different chip-internal timing. Today's MOSI launch sits near
an edge of chip0's window and inside chip1's.
- **Expected:** a window for each chip; chip0's has an edge close to
  today's launch point (Δ = 0, §3.1); the two windows overlap.
- **Refuted if:** chip0's window contains Δ = 0 with margin, or a failing
  chip0 answers wrong at every Δ (then the cause is not MOSI timing).

**Counter-view, recorded (Claude).** The tightest path in the `.twr` is
the MISO round trip (1.632 ns slack at 45.54 MHz, placeholder board
delays), and the RTL gives MOSI about one `clk` period of setup and hold
at the chip (§3.1). Agreed order: MOSI first (this document); MISO
capture only if needed (D1). The scan helps separate the two: both
halves of a chip see the same MOSI, so a MOSI fault shows on A and B
together, while A and B differing points to MISO.

**Temperature** (the chip0 thermal rig) is out of scope until after the
animal test (D6).

## 2. Today's SPI1 timing (read from the RTL)

`spi_master_rhd2164x2.v`, `spi_master_controller`. T = one `clk` period
(26.35 ns at 37.95 MHz, 23.53 ns at 42.504 MHz).

- Each SCK period is two `clk` states, `sckNb` (SCK high) and `sckNd`
  (SCK low). `spi1_sck` is a combinational decode of the state register.
- MOSI = `txsr` `areg[15]`. `tx_en` is high in `sckNb`, so MOSI shifts at
  the `clk` edge that ends `sckNb`, i.e. as SCK falls. Each bit lasts 2T.
- The chip samples MOSI on SCK rising, at the `clk` edge that starts
  `sckNb`. Bit N is valid from one T before that edge to one T after it:
  **about T of setup and T of hold**, before board and chip delays.
- MISO is captured on `clk` (`rxsr_*`). §3 leaves that path alone.

## 3. RTL requirements (Manuel)

### 3.1 MOSI launch path

**Δ** is the MOSI launch time relative to today's, in ns; positive is
later. Δ = 0 is today's MOSI.

**Sources.** Four copies of the MOSI bit, in the `clk` domain, each
changing only just after one kind of `clk` edge:

| `mosi_sel` | Source | Changes after | Offset *o* |
|---|---|---|---|
| 0 | `m_early`: the value `areg[15]` takes at the next `clk` edge (`tx_load ? data_tx[15] : tx_en ? areg[14] : areg[15]`) | `clk` rising | −T |
| 1 | `m_early` registered on `clk` falling | `clk` falling | −T/2 |
| 2 | `m0` = `areg[15]` (today's MOSI) | `clk` rising | 0 |
| 3 | `m0` registered on `clk` falling | `clk` falling | +T/2 |
| 4 | **bypass: `spi1_mosi` = `m0`, exactly as today** | | **reset value** |

For `mosi_sel` 0–3 the chosen source goes through one register on
`clk_tx` rising, and that register drives `spi1_mosi`. `clk_tx` is
`pll0`'s `CLKOS` (today's unused `clk90`), same frequency as `clk`, with
dynamic phase (§3.2). `clk_tx`'s phase φ (a fraction of a turn, 0 at
the static phase) moves the launch:

  x = (φ·T − *o*) mod T,   Δ = *o* + x

**A scan point is allowed only if x is in [T/4, 3T/4],** so the `clk_tx`
edge that samples the source is at least T/4 away from any change of it.
That is how the `clk` → `clk_tx` crossing is safe at every phase: by
construction, since STA cannot check a moving phase. Sources 0 and 2 are
allowed for φ in [90°, 270°], sources 1 and 3 for the rest of the turn.
Together the four cover **Δ from −3T/4 to +5T/4** without gaps:

| `mosi_sel` | Δ range |
|---|---|
| 0 | −3T/4 … −T/4 |
| 1 | −T/4 … +T/4 |
| 2 | +T/4 … +3T/4 |
| 3 | +3T/4 … +5T/4 |

That spans the hold-side edge (MOSI too early) and the setup-side edge
(MOSI too late). Beyond about +T the chip takes bit N at SCK rising of
bit N + 1, so the word arrives shifted by one bit and every point fails:
the map ends there.

**Timing of `m_early`.** It is combinational after `clk` rising, and
`clk_tx` samples it at least T/4 later. The `.sdc` must bound that path:
`clk` → the `clk_tx` MOSI register ≤ T/4 − 1 ns (about 4.9 ns at
42.504 MHz), checked in the `.twr`. The same holds for the falling-edge
copies.

**Not changed:** SCK, CS, the FSM, `txsr`, MISO capture, the capture
buffer. With `mosi_sel` = 4 the design is today's.

### 3.2 Phase stepper

`pll0` gets dynamic phase on `CLKOS` (`gui_en_dyn_phase`), as the
companion's PLL already has (`lvds-tunnel.md` §6.4 *Run-time phase
steps*, TN-02095 §14.5.9, §14.6.1):

- **One step** = 360° / (8 × (DIV + 1)), DIV from `DIVOS_ACTUAL_STR` of the
  generated IP. **Steps per turn (SPT)** = 8 × (DIV + 1), a parameter
  per implementation (`impl_25k`, `impl_28k`), readable by the MCU.
- **Delaying steps only** (`PHASEDIR` = 0): glitch-free per the TN. An
  advancing step may glitch `CLKOS`. A full turn is SPT delaying steps.
- `PHASESEL` selects `CLKOS` (`3'b001` on the companion: confirm for
  Kuntur's IP). `PHASESEL`/`PHASEDIR` held ≥ 5 ns before `PHASESTEP`
  falls. `PHASESTEP` from a register (a glitch is a step), idle high,
  each pulse low ≥ 4 VCO cycles then high ≥ 4 VCO cycles: one `clk` low,
  one `clk` high satisfies both.
- **Internal feedback** (the TN requires it for dynamic phase): check
  Kuntur's `pll0`.
- One write of `PHASE_STEP_CMD` = N steps. `PHASE_POS` counts them mod
  SPT and returns to 0 with `rst_n_clk` (a lock drop also puts `CLKOS`
  back at its static phase, so the two stay consistent). A write while
  busy is ignored.

### 3.3 Known-answer checker

In the `clk` domain, on sampling transfers (`xfer_done`).
- The command shifted out in transfer *t* (`regbank_dout1` as the master
  loads it) goes into a two-deep history. At the end of transfer *t*,
  the four answers (`data_rx_a`, `data_rx_b`, `data_rx_a1`,
  `data_rx_b1`) belong to the command of transfer *t* − 2.
- **Checked commands**, with their expected answer on all four halves:

  | Command | Expected |
  |---|---|
  | `READ(40..44)` | `{00, "INTAN"[R − 40]}`: `0049 004E 0054 0041 004E` |
  | `READ(48..50)` | `{00, "RHD"[R − 48]}`: `0052 0048 0044` |
  | `WRITE(R, D)` | `{FF, D}` |

  Anything else, including `CONVERT`, is not counted. The `WRITE` echo
  is the chip's own copy of the 8 data bits it latched from MOSI. A
  misread opcode turns the answer into something else, which also counts.
- Counters, saturating at `FFFF`, cleared together: transfers checked;
  errors on chip0 A, chip0 B, chip1 A, chip1 B; the first wrong answer
  since the clear, its half, and what was expected.
- Enabled by `CHK_EN`; when off, the counters hold.

### 3.4 Regbank words

MCU-written (RAM, read back as written; the RTL also keeps live copies,
as for `ch_a`/`stream_enable`):

| Addr | Name | Bits |
|---|---|---|
| 232 | `MOSI_SCAN_CTRL` | [2:0] `mosi_sel` (reset **4**), [3] `CHK_EN` (reset 0), [4] `CHK_CLEAR`: a write with this bit set clears the checker |
| 233 | `PHASE_STEP_CMD` | [9:0] N steps (0 = none), [15] direction, 0 = delay (the only one the procedure uses). A write starts the steps |

Read-only, served from logic (writes ignored):

| Addr | Name | Bits |
|---|---|---|
| 240 | `PHASE_POS` | steps from the static phase, 0 … SPT − 1 |
| 241 | `PHASE_INFO` | [15] stepping busy, [11:0] SPT |
| 242 | `CHK_COUNT` | transfers checked |
| 243 | `ERR_C0A` | errors, chip0 A |
| 244 | `ERR_C0B` | errors, chip0 B |
| 245 | `ERR_C1A` | errors, chip1 A |
| 246 | `ERR_C1B` | errors, chip1 B |
| 247 | `FIRST_ERR_ANS` | first wrong answer since the clear |
| 248 | `FIRST_ERR_INFO` | [15] valid, [1:0] half (0 = chip0 A, 1 = chip0 B, 2 = chip1 A, 3 = chip1 B) |
| 249 | `FIRST_ERR_EXP` | what that answer should have been |

232–239 and 240–255 are unused today (`regbank.v`); 230 is reserved for
`rsp_delay` (`fpga-diagnostic-access.md`). #8 (the A.7 counter) can take
250+.

### 3.5 Builds

In every build, idle unless commanded (D5): `mosi_sel` = 4 and `CHK_EN`
= 0 at reset. After the scan, the chosen point goes into each operating
build as the reset value of `mosi_sel` and the static `CLKOS` phase of
that rate's PLL (§5.4). No MCU action at boot.

## 4. What it does not do

- No MISO capture change (D1: later, if needed).
- No live tracking: the result is a static setting per build.
- No change to SCK or CS. Their timing at the chip is what the scan
  measures MOSI against.
- No board delay measurement: it finds the window, it does not explain it.
- No temperature run before the animal test (D6).

## 5. Scan procedure (Claude: script; bench: both)

### 5.1 Set-up

Driven from the PC with the existing `REG_WRITE16`/`REG_READ16`
commands through the bridge (the MCU passes them to the regbank; no new
firmware). Streaming stopped, as those commands require. Sampling keeps
running, so the chips answer at the full transfer rate (825k transfers/s
at 25k, 924k at 28k). The script writes a CSV per run, one row per
point.

1. Read `PHASE_INFO`: SPT, not busy. `PHASE_POS` = 0.
2. Load the 33 sampling entries (words 48–80) with the known-answer
   pattern (D3), repeating every 8 entries:
   `WRITE(6, 55)`, `READ(40)`, `WRITE(6, AA)`, `READ(41)`, `WRITE(6, 00)`,
   `READ(42)`, `WRITE(6, FF)`, `READ(43)`; entry 32 = `READ(44)`.
   Consecutive `WRITE`s alternate every data bit.
   **Register 6** is the impedance-check DAC value (`RHD_ZCHECK_DAC`):
   it does nothing while the DAC is powered off (register 5,
   `RHD_ZCHECK_DAC_POWER` = 0 in the config), so the `WRITE`s are harmless.
3. `CHK_EN` = 1.

### 5.2 One turn

For each `PHASE_POS` from 0 to SPT − 1 (one delaying step between), for
each of the two `mosi_sel` values allowed at that φ (§3.1):
1. Write `mosi_sel`. Wait at least 3 transfers (a BLE round trip is far
   longer).
2. Clear the checker; wait the dwell (default 10,000 transfers checked,
   about 12 ms; the script reads `CHK_COUNT` until it is reached).
3. Read 242–249. Row: rate, SPT, `PHASE_POS`, `mosi_sel`, Δ (ns), count,
   the four error counts, first error.

That is 2 × SPT points (about 600), each a handful of BLE commands.

### 5.3 Afterwards

- `mosi_sel` = 4, `CHK_EN` = 0, step on to complete the turn
  (`PHASE_POS` = 0), restore the sampling table.
- **Power-cycle Kuntur** before any recording. Points outside the window
  can garble commands into `WRITE`s to any register 0–21, or a
  `CALIBRATE`; the known answers do not depend on that state, but a
  recording does. (A reset path from the MCU would do instead, once it
  exists: `system-startup.md`.)

### 5.4 Reading the map, choosing the point

- Per half, Δ with zero errors forms the window. Expect A and B of a
  chip to agree (same MOSI); if they don't, suspect MISO.
- **Chosen Δ\*:** the middle of the Δ range error-free on all four
  halves, **≥ T/2 (25% of a 2T bit, the G5 rule) from any error on both
  sides**. If the overlap is too narrow for that, report it and stop:
  that is a finding, not something to work around.
- Δ\* → (`mosi_sel`, static `CLKOS` phase) by the table in §3.1, per
  rate. Each rate is scanned on its own build (#6): the window in ns is
  the board's, but T differs.
- **A pass at Δ\* afterwards is not evidence** (A.1.2): the map is.

## 6. Testbench (Claude)

- `kuntur_prims_sim.v`: `pll0` `CLKOS` with a static delay and a
  `PHASESTEP` model (reuse the companion `cdr_tb` model).
- `rhd2164_bfm.v`: each chip samples MOSI at its SCK rising plus a
  per-chip delay, with a setup/hold window; a violation corrupts the bit.
  Two chips with different delays give a known pair of windows.
- Checks: `mosi_sel` = 4 is bit-identical to today (the whole
  `kuntur_tb` passes unchanged); for each source and allowed φ, Δ matches
  §3.1; the checker counts injected errors on the right half with the
  right first-error words; a scan over the BFM's windows finds both
  edges for each chip at the expected Δ; stepping (`PHASE_POS`, busy,
  SPT, wrap) and the regbank words.

## 7. Open

- O1: Kuntur `pll0` feedback mode and `PHASESEL` code for `CLKOS`
  (§3.2), from the regenerated IP.
- O2: the `.sdc` form of the T/4 bound on the `m_early` path (§3.1).
