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

- [ ] **Procure the companion FPGA dev kit.** COTS, not a custom board — not worn by
      the subject, so unconstrained by size/power. Criteria in priority order:
      stay in the **CrossLink-NX family** (one toolchain, shared RTL idioms;
      LIFCL-40 eval boards are the obvious candidates) · CrossLink-NX boards commonly
      carry **HDMI connectors**, matching the uHDMI link without a breakout ·
      verify LVDS pairs are exposed on accessible headers at the needed rate ·
      pin exact part number + board revision (reproducibility depends on
      purchasability).
- [ ] **T1.1 live risks** — `CFG_BONDING_MODE=0` is uncommitted (committed value is
      `1`; a fresh clone cannot accept BLE connections). Also decide
      `STREAM_DIAG_POST_DRAIN_WATCH=1` (`stream_app.c:165`), which prints on the hot
      path. *Minutes, and a broken build during this window would be painful.*
- [ ] **Verify `RHD_REG13`** (`intan.vh:149`) — `{RHD_ADC_AUX3_EN, RHD_RL_DAC3,
      RHD_RH1_DAC2}` mixes RL and RH1 prefixes where every other register is
      consistent. RHD2000 reg 13 is `[7] aux3_en, [6] RL_DAC3, [5:0] RL_DAC2`, and
      `RH1_DAC2` is 5 bits (per REG9) where 6 are needed — likely a 7-bit
      concatenation into an 8-bit field, shifting the register. **Reg 13 sets the
      low-frequency cutoff.** Never noticed because the amplifier path has never run.
- [ ] Confirm RHS2116 is unpopulated or provably disabled on the test hardware
- [ ] Confirm whether the collaborator's animal protocol needs an amendment to admit
      a new device (same logic as an IRB amendment; their protocol may already cover it)

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
- [ ] **T3.3 Remove debug hijacks from product paths** — `serial_lvds_tx = spi0_csb`
      and `serial_lvds_rx` **declared as an output** (`kuntur_fpga.v:36-37`), which
      must be undone before bidirectional tunnel work · `assign cmd_is_00 = fifo_full`
      · `mode` hardwired `2'b00` with `mode1_*`/`mode2_*`/`mode3_*` declared and
      unwired · delete `old.v`.

*Already verified correct:* RHD init sequence — chip-ID read, regs 0–21,
`RHD_CALIBRATE`, then nine dummy reads as the datasheet requires.

## A.2 — Minimum control plane  *(Claude: MCU + app; Manuel: RTL side)*

Enough to choose which two channels to record — without it the animal test is stuck
with a hardcoded pair. Polished UI is Phase B.

- [x] FPGA endpoint exists — `ch_a`/`ch_b` driven from regbank, writable via `spi0`
- [ ] **MCU→FPGA register-write API** — `fpga_spi.c` has none; it only reads samples
- [ ] **BLE command handler on 0xFFF1** — declared, "reserved for future commands",
      no handler
- [ ] Minimal channel selection in the pc-app

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
- [ ] **WB09KE bridge RAM at 100%** (64/64 KB) — blocks all bridge feature work
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
