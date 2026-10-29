# T3 — tunnel link bring-up on hardware

**Status:** procedure written 2026-10-29 (Claude), for Manuel's bench
session. Not run yet. Results go in the record sheet (§5) and the day's
log; this file changes only if the procedure does.

T3 (PLAN.md, *T: tunnel to A2*) asks three things of the hardware:

1. **The receiver locks to the K4.2 link test pattern** on the real
   cable, by its own sweep (`lvds-tunnel.md` §6.6).
2. **O2b(a):** does the first bit received land in `IDDRX4` `Q0` or `Q7`?
3. **O9:** does `IDDRX4` work at 45.54 MHz, below the IP Catalog's
   100 MHz floor?

and, because the start-up logic is now in both bitstreams, it also checks
the start-up behaviour that simulation could not (`system-startup.md`
§1.7, *Bench*; R-C4; O-S2).

## 1. What is on the bench

| Item | State |
|---|---|
| Kuntur FPGA | `kuntur` main `5470cef` (reset generator, `gddr_sync`, clock groups), flashed 2026-10-29 (Manuel) |
| Kuntur MCU | any current firmware: T3 needs only MCO (PB14, 32 MHz) |
| Companion | `intan_rec_adapter` from `kuntur` `6015d75` (status LEDs, 16:13 build) or later, by JTAG or from flash |
| Board | LIFCL-40-EVN, 12 V, **JP2 installed** (R-C7: the 12 MHz `clkin`) |
| Link | the micro-HDMI pigtail, Kuntur → companion |
| Optional | scope on the companion's LED pins (active low): G13 (LED2) to time the sweep, F13 (LED1) for short lock drops |

Nothing on the Intan side is needed: T3 is the link only.

## 2. Reading the companion (R-C6)

| LED | Ball | Lit means |
|---|---|---|
| LED0 | E17 | heartbeat: 0.7 s on, 0.7 s off. Stopped = supervisor in reset (SW2 held) or not configured |
| LED1 | F13 | `pll0` locked to `TUN_CLK` |
| LED2 | G13 | sweeping (`READY`, `cdr` not yet `rdy`): about **2.0 s** with N = 10,000 |
| LED3 | F14 | **link up**: `cdr` locked at the eye centre |
| LED4 | L16 | `cdr` **gave up**: a whole turn and no error-free step |

The receiver as built takes `Q0` as the first bit received (`din =
kuntur_data_8b`, `Q0` → bit 0; `cdr_tb` models the same). So:

- **LED3 = T3 passed on all three counts:** lock, O2b(a) = `Q0`, O9 =
  `IDDRX4` works at 45.54 MHz.
- **LED4 = one of: bits in `Q7` order (O2b(a)), `IDDRX4` failing (O9), or
  a closed eye.** §4 separates them.

What the LEDs cannot show: errors *after* lock. `cdr` re-sweeps only on a
LOCK drop, so LED3 stays lit even if the data later goes bad. Data
integrity after lock is T5's frame CRC.

## 3. Procedure

Each step: do, observe, record (§5).

**S1 — companion alone.** Kuntur off. Power the companion (or load by
JTAG).
- Expect: DONE (D18) lights; LED0 blinks; LED1–LED4 off.
- From flash, time 12 V on → DONE (**O-S2**; the guide quotes ~2 s for
  its demo design).

**S2 — SW2, companion alone.** Hold SW2 a second, release.
- Expect: all LEDs off while held, LED0 included; the heartbeat resumes on
  release.

**S3 — first lock.** Cable in, power Kuntur.
- Expect: LED1 within seconds (MCU boot, MCO, Kuntur's configuration, its
  1.024 ms hold-off, then `pll0` lock ≤ 10 ms), then LED2 for about 2.0 s,
  then **LED3**.
- Record: the LED2 duration (scope on G13, or by eye) → **the sweep time,
  R-C4**.
- If LED4: stop here, go to §4.
- If LED1 never lights: no `TUN_CLK` at the companion. Check the cable,
  then `TUN_CLK` on Kuntur's side (it should run once Kuntur's `READY` is
  up; the scope pattern of 2026-10-20/21).
- If LED1 but never LED2: `gddr_sync` never reaches `READY` (with LED1
  lit its `START` is high), or `cdr` stays in reset. A debug build with
  `READY` on a spare LED separates the two.

**S4 — hold.** Leave it 10 minutes.
- Expect: LED3 stays; LED1 never flickers off. (Any re-sweep shows as LED2
  lighting again.)

**S5 — restart from Kuntur's side** (the `MUT6=3` dependency,
`system-startup.md` §1.7). The companion recovers only if its PLL drops
LOCK while `TUN_CLK` is stopped (≥ 1.024 ms). The sign that it did is
**LED2 lighting again for ~2 s** after the event, then LED3. If LED3
simply stays lit through the restart, LOCK did not drop: the link is
then up on a stale word boundary and **the data is wrong although LED3
says link up**. Record that as a T3 finding (it needs a data-error
re-sweep in `cdr`, Manuel's call).
- S5a: reset Kuntur's MCU (NRST). MCO stops, Kuntur's LOCK falls, its
  generator holds off, `TUN_CLK` stops for the whole reset.
- S5b: power-cycle Kuntur.
- S5c: if E3 (Kuntur `rstb`, the MCU's PA10 through R15) is reachable:
  pull it low for a moment with the MCU running. Optional.
- Expect each time: LED3 off, LED2 ~2 s, LED3.

**S6 — cable out / in.** Unplug the pigtail for a few seconds, plug it in.
- Expect: LED1–LED3 off while out (LED0 keeps blinking); on re-insertion
  LED1, LED2 ~2 s, LED3.

**S7 — SW2 with the link up.**
- Expect: all off while held; on release LED1, LED2 ~2 s, LED3. (The
  emulator is reset too, by design; nothing on the Intan side is
  connected in T3.)

**S8 — repeatability.** Power-cycle both boards five times, in either
order. Each time: LED3 or LED4, and the sweep time.

## 4. If it gives up (LED4)

No on-chip logic analyzer is used in T3 (decided 2026-10-29, Manuel:
no Reveal), so the cases are told apart by rebuilds, one at a time:

| Build | LED3 | LED4 |
|---|---|---|
| 1. as is (`Q0` first) | T3 passes | go to build 2 |
| 2. `din` bit-reversed (`{kuntur_data_8b[0], …, kuntur_data_8b[7]}`) | **O2b(a): first bit in `Q7`**; keep this order | go to build 3 |
| 3. debug: the aligner's "preamble found" (A5 5A A5 5A at any `bitsel`) latched onto a spare LED (LED5, L15), cleared by SW2 | — | lit: the bits arrive in order but no step is error-free, so **the eye is too small** (pigtail, termination `DIFFRESISTOR=100`, `DIVOS_ACTUAL_STR` = 34 → 280 steps); dark: no pattern at all, so **O9: `IDDRX4` at 45.54 MHz suspect**, fallback `IDDRX1` + 2:8 in fabric (PLAN.md T3 risk) |

Builds 2 and 3 are Manuel's RTL, and are needed only if build 1 gives
up. Build 3's LED can stay in build 2's bit order: the preamble reads the
same in either order (`lvds-tunnel.md` §6.6), so it separates "pattern
present" from "pattern absent" either way.

Not measured in T3 without a read-out: the bathtub curve and the chosen
eye centre and width (O2b(b)), and whether `PHASESTEP` keeps rotating
past 360° (`lvds-tunnel.md` §6.6, *Before relying on the sweep*). A lock
after a full sweep shows only that it rotated at least once. Those wait
for the diagnostics console (O8) or a later debug build.

## 5. Record sheet

| Step | Result | Time / value | Notes |
|---|---|---|---|
| S1 | | 12 V → DONE: | |
| S2 | | | |
| S3 | LED3 / LED4 | sweep (LED2): | |
| S4 | | 10 min: | |
| S5a | LED2 seen again? | | |
| S5b | LED2 seen again? | | |
| S5c | | | |
| S6 | | | |
| S7 | | | |
| S8 | n × LED3, m × LED4 | sweeps: | |
| O2b(a) | `Q0` / `Q7` | | |
| O9 | works / fails | | |
| Builds used | 1 / 2 / 3 | | |

## 6. Not in T3

The R1 retune (decision 7: T3 runs at 45.54 MHz, and a sweep measured
now does not carry over to 42.504 MHz); RHX and the emulator; frames and
CRC (T4/T5); the RHX activity LED (deferred, R-C6); R-K3, R-K5/R-K6.
