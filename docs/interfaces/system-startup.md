# System start-up: Kuntur and the companion — interface spec

**Status: SPEC ONLY, written 2026-10-28. Nothing here is implemented yet.**
§1 (Kuntur) and §2 (the companion) are both agreed with Manuel. Start-up spans the MCU, the FPGA, its PLL and the RHD2164s, so it
has its own document rather than living inside the tunnel spec; the tunnel's
part (Lattice `gddr_sync` on both ends, T2) stays in `lvds-tunnel.md` §6.4
and takes its reset from here.

**Lane split:**

| Part | Owner |
|---|---|
| §1.3 — Kuntur FPGA RTL | Manuel (this document is the spec) |
| §1.4 — Kuntur MCU firmware | Claude, unless Manuel takes it |
| §1.7 — testbench for the reset generator | Claude |
| Board changes (§1.6) | Manuel |
| §2.3 — companion FPGA RTL | Manuel |
| §2.6 — companion testbench additions | Claude |

**Goal.** From power-on to "ready to stream" in well under a second, with
every piece of logic starting from a known state on a locked clock,
whatever order the MCU and the FPGA come up in, and with the MCU able to
tell that it happened.

## 1. Kuntur

### 1.1 What happens today (found 2026-10-28)

Read from the MCU firmware (`Core/Src/main.c`, `STM32_BLE/App/app_ble.c`,
`Core/Src/fpga_spi.c`), the FPGA RTL and pin file
(`kuntur_fpga.v`, `rhd2164_controller.v`, `regbank.v`, `impl_1.pdc`) and the
board (`kuntur144-ecl.kicad_pcb`, final BOM 2024-11-18, as-built from
Manuel).

1. **Power-on.** All rails come up together; nothing holds any of them off
   (Manuel). The FPGA (LIFCL-17, U2) runs its power-on reset, loads its
   bitstream from the SPI flash (U3, MX25R8035F) and wakes up. `PROGRAMN`
   and `DONE` go only to the programming header J2: the MCU can neither
   reconfigure the FPGA nor see that it has finished.
2. **MCU boot.** At power-on the STM32WB09 samples PA10, its internal
   pull-up makes it read high, and the ROM bootloader waits for a UART host
   before launching the application: about 5 s (recorded 2026-08-03, not
   measured since; see O-S1). `main()` then configures the clocks and
   starts **MCO3 = HSE 32 MHz on PB14**, which is the FPGA's `clkin`, before
   the 5 s debugger-attach delay (`HAL_Delay(5000)`, development only).
3. **The FPGA's clock appears** when MCO starts. Its PLL (`pll0`, 32 →
   45.54 MHz) begins to lock; its lock output is not generated
   (`LOCK_EN(0)`), so nothing waits for it.
4. **`rhd2164_controller` starts on the first clock edges.** It has no
   trigger: it plays the regbank config table once (2 dummy reads,
   registers 0–21, `CALIBRATE`, 4 dummy reads) and then loops over the
   sampling table for ever. Both RHD2164s are therefore configured **while
   the PLL is still acquiring lock**, and never again short of a power cycle
   or reprogramming.
5. **`rstb` (FPGA pin E3) is floating.** E3 connects only to R15 (to the
   MCU's PA10; **not fitted**) and to J2 pin 12, and the `.pdc` sets
   `PULLMODE=NONE`. The FPGA's global asynchronous reset is an open 1.8 V
   input whenever the programmer is not attached.
6. Streaming starts when the MCU writes `stream_enable`
   (`START_STREAMING`). The tunnel's clock chain and `block_gen` hang off
   the same `rstb` (T2 fixes those, `lvds-tunnel.md` §6.4).

The FPGA's own power-on reset does not cover this. It holds the device
while the rails ramp, configuration runs, and the wake-up sequence then
releases the global set/reset on the FPGA's **internal** oscillator
(TN-02099 §5.1, §5.4, §8). After wake-up every flip-flop is at its declared
initial value, but nothing in that sequence knows about `clkin` or the PLL.

### 1.2 Decisions (Manuel, 2026-10-28)

1. **Reset = the FPGA's power-on reset plus PLL lock.** The internal reset
   is built from flip-flops whose initial value (set by the global reset at
   wake-up) is "in reset", released only after the PLL has been locked for
   a hold-off time, and asserted again on any later loss of lock (§1.3).
2. **A lock loss mid-session resets all of Kuntur's logic** and so re-runs
   the RHD config. A bad `clk` makes everything downstream suspect.
3. **A regbank status word** (ID, locked, tunnel ready, RHD config done)
   that the MCU polls instead of waiting a fixed time (§1.3, §1.4).
4. **Measure the boot time without the debug delay** before deciding
   anything about PA10 (O-S1).
5. The debugger-attach delay is development-only and must not be in the
   operational build.
6. Kuntur's `pll0` is regenerated with its lock output, at the same
   45.54 MHz; R1 keeps it when it retunes (also T2).

### 1.3 Kuntur FPGA requirements

**R-K1 — `rstb` pin.** `PULLMODE=UP` on `rstb` in `impl_1.pdc`, so that it
can no longer float. It stays as an optional term of the reset (R-K2): with
nothing attached it is always high. If R15 is ever fitted (§1.6) the MCU
gets an FPGA reset through it with no RTL change.

**R-K2 — reset generator.** In the `clkin` domain (32 MHz, the clean
reference; `clk` is the clock that is settling):

```
lock_sync   = pll0.lock_o through 2 clkin flops   (initial value 0)
hold-off    = counter on clkin, cleared while lock_sync = 0 or rstb = 0,
              counts while lock_sync = 1, saturates at HOLDOFF
rst_n_clkin = 1 when the counter has reached HOLDOFF  (initial value 0;
              registered on clkin; cleared at once when lock_sync or rstb
              falls)
rst_n_clk   = rst_n_clkin through 2 clk flops: asserted (0) at once,
              released in step with clk                (initial value 0)
```

- **`HOLDOFF` ≈ 1 ms** (32,768 `clkin` cycles). The PLL's lock time is
  ≤ 10 ms (DS-02049, `tLOCK`) and its `LOCK` is non-sticky
  (`PLL_LOCK_STICKY(0)`), so it can toggle while it acquires; the hold-off
  restarts on every drop.
- **Every flip-flop of the generator has initial value 0**, so the design is
  in reset from the first instant after wake-up, whether or not `clkin`
  is already running. That is what makes the FPGA's power-on reset the
  root of the reset tree.
- **Check in Radiant** that the initial values are honoured as power-up
  values (the flip-flops' REGSET must agree with the global reset):
  one look at the map report, or a post-synthesis simulation. It is the
  only assumption in this section.

**R-K3 — who uses it.** Every block that is reset by `rstb` today in the
`clk` domain is reset by `rst_n_clk` instead: the SPI slave and its
controller, `main_controller`, the regbank's logic, `rhd2164_controller` and
`spi_master_rhd2164x2`, `ch_sel`, the FIFO and its mux, the test-pattern
generator. Two consequences:

- the RHD config table plays only on a locked clock, and again after any
  lock loss (decision 2);
- the regbank's **contents** survive a lock loss, since the reset touches
  logic, not the EBR. The MCU's channel selection and any `REG_WRITE`s
  therefore persist; only the state machines restart.

**R-K4 — the tunnel.** `gddr_sync`'s `RST` is `!rst_n_clkin` (it runs on
`clkin`, so it takes the `clkin`-side reset), its `START` is `lock_sync`.
`block_gen` is released by `READY` as in `lvds-tunnel.md` §6.4. This
replaces the `RST = !rstb || !lock_sync` given there for Kuntur; the
companion keeps its own (§2).

**R-K5 — RHD config done.** A flag set when `rhd2164_controller` finishes
the config table (leaves `op0d` for `op1a`) and cleared by `rst_n_clk`.

**R-K6 — status word.** One **read-only** regbank word, returning live
status (not RAM), at an address Manuel chooses in the control region:

| Bits | Meaning |
|---|---|
| 15:8 | constant ID, e.g. `0xA5`; tells "FPGA answering" apart from a floating or unconfigured MISO (`0xFF`/`0x00`) |
| 7:4 | reserved, 0 |
| 3 | tunnel `READY` (`gddr_sync`) |
| 2 | RHD config done (R-K5) |
| 1 | reset released (`rst_n_clk`) |
| 0 | PLL locked (`lock_sync`) |

A later version can widen the ID into a bitstream version, which is what
the PLAN's version/name handshake needs.

### 1.4 Kuntur MCU requirements

**R-M1 — debug delay.** `HAL_Delay(5000)` only in a development build (a
`#define`, off by default), never in the operational one.

**R-M2 — MCO first.** Start MCO as early as `main()` allows (it already
is: before the delay).

**R-M3 — poll, don't wait.** After MCO starts, read the status word every
1 ms until the ID matches and bits 0–3 are all 1, with a 100 ms timeout.
- On success: log the time taken, carry on (BLE, advertising).
- On timeout: log the word read, carry on anyway, and keep the
  "not ready" state (R-M4). The headstage must still be reachable over BLE
  to be diagnosed.

**R-M4 — refuse to stream when not ready.** `START_STREAMING` reads the
status word first (it runs in the streaming-stopped branch, where regbank
access is already allowed) and answers `success = 0` if it is not all
ready. `SET_CHANNELS` and the register console are unaffected.

**R-M5 — during a session.** A lock loss resets Kuntur's logic (decision 2)
and the stream will show it. Reading the status word while streaming is
deferred: the only regbank read allowed then is the 1 Hz telemetry call
site (CLAUDE.md, telemetry plane), and adding the status word to it is a
later item.

### 1.5 Timeline (Kuntur, nothing fixed)

| When | MCU | FPGA |
|---|---|---|
| 0 | power-on | power-on reset, configuration from flash |
| a few ms | application starts *(if PA10 reads low, O-S1)*; MCO on | wakes up; `rst_n_*` = 0, logic held in reset |
| + ≤ 10 ms | polls the status word | PLL locks; 1 ms hold-off; reset released |
| + < 1 ms | | RHD config (≈ 25 commands); tunnel `gddr_sync` (23 `clkin` cycles); status bits set |
| ≈ 20 ms | status OK; BLE up, ready to stream | waits for `stream_enable` |

The order does not matter: if MCO is running before the FPGA wakes up, the
FPGA wakes up in reset and finds the PLL already locked.

### 1.6 Board facts and later options

As built (Manuel, 2026-10-28), against the final BOM of 2024-11-18:

| Part | Function | BOM | As built |
|---|---|---|---|
| R12 | MCU MCO (PB14) → FPGA `clkin` (G8) | DNP | **fitted** |
| R13 | U4 → FPGA `clkin` | fitted | **removed** |
| U4 | SiT8021, 24 MHz oscillator | fitted | fitted, unused |
| R15 | MCU PA10 → FPGA `rstb` (E3) | DNP | not fitted |

**PA10's net, re-identified 2026-10-28:** `/PA10` = MCU U1.L5 → R15 →
FPGA E3 (`/PR7A`), and J2 pin 4. (The 2026-08 search had followed TP5,
which is PB1.)

**Later, not v1:**
- **Fit R15 and an external pull-down on `/PA10`.** PA10 then reads low
  at power-on, so the MCU skips the ROM bootloader's wait (O-S1), and the
  FPGA is held in reset until the MCU drives PA10 high: an MCU-controlled
  FPGA reset, entering R-K2 through R-K1. The pull-down must beat PA10's
  internal pull-up at power-on.
- **Replay the RHD config from the MCU** (a regbank bit that restarts
  `rhd2164_controller`'s config phase), for the B.5 pre-session self-test.
- **MCU visibility of FPGA configuration** (`DONE`, `PROGRAMN`), which
  today reach only J2.

### 1.7 Verification

- **Reset generator testbench (Claude):** `clkin` starting before and
  after wake-up; `LOCK` toggling during acquisition; a short and a long
  lock drop mid-run; `rstb` low. Checks: no release before `HOLDOFF`
  cycles of continuous lock; release synchronous to `clk`; immediate
  assertion on any drop; initial state in reset.
- **Radiant:** the REGSET check of R-K2.
- **Bench:** power-on to status-OK time on the MCU's UART, with and
  without the debug delay; status bits after an MCO stop and restart
  (a lock loss).

### 1.8 Open

| # | Question | State |
|---|---|---|
| O-S1 | Does the ROM bootloader still cost ~5 s at power-on (PA10 read high)? Measure power-on to UART banner with `HAL_Delay(5000)` removed. If yes, < 1 s needs the PA10 pull-down (§1.6). | open (Manuel, bench) |

## 2. Companion

The companion is the LIFCL-40-EVN eval board running `intan_rec_adapter`
(RTL in the `kuntur` repo). It has no MCU, so start-up is the FPGA's alone,
and its observer is the operator (LEDs) and RHX.

### 2.1 Three clock domains

| Domain | Clock | Holds | Clock present when |
|---|---|---|---|
| Supervisor | `clkin`, 12 MHz, ball L13 | §7.1 watchdog, link-down flag, `gddr_sync`, the `PHASESTEP` synchroniser, LEDs | always: the board oscillator, shared with the FTDI chip through **JP2** |
| Receiver | `wclk`, from `TUN_CLK` through `pll0` | `cdr`; later framing, CRC, the elastic buffer (T4/T5) | only while Kuntur is powered and the cable is in |
| Emulator | the Intan controller's SPI `sck` | `rhd2164x2_spi_slave_model`, its register RAM, MISO | only while RHX is running |

Each comes up at a different time, independently of the others, and each
gets its own reset (§2.3).

### 2.2 What happens today (found 2026-10-28)

Read from `intan_rec_adapter.v`, its `impl_1.pdc` and pad report, and the
eval board user guide (EB-02028).

1. **Power-on** (12 V adapter): power-on reset, then configuration. During
   development the bitstream is loaded over JTAG; in operation it will be in
   the board's 128 Mbit SPI flash (Manuel), which the user guide quotes at
   about 2 s to `DONE` for its demo design. **Until `DONE` every user pin
   is high-impedance, MISO included.**
2. **Wake-up.** Flip-flops at their initial values. The emulator's
   register RAM (chip ID, `INTAN`, `RHD`, registers 0–21) comes from
   `initial` blocks, so **the emulator passes RHX detection with no
   Kuntur, no cable and no `clkin`.** That property is kept (R-C2).
3. **`rstb` is push-button SW2 (ball G14),** pulled up on the board
   (10 kΩ, 10 nF to ground), high unless pressed. The pad report shows
   **`PULLMODE:DOWN`** on G14 (Radiant's default; the `.pdc` sets none),
   so the internal pull-down fights the board's pull-up. `clkin` (L13) is
   also `PULLMODE:DOWN`.
4. **One `rstb` resets all three domains**, and nothing else resets
   anything. The tunnel chain (`ECLKDIV.DIVRST`, `IDDRX4.RST`) takes
   `~rstb`, and `ECLKSYNC.STOP` is tied to 0 (T2 replaces both).
5. **No link state yet.** `CONVERT` is not decoded; the emulator answers
   with whatever its output register last held. The watchdog, the
   link-down flag and the sentinel (`lvds-tunnel.md` §7.1, §7.3) are T5.

### 2.3 Companion FPGA requirements (agreed with Manuel, 2026-10-28)

**R-C1 — a reset per domain, rooted in the power-on reset.**

```
Supervisor (clkin):
  rst_n_sup  = 1 after a few clkin cycles with rstb high; all of its flops
               have initial value 0 (in reset from wake-up, as R-K2);
               cleared at once when rstb falls. Never reset by the link.

Receiver (wclk):
  gddr_sync.RST = !rst_n_sup || !lock_sync          (lvds-tunnel.md §6.4)
  cdr_rstb      = rst_n_sup && READY, asserted at once, released through
                  2 wclk flops

Emulator (sck):
  rst_n_emu  = the power-on initial values plus rstb, asynchronous (sck
               may not be running when it releases). Never reset by the
               link: not by lock, READY, the watchdog or link-down.
```

`clkin` is local and always running, so the supervisor needs no lock and
no hold-off; a short counter (e.g. 16 cycles) is enough to keep the
release clear of wake-up. The emulator re-synchronises its bit counter on
every chip-select high already, so a release in the middle of an SPI word
costs at most that word.

**Why the emulator is never reset by the link:** a Kuntur power cycle or a
pulled cable must not disturb what RHX sees of the "chips". RHX reads the
chip registers only at detection; it does not re-read them, so emulator
state lost mid-session would never be noticed, only mis-answered.

**R-C2 — the emulator works from wake-up.** Detection (`READ` of the chip
ID, `INTAN`, `RHD`, §9.1b) depends only on the companion being
configured, whatever the state of Kuntur, the cable, the PLL or the
tunnel. T5 must not gate the emulator's register answers on link state;
only the *sample* answers (`CONVERT`) depend on the link (R-C3).

**R-C3 — start "link down".** The link-down flag's initial value is
**down**, so from wake-up until the first valid frame every `CONVERT`
gets the sentinel `0x8000` (`lvds-tunnel.md` §7.3). Zeros or stale values
at start-up would be a quiet, plausible-looking signal, which is exactly
what §7.3 forbids. (A T5 requirement, decided here.)

**R-C4 — when the link is up.** In order: `pll0` locked; `gddr_sync`
`READY`; `cdr` `rdy` and `valid` (locked at the eye centre, §6.6); then
valid frames (T5, §7.1). With N = 10,000 the sweep is about 2 s (280
steps × 10,000 blocks × 8 `wclk` of 87.8 ns ≈ 2.0 s; to be measured in T3),
so **after Kuntur powers up or the cable goes in, RHX shows the sentinel
rail for about 2 s, then data.** Expected; it goes in the runbook (R4).

**R-C5 — pins.** `PULLMODE=UP` on `rstb` (G14) in `impl_1.pdc`, so it
agrees with the board's pull-up. `clkin` (L13) is driven by an
oscillator; set `PULLMODE=NONE` on it.

**R-C6 — status LEDs.** No MCU, so the operator reads start-up from the
board's LEDs. Proposed (Manuel adjusts freely; the board has 14 spare):

| LED | Meaning | Domain |
|---|---|---|
| 1 | heartbeat, ~1 Hz (supervisor alive) | `clkin` |
| 2 | `pll0` locked (`lock_sync`) | `clkin` |
| 3 | sweep in progress (`READY` and not `rdy`) | synchronised to `clkin` |
| 4 | link up (`valid`; later the T5 link-up flag) | synchronised to `clkin` |
| 5 | `cdr` gave up (`rdy` and not `valid`, `fail`) | synchronised to `clkin` |

Every status bit crosses into `clkin` through two flops, like everything
else the supervisor reads (§6.1). Later, the O8 console reports the same
bits.

**R-C7 — JP2 installed.** The supervisor's 12 MHz clock is the FTDI
oscillator, reaching L13 only through JP2 (installed by default). Removing
JP2 removes the companion's only always-running clock: no watchdog, no
sentinel. A board requirement, for the bench setup notes and the runbook.

**R-C8 — reset generator module** *(proposed 2026-10-29, Claude; named
`reset_gen_adapter` by Manuel the same day, port `gddr_rdy`; Manuel
adjusts the names and the boundary freely — the testbench follows)*. One
module holds R-C1. `gddr_sync` stays outside it, in the top, so that the
module has no Lattice IP inside:

```verilog
module reset_gen_adapter (   // SUP_CYCLES = 16, internal
  input  wire clkin,      // 12 MHz board oscillator (supervisor clock)
  input  wire rstb,       // SW2, active low, asynchronous
  input  wire pll_lock,   // pll0 lock_o, asynchronous to clkin
  input  wire wclk,       // receive word clock: stops (STOP), may be absent
  input  wire gddr_rdy,   // gddr_sync READY
  output wire rst_n_sup,  // supervisor reset, clkin domain
  output wire lock_sync,  // pll_lock through 2 clkin flops -> gddr_sync START
  output wire gddr_rst,   // -> gddr_sync RST
  output wire cdr_rstb,   // receiver reset, wclk domain -> cdr rstb
  output wire rst_n_emu   // emulator reset
);
```

Ports:

| Port | Dir | Active | Domain | Definition |
|---|---|---|---|---|
| `clkin` | in | — | — | 12 MHz board oscillator on L13, through JP2 (R-C7). Runs from `DONE` on, Kuntur or not. Clocks the supervisor, `lock_sync` and `gddr_sync`. |
| `rstb` | in | low | async | SW2 on G14: board pull-up 10 kΩ, 10 nF to ground (τ = 100 µs, so a press is already debounced), `PULLMODE=UP` (R-C5). Low resets all three domains. |
| `pll_lock` | in | high | async | `pll0.lock_o`, non-sticky. 0 with no `TUN_CLK`; chatters while the PLL acquires (≤ 10 ms, `tLOCK`). |
| `wclk` | in | — | — | `ECLKDIV` ÷4, ≈ 10.6 MHz. Absent with Kuntur off or the cable out; stopped while `gddr_sync` holds `STOP`; restarts at an arbitrary phase after `DIVRST`. |
| `gddr_rdy` | in | high | `clkin` | `gddr_sync` `READY`. 1 when the start-up sequence is done; falls at once on `RST`, or when `START` falls. |
| `rst_n_sup` | out | low | `clkin` | Supervisor reset. 0 at once with `rstb`; released on a `clkin` edge after `SUP_CYCLES` with `rstb` high. Resets the watchdog, the link-down flag, the LEDs. Never depends on the link. |
| `lock_sync` | out | high | `clkin` | `pll_lock` through 2 `clkin` flops, cleared by `rstb`. To `gddr_sync` `START`, LED 2, the supervisor. |
| `gddr_rst` | out | high | `clkin` | `!rst_n_sup \|\| !lock_sync`, to `gddr_sync` `RST` (asynchronous). Holds `DDR_RESET` = 1, `READY` = 0 until both are up. |
| `cdr_rstb` | out | low | `wclk` | Receiver reset: `rst_n_sup && gddr_rdy`, 0 at once, released through 2 `wclk` flops. To `cdr` `rstb` (its `wclk` logic and its `clkin` `PHASESTEP` synchroniser, §6.4). |
| `rst_n_emu` | out | low | async | Emulator reset = `rstb`, nothing else. To `rhd2164x2_spi_slave_model`, `rhd2164_model_reg_ram` and the `data_tx` registers (`sck` domain). |

**Power-up values come from the reset value, not from `initial`**
*(checked 2026-10-29 in Radiant 2025.2.1)*. A Nexus flop's wake-up value
is set by its primitive: `FD1P3DX` (async clear) and `FD1P3IX` (sync
clear) have `REGSET = "RESET"` and wake up 0; `FD1P3BX` / `FD1P3JX`
(preset) have `REGSET = "SET"` and wake up 1 (`cae_library/simulation/
verilog/uaplatform/FD1P3*.v`). The configuration's wake-up asserts GSR to
every flop with `GSR = "ENABLED"` (the default, and what synthesis
writes: `intan_rec_adapter_impl_1.vm`). That wake-up GSR is the power-on
reset; no `GSR` primitive is instantiated (one would add a user-pin GSR,
which is not wanted; the current build's `GSR_INST` is undriven and
clipped). Whether synthesis honours an `initial` value on a flop with no
reset is not documented here, so the rule is:

- **every flop of the generator has an asynchronous reset whose value is
  its required power-up value** (0 here), so it maps to `FD1P3DX`;
- **no initial values in the RTL** *(Manuel, 2026-10-29)*: the testbench
  sets each register to its power-up value at t = 0, standing in for GSR
  (`reset_gen_adapter_tb.sv`, *GSR stand-in*);
- **no `GSR = "DISABLED"`** on any of them.

**The check after synthesis** *(script added 2026-10-29)*: every
generator flop in the `.vm` has `GSR = "ENABLED"` and is `FD1P3DX` or
`FD1P3IX`, except `gddr_rst`, which is `FD1P3BX` (G5). It is scripted,
and it is the REGSET check of R-K2 for both ends (kuntur repo, from
`kuntur144/fpga`):

```
scripts/check_powerup.py intan_rec_adapter/impl_1/intan_rec_adapter_impl_1.vm reset_gen_adapter --one '^gddr_rst'
scripts/check_powerup.py intan_rec_adapter/impl_1/intan_rec_adapter_impl_1.vm gddr_sync --one '^ddr_reset_d'
```

`gddr_sync`'s `ddr_reset_d` wakes up 1 by Lattice's design (set by
`rst`), which holds `ECLKDIV` and `IDDRX4` in reset from configuration.
Both pass on the 2026-10-29 10:25 build (11 and 12 flops).

It walks the module and everything it instantiates in the netlist (which
keeps the RTL hierarchy), and exits 0 on PASS, 1 on a wrong flop, 2 if the
module is missing (not built yet, or its hierarchy dissolved:
`syn_hier = "hard"` keeps it). `--one REGEX` names flops that must wake
up 1. It warns when the RTL is newer than the netlist. Tried on the
2026-10-28 builds: the companion's 549 flops (= a `grep` count) pass with
its six intended presets named (`cdr`'s `PHASESTEP` synchroniser, two
FSM state bits, the emulator's `cnt0`); Kuntur shows 11 presets, all
FSM state bits or regbank defaults (channel bits, `stream_enable`). Simulation cannot see
it: the testbench's mutant 8 (`lock_sync` with no reset, initial value
only) fails there only through `rstb`, not through its power-up value.

What the testbench holds it to (`tb/reset_gen_adapter_tb.sv`):

| # | Requirement |
|---|---|
| G1 | Every flop but `gddr_rst` (G5) has initial value 0, so `rst_n_sup`, `lock_sync` and `cdr_rstb` are 0 at wake-up, with or without `clkin` running. |
| G2 | `rst_n_sup` = 0 at once (no clock edge) whenever `rstb` = 0, however short the pulse. |
| G3 | `rst_n_sup` rises on a `clkin` edge, after `SUP_CYCLES` (20 in the RTL) to `SUP_CYCLES` + 4 edges of `rstb` continuously high (room for a `rstb` synchroniser), and does rise. |
| G4 | `lock_sync` = `pll_lock` through exactly 2 `clkin` flops, and 0 at once whenever `rstb` = 0. |
| G5 | `gddr_rst` = `!rst_n_sup \|\| !lock_sync`, registered on `clkin` (Manuel's RTL, 2026-10-29): one `clkin` late, initial value 1, set to 1 at once by `rstb`. So it is a preset flop (`FD1P3BX`), the one generator flop that wakes up 1. |
| G6 | `cdr_rstb` = 0 at once (no `wclk` edge) when `rst_n_sup` or `gddr_rdy` falls; rises on a `wclk` edge after 2 (at most 3) edges of both high. |
| G7 | `rst_n_emu` = `rstb`, from t = 0 with no clock running, and nothing else: not `pll_lock`, `gddr_rdy`, `wclk`. |
| G8 | With `gddr_sync` in the loop: `READY` 20–26 `clkin` edges after `rst_n_sup && lock_sync`, and back after every lock drop and every `rstb` press. |

Two notes for the RTL:
- *(Done 2026-10-29: Manuel registered `gddr_rst`, G5.)* An unregistered
  `gddr_rst` ORs two `clkin` flops and can glitch low for a moment when
  `rst_n_sup` rises on the same edge as `lock_sync` falls.
- `cdr_rstb` and Kuntur's `block_gen` reset and `rst_n_clk` are the same
  circuit (assert at once, release through 2 flops of the destination
  clock). One small common module (e.g. `common/rst_sync.v`) would serve
  all three.

### 2.4 Order with Kuntur and RHX (runbook material)

| Event | Companion | Status |
|---|---|---|
| Companion configured **before** RHX starts | detection passes; sentinel until the link is up | detection yes; sentinel T5 |
| RHX started **before** the companion is configured | RHX finds no chips (MISO high-impedance); after `DONE`, **rescan** in RHX | hardware limitation; runbook |
| Kuntur on, or cable in, at any time | lock, sweep (≈ 2 s), link up; RHX does not rescan | T1/T2 by design |
| Kuntur off, or cable out, mid-session | link down within µs (watchdog), sentinel, counted (`frames_sentinel_served`) | T5 |
| SW2 pressed mid-session | everything restarts; the emulator returns to its initial registers; RHX carries on | by R-C1 |
| Companion power cycle or reprogramming mid-session | MISO high-impedance for seconds: RHX sees garbage, **not** the sentinel | cannot be fixed in the FPGA; runbook: don't |

**Operational order:** power the companion (bitstream in flash) and wait
for `DONE`; then start RHX; Kuntur at any time. During development, with
JTAG loading, the same order applies with "programmed" for "`DONE`".

### 2.5 Timeline (companion, nothing fixed)

| When | Supervisor | Receiver | Emulator |
|---|---|---|---|
| 0 | power-on reset, configuration | | MISO high-Z |
| ≈ 2 s (flash) | wakes up in reset; released after a few cycles; link down | held (`READY` = 0) | answers detection; sentinel on `CONVERT` |
| Kuntur on / cable in | `lock_sync` | `gddr_sync` (23 cycles), sweep ≈ 2 s | sentinel |
| + ≈ 2 s | LED 4 on | `valid` | data |

### 2.6 Verification

- **Reset generator testbench (Claude, 2026-10-29):**
  `intan_rec_adapter/source/impl_1/tb/reset_gen_adapter_tb.sv`, checks
  G1–G8 of R-C8 continuously. Scenarios: wake-up with no Kuntur; LOCK
  chattering during acquisition; a sub-cycle glitch; a 2-cycle drop; cable
  out 50 µs; a 20 ns `rstb` pulse; SW2 held 100 µs; SW2 with the cable
  out; variants `clkin` 20 µs late and Kuntur locked before wake-up.
  Passes against a behavioural model of R-C8 kept in the testbench
  (`-DREF_MODEL`); nine deliberate mutants of it all fail. **Passes on
  Manuel's `reset_gen_adapter` RTL (2026-10-29)**: all six runs (default,
  `+late_clkin`, `+early_kuntur`, seeds 7, 42, 1234), after three fixes
  the testbench found (`gddr_rst` cleared instead of set by `rstb`; no
  power-up values in simulation, now set by the testbench; `cdr_go`
  inverted). READY 25 `clkin` edges after `lock_sync`.
- **Top-level integration (Manuel, 2026-10-29), checked by Claude:**
  `rst_gen_0` and `u_gddr_sync` wired as in `lvds-tunnel.md` §6.4
  (`STOP` → `ECLKSYNC`, `DDR_RESET` → `ECLKDIV.DIVRST` and `IDDRX4.RST`,
  `cdr` on `cdr_rstb`, the emulator on `rst_n_emu`); `kuntur_rst` gone.
  Build of 10:25: netlist check passes for both modules (§2.3 R-C8);
  timing clean with the new receive-side constraints (`lvds-tunnel.md`
  §6.4, *Timing constraints*). Not yet on hardware.
- **`cdr_tb` part 5 (Claude, 2026-10-29):** the real
  `reset_gen_adapter` and `gddr_sync` in the loop, wired as the top;
  `STOP` gates the model's ECLK (glitch-free, on a falling edge),
  `DDR_RESET` holds the ECLKDIV and IDDRX4 models. Four events from a
  locked link: SW2 with Kuntur locking 20 µs late; `LOCK` low 1 µs;
  cable out 50 µs; SW2 with `LOCK` held. After each: `READY` fell and
  rose (26–27 `clkin` after `LOCK`, 46 after SW2), `cdr` was reset and
  released 1–2 `wclk` after `READY`; the last `DDR_RESET` release before
  `READY` came with ECLK stopped; no `PHASESTEP` pulse during reset; one
  whole sweep (judged as part 2) locked at its centre; `bitsel` equal to
  a fresh reference receiver's offset (it moved at every restart: a new
  word boundary each time, as §6.4 says); `rst_n_emu` fell for SW2 only.
  All pass, also with `+inj=4` (part 5 skipped) and `+start=100
  +seed=7`. Three testbench mutants (ECLKSYNC ignoring `STOP`; `cdr`
  reset by `rstb` alone; `gddr_sync` `RST` = `!rstb` alone) must fail:
  see the run notes in `cdr_tb.sv`.
- **Emulator reset independence (Claude, with T5's testbench):** a lock
  drop, a `READY` drop and a watchdog trip mid-SPI-word leave the register
  RAM and the detection answers unchanged; `CONVERT` answers `0x8000`
  from wake-up until the first valid frame.
- **Radiant:** the REGSET check of R-K2, for the companion's supervisor
  and emulator flops too. *Pad report, 10:42 build:* G14 `PULLMODE:UP`,
  L13 (`clkin`) `PULLMODE:NONE`: R-C5 done.
- **Bench:** boot from flash and time power-on to `DONE`; start RHX
  before and after `DONE`; plug and unplug the cable with RHX running and
  watch LEDs 2–4 and the sentinel rail.

### 2.7 Open

| # | Question | State |
|---|---|---|
| O-S2 | Power-on to `DONE` from the eval board's flash with our bitstream (the guide's ~2 s is for its demo). Faster with a higher `MCCLK` or quad SPI if it matters. | open (bench, with T3) |
