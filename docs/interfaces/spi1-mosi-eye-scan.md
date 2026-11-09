# SPI1 MOSI eye scan (task #6a): interface spec

**Status: SPEC, written 2026-11-04; RTL in progress (Manuel).** Decisions
D1–D7 agreed with Manuel (`log/2026-11-04.md`); RTL structure decisions
S1–S7 (§3.6) agreed 2026-11-04. Updated after #6 for its PLLs
(`pll_25k`/`pll_28k` in `clock_gen`; O1 closed, §3.2); stepper
requirements and reset behaviour 2026-11-05 (§3.2). Schedule:
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
the `CLKOS` of `clock_gen`'s PLL (`pll_25k` or `pll_28k`, #6; the old
`clk90`), same frequency as `clk`, static phase 0°, dynamic phase
(§3.2). `clk_tx`'s phase φ (a fraction of a turn, 0 at
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
`clk_tx` samples it at least T/4 later, so that path is bounded:
`clk` → the `clk_tx` MOSI register ≤ T/4 − 1 ns, relative to each
source's launch edge (the falling-edge copies included). *(Built
2026-11-09, O2.)* It is in `impl_1.pdc`, not the `.sdc`, as
`set_max_delay -from [get_clocks clk] -to [get_pins
{scan0/mosi_tx_c.ff_inst/DF}] 4.881`: the register's name exists only
after synthesis, and map drops the RTL or cell name with only a map
warning. One `.pdc` serves all builds, so the 28k value (4.881 ns) is
used at 25k too (5.587 ns would do). `build_kuntur.py` fails a build
whose `.twr` lacks the Path Exception. Worst path: `regbank_dout1[15]`
(EBR) → `txsr`'s load mux (`a_next`) → the source mux → `mosi_tx`, +0.78
ns at 28k and 25k, +1.04 ns on the bench build.

**Not changed:** SCK, CS, the FSM, `txsr`, MISO capture, the capture
buffer. With `mosi_sel` = 4 the design is today's.

### 3.2 Phase stepper

Both #6 PLLs already have dynamic phase on `CLKOS`
(`gui_en_dyn_phase`), as the companion's PLL does (`lvds-tunnel.md` §6.4
*Run-time phase steps*, TN-02095 §14.5.9, §14.6.1). `clock_gen`'s phase
inputs are constants today; the stepper drives them.

- **One step** = 1/8 of a VCO period (TN-02095 §14.6.1) = 360° /
  (8 × (DIV + 1)), DIV from the IP's `DIVOS_ACTUAL_STR`. **Steps per turn
  (SPT)** = 8 × (DIV + 1):

  | PLL | VCO | `DIVOS_ACTUAL_STR` | SPT | One step |
  |---|---|---|---|---|
  | `pll_25k` | 1593.90 MHz | 41 | **336** | 78.4 ps |
  | `pll_28k` | 1572.65 MHz | 36 | **296** | 79.5 ps |

  A `localparam` per `clock_gen` branch, readable by the MCU (S5).
- **Delaying steps only** (`PHASEDIR` = 0): glitch-free per the TN. An
  advancing step may glitch `CLKOS`. A full turn is SPT delaying steps.
- `PHASESEL` = `3'b001` selects `CLKOS` (TN-02095 Table 14.3; what
  `clock_gen` ties). `PHASESEL`/`PHASEDIR` held ≥ 5 ns before `PHASESTEP`
  falls: `PHASEDIR` registered at least one `clk` before the first pulse. `PHASESTEP` from a register (a glitch is a step), idle high,
  each pulse low ≥ 4 VCO cycles then high ≥ 4 VCO cycles: one `clk` low,
  one `clk` high satisfies both.
- **Internal feedback** (the TN requires it for dynamic phase): both
  PLLs have `FBK_MODE` `INTCLKOP`.
- One write of `PHASE_STEP_CMD` = N steps (N = 0: nothing; N up to
  1023, more than a turn, so one write reaches any position). The
  stepper takes it on a one-`clk` strobe from the regbank when word 233
  is written, not from a change of the stored word (the scan writes
  N = 1 over and over). A write while busy is ignored. Busy from the
  `clk` after the write until the last pulse rises (2N `clk`).
- `PHASE_POS` counts the steps mod SPT: + 1 per delaying step, − 1 per
  advancing one. It **accumulates across writes**: it is the only record
  of where `CLKOS` is, because the PLL takes relative steps and keeps
  them. There is no way to clear it on its own (that would leave `CLKOS`
  where it was); back to 0 is SPT − `PHASE_POS` more delaying steps,
  which moves both.
- **Reset.** `PHASE_POS`, busy, `PHASESTEP` (high) and `PHASEDIR` (0)
  reset with `rst_n_clk`, which follows `rstb && pll_lock` at once
  (`reset_gen_kuntur`); nothing new at the top. The counter and `CLKOS`
  agree after each event as follows:

  | Event | `PHASE_POS` | `CLKOS` phase | Agree |
  |---|---|---|---|
  | Power-up, reconfiguration | 0 | static (bitstream) | yes |
  | `rstb` (MCU resets the FPGA, PA10) | 0 | keeps its steps: `rstb` does not reach the PLL | **no** |
  | Lock drop | 0 | not known (the PLL has no reset port); `pll_sim` assumes static | unverified |

  A disagreement is harmless outside a scan: `mosi_sel` = 4 does not use
  `clk_tx`, and the #6b setting is a static phase in the bitstream, not
  run-time steps. Within a scan the script detects it (a jump of
  `PHASE_POS`, §5.2) and stops; only reconfiguring the FPGA (power-cycle
  Kuntur) brings the two together again. A scan therefore starts from a
  power-cycled Kuntur: `PHASE_POS` = 0 alone does not prove `CLKOS` is
  static. Resetting `PHASE_POS` only at configuration would fix the
  `rstb` row but tie the lock-drop row to the unverified PLL behaviour,
  and the stepper's FSM needs `rst_n_clk` anyway: not done.
- Optional bench check (R1a session, not before): step to SPT / 4, make
  the PLL lose lock, repeat one scan point; if the eye is where SPT / 4
  predicts, the phase survives a lock drop.

### 3.3 Known-answer checker

In the `clk` domain, on sampling transfers (`xfer_done`).
- The command of each SPI1 transfer, `regbank_dout1` at `rhd_spi1_start`
  (S3), goes into a history `h0` → `h1` → `h2`, advanced at the
  **start** of **every** transfer, config walk included, so the first
  sampling answers are paired correctly. At `xfer_done` of transfer *t*
  (controller `op1d`, after the answers are loaded in `csbend1` and
  before transfer *t* + 1 starts), `h0` = command *t*, `h1` = *t* − 1,
  and the four answers (`data_rx_a`, `data_rx_b`, `data_rx_a1`,
  `data_rx_b1`) belong to `h2`, the command of transfer *t* − 2.
  Advancing at the end instead (a rising edge of `done`, which is a
  level: high while the master is idle) would put the shift one `clk`
  before `xfer_done` and pair every answer with the wrong command.
- **Checked commands**, with their expected answer on all four halves:

  | Command | Expected |
  |---|---|
  | `READ(40..44)` | `{00, "INTAN"[R − 40]}`: `0049 004E 0054 0041 004E` |
  | `READ(48..50)` | `{00, "RHD"[R − 48]}`: `0052 0048 0044` |
  | `WRITE(R, D)` | `{FF, D}` |

  Anything else, including `CONVERT`, is not counted. The `WRITE` echo
  is the chip's own copy of the 8 data bits it latched from MOSI. A
  misread opcode turns the answer into something else, which also counts.
- Counters, saturating at `FFFF`, cleared together: transfers checked
  (one per transfer, not per half); errors on chip0 A, chip0 B, chip1 A,
  chip1 B; the first wrong answer since the clear, its half, and what
  was expected. If several halves are wrong in that transfer, the first
  error is the lowest half (chip0 A, chip0 B, chip1 A, chip1 B).
- Enabled by `CHK_EN`; when off, the counters hold. `CHK_CLEAR` clears
  everything, the first error's valid bit included; a clear and a count
  in the same `clk`: the clear wins. Reset by `rst_n_clk` (§3.6).

### 3.4 Regbank words

MCU-written (RAM, read back as written; the RTL also keeps live copies,
as for `ch_a`/`stream_enable`):

| Addr | Name | Bits |
|---|---|---|
| 232 | `MOSI_SCAN_CTRL` | [2:0] `mosi_sel` (reset **4**; 5–7 also select the bypass), [3] `CHK_EN` (reset 0), [4] `CHK_CLEAR`: a write with this bit set clears the checker; **reads back 0** (RAM and live copy masked, 2026-11-09), so a read-modify-write cannot clear again |
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

234–239 and 250–255 are unused. 240–249 are served by a read mux on
`dout0` (the MCU port; `dout1`, the SPI1 command port, stays pure RAM):
a write to them still lands in the RAM but is never read back. 230 is reserved for
`rsp_delay` (`fpga-diagnostic-access.md`). #8 (the A.7 counter) can take
250+.

### 3.5 Builds

In every build, idle unless commanded (D5): `mosi_sel` = 4 and `CHK_EN`
= 0 at reset. After the scan, the chosen point goes into each operating
build as the reset value of `mosi_sel` and the static `CLKOS` phase of
that rate's PLL (§5.4). No MCU action at boot.

The three implementations (#6) share the RTL, so the logic is in all of
them (S7). Develop on `impl_25k`; before a push, `scripts/build_kuntur.py`
(all three, timing) and `scripts/run_kuntur_tb.sh` (all three variants).

### 3.6 RTL structure (S1–S7, agreed 2026-11-04)

- **S1** `m_early` is the shift register's own `a_next`
  (`load ? data[n-1] : en ? areg[n-2] : areg[n-1]`), passed up by
  `spi_master_rhd2164x2`. *As built (2026-11-09):* in `sr_p2s_1`, a copy
  of `sr_p2s` plus `a_next`, kept beside `spi_master_rhd2164x2`, so
  `common/` and the other `sr_p2s` users are unchanged. A change to
  `sr_p2s` must be made in both.
- **S2** One shell in the top, `spi1_eye_scan` (`scan0`): sources, mux,
  the `clk_tx` register, the stepper, and the checker. *(Changed
  2026-11-09 from two modules, `mosi_scan` and `mosi_checker`.)*
  `spi_master_rhd2164x2` only gains an output (`a_next`), and its MOSI
  output now feeds the shell (`spi1_mosi_m0`); the shell drives the pin.
  Its unused `clk90` input can go.
- **S3** The checker's command is `regbank_dout1` latched at
  `rhd_spi1_start`, as `tun_aux` does: `rb_addr1` does not change from
  `op1a` to `op1d`, so it is the word `tx_load` puts in `txsr` one `clk`
  later. Not `regbank_dout1` sampled at the end (the next command may be
  on it). *(Changed 2026-11-09, Manuel: option (a); the earlier
  `cmd_sent` output of the master is not needed.)*
- **S4** The bypass mux sits after the `clk_tx` register, before the pad
  (no I/O register): `mosi_sel` = 4 must stay bit-identical to today,
  and a fixed mux delay shifts the whole map, not the window.
- **S5** SPT is a `localparam` per `clock_gen` branch, beside the
  `DIVOS_ACTUAL_STR` comment, exported as an output.
- **S6** `clock_gen`'s variant `generate` gets a name: both branches
  are `g_pll` (done 2026-11-05; `kuntur_tb` uses it), a stable
  testbench path, and no Questa `vsim-8852`.
- **S7** In all three builds, idle at reset.
- The RTL does not enforce the allowed (`PHASE_POS`, `mosi_sel`) pairs;
  the script does. A forbidden pair garbles commands, which the
  power-cycle after the scan clears (§5.3).
- `rst_n_clk` resets everything in §3.1–3.4; the `clk_tx` register
  resets asynchronously with it (`csb` is high then). It does not reset
  the PLL's phase: §3.2 *Reset* for what that means for `PHASE_POS`.

## 4. What it does not do

- No MISO capture change (D1: later, if needed).
- No live tracking: the result is a static setting per build.
- No change to SCK or CS. Their timing at the chip is what the scan
  measures MOSI against.
- No board delay measurement: it finds the window, it does not explain it.
- No temperature run before the animal test (D6).

## 5. Scan procedure (Claude: script; bench: both)

Script: `pc-app/mosi_eye_scan.py` (written 2026-11-04; tested against a
fake regbank, `pc-app/test_mosi_eye_scan.py`). `--analyze FILE.csv`
re-reads a run.

### 5.1 Set-up

Driven from the PC with the existing `REG_WRITE16`/`REG_READ16`
commands through the bridge (the MCU passes them to the regbank; no new
firmware). Streaming stopped, as those commands require. Sampling keeps
running, so the chips answer at the full transfer rate (825k transfers/s
at 25k, 924k at 28k). The script writes a CSV per run, one row per
point.

1. Kuntur power-cycled since the last scan or FPGA reset (§3.2
   *Reset*). Read `PHASE_INFO`: SPT, not busy. `PHASE_POS` = 0.
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
3. Read 242–249, then `PHASE_POS` again. Row: rate, SPT, `PHASE_POS`,
   `mosi_sel`, Δ (ns), count, the four error counts, first error. The
   row is kept only if `PHASE_POS` is still where the scan put it; it is
   also checked after every step.

That is 2 × SPT points (672 at 25k, 592 at 28k), each a handful of BLE
commands.

### 5.3 Afterwards

- `mosi_sel` = 4, `CHK_EN` = 0, step on to complete the turn
  (`PHASE_POS` = 0), restore the sampling table.
- If `PHASE_POS` jumped during the scan (an FPGA reset or a lock drop),
  the script does not step: the counter no longer says where `CLKOS` is.
  It restores the rest, keeps the rows measured before the jump, and
  says to power-cycle before the next scan.
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

- `kuntur_prims_sim.v` (done 2026-11-04): `pll_sim`'s `clkos` delayed by
  `phase_pos` × T / SPT plus the static delay, moved by `PHASESTEP`
  falling edges with `PHASESEL` 001 (`PHASEDIR` 0 = later), SPT 336 / 296
  per wrapper, back to 0 on a lock drop; `n_step_viol` counts pulses
  that break TN-02095's 5 ns setup or 4-VCO-cycle widths.
- `rhd2164_bfm.v`: parameters `MOSI_DELAY`, `SETUP`, `HOLD` (ns, default
  0 = no change): the chip sees MOSI `MOSI_DELAY` late and needs it
  stable `SETUP` before and `HOLD` after SCK rising; a violation in a
  transfer makes it decode wrong (the word inverted) and counts in
  `n_viol`. Two chips with different delays give a known pair of windows.
- Both models are checked on their own by `tb/eye_models_tb.sv` (15
  checks, done 2026-11-04), run by `scripts/run_kuntur_tb.sh`.
- `tb/phase_stepper_tb.sv` (2026-11-05, 86 checks per rate, run at 25k
  and 28k by `run_kuntur_tb.sh`): the stepper driving `pll_sim`, so each
  command also checks that `PHASE_POS` and the model's phase agree. N
  steps = N falling edges; both directions and both wraps; a full turn;
  N = 1023; N = 0; pulse widths and the 5 ns `PHASEDIR` set-up; busy
  over the command; a write while busy ignored, one right after taken;
  no pulses while idle (2100 `clk`); `rst_n` mid-run, alone (the counter
  and the model then disagree, reported) and with a lock drop.
- Checks: `mosi_sel` = 4 is bit-identical to today (the whole
  `kuntur_tb` passes unchanged); for each source and allowed φ, Δ matches
  §3.1; the checker counts injected errors on the right half with the
  right first-error words; a scan over the BFM's windows finds both
  edges for each chip at the expected Δ; stepping (`PHASE_POS`, busy,
  SPT, wrap) and the regbank words.

## 7. Open

- ~~O1~~ closed 2026-11-04 (#6 IPs): internal feedback (`INTCLKOP`),
  `PHASESEL` 001, SPT 336 / 296 (§3.2).
- ~~O2~~ closed 2026-11-09: the T/4 bound is a `set_max_delay` in `impl_1.pdc` (§3.1).
