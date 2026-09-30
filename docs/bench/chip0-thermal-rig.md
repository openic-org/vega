# chip0 thermal rig — as built

**Status:** built 2026-09-30 (Manuel). This is the *as-built* record of the
instrumentation for PLAN.md A.1.2 (chip0 intermittency). The plan says
*what* to run and why; this says *what is on the bench* so that every trial
in `log/chip0-temperature-trials.md` can name its setup instead of
re-describing it. If the rig changes, change this file in the same commit.

## 1. Board facts that decide placement

Read from `kuntur144-nil.kicad_pcb` / `kuntur144-ecl.kicad_pcb`, not from
memory:

- **chip0 = U0, chip1 = U1**, both on `kuntur144-nil`
  (`docs/interfaces/fpga-rhd2164-chip0-placement.md` §2.2). 9 × 7 mm BGA,
  16 mm apart, mirror-imaged. The RHS2116 (U2, QFN-44) sits between them.
- **Both RHD2164s are sandwiched inside the stack.** They are on the
  *front* of `nil`, the same face as its board-to-board receptacle J2; the
  `ecl` plug J0 is on `ecl`'s *back*. The gap is set by the DF40C(2.0)
  stacking height, nominally ~2 mm.
- **Each RHD2164 sits at one short end of the stack.** Both boards are
  24 × 13 mm; chip0's package edge is ~0.4 mm from the **MCU end** and
  chip1's from the **micro-HDMI end**, ~1 mm from the long edges. So each is
  reachable by sliding a bead into the gap.
- **The FPGA (`ecl` U2) faces up** and is directly reachable.
- **The SCK/MOSI traces cannot be targeted separately.** chip0's SPI branch
  runs on internal layer 3, and the 100 Ω terminations R3–R5 sit inside the
  gap beside chip0. Spray localisation can therefore resolve **chip0 end vs
  chip1 end vs FPGA** — not traces as a fourth target, which PLAN.md A.1.2
  step 3 originally listed.

## 2. Probes

Labfacility `XE-3506-001`: type K, exposed welded junction, 32 AWG, PTFE.
Bead taped with Kapton on the package top, a second tape point on the lead
for strain relief, leads looped and taped along the bench.

| Probe | Target | Meter | Input / mode |
|---|---|---|---|
| **P1** | **chip0** (`nil` U0) | **Keithley DMM6500** | front terminals via K-type adapter; **TEMPERATURE, thermocouple K** |
| **P2** | **chip1** (`nil` U1) | Keysight U1242B | **T1** |
| **P3** | **FPGA** (`ecl` U2) | Keysight U1242B | **T2** |

Chip0 is on the DMM6500 because it is the only channel that can be logged
(§4); chip1 − FPGA or chip0 − chip1 differentials are read live on the
U1242B (`T1−T2`) by moving plugs at the meter — the beads never move.

- **Bead placement (P1, P2):** in the inter-board gap, on the package top.
  **Caveat (Manuel):** the packages are small, so the tape has little area to
  grip and the beads *may move*. A bead that shifts reads as a temperature
  change: an unexplained step on one probe with no matching step on the
  others, with nobody touching the rig, is movement, not thermal. The
  per-session at-rest check (§5) is what catches it.
- **DMM6500 reference junction: Simulated** (confirmed). Front-terminal CJC
  is a fixed setting, not a measurement, so the display is ≈ *setting +
  (bead − terminal temperature)*. At rest, with bead and terminals both near
  room, it therefore shows roughly the **setting**, not the room — which is
  why it read 21.25 °C and later 20.21 °C while the room moved ~0.1 °C.
  **Deltas are exact; absolutes need a per-session offset.** Setting:
  **Simulated Reference Temperature = 23 °C** (factory default; found by
  Manuel 2026-09-30). **Leave it at 23 °C** — changing it mid-series shifts
  every P1 number and fixes nothing. From display ≈ 23 + (bead − terminal)
  with the bead at room, the front terminals ran **~22.5 °C** at the first
  check and **~23.6 °C** at the second: ~2.8 °C above room and still
  warming. So P1's absolute value carries the terminal drift — irrelevant
  over a spray burst, roughly **±1 °C over an overnight run** until the DMM
  is thermally settled. Cross-check by repeating the at-rest check at the
  end of a run (board cooled) and against T1/T2, which have real CJC.
  At the at-rest check (§5) chip0's bead *is* at room, so
  **P1 offset = Govee − DMM6500 at rest**, added to every P1 reading of that
  session. Valid while the DMM's terminal temperature is steady — **keep the
  DMM6500 powered continuously**, not switched on just before a run.
- **The U1242B measures its own cold junction**, so its readings are
  absolute within the meter + probe tolerance.
- **U1242B floor:** −40 °C. Freeze spray is −51 °C; a package under short
  bursts should stay above −40 °C, but it can clip. If a spray reading pins
  at the floor, move that probe to the DMM6500 (floor −200 °C in TC mode).

## 3. Ambient

**Govee H5075** (`A4:C1:38:E1:0D:8C`) placed beside the Kuntur stack.
Logged by `pc-app/ambient_logger.py` → `pc-app/bench/ambient_*.csv`
(°C, %RH, dew point, battery, error flag, raw payload) on the
`wall_time_utc` timebase shared with `health_*.csv`. The display reads °F;
the log is °C. Dew point is the well-mixed quantity (one sensor anywhere
reasonable in the room is enough), and it is the frost budget for spraying.

## 4. Timebases

| Record | Source | Timebase |
|---|---|---|
| Channel liveness | pc-app → `bench/health_*.csv` | `wall_time_utc`, 1 s |
| Ambient | `ambient_logger.py` → `bench/ambient_*.csv` | `wall_time_utc`, ~6–10 s |
| chip0 temperature (P1) | DMM6500 reading buffer → USB stick CSV | DMM clock (local), converted to UTC at alignment |
| chip1 / FPGA (P2, P3) | U1242B | read by eye, noted in the trial row |

**This DMM6500 has no host interface.** Only the front USB-A (a flash-drive
host) is fitted — no rear USB-B, no LAN (checked by Manuel, 2026-09-30).
P1 is therefore logged **in the instrument**: interval readings into the
reading buffer (each timestamped by the DMM), saved to a USB stick as CSV
after the run, and aligned afterwards. For that to work:

- **DMM clock:** set by hand 2026-09-30 16:47 local, against the bench PC
  (NTP-synchronised, CDT = UTC−5): agreed to within a minute. DMM
  timestamps are local — **UTC = DMM + 5 h** while CDT holds (CST from
  2026-11-01: +6 h). A hand-set clock leaves a residual offset of up to
  tens of seconds: harmless for slow drift, not for spray bursts. **At the
  start and end of each run, photograph the DMM clock and a PC terminal
  running `date` in one frame** — that pins the offset to ~1 s and
  measures the DMM clock's drift over the run.
- **Buffer capacity ≥ run length × rate** (an overnight run at 1 Hz is
  ~60,000 readings), and **fill-and-stop, not circular** — a circular buffer
  silently overwrites the run's start, which is the cold start itself.

## 5. At-rest check — every session, before anything is powered

Kuntur off; record all four readings in the trial row. It does two jobs:
confirms no bead has moved (a probe that stops agreeing with the others
has), and gives the **T1 − T2 zero offset**, which must be subtracted from
every differential that session — or zeroed with the U1242B's relative
(Null) function before spraying. Without it, a sub-degree "localisation"
is indistinguishable from the offset.

| When | Govee | P1 DMM6500 (chip0) | P2 T1 (chip1) | P3 T2 (FPGA) | T1 − T2 | Conditions |
|---|---|---|---|---|---|---|
| 2026-09-30, first | 69.6 °F / 20.9 °C, 69 %RH | 21.25 °C | 20.5 °C (one channel shown) | — | — | Kuntur off |
| 2026-09-30, second | 69.4 °F / 20.8 °C | 20.21 °C (P1 offset **+0.6 °C**) | 19.8 °C | 18.9 °C | **+0.9 °C** | Kuntur off, PSU off, scope on |

Reading of the second row: T1 and T2 sit 1.0 and 1.9 °C below the Govee —
within what type-K probe tolerance plus meter accuracy allows, and the
point is that they are **stable**, not that they match. The DMM6500's
number is not comparable to the others (simulated CJC, §2).

## 6. Handling rules (from PLAN.md A.1.2)

- Place or re-seat beads only with the board **powered off**; wrist strap on.
- The bead is bare metal: junction on the package's mould compound only,
  Kapton on the side facing the other board.
- Freeze spray: short bursts, **full rewarm and dry before the next**;
  visible frost is the stop signal. At 20.9 °C / 69 %RH the dew point is
  ~15 °C, so every burst will frost — pick a dry day if there is a choice.
- Keep the Klein adapters and meters out of the spray plume (the alloy →
  copper transition in the adapter is a cold junction too).
