# Recording format — interface spec

**Status: AGREED 2026-08-27, IMPLEMENTED 2026-08-28** (`csv_recorder.py`,
`main_window.py`, `analyze_recording.py`). Written before touching
`csv_recorder.py`, per PLAN.md's standing rule (working principle 5:
"interface specs outrank subsystem specs") and A.6.5's explicit
instruction. Every open design question (JSON sidecar format §1; CSV
format versioning §1a; device state provenance tag §2.1; `sample_rate` as
a config-named object, not a bare scalar, §3; `firmware_version`/
`bitstream_version` tracked as new Phase B RTL/firmware work rather than a
permanent placeholder, §5) is resolved and confirmed by Manuel.

Both prior implementation gates (the bench session and the PLL retune)
cleared 2026-08-27; PLAN.md confirmed A.6.5 unblocked 2026-08-28. One
design change made during implementation, against Manuel's explicit
instruction that session: **`filter_settings` is read by an
operator-triggered "Get Settings" button, not automatically at connect**
— see §2.1a. Two additions the original spec didn't fully specify are
filled in below: the `filter_settings.registers` JSON shape (§2.1a) and
the stop()-time sidecar fields (§2.2).

**Purpose:** define a metadata sidecar for `vega_*.csv` recordings, so a
recording can be interpreted correctly (units, channel identity, sample
rate) without hand-me-down knowledge of whatever the pc-app's constants
happened to be on the day it was captured. Minimum content, per PLAN.md
A.6.5: sample rate, gain / µV-per-LSB, channel map, filter settings,
firmware/bitstream versions, and a format version field.

---

## 1. File relationship

One sidecar per recording, same basename as the CSV, `.json` extension:

```
vega_20260827_101500.csv
vega_20260827_101500.json
```

**Why JSON, not YAML/TOML/a flat comment scheme (agreed 2026-08-27):**
stdlib-only (`json` module) — this project has zero config-file
dependencies today and JSON doesn't add one. Nests naturally onto this
metadata's actual shape (`sample_rate`, `gain`, `channels` are each a
value-plus-provenance group, not flat scalars) — a flat `key=value`
scheme loses that structure. Forward-compatible by convention (a reader
ignores keys it doesn't recognize; a v1 reader on a v2 file degrades
gracefully rather than failing to parse). Ecosystem fit: this project's
target audience (SpikeInterface, probeinterface) already uses JSON
sidecars for exactly this kind of metadata.

**Written in two passes, not one** — `CsvRecorder.start()` and
`CsvRecorder.stop()` map directly onto "known before the recording" vs.
"known only after it ends", and this also makes the sidecar
crash-resilient: everything in §2 is known at `start()` and written
immediately, so a sidecar exists next to any non-empty CSV even if the
app dies mid-recording (power loss, crash, forced quit) before `stop()`
ever runs — losing only the §3 fields (final duration, measured rate,
stop reason), not the whole record. The alternative (write once, at
`stop()`) loses everything on exactly the failure mode this system needs
to be honest about.

**Write atomically.** `open(tmp, "w")` → `json.dump()` → `close()` →
`os.replace(tmp, final)`, both at start and at the stop-time rewrite. A
`SIGKILL` or crash mid-`json.dump()` must never leave a torn/unparseable
sidecar sitting next to a good CSV.

## 1a. CSV format version — agreed 2026-08-27

The `.csv` itself gets a version too, not just the sidecar. A leading
comment line before the existing column header:

```
# vega-recording-format-version: 1
timestamp_us,ch0,ch1,seq_num
100000000,123,-456,7
...
```

Every existing reader (`analyze_recording.py`, `compare_recordings.py`)
currently does `f.readline()` to get the header, then
`np.loadtxt(..., skiprows=1)`. Detection must be dynamic — peek line 1;
if it starts with `#`, the real header is line 2 and `skiprows=2` —
**so every recording already in `pc-app/recordings/` (all pre-A.6.5,
§6) still parses with no migration**, since they simply don't have the
comment line and fall through to the old `skiprows=1` path.

This version number tracks the **column schema** (`timestamp_us,ch0,ch1
[,seq_num]`) specifically, independent of `format_version` in the JSON
sidecar (§4), which tracks the *sidecar's* schema. The two are versioned
separately because they can change independently — a new CSV column
doesn't necessarily change what the sidecar records, and vice versa.

## 2. Written at `start()`

```json
{
  "format_version": 1,
  "csv_filename": "vega_20260827_101500.csv",
  "recording_started_utc": "2026-08-27T10:15:00Z",

  "sample_rate": {
    "config": "2ch_v1",
    "channel_hz": 29999.97,
    "source": "docs/interfaces/stream-packet-format.md §1.1 -- 2026-08-27 PLL retune. Will be revised after PLAN.md A.7 step 3 sets the rate margin; the actual streaming rate is expected to land below this figure deliberately."
  },

  "gain": {
    "amplifier_uv_per_lsb": 0.195,
    "source": "Intan_RHD2000_series_datasheet.pdf, page 6, table 'Electrical Characteristics', symbol V_LSB, row 'referred to amplifier input'. Confirmed by Manuel 2026-08-27 (PLAN.md A.6.2, DECISION 1). Applies to CH0/CH1 as amplifier channels, which is what SET_CHANNELS selects in normal operation -- see pc-app/rhd2164_units.py for the auxiliary-input and supply-sensor step sizes, not used by this field."
  },

  "channels": {
    "ch_a": null,
    "ch_b": null,
    "provenance": "unknown"
  },

  "filter_settings": {
    "registers": null,
    "provenance": "unknown"
  },

  "firmware_version": "unknown",
  "bitstream_version": "unknown"
}
```

`channels`/`filter_settings` above show the state before Apply/Get
Settings has ever run this session (`"unknown"`) — see §2.1a for what
`filter_settings.registers` looks like once populated, and §3 for how
`sample_rate.channel_hz` was resolved.

### 2.1 Device state (`channels`, `filter_settings`)

**Design agreed with Manuel 2026-08-27, generalizing a gap this spec
found while looking at `channels` alone.** Two related fields, one
pattern:

**Clarified 2026-08-27: "read once at connect" governs the *read*, not
the *write*.** Every recording's sidecar still gets the current cached
value written into its `channels`/`filter_settings` fields at `start()`
(§2's JSON skeleton already does this) — what changes is that the pc-app
doesn't re-query the hardware for it on every recording, only on connect
and after a future settings-change. A recording started with no fresh
read since connect still gets the cached value plus its `provenance` tag,
never an omitted field.

- **`channels`** — friendly indices `ch_a`/`ch_b` (0–127), set via
  `SET_CHANNELS`.
- **`filter_settings`** — the RHD2164's bandwidth-selection registers:
  Register 4 (`DSPEN`/`DSP_CUTOFF`, on-chip DSP high-pass), Registers
  8–11 (upper bandwidth `fH`), Registers 12–13 (lower bandwidth `fL`).
  Read via `RHD_READ(n)`, the exact SPI command class already proven on
  hardware in A.1.1a–d (regs 59/61–63/40–44) — **no new RTL or firmware
  needed**, this is pc-app orchestration against the existing register
  console (`fpga-diagnostic-access.md`). Stores **raw register values**,
  not decoded Hz — the register→Hz mapping needs the datasheet's lookup
  tables (pages 25–26) and decoding is a separable fast-follow, not a
  blocker to recording the ground-truth values.

**`channels` is read/refreshed via the existing `SET_CHANNELS`/readback
flow (Apply), cached in `main_window.py`.** `filter_settings` is
**deliberately not** auto-read at connect — changed during
implementation, 2026-08-28, from this section's original framing.
Reason: the only way any RHD2164 SPI response reaches the host is by
pointing the live streamed channel at the FPGA's command slot (§2.1a),
which means reading filter registers unavoidably touches `REG_CH_A`
transiently, even though it's restored before returning. Doing that
silently on every connect was ruled out (Manuel) in favor of an explicit
**"Get Settings" button** (§2.1a) — an operator-triggered action with the
same STOP → act → restore → START shape as Apply, not something that
happens without the operator asking for it. Each device-state field
therefore needs:

1. A read sequence (STOP if not already stopped → read the relevant
   registers/regbank words → restore/resume) — for `channels`, this is
   Apply; for `filter_settings`, this is Get Settings (§2.1a).
2. A **provenance tag**, not a bare value — because "confirmed by the
   FPGA" and "requested but never confirmed" are different levels of
   confidence, exactly like the existing `channels`/`✓ Verified` /
   `✗ Mismatch` distinction:

   | State | Value | `provenance` |
   |---|---|---|
   | Confirmed by the FPGA at least once (Apply's readback, or a Get Settings run) | the confirmed value | `"verified_readback"` |
   | Requested (e.g. spinbox for channels) but never confirmed, or a confirmation attempt timed out | the requested value | `"unverified_requested"` |
   | Never connected, or never attempted | `null` | `"unknown"` |

3. Invalidation/refresh whenever the underlying setting is changed —
   `channels` has the mechanism in `_apply_channels`/`_on_channels_readback`
   (downgrade to `unverified_requested` the instant Apply is clicked,
   upgrade to `verified_readback` on the FPGA's actual reply, whether or
   not it matches what was requested); `filter_settings` doesn't need an
   equivalent invalidation path since nothing changes it other than a
   fresh Get Settings run, which always overwrites the cached value
   directly.

**`channels`, specifically — the gap that motivated this design.**
Checked `main_window.py`'s channel-apply flow
(`_apply_channels` → `_on_channels_readback`): there is currently **no
persisted "last-verified" channel state**. `_on_channels_readback`
compares the FPGA's readback against `_pending_channels` to drive the
`✓ Verified` / `✗ Mismatch` UI label, then clears `_pending_channels` —
it never stores the confirmed `(ch_a, ch_b)` pair anywhere durable. The
only channel state that persists across the session is
`self._spin_ch_a.value()` / `self._spin_ch_b.value()` — what the
operator last *typed*, not what was last *confirmed on the FPGA*. Those
two can disagree (a mismatch, a timeout, or never clicking Apply after
changing a spinbox). `_btn_rec` is enabled purely on `connected`,
independent of channel-apply state (`main_window.py:404`), so a
recording can start with channels in any of the three states above.

## 2.1a. `filter_settings` — "Get Settings" button, and the `registers` shape

**Implemented 2026-08-28** as `diagnostics.FilterSettingsReader`, a
sibling of the A.1.1 verification ladder's `RungRunner` (same
register-console primitives: `rhd_read`, `slot_word`, `ch_code`, the
ack-gated queue with retries), triggered by a new "Get Settings" button
next to the channel controls in `main_window.py`. Mutually exclusive with
Apply and the diagnostics ladder — all three drive the same live FPGA
channel-selection/streaming state.

Sequence: STOP → for each register in `[4, 8, 9, 10, 11, 12, 13]`, write
`READ(reg)` into the dedicated command slot (regbank word 80, "slot 32")
→ point `REG_CH_A` at slot 32 → START → collect ~64 samples → majority-
vote decode → STOP → put slot 32 back to its normal-operation value
(`READ(63)`, the chip-ID read) → **restore via `SET_CHANNELS`** (the same
command Apply uses, verified the same way) rather than a raw register
write, landing back on exactly the channels the operator had before the
button was pressed. **`REG_CH_B` and sampling-table slots 0–31 are never
written**, at any point in the sequence — the constraint Manuel gave when
this button was scoped, 2026-08-28.

`filter_settings.registers` shape, not fully specified when §2 was
written — one key per register number, decimal string (JSON object keys
are always strings), value is the register's raw content (the low byte of
the RHD2164's `{8'h00, D}` response, per `rhd_read`'s contract — not
decoded Hz, per this section's original scope note):

```json
"filter_settings": {
  "registers": {"4": 31, "8": 80, "9": 81, "10": 82, "11": 83, "12": 10, "13": 11},
  "provenance": "verified_readback"
}
```

Tested offline against a fake register-console model
(`test_filter_settings.py`, mirrors `test_diagnostics.py`'s `FakeReader`
pattern) — proves the queue sequencing, the retry/timeout handling, and
that only slot 32 and `REG_CH_A` are ever touched. **Not yet verified
against real hardware** — needs a bench run confirming the decoded
register values are plausible and that the streamed channels/graph are
byte-for-byte unaffected after a run.

## 2.2. Written at `stop()`

Not specified when §2 was written — §1 only says the stop-time rewrite
exists ("everything in §2 is known at `start()`... losing only the final
duration, measured rate, stop reason"), not its field names. Implemented
2026-08-28 as an update merged into the same sidecar file (same atomic
write as §1), on top of every §2 field:

```json
"recording_stopped_utc": "2026-08-28T10:22:31Z",
"duration_sec": 123.4,
"rows_written": 3600000,
"auto_stopped": false,
"auto_stop_reason": null
```

`auto_stop_reason` is `"max_duration" | "low_disk" | null` (`null` for an
operator-initiated stop) — distinguishes `csv_recorder.py`'s two
`write_batch()` auto-stop call sites, which previously both collapsed
into the same `auto_stopped: bool`.

## 3. `sample_rate` — RESOLVED 2026-08-28

**FPGA-driven rate, derived from RTL 2026-08-27 (Manuel: "look at the
code again to see what is the actual rate").** Cycle-counted from the
current source, not measured or recalled — full derivation, so it's
checkable:

- `spi_master_controller` (`afe/rhd2164/spi_master_rhd2164x2.v`): one
  16-bit SPI1 transaction is states `op0` through `csbend7` inclusive —
  42 states, 1 `clk` cycle each (pure combinational `next_state`, no
  stalls) = **42 cycles**.
- `rhd2164_controller`'s outer loop (`op1a→op1b→op1c→op1d`) adds `op1a`
  + `op1b` before the inner FSM's `start` is sampled, and `op1c` holds
  one extra cycle after the inner FSM re-enters `idle` before `rhd_done`
  is acted on (registered-state detection latency), then `op1d` — **+4
  cycles**. Total: **46 `clk` cycles per sampling slot**.
- `RB_SAMPLING_MAX = 6'd32` (`regbank_map.vh`) → `cnt0` spans 0..32
  inclusive → **33 slots/frame** (matches A.1.1's already-established
  slot count). One frame = one new sample per selected channel (`ch_sel`
  latches once per frame when the sampling counter matches `ch_a`/`ch_b`).
- `clk = 44.549 MHz` (`pll0.ldc: CLKOP_FREQ_ACTUAL`, confirmed in
  `fpga-timing-constraints.md`; PLL `-multiply_by 71 -divide_by 51` off
  the 32 MHz `clkin`).

**Result: 33 × 46 = 1,518 cycles/frame ÷ 44.549 MHz = 34.074 µs/frame →
≈29,348 SPS per channel.** Hitting exactly 30,000 with this same 1,518-
cycle structure would need `clk ≈ 45.54 MHz`, not 44.549 — a ~2.2%
shortfall, small and PLL-adjustable as you said, but real and not zero.

**This number cross-validates against the best real measurement on
record**, not just against itself: 2026-08-03's post-mblock-fix
*production* (ground-truth) figure was 29,350–29,390 SPS — within
0.1% of this derivation. That session's fix was purely on the BLE
delivery side (`CFG_BLE_MBLOCK_COUNT_MARGIN`); it never touched the
FPGA, so the FPGA's production rate should be unchanged since — good
agreement, not a coincidence. **Please check this cycle count against
the RTL yourself** — this kind of count is exactly where an off-by-one
is easy to make and hard to self-catch (see A.1.1's own "offset is 3,
not 2" episode), and you can verify it far more reliably than I can
from a single read-through.

**BLE transport ceiling — checked, not assumed.** `ble-transmission-
summary.md` §2 states the sustained ceiling is set by real link
capacity (controller drain rate over the air), not something with a
clean closed-form spec-sheet number — it's deliberately measured, not
computed. The most recent — and only — full-stream measurement of it is
the same 2026-08-03 result: **506.0 pps × 59 ≈ 29,854 SPS delivered**,
matching FPGA production to +0.42–0.45 sps with zero drift over two
clean 315–338 s recordings. So as of the last time this was actually
tested, **BLE was not the bottleneck** — delivery slightly *exceeded*
the FPGA's own production rate and tracked it exactly. Nothing more
recent exists to check this against: no full-stream recording exists
anywhere on this machine after 2026-08-03 (same gap noted for A.6.4).

**Future modes — sample rate becomes mode-dependent, not a constant
(Manuel, 2026-08-27).** Multi-channel modes (PLAN.md's roadmap: 4ch@15k,
8ch@7.5k, …) will each have their own achievable per-channel rate,
computed the same way — from that mode's own FSM slot count and clock
configuration, not the constant above. The schema needs to anticipate a
lookup keyed by active mode, not a single scalar, even though only one
mode/config exists today and collapses to one value. Concretely, this
argues for a small `sample_rate` object naming *which configuration*
the value applies to, e.g. `{"config": "2ch_v1", "channel_hz": 29348,
"source": "derived from RTL, see interface spec §3"}` rather than a
bare number — so adding a second row to the (future) lookup table is
additive, not a schema break. The FPGA doesn't expose a live
"which config is active" identifier today (same underlying gap as
`bitstream_version`, §5) — for now `config` would be a hardcoded
literal (there's only one), revisited once that identifier exists.

**Original proposal, superseded by the above, kept for the discussion
record:**
`nominal_adc_hz: 30000` (from `packet_parser.SAMPLE_RATE_HZ`, labelled
explicitly as a protocol constant, not a measurement) plus
`measured_sps` computed post-hoc from the recording's own timestamps.

Manuel's objection, and the reason this needs more than an arithmetic
fix: **the "nominal 30 kSPS" framing itself has never matched reality.**
Every measured-SPS figure recorded across this project's session logs
(`grep`'d 2026-08-27, not from memory):

| Session | Measured | Note |
|---|---|---|
| 2026-04-27 | 7,771 / 1,641 | early ANDROID_BLE / LENOVO_SMOOTH bring-up |
| 2026-05-04 | 30,680 | delivered/BLE rate |
| 2026-05-15 | 25,020 → 30,215 | delivered/BLE rate; clock-speed fix (32→64 MHz) |
| 2026-07-27 | ~31,060 delivered, **~28,600–29,300 real FPGA production** | **first session to measure both** — delivered and produced already disagreed, produced was lower |
| 2026-07-30 | 29,551 | delivered/BLE rate |
| 2026-08-03 (before fix) | production ~29,350–29,390 flat; delivered 29,344 → 28,844, chronic deficit | root cause: MCU's steady-state cycle tuned to ~30,000 with zero surplus margin |
| 2026-08-03 (after `CFG_BLE_MBLOCK_COUNT_MARGIN` 54→200, same session) | **production/delivered matched to +0.42–0.45 sps, flat, zero drift; bench throughput 506.0 pps × 59 ≈ 29,854 SPS** | resolved — this is the most recent full-stream ground-truth measurement on record |
| PLAN.md B.5 (open) | ~30,700–31,900 | delivered/BLE rate, "overshoot", unresolved |

**Correcting my own first pass at this table:** every figure that reads
*above* 30,000 (05-04, 05-15, B.5's open item) is a **delivered/BLE
packet-rate** measurement (`pkt/s × 59 pairs`) — a different quantity
from **production rate**, the FPGA's own ramp-counter ground truth. The
only two sessions that measured *both* on the same recording (07-27,
08-03) agree with each other and with Manuel: production rate was below
30,000 in both, and after the mblock-margin fix that closed the 08-03
deficit, the *resolved, matched* rate still settled at ~29,854 SPS —
under nominal, not at it. The apparent "overshoot" entries may be a
measurement-methodology artifact (packet-rate arithmetic during bursty
delivery) rather than the chip genuinely producing samples faster than
its own SPI clock permits, which is what the RHD2164's synchronous SPI
sampling would make surprising in the first place. **Not confirmed —
this is a hypothesis to check with Manuel**, not a resolved fact; B.5's
own open item still frames it as "overshoot" and this spec shouldn't
silently overrule that without his read.

A single `nominal_adc_hz: 30000` field, as originally proposed, risks
implying a stable target this system has consistently hit — it hasn't,
by either measure, and conflating "delivered rate" with "production
rate" is itself part of what made the number look inconsistent across
sessions.

**A second problem, found while re-examining this for the discussion:**
`measured_sps` as originally proposed (`row_count / duration`) would
not actually reveal FIFO-underrun data loss, because
`csv_recorder.py`'s own header says it writes underrun sentinel rows
**verbatim** — an underrun doesn't produce a missing row, it produces a
`-32768,-32768` row. So `row_count / duration` measures packet-delivery
cadence (degraded only by whole-packet BLE loss, visible via `seq_num`
gaps), not the rate of genuinely valid samples — a recording could show
a `measured_sps` near 30,000 while a real fraction of those rows are
underrun padding, which is the same kind of "looks fine, silently
isn't" failure this plan has already flagged twice (A.6.4's sentinel
ambiguity; the REG13 bug before it).

**Resolved 2026-08-28**, in the same session that agreed the
`stream-packet-format.md` spec: the config-named-object shape (this
section's own proposal) is exactly what absorbed the resolution.
`stream-packet-format.md` §1.1 records the 2026-08-27 PLL retune moving
production from 29,348 to 29,999.97 SPS/ch — this is the value
implemented into every sidecar's `sample_rate.channel_hz`:

```json
"sample_rate": {
  "config": "2ch_v1",
  "channel_hz": 29999.97,
  "source": "docs/interfaces/stream-packet-format.md §1.1 — 2026-08-27 PLL retune. Will be revised after PLAN.md A.7 step 3 sets the rate margin; the actual streaming rate is expected to land below this figure deliberately."
}
```

**This is not the final number.** PLAN.md A.7 step 3 (loss accounting —
still open as of this writing) is expected to set the real streaming rate
λ *below* 29,999.97 deliberately, per `stream-packet-format.md`'s
lossless-by-margin design (production must stay below measured transport
capacity). When that lands, only `channel_hz`'s *value* changes — the
schema doesn't, which is exactly what this section argued for before it
was implemented.

## 4. `format_version`

Integer, starts at `1`. Bump on any breaking change to this schema (field
removed, meaning changed, type changed). Additive changes (a new optional
field) do not require a bump — a `format_version: 1` reader must still be
able to read a file with extra fields it doesn't recognize.

A CSV with **no sidecar at all** is implicitly pre-A.6.5 — every existing
recording in `pc-app/recordings/` predates this spec (see §6) — and should
be treated as such by any tool that consumes these files.

## 5. `firmware_version` / `bitstream_version` — tracked as new Phase B work, not permanent placeholders

Checked 2026-08-27 whether either is actually obtainable today, rather
than taking PLAN.md's existing framing at face value:

- **`bitstream_version`:** not readable over the path the MCU actually
  uses. Lattice's `USERCODE` field exists but is unused
  (`impl_1.xcf:33`, `VerifyUsercode value="FALSE"`) and is a
  JTAG-programmer feature in any case — not reachable over SPI0. Needs a
  **new read-only regbank word** holding a hand-maintained version
  constant (cheap RTL, same `initial`-block mechanism as the 2026-08-26
  EBR rewrite). Tracked: PLAN.md B.5, "FPGA regbank has no read-only
  registers."
- **`firmware_version`:** no version constant is compiled into the MCU
  firmware anywhere (checked `App/*.c`/`.h` for
  `VERSION`/`__DATE__`/UID — nothing), and no command exists to fetch
  one. Needs a version constant plus a way to carry it back. Tracked:
  PLAN.md B.6, "Version/name handshake."

Both fields read `"unknown"` literally until their tracked item lands —
**do not** infer a value from `git describe` or repo state; the board's
actual flashed firmware/bitstream can lag the repo by any amount, and a
git-derived value would look authoritative while being unverifiable
against what's actually running.

## 6. Existing recordings are unaffected

`pc-app/recordings/*.csv` (all dated 2026-07-24 through 2026-08-03,
confirmed by directory listing 2026-08-27 — all predate A.1.1e connecting
real RHD2164 data on 2026-08-11, so all of them are ramp-test-pattern
recordings, not real signal) get no retroactive sidecar or version
comment line. Nothing reads for their absence; §1a/§4 cover how a
consumer should treat that.

## Open items

- [x] Design agreement (Manuel, 2026-08-27) — all of §1/§1a/§2.1/§3/§5.
- [x] **Blocking implementation:** PLL retune — landed 2026-08-27
      (`CLKOP_FREQ_ACTUAL = 45.539955 MHz`), moving production to
      29,999.97 SPS/ch. `sample_rate.channel_hz` resolved (§3) — will take
      one more *value* update after PLAN.md A.7 step 3 sets the rate
      margin, not a schema change.
- [x] **Blocking implementation:** bench session — ran 2026-08-27.
- [x] `main_window.py`: `channels` provenance via the existing
      `SET_CHANNELS`/readback flow (§2.1); `filter_settings` via the new
      "Get Settings" button, not a connect-time read (§2.1a — changed
      from this item's original framing, 2026-08-28).
- [x] `csv_recorder.py`: sidecar at `start()`/`stop()` per §§2-2.2,
      atomically (§1); `# vega-recording-format-version: 1` comment line
      (§1a).
- [x] `analyze_recording.py`: dynamic `skiprows` detection for the new CSV
      comment line (§1a) — `compare_recordings.py` needed no direct
      change, it only calls `analyze_recording.compute_stats()`.
- [x] `csv_recorder.py`: `stop()` gained `auto_stop_reason`
      (`"max_duration" | "low_disk" | None`) distinguishing its two
      `write_batch()` auto-stop call sites (§2.2).
- [ ] FPGA: new read-only regbank word for `bitstream_version`
      (PLAN.md B.5).
- [ ] MCU: version constant + a way to read it, for `firmware_version`
      (PLAN.md B.6).
- [ ] **Needs a bench run** (not done this session, no hardware access):
      confirm "Get Settings" returns plausible RHD2164 filter-register
      values, and that `REG_CH_A`/`REG_CH_B`/the streamed channels come
      back byte-for-byte unchanged after a run (§2.1a).
