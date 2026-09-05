# chip0 intermittency — temperature trial log

**What this is.** A running record of chip0 pass/fail against thermal state,
started 2026-09-04. Background, mechanism and the reasoning behind it:
**PLAN.md A.1.2** and `log/2026-09-04.md` §7. Kept as one appendable file
rather than scattered through daily logs, because the whole point is the
*series* — a single trial says nothing.

**Why it exists.** chip0 has been root-caused three times and every one was
confirmed by a single hardware pass. On a board that drifts over hours, one
pass cannot distinguish a fix from a lucky boot. Until this table has enough
rows to show a pass *rate* and what it tracks, no bench result on this board
can be scored — including any future "fix".

## Method

- **Indicator:** live waveform in the pc-app, not the A.1.1 ladder.
  **Ch A = 42** (chip0, range 0–63) and **Ch B = 94** (chip1, range 64–127),
  chosen at random on 2026-09-04 and **held fixed for the whole series**.
  One channel per chip is mandatory: with both on chip1 a dead chip0 is
  invisible and the trial records a false pass.
- **Failure signature:** chip0 returns all `0xFFFF`, which decodes as −1 in
  int16, so Ch A reads as a **flat trace at essentially zero** while Ch B
  shows normal noise. This does **not** trip the pc-app's underrun
  indicator — that fires on `0x8000` on *both* channels, a different
  condition. Flat vs. alive is the signal.
- **Bitstream, held fixed:** `cdc7d39dca801aa8864cb0840d6aac1d2d8601c34c5026c80a1dd72d90da9fa7`
  (`kuntur` `761d662`, on `main`). The FPGA is SRAM-configured, so every
  power cycle requires a reflash — reflash from this file, and **do not let
  Radiant rebuild**: rebuilds here are not bit-identical, and a new
  bitstream would void the series.
- **Thermal state** is recorded as a category, not a temperature: no
  thermometer is available yet (see Limitations).

## Trials

| # | Date | Time | Thermal state | Ch A (chip0) | Ch B (chip1) | Ambient | Notes |
|---|---|---|---|---|---|---|---|
| 0 | 2026-09-04 | ~11:09 | cold — first bench activity of the day | **FLAT** | ok | not measured | Failed twice: committed bitstream `7a5418d6`, then a rebuild. Retrospective entry, before this protocol existed; different bitstream, so not directly comparable to the rows below |
| 1 | 2026-09-04 | 15:50 | **warm** — powered and running several hours, undisturbed | ok | ok | thermostat 72 °F / 22.2 °C (see Environment) | Baseline / initial state. Recovered untouched earlier the same afternoon after trial 0's failures. Ch A/Ch B set to 42/94 for the first time here. **Oscilloscope already off** for some minutes before this reading — so trials 1 and 2 share that condition and it is controlled between them |
| 2 | 2026-09-05 | 08:06 | **warm** — powered overnight, undisturbed, scope off | ok | ok | thermostat 72 °F / 22.2 °C; outside 70 °F / 21.1 °C | **PASS.** Checked before touching anything. Room reading identical to trial 1 — the overnight drift below setpoint did not occur, so ambient is roughly constant across trials 0–2 |
| 3 | 2026-09-05 | 09:08 | **cold soak** — powered off 08:10, off 58 min, reflashed, checked promptly | ok | ok | thermostat 72 °F / 22.2 °C; outside ~70 °F / 21.1 °C | **PASS — a null.** Everything powered down (FPGA, MCU, bridge). Channels re-set to 42/94 after reconfiguration (SET_CHANNELS is runtime state, cleared by FPGA reset). Power-up order not recorded |

### Trial 2 — and a result the thermostat did not predict

**The room did not get colder overnight.** The thermostat read 72 °F at
trial 1 (2026-09-04 15:50) and reads **72 °F again at trial 2**
(2026-09-05 08:06), with outside at 70 °F — only 2 °F below setpoint, not
enough to pull a thermally massive house below it. The predicted overnight
drift below setpoint did not happen.

That is more useful than a drop would have been:

- **Room ambient is roughly constant across trials 0, 1 and 2.** Outside
  was ~70 °F during yesterday morning's *failure* and is ~70 °F during
  today's *pass*; the thermostat reads the same 72 °F at both of
  yesterday's afternoon pass and today's morning pass. Within the limits
  of a single-zone thermostat one floor up, **the room was at a similar
  temperature when chip0 failed and when it worked.**
- **That argues against room ambient as the driver**, and toward the board
  — self-heating, or something else about a fresh power-up.
- **It makes trial 3 close to a clean single-variable test.** Room
  unchanged from trial 2, only the board's own temperature falls. If
  trial 3 fails, board temperature is isolated with the room held constant
  by observation rather than assumption.

Caveat kept in view: the thermostat is one zone, a different floor, and
biased warm. "Similar reading" is not "same test-room temperature". It is
the best available and it is weak.

### What trials 2 and 3 do and do not show

**Trial 3 is a null, and it was pre-registered as one that refutes
nothing.** Recording what it actually narrows:

Running tally for bitstream `cdc7d39d…`, the only one under the protocol:

| | Condition | chip0 |
|---|---|---|
| trial 0b | 2026-09-04 ~11:09, cold, after an overnight power-off | **FAIL** |
| trial 1 | 2026-09-04 15:50, warm, hours powered | pass |
| trial 2 | 2026-09-05 08:06, warm, powered overnight | pass |
| trial 3 | 2026-09-05 09:08, cold, 58 min off | pass |

**One failure in four boots.** Three consecutive passes is not evidence of
anything: at a per-boot failure probability of 25 % the chance of three
passes in a row is 42 %, and at 50 % it is still 12.5 %. **Nothing here
distinguishes "fixed" from "unremarkable luck"** — which is the exact trap
A.1.2 exists to name, so it must not be sprung here.

**What did move:** a 58-minute cold soak at the same room reading did
*not* reproduce the failure. A small unenclosed board reaches ambient in
well under that, so if a simple board-temperature threshold existed at
~72 °F ambient, trial 3 should have found it. It did not.

Live hypotheses after today, none eliminated:

1. **Temperature, but needing colder than this room reached.** The
   thermostat is a floor up and biased warm; yesterday's test room may
   genuinely have been colder than today's despite matching readings.
2. **Off-duration, not temperature.** Overnight-off is not 58-minutes-off.
   Something with a long time constant — moisture, a slowly-settling
   rail, an electrolytic — would separate them while board temperature
   does not.
3. **Per-boot randomness, with no thermal driver at all.** One failure in
   four boots is entirely consistent with this, and it is the hypothesis
   the data currently fits most cheaply.
4. **Humidity**, unmeasured throughout.

**This shifts the priority.** More single trials have low information
value now: each costs ~15 minutes and moves the estimate barely at all.
**The pass-rate measurement (PLAN.md A.1.2, item 0) is now the thing to
do** — ten rapid power cycles, each ~2 minutes (off, on, reflash, check),
gives a real number in under an hour and separates hypothesis 3 from the
rest. If the rate comes out near zero, the thermal hypotheses survive and
deserve equipment; if it comes out at 20–30 % with no thermal pattern,
that reframes chip0 entirely.

## Environment, 2026-09-04

Recorded because it turns out to matter for how the results can be read.

- **Test room is in a house with a single thermostat, on the floor above.**
  One zone for the whole building, so temperature varies broadly between
  rooms and floors and the thermostat reading is **not** the test room's
  temperature. Heat rises, so the floor above is likely *warmer* than the
  test room — the reading is probably an over-estimate.
- **Thermostat: cool mode only** — it can lower the temperature, never
  raise it. Reading at trial 1: **72 °F (22.2 °C)**.
- **Outside at trial 1: 89 °F (31.7 °C)**, feels-like 94 °F (34.4 °C),
  per phone weather.
- **Oscilloscope off**, switched off some minutes before trial 1 — the one
  heat source near the board that is being deliberately controlled.

### What cool-only mode implies

*This section was written backwards on first attempt and corrected the same
evening, 2026-09-04 — the wrong version is not preserved because this file
is a protocol others will act on, but the error is worth naming: it
confused the AC "running harder" with the room "going colder". It cannot.*

**In cool mode the setpoint is a ceiling, not a floor.** The AC holds the
house *at* 72 °F and can never drive it below. The only path below setpoint
is **passive drift when outside is cooler than the setpoint** — and with no
heating in the loop, nothing pushes back up until the sun does.

So for 2026-09-04:

| | Outside | Room |
|---|---|---|
| morning | **~70 °F / 21.1 °C** | drifting toward outside, **below setpoint** — the coldest the room gets |
| 16:00 | 89 °F / 31.7 °C (day's high) | pinned at the setpoint, **72 °F / 22.2 °C** |

**The morning is the cold end, and the afternoon is the warm end.** That
matches the observations directly: trial 0 failed at 11:09 in the coldest
room of the day, trial 1 passed at 15:50 with the room at its ceiling.

### Room ambient and board self-heating point the same way

Both effects act in the same direction here, so 2026-09-04 does not
separate them:

- **Room:** ~70 °F in the morning, 72 °F in the afternoon.
- **Board:** freshly powered at 11:09 for the first bench activity of the
  day; running for hours by 15:50. A powered board typically sits well
  above ambient, so this term is probably the larger of the two — a couple
  of °F of room swing against ten or more of self-heating.

They reinforce rather than compete, which is why the failure was so clean.
It also means **either could be the actual driver**, and separating them is
what the paired trials are for: trials 2 and 3 sit minutes apart in the
same room, so room ambient is constant between them and only the board's
temperature changes.

Favourably for tomorrow, both trials land in the morning — the room's own
coldest window — so trial 3 is the coldest combined condition available
without any equipment.

**Do not over-read a null.** If trial 3 passes, that does **not** refute
temperature: the room swing is only a couple of °F, and a board that
reaches ambient quickly may still not cross the threshold. A null narrows
nothing on its own, which is the whole reason this is a series and not an
experiment.

## Limitations, recorded so they are not forgotten

- **No measurement of the test room, and none of the board.** The
  thermostat is a different floor and a single zone (see Environment), so
  it is a weak proxy at best and biased warm. Board temperature — which
  the Environment section argues is the more likely variable — is not
  measured at all. Logged as *not measured* rather than estimated: an
  invented number would be worse than a gap, and this series exists
  precisely because unsupported inferences were previously read as
  evidence. A cheap BLE thermo-hygrometer for the room and a K-type probe
  for the board would close both.
- **Trial 0 used a different bitstream** (`7a5418d6`, pre-fH-fix) and a
  different indicator (register readback, not the waveform). It is recorded
  for completeness, not for comparison.
- **Thermal state is categorical**, so this can establish *correlation with
  warm/cold*, not a threshold temperature. A threshold needs instrumentation.
- **Self-heating confounds "overnight running".** A board left powered all
  night is warmer than one that was off, so a pass in that state is weaker
  evidence than a pass after a cold soak. This is why trials are run in
  pairs — warm first, then again after a power-off soak, same morning, same
  room.

## Next session — Monday 2026-09-07

**Ten rapid power cycles, counted.** Off, on, reflash from the fixed
bitstream, check Ch A 42 / Ch B 94, record pass/fail. ~2 minutes each.
Add one row per cycle below.

This replaces further paired thermal trials, which have low information
value at the current sample size. The question it answers — *is there a
baseline per-boot failure rate, and what is it?* — has to be settled
before any thermal manipulation can be interpreted, because against a
25% baseline a dropout during freeze spray would mean nothing.

If the rate comes back near zero, the thermal hypotheses survive and the
instruments are worth buying. If it comes back at 20–30% with no thermal
pattern, chip0 is a different problem than three previous investigations
assumed.

## Completed trials — original schedule

- **2 — 2026-09-05, first thing.** Board left powered overnight,
  oscilloscope off (off since before trial 1, so this condition is shared
  with the baseline). Check the waveforms *before touching anything* —
  the board is at its warmest here, having self-heated all night.
- **3 — 2026-09-05, ~60 min later.** Power off, wait 60 min so the board
  reaches room ambient, reflash from the fixed bitstream, check again.

Trials 2 and 3 are the same room and the same morning at two **board**
temperatures. If 2 passes and 3 fails, board temperature is isolated as
the variable with no instrumentation at all — room ambient is held
constant by the design rather than by measurement. Also record the
overnight outdoor low from the phone the next morning: a poor proxy for
the room, clearly marked as such, but across several trials it orders them
coldest-to-warmest, which is enough to see whether a correlation exists at
all.
