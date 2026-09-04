# Stream packet format (v1) — interface spec

**Status: AGREED 2026-08-28. §6's telemetry frame implemented
2026-09-04 (desk-verified, not yet on hardware — §6.8); the v1 header
(§3–§4) remains unimplemented.** Written before any code, per PLAN.md
working principle 5 and the standing project rule that cross-boundary
interfaces get a spec first. This is a **breaking wire-format change** to
the `0xFFF2` notify payload, plus one new characteristic and one new
frame type; it supersedes the format documented in CLAUDE.md's *BLE
Device Protocol* section (here called **v0**).

The two halves are independent and were always meant to be: §6's frame is
a pure addition that breaks nothing and needed no version handshake,
which is why it could be built first, ahead of the header change it was
originally bundled with.

CLAUDE.md is deliberately **not** updated to describe the v1 header — it
documents as-built, and that half is not built (working principle 4). It
*does* now describe `0xFFF4` and the `0xDD 0x22` frame, which are.

**Agreed with Manuel, 2026-08-28** — the four questions that were open at
proposal, now closed:

- **No header CRC** (§3.5). Argued and rejected as the wrong layer: BLE
  already CRCs and retransmits the headstage→bridge hop, so a header CRC
  computed on the MCU protects a hop that is already protected. The
  exposed segment is bridge→PC over UART, which needs a frame-level CRC
  over header *and* payload added by the bridge — an existing B.2 item,
  not this one. Byte 7 stays reserved.
- **Telemetry gets its own characteristic, `0xFFF4`** (§6.1) — *changed
  from the proposal*, on Manuel's call, and correctly. See §6.1 for the
  reasoning; the short version is that `0xFFF3`'s contract is
  request/response and unsolicited traffic on it would be safe only by
  convention, which is this project's recurring failure shape.
- **`mode_id` changes require streaming stopped** (§3.2), matching
  `SET_CHANNELS`, so no new enforcement mechanism exists to get wrong.
- **`sample_index` stays `uint32`** (§3.1), accepting the wrap with a
  modular-comparison requirement on receivers. *(The wrap was quoted as
  19.9 h when this was decided; §3.1 now gives 21.3 h in the 16-bit modes
  and **15.9 h** in the 12-bit ones. The decision stands — 15.9 h is still
  past any realistic session — but it was taken against a figure that has
  since moved, so it is worth re-checking if aggregate ever rises again.)*

Two decisions from the same day's architecture discussion are taken as
settled inputs and are not re-argued here:

- **Lossless-by-margin** (option A): production rate is set *below*
  measured transport capacity, and the system claims zero sample loss for
  a stated duration at a stated rate. §1.
- **Build the loss-accounting machinery anyway**, because the counters
  that prove the losslessness claim are the same counters that would have
  reported loss under option B — and because they are the only way to
  size `fifo0` and pick the margin on evidence rather than by guess. §6.

**Purpose:** replace a packet header whose fields cannot express what the
system now needs to say — where a packet sits in the stream, which mode
produced it, and whether anything was lost — with one that can, at
identical cost on the wire, and in a way that does not get worse as
channel count rises.

---

## 0. Why this changes now, and why it is cheap now

Three open items independently converge on the same header:

- **A.6.4 / DECISION 2** — `0x8000` is simultaneously the FIFO-underrun
  sentinel and a legal full-negative-rail ADC code. PLAN.md records that
  only option *(b)*, "carry underrun as out-of-band metadata rather than
  in-band in the sample values", actually resolves it. §7 is that option.
- **B.2 format versioning** — flagged as blocking safe evolution once the
  format is public. It is not public yet. This is the last moment the
  change is free.
- **The multi-channel roadmap** (4ch@15k, 8ch@7.5k) — v0 has no field
  that says how many channels a packet carries, so a mode change is
  undetectable by the receiver, and v0's fixed 59-pair shape imposes a
  packet-rate penalty on every mode with more than two channels (§5).

Doing them as one header change costs one migration instead of three.

---

## 1. The rate model — the invariant this format exists to serve

### 1.1 The failure this fixes

The system is a **free-running producer feeding a variable-capacity
transport that cannot exert backpressure**, through a finite buffer. For
that shape the governing condition is λ < μ: if the arrival rate meets or
exceeds the service rate, backlog grows without bound and a finite buffer
guarantees loss.

The 2026-08-27 PLL retune moved λ from 29,348 SPS/ch to 29,999.97 SPS/ch.
Measured delivery afterwards was 29,482.9 SPS (499.7 pkt/s) with
**underrun at 0%** — the read side never starved, so `fifo0` was
*accumulating*, not draining. ρ ≥ 1. **§1.5 confirms this quantitatively
on a 22.8-minute recording: ρ = 1.018, `fifo0` saturating in 7.7 s and
discarding 1.78% of all samples silently thereafter.**

This is why the 2026-08-03 mblock-margin fix does not apply a second
time. That was a variance fix for a variance problem, and it worked
because λ was comfortably below μ at the time. The present problem is a
**mean-rate** problem, and no buffer size solves a mean-rate problem — it
only changes how long failure takes to appear.

### 1.2 Two parameters, not one

Buffer depth and rate margin do different jobs and have been treated as
one knob:

| Parameter | Sets | Formula |
|---|---|---|
| Buffer depth `B` | how long a stall is survived | `B ≥ λ × T_stall_max` |
| Rate margin `m = (μ−λ)/λ` | how long recovery takes | `T_recover = T_stall / m` |

Depth is adequate today. Real elastic storage, corrected against source
(`stream_app.c:226`, `kuntur_fpga.v:246` `ADDR_WIDTH=12`):

| Buffer | Depth | Ride-out @ 60 kSPS aggregate | Protects against |
|---|---|---|---|
| `fifo0` (FPGA) | 4096 frames | ~137 ms | BLE/MCU stalls |
| MCU ring (`s_ringBuf`) | 2048 pairs / 8 KB | ~68 ms | BLE TX-pool flow-off |
| **Headstage subtotal** | | **~205 ms** | vs. ~22 ms worst measured stall |
| Bridge TX ring | 4096 B | ~32 ms at fill rate | USB/host stalls |

> **Documentation correction.** CLAUDE.md and `log/2026-08-28.md` both
> state `fifo0` is "~34 ms". That was true until 2026-07-31, when it was
> deepened 1024→4096 frames (`ADDR_WIDTH` 10→12). `stream_app.c:226-229`
> is correct; the two docs are stale. One for B.1's ground-truth audit.

The margin is what is broken. At λ = 508.5 pkt/s against the only
measured ceiling on record (512 pkt/s, 2026-05-15), `m = 0.69%`, so
recovery from a single 22 ms stall takes **3.1 s**. If stalls arrive more
often than that, backlog accumulates monotonically no matter how deep the
buffers are.

| `m` | Recovery from one 22 ms stall |
|---|---|
| 0.69% (today's design intent) | 3.1 s |
| 2% | 1.1 s |
| 5% | 440 ms |
| ≤ 0% (today's measured reality) | never |

### 1.3 The invariant

> **λ_aggregate < μ_low**, where `μ_low` is a measured low percentile of
> sustained transport capacity — not its peak, and not a nominal target.
> **`m` ≥ the stall duty cycle** (stall duration × stall frequency).

Two consequences the project should adopt explicitly:

- **30,000 SPS is a target, not a requirement.** Nothing downstream needs
  it round; A.6.5's sidecar records the actual rate either way
  (`recording-format.md` §3). 28,500 SPS losslessly is worth more to
  every analysis than 30,000 SPS with 1.7% silent loss.
- ~~**`μ_low` and the stall duty cycle are both currently unmeasured.**~~
  **Both measured 2026-09-03 — see §1.5.** `μ` = 512 pkt/s (2026-05-15) is
  **superseded and was 2.5% optimistic**. λ is now set: **28,000 SPS/ch**.

### 1.4 What is foreclosed

True store-and-forward through multi-second radio outages needs on the
order of 120 kB/s of headstage buffering. The WB09's 64 KB of RAM, most
of it taken by the BLE stack, cannot provide it. **Riding out outages is
a headstage-storage feature, not a tuning parameter** — it would require
adding non-volatile storage to the headstage and is out of scope for v1.
The margin is therefore the only free lever, which is what makes §1.3 an
invariant rather than a preference.

### 1.5 μ measured — 2026-09-03

**Source:** `pc-app/recordings/vega_20260831_123301.csv` — 22.8 minutes,
40,258,709 rows, **682,351 packets, zero `seq_num` gaps (no packet loss
at all)**. Analysed by a streaming pass over the raw CSV; per-second bins,
1365 full bins.

**Why a recording measures both rates at once.** `StreamAssemblePacket`
(`stream_app.c`) always fills all 59 pairs — ring first, then
`FPGA_SPI_ReadSamples`, which returns the `0x8000` sentinel when `fifo0`
is empty. The MCU therefore sends a full packet whether or not real data
exists, so:

- **delivered rows ÷ duration = μ**, the transport's sustained capacity,
  independent of what the FPGA produced;
- **(rows − underruns) ÷ duration = λ**, the FPGA's production rate.

| | pkt/s | SPS/ch |
|---|---|---|
| **μ** — transport, mean over 22.8 min | **499.420** | 29,465.8 |
| μ at p1 and p5 of 1-second bins | 499.00 | 29,441 |
| μ standard deviation | 3.37 | 197 |
| **λ** — production (pre-retune bitstream) | 497.424 | **29,348.0** |
| margin `m` as recorded | | **0.401%** |
| underrun | | 160,837 rows (0.400%) |

λ = **29,348.04 SPS** reproduces §1.1's stated pre-retune figure of
29,348 SPS **exactly**, from a completely independent derivation — which
is the check that the method is sound.

#### 1.5.1 The stall distribution is bimodal, and the worst stall is 5× the assumed figure

99.2% of seconds sit within 2 packets of the peak (501 pkt/s). Then there
are **exactly five outlier seconds**, each missing 56–58 packets:

| t (s) | pkt/s | packets missing | stall |
|---|---|---|---|
| 112 | 443 | 58 | **116 ms** |
| 232 | 444 | 57 | 114 ms |
| 292, 1073, 1133 | 445 | 56 | 112 ms |

**Minimum spacing between events: 60 s.** §1.2's buffer table is sized
against "~22 ms worst measured stall" — **the real figure is ~116 ms**.
The headstage's 208 ms of combined buffering does survive it (hence zero
packet loss), but at **1.8× margin, not the ~9× the 22 ms figure implies**.
That table's *conclusion* still holds; its safety factor does not.

**Measured stall duty cycle: 0.316%** (2158 packets of 683,865 possible).
That is the floor §1.3 requires `m` to clear.

#### 1.5.2 λ = 28,000 SPS/ch — decided 2026-09-03

| λ (SPS) | pkt/s | `m` vs μ_p1 | recovery from a 116 ms stall |
|---|---|---|---|
| 30,000 *(as shipped today)* | 508.47 | **−1.86%** | **never** |
| 29,500 | 500.00 | −0.20% | **never** |
| 29,348 *(pre-retune)* | 497.42 | +0.32% | 35.3 s |
| 29,000 | 491.53 | +1.52% | 7.4 s |
| 28,500 | 483.05 | +3.30% | 3.4 s |
| **28,000** | **474.58** | **+5.15%** | **2.2 s** |

**λ = 28,000 SPS/ch chosen** (Manuel, 2026-09-03) — *"we should work with
the highest data rate."* `m` = 5.23% against mean μ, **16.6× the measured
0.316% stall duty cycle**, and a worst-case 116 ms stall recovers in 2.2 s
against the 60 s minimum observed spacing.

28,000 was preferred over 28,500 for one reason: μ is a **bench**
measurement, and in vivo it can only get worse — 2.4 GHz is absorbed by
tissue, a surgical suite is RF-noisy, antenna orientation moves with the
animal, and BLE retransmissions reduce effective μ directly. 28,000
tolerates μ being **5.2% worse** than measured; 28,500 tolerates only
3.4%. The 1.75% of samples that buys is free.

#### 1.5.2a Sample rate is not the lever on signal quality — fH is

Worth recording because it was checked while choosing the rate, and it
changes what the choice is *about*.

`rhd2164_defs.vh` sets `RH1_DAC1 = 8`, `RH1_DAC2 = 0`, `RH2_DAC1 = 4`,
`RH2_DAC2 = 0` — an exact match for the RHD2000 datasheet's **fH = 20 kHz**
row, the chip's *maximum* upper cutoff. Nyquist for 20 kHz is 40 kSPS.

| λ | Nyquist | band folding back |
|---|---|---|
| 30,000 | 15.0 kHz | 15–20 kHz (5.0 kHz wide) |
| 28,500 | 14.25 kHz | 14.25–20 kHz (5.75 kHz) |
| **28,000** | **14.0 kHz** | **14–20 kHz (6.0 kHz)** |
| 25,000 | 12.5 kHz | 12.5–20 kHz (7.5 kHz) |

**Every candidate rate already aliases**, and the RHD's 3rd-order
Butterworth rolls off only *above* fH, so 14–20 kHz is essentially
passband today. 28,000 vs 28,500 differs by 250 Hz of folded band against
~6 kHz already folding — which is why the rate decision was correctly made
on transport margin alone.

**The fix is fH, not λ. ✅ APPLIED 2026-09-03** (Manuel): fH changed from
20 kHz to **7.5 kHz** — `RH1 DAC1=22/DAC2=0`, `RH2 DAC1=23/DAC2=0`, the
datasheet's literal 7.5 kHz row — in
`kuntur/.../afe/rhd2164/rhd2164_defs.vh`. At 28 kSPS, Nyquist (14 kHz)
now sits well above the corner and the signal path is properly
anti-aliased for the first time. 7.5 kHz is also Intan's standard choice
for spike work and preserves spike waveform shape.

**Do not expect a noise improvement from it.** The datasheet specifies
`vni` = 2.4 µVrms typical and notes it *"varies slightly (< 15%) with
amplifier bandwidth"* — so the naive √(bandwidth) reduction does not
apply. This is an anti-aliasing fix, not a noise fix, and A.3's headline
noise-floor number should not be expected to move much.

**Requires an FPGA rebuild and reflash** — the values are baked into
`regbank.v`'s power-up configuration table. Best done in the same rebuild
as §1.5.3's PLL retune, since both are FPGA changes gated on the same
bench session.

**fL is unchanged at 0.5 Hz and was always correct.** `RL_DAC1 = 35`,
`RL_DAC2 = 17`, `RL_DAC3 = 0` is the datasheet's literal **0.50 Hz** row
(p.26). An earlier pass in this session flagged it as matching no row —
**that was wrong**, caused by a table extraction that truncated below
1.5 Hz. Recorded so the false alarm is not re-raised.

#### 1.5.3 The PLL retune that produces it

The sampling frame is a structural constant: **33 slots × 46 `clk` = 1518
`clk`** (`rhd2164_controller`, `spi_master_controller`). So

The PLL is fractional-N: `FVCO = 32 MHz × (N_int + FRAC_N/4096)`. That
model reproduces today's `pll0.ldc` exactly — `32 × (49 + 3315/4096)` =
1593.898438 MHz, ÷35 = 45.539955 MHz, ÷1518 = 29,999.97 SPS — so it can
be trusted for the new target.

```
clk_target = 28,000 x 1518 = 42.504000 MHz
```

| | production | wired-mode bring-up (§1.5.5) |
|---|---|---|
| λ target | **28,000 SPS/ch** | 25,000 SPS/ch |
| `CLKOP` target | **42.504 MHz** | 37.950 MHz |
| Expected achieved | 42.5040118 MHz | **37.9500000 MHz** |
| Resulting λ | **28,000.01** (+0.28 ppm) | **25,000.00** (+0.00 ppm) |
| `FVCO` | 1572.648438 = 32×(49 + 595/4096), ÷37 | 948.75 = 32×(29 + 2656/4096), ÷25 |
| Packet rate | 474.576 pkt/s | 423.729 pkt/s |
| `m` vs measured μ | **5.23%** | 17.86% |

The IP generator picks `FVCO` itself from the target frequency — the
actionable input is the `CLKOP` target, and whatever `CLKOP_FREQ_ACTUAL`
comes back is what A.6.5's sidecar records, exactly as 45.539955 →
29,999.97 does today.

#### 1.5.5 25,000 SPS as a wired-mode bring-up step

**Decided 2026-09-03 (Manuel):** *"For initial work with wired mode, we
can start with 25 kSPS, but the goal is to make it work with 28 kSPS."*

25,000 SPS is the one candidate that lands **exactly** on a rate the Intan
controller can select. That collapses `lvds-tunnel.md` §9.5's systematic
offset to crystal tolerance alone (~100 ppm, ~1 frame every 5.6 s) and
makes A2's comparison sample-for-sample with **no resampling step at
all** — which is worth a great deal while bringing an unproven link up,
because it removes one whole class of "is this a link bug or a rate
artifact?" ambiguity.

It is a **bring-up aid, not the target.** Production is 28,000, where the
Intan side sees a 6.67% systematic offset (one frame in fifteen) and A2's
comparison does need resampling. Both rates share `clk` as the tunnel's
`ECLK`, and every ratio in the tunnel spec is invariant between them —
only absolute frequencies move — so nothing in the A.4 contract changes
when the rate does.

Note 37.95 MHz is an **exact** PLL solution (+0.00 ppm), which is a small
extra convenience for a bring-up reference.

#### 1.5.4 What this does *not* establish

**It cannot verify losslessness.** FPGA-side overflow is invisible
downstream: discarded samples never appear, and against real analog data
there is no way to detect the gap. This analysis *sets* λ; only A.7 step
1's overflow counter can *confirm* it. Step 1 remains required, and is now
the single most valuable item in A.7.

Two further limits, stated rather than buried:

- **One session, one RF environment.** μ is a 22.8-minute measurement from
  a single recording. `m` = 3.39% is what buys tolerance against the next
  environment being worse.
- **μ was measured with λ < μ**, so the MCU periodically read an empty
  `fifo0`. `FPGA_SPI_ReadSamples` costs the same either way (bit-banged,
  fixed-length), so μ should be unchanged under λ > μ — but that is an
  argument, not a measurement.

---

## 2. What v0 is, and what is wrong with it

Current `0xFFF2` notify value, 244 bytes (`stream.h:127-134`,
`packet_parser.py:71-90`):

| Off | Size | Field |
|---|---|---|
| 0 | 4 | `uint32 timestamp_s` |
| 4 | 2 | `uint16 timestamp_sub_s` |
| 6 | 1 | `uint8 seq_num` |
| 7 | 1 | `uint8 num_pairs` |
| 8 | 236 | 59 × (`int16 ch0`, `int16 ch1`) interleaved |

Defects, in the order they bite:

1. **No absolute position in the stream.** `seq_num` is a *packet*
   counter that wraps every 256 packets (~0.5 s at 508 pkt/s), so a loss
   longer than that is unquantifiable. Sample position is *synthesized*
   by the receiver from a hardcoded constant
   (`packet_parser.py:22,90`) — noted on 2026-08-27 as a trap: those
   timestamps are not measurements and must never be used to compute a
   real rate.
2. **Per-packet RTC timestamps at 1 ms resolution**, requiring the
   monotonicity clamp in `onBatchDataReceived` to hide backwards jumps
   caused by HAL tick resolution against BLE CI jitter. The clamp is a
   workaround for using wall-clock as a stream position.
3. **Loss is reported in-band** via the `0x8000` sentinel, which is also
   a legal ADC code (A.6.4).
4. **Mode is implicit.** Nothing says "2 channels"; it is baked into the
   struct shape, the parser, the recorder and the analysis tools.
5. **The fixed 59-pair shape imposes a packet-rate penalty** on
   >2-channel modes. §5.

---

## 3. The v1 header — 8 bytes, unchanged in size

All fields little-endian, matching v0 and the rest of the project.

| Off | Size | Field | Type |
|---|---|---|---|
| 0 | 4 | `sample_index` | `uint32` |
| 4 | 1 | `mode_id` | `uint8` |
| 5 | 1 | `payload_samples` | `uint8` |
| 6 | 1 | `flags` | `uint8` |
| 7 | 1 | `reserved` | `uint8`, must be 0 |

**The header stays at exactly 8 bytes**, and growing it is paid for in
margin. With a 247-byte negotiated ATT MTU the notify value caps at
244 bytes (251 LL PDU − 4 L2CAP − 3 ATT), so payload `P = 244 − H`. At
§1.5.2's 112,000 B/s aggregate budget:

```
packets/s = 112,000 / P
H = 8  ->  P = 236  ->  474.58 pkt/s   m = 5.23%
H = 9  ->  P = 235  ->  476.60 pkt/s   m = 4.79%
H = 10 ->  P = 234  ->  478.63 pkt/s   m = 4.34%
```

**Each header byte costs ~2.0 packets/s, or ~0.45 percentage points of
margin** against the measured μ = 499.42 pkt/s (§1.5).

**Updated 2026-09-03.** This paragraph previously computed against a
120,000 B/s aggregate and a 2026-05-15 ceiling of "~512 pkt/s", and
concluded there was "roughly 3.5 pkt/s of slack — about a byte and a
half… the header cannot grow." Both inputs are superseded by §1.5: the
budget fell to 112,000 B/s when λ was set to 28,000, and the real measured
ceiling is 499.42 pkt/s, not 512. **The header is no longer against a
wall** — there is 24.8 pkt/s between demand and capacity, about twelve
header bytes' worth.

That is not licence to spend it. The 24.8 pkt/s *is* the margin §1.3
requires, so a byte taken for the header is a byte taken from stall
recovery; it is a trade with a known price, not free space. Any future
field should still prefer displacing an existing one or moving to the
telemetry frame (§6) — but the constraint is now quantified rather than
absolute, and a genuinely necessary field can be paid for by lowering λ.

### 3.1 `sample_index` — absolute aggregate stream position

Count of samples produced since stream start, **across all channels**,
of the first sample in this packet's payload. Monotonically increasing by
exactly `payload_samples` per packet.

This one field replaces `seq_num`, the per-packet timestamp, and the
monotonicity clamp, and it makes loss exactly quantifiable (§7).

- **Channel of any sample** = `(sample_index + i) mod N`, where `N` is
  the channel count of `mode_id`.
- **Reset to 0** on `START_STREAMING`. Not reset by a flow-off stall,
  a reconnection within a session, or a telemetry frame.
- **Wrap:** `2³² / 56,000 = 76,696 s ≈ 21.3 h` in the 16-bit modes
  (§5.3), and `2³² / 75,000 = 57,266 s ≈ 15.9 h` in the 12-bit ones —
  **the wrap is mode-dependent, and 15.9 h is the binding figure.**
  *(Updated 2026-09-03; previously stated as 19.9 h against the
  superseded 60,000 aggregate.)* Still past the recording cap and any
  realistic session, but the margin is smaller than the original decision
  assumed, and it shrinks further if aggregate rises. Receivers **must**
  treat
  `sample_index` as wrapping (unsigned modular comparison), not as
  monotonic forever. **Decided 2026-08-28: `uint32` accepted**, with that
  modular-comparison requirement as the price. Revisit only if the
  aggregate budget rises enough to bring the wrap inside a plausible
  session.

### 3.2 `mode_id` — an index into the mode table, not a channel count

A bare channel count would be insufficient: a mode determines channel
count *and* per-channel rate *and* which physical channels are mapped.
An id into an agreed table (§5) carries all three, and lines up with the
config-named `sample_rate` object that `recording-format.md` §3 already
adopted for exactly this reason.

`mode_id = 0` is reserved and means *unknown/unspecified*; a receiver
seeing it must refuse to decode rather than assume 2 channels.

Mode changes take effect only at a packet boundary, and only while
streaming is stopped — the same constraint `SET_CHANNELS` already carries
in the control plane, so no new enforcement mechanism is needed.

### 3.3 `payload_samples` — variable length, in samples

Number of `int16` samples in the payload; payload byte length is
`payload_samples × 2`. Maximum 118 (236 B), which fits `uint8` with room
to spare.

**Variable, not fixed, for a reason.** A packet only fills as fast as the
aggregate rate allows:

| Aggregate rate | Time to fill 236 B |
|---|---|
| 75,000 samples/s (12-bit modes, §5.3) | 1.57 ms |
| 56,000 samples/s (16-bit modes, §5.3) | 2.11 ms |
| 20,000 samples/s | 5.90 ms |
| 6,000 samples/s | 19.7 ms |

A constant-size packet would make any future low-rate mode inherit bad
latency. With a length field the sender fills to 118 whenever the rate
permits and sends short when a latency budget expires, so efficiency and
latency stop trading against each other. Costs nothing: the field is
needed anyway to express the last packet of a stream.

**Sender rule:** emit when the payload reaches 118 samples **or** when
`T_fill_max` has elapsed since the first sample in the buffer, whichever
comes first. `T_fill_max` is a per-mode constant; at the 2ch/30k mode it
never binds.

### 3.4 `flags`

| Bit | Name | Meaning |
|---|---|---|
| 0 | `LOSS_SINCE_LAST` | a producer-side drop occurred since the previous packet |
| 1 | `STREAM_START` | first packet of a stream; `sample_index` is 0 |
| 2–7 | reserved | must be 0 |

`LOSS_SINCE_LAST` is a cheap in-band *hint* so a receiver can mark a gap
immediately without waiting up to a second for the next telemetry frame.
**The authoritative counts are in §6**, always. The flag says *that*
something was dropped, never *how much* or *where*.

### 3.5 `reserved`

Must be written 0. Receivers **must** tolerate a non-zero value they do
not understand, and must not validate it as 0 beyond the v0/v1
discrimination in §8.2 — that is what keeps the byte genuinely available
for a future field.

**Decided 2026-08-28: no header CRC here.** It was proposed and rejected
as the wrong layer. BLE's link layer already carries a 24-bit CRC per
packet and retransmits on failure, so a CRC computed on the MCU would
protect the headstage→bridge hop, which is already protected. The
unprotected segment is bridge→PC over UART, where a corrupted length
desynchronizes the stream until the next magic pair — and there the fix
is a frame-level CRC over header *and* payload, emitted by the bridge.
That is an existing B.2 item ("bridge UART wire format — add CRC") and it
covers 248 bytes rather than 8. Spending MCU hot-path cycles at 508 pkt/s
on the one lane with no slack, to protect a hop that does not need it and
only 3% of the frame that does, is the wrong trade.

---

## 4. Payload — a sample stream, not a frame array

The payload is `payload_samples` consecutive `int16` little-endian
samples, beginning at stream position `sample_index`.

**Frames may straddle a packet boundary.** This is the substantive change
from v0 and it is what makes the packet rate mode-independent.

The whole-frame constraint in v0 exists only because v0 has no absolute
position: if a frame is split and a packet is lost, the receiver cannot
tell which channel a subsequent sample belongs to, and the interleave
desynchronizes permanently. With `sample_index` the receiver always knows
its absolute position, so a split frame is harmless — the channel of
every sample is computable from its own index.

Rules:

1. **Never split a sample.** Payload byte length is always even, which
   `payload_samples` guarantees by construction.
2. **Channel order within a frame** is logical channel `0 … N−1`
   ascending. The map from logical channel to physical RHD2164 channel is
   *not* on the wire; it is set by `SET_CHANNELS` and recorded in the
   sidecar (`recording-format.md` §2.1), which already carries a
   `provenance` field distinguishing a verified readback from an
   unverified request.
3. **`payload_samples` need not be a multiple of `N`.**
4. A receiver that has never seen a telemetry frame or a `mode_id` it
   recognizes must buffer or discard, never guess.

---

## 5. Modes — one aggregate budget, and packet rate that no longer depends on channel count

### 5.1 The arithmetic that motivated this

Under v0's whole-frame packing, `frames/packet = floor(236 / 2N)`, and
the rounding waste raises the packet rate even though the data rate is
identical:

| Mode | Frame | Frames/pkt | Waste | pkt/s @ 60 kSPS aggregate |
|---|---|---|---|---|
| 2ch × 30k | 4 B | 59 | 0 B | 508.5 |
| 4ch × 15k | 8 B | 29 | 4 B | 517.2 |
| 8ch × 7.5k | 16 B | 14 | 12 B | 535.7 |

Because per-packet MCU cost dominates and the headstage MCU is the only
lane in the chain without slack (`log/2026-08-28.md` §3), that penalty
lands squarely on the binding resource: an 8-channel mode would have
needed **5.4% more packets/s for identical science throughput**, and
535.7 pkt/s exceeds the only measured ceiling on record.

Under §4 the waste disappears entirely. Payload is always 236 B, so:

```
packets/s = aggregate_bytes_per_second / 236     — for every mode
```

*(The three-row table that stood here, `2ch_30k` / `4ch_15k` / `8ch_7k5`
at a 60,000 aggregate, is superseded by §5.3 — the aggregate came down to
56,000 when §1.5.2 set λ = 28,000.)*

**Per-channel rates in any mode table are targets, not commitments.** §1.3's
invariant sets the actual aggregate rate from measurement, and the real
FPGA-derived per-channel rate — cycle-counted from RTL and
oscilloscope-confirmed, per `recording-format.md` §3 — is what a sidecar
records. The table's job is to fix `N` and the nominal partition, not to
assert a rate nobody measured.

### 5.2 Why this matters beyond the roadmap

Packet rate becomes a pure function of aggregate data rate, so:

- There is genuinely **one budget number** for the whole system, not one
  per mode, and §1.3's margin `m` is defined once and holds everywhere.
- **B.4 characterisation does not multiply by the number of modes.**
  `μ_low` measured in any mode applies to all of them, because every mode
  presents the transport with the same packet rate and the same packet
  size. This is the largest practical payoff of the change.

### 5.3 The mode roadmap — agreed 2026-09-03

Proposed by Manuel and corrected in review the same day. **Mode 1 alone is
needed for the animal test; Modes 1–5 for public release; 6–10 are future
versions.** Recorded here because this table is what `mode_id` (§3.2)
indexes, and because fixing the partition early is what keeps §5.2's "one
budget for the whole system" property true.

**`mode_id` 0 stays reserved** for *unknown*, per §3.2: a receiver seeing
it "must refuse to decode rather than assume 2 channels". That is the
load-bearing reason — without a reserved value a receiver has to guess,
and the natural guess is the legacy 2-channel mode, which mis-decodes an
N-channel stream into plausible-looking waveforms with every sample
attributed to the wrong channel. A secondary benefit: all-zeros is the
most likely corruption value, and the bridge→PC UART hop has no CRC yet
(§3.5 defers it to B.2) on a link known to drop bytes — so a zeroed header
failing on both `mode_id` and `payload_samples` is worth having. Modes are
therefore numbered **1–10** on the wire and in prose.

#### 5.3.1 The budget every mode must fit

From §1.5, `μ` = 499.42 pkt/s = 117,863 B/s. Because §4 makes payload
always 236 B, `pkt/s = aggregate_B_per_s / 236` in **every** mode, so a
mode is legal iff its aggregate byte rate fits with margin.

#### 5.3.2 The table

| `mode_id` | Name | N | F | k | SPS/ch | bits | aggregate | B/s | pkt/s | `m` | needed for |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | *reserved / unknown* | — | — | — | — | — | — | — | — | — | — |
| **1** | `2ch_28k` | 2 | 28k | 1 | **28,000** | 16 | 56,000 | 112,000 | 474.58 | +5.23% | **animal test** |
| **2** | `4ch_14k` | 4 | 28k | 2 | 14,000 | 16 | 56,000 | 112,000 | 474.58 | +5.23% | public release |
| **3** | `8ch_7k` | 8 | 28k | 4 | **7,000** | 16 | 56,000 | 112,000 | 474.58 | +5.23% | public release |
| **4** | `16ch_3k5` | 16 | 28k | 8 | **3,500** | 16 | 56,000 | 112,000 | 474.58 | +5.23% | public release |
| **5** | `32ch_1k75` | 32 | 28k | 16 | **1,750** | 16 | 56,000 | 112,000 | 474.58 | +5.23% | public release |
| 6 | `3ch_25k_12b` | 3 | 25k | 1 | 25,000 | 12 | 75,000 | 112,500 | 476.69 | +4.77% | future |
| 7 | `6ch_12k5_12b` | 6 | 25k | 2 | 12,500 | 12 | 75,000 | 112,500 | 476.69 | +4.77% | future |
| 8 | `12ch_6k25_12b` | 12 | 25k | 4 | 6,250 | 12 | 75,000 | 112,500 | 476.69 | +4.77% | future |
| 9 | `72ch_1k04_12b` | 72 | 25k | 24 | **1,041.67** | 12 | 75,000 | 112,500 | 476.69 | +4.77% | future |
| 10 | `spikes_128ch` | 128 | — | — | event stream | — | data-dependent | §5.3.4 | | | future |

**Modes 3–5 are corrected from the original proposal** (7,500 / 3,750 /
1,875, all at a 60,000 aggregate). That figure was the pre-A.7 budget,
correct at λ = 30,000 and not at λ = 28,000: it put those modes at 107.1%
of budget and `m` = **−1.78%** — numerically the identical ρ > 1 failure
§1.5.3's retune exists to escape. 7,000 / 3,500 / 1,750 fixes it.

**Mode 9's per-channel rate is 1,041.67**, not the proposed 1,040 — k = 24
on the 25 kHz frame gives exactly 75,000 aggregate, matching Modes 6–8.

Packet rate across the whole table spans **474.58 – 476.69 pkt/s, a 0.45%
spread**, so §5.2's claim — one `μ_low` measurement covers every mode —
holds despite the two frame rates.

#### 5.3.3 Two frame rates, integer decimation

The RHD2164 pair converts **all 128 channels every frame**. A mode is
therefore "pick N of the 128, deliver each every k-th frame", per-channel
rate F/k — and **k must be an integer**, or delivered samples are
non-uniformly spaced, which no downstream analysis can undo.

That constraint, plus the aggregate budget, is satisfied by exactly two
frame rates:

| Family | F | `clk` | k values | aggregate | `m` |
|---|---|---|---|---|---|
| **16-bit** (Modes 1–5) | 28,000 | 42.504 MHz | 1, 2, 4, 8, 16 | 56,000 smp/s | +5.23% |
| **12-bit** (Modes 6–9) | 25,000 | 37.950 MHz | 1, 2, 4, 24 | 75,000 smp/s | +4.77% |

Both `clk` values are already derived: 42.504 MHz is §1.5.3's production
retune, and **37.95 MHz is an exact PLL solution** (+0.00 ppm) that
§1.5.5 already specifies as the wired-mode bring-up rate. **No third
clock is needed anywhere in the system.**

The 16-bit family costs one power-of-two decimation counter and extends
**free** to channel counts the proposal did not reach:

| N | k | SPS/ch | aggregate |
|---|---|---|---|
| 64 | 32 | 875.0 | 56,000 |
| 128 | 64 | 437.5 | 56,000 |

**Runtime switching between the two frame rates** needs a second clock
source and a glitch-free mux. The hardware has exactly that spare: the
`.mrp` reports **PLLs 1 of 2 used** and **DCSs 0 of 1 used** — one free
PLL to generate 37.95 MHz and one dynamic clock-select primitive, which is
precisely what DCS exists for. Without it the alternative is a bitstream
reload to change families, which is acceptable for v1 (Modes 1–5 all share
F = 28,000, so no switching is needed until Mode 6 ships).

#### 5.3.4 Mode 10 — spike times only. Specified as a placeholder, not designed.

**Not a sample stream.** Mode 10 emits spike time-locations for up to 128
channels after spike-detection RTL exists. Recorded now so the mode space
and its consequences are reserved; the design is future work.

Three things it breaks that every other mode obeys, all of which must be
resolved before it is built:

1. **§4's payload contract does not apply.** `sample_index` and
   `payload_samples` are meaningless for an event stream. Mode 10 needs
   its own `frame_type`, not just a `mode_id`.
2. **Its bandwidth is data-dependent** — it scales with the firing rate,
   not with a configured sample rate. This is the significant one:
   **§1.3's λ < μ stops being a static check**, because λ is no longer a
   design constant. Mode 10 needs either a worst-case firing-rate
   assumption with the arithmetic written down, or an explicit rate
   limiter with documented overflow behaviour. Silent loss under a
   burst — a seizure, a stimulation artifact — is exactly the failure this
   whole spec exists to prevent.
3. **It has no per-sample timestamp to inherit.** Event times need their
   own encoding and their own resolution decision, tied to the frame
   clock rather than to a sample index.

#### 5.3.5 Implementation notes carried by this table

- **12-bit packing needs a §4 amendment.** 236 B = 1888 bits = 157.33
  samples at 12 bit. Either 157 samples fit with 4 bits spare (0.2% waste,
  preserves §4 rule 1's "never split a sample") or samples straddle
  packets at bit level (breaks it). **Take the former**, and amend §4
  before any 12-bit mode ships. Not needed for Modes 1–5.
- **`ch_sel` must be restructured for N > 2.** It has a 4-way mux serving
  2 channels today. Modes 2–5 are the natural forcing function for PLAN.md
  B.3's already-flagged decoupling of `ch_sel` into a generic
  `{channel, sample, valid}` source.
- **`SET_CHANNELS` currently carries two channel indices**
  (`channel-selection-control-plane.md` §1a). Modes 2–5 need it to carry
  N of them, or to be replaced by a channel-set descriptor. That is a
  control-plane change, and it belongs in that spec rather than this one.

---


## 6. Telemetry and time anchor — the `0xDD 0x22` frame

One new frame type, carrying **every counter and the RTC anchor**. It is
deliberately *one* type: PLAN.md's existing B.5 item proposes `0xDD 0x22`
for bridge TX-ring drops alone, and A.6.4 needs an out-of-band loss
report, and §3.1 removes the per-packet timestamp that absolute time
depended on. Three separate frame types doing the same job is the outcome
to avoid; this spec supersedes that B.5 item's narrower shape.

### 6.1 Path

Counters originate in two places, so the frame is assembled in two hops:

```
FPGA  fifo0 overflow counter  ──(regbank read)──▶ MCU
MCU   ring truncation, flow-off, stall time, RTC anchor
      ──(0xFFF4 notify)──▶ Bridge
Bridge adds its own TX-ring counters
      ──(0xDD 0x22 frame)──▶ pc-app
```

**Telemetry gets a new notify characteristic, `0xFFF4`** — decided
2026-08-28, changed from this spec's original proposal, which was to
reuse `0xFFF3` with an unsolicited high-bit opcode (`0x80`).

**Why the change.** `0xFFF3`'s contract is request/response: every
notification on it answers a command, first byte echoing that command's
opcode. Unsolicited traffic there would be safe only by *convention* — a
high-bit rule enforced nowhere, which breaks the moment anyone writes the
natural code ("a `0xFFF3` notification answers my pending command") or
adds an opcode with the high bit set. That is the same failure shape as
the bridge's single-producer TX ring found 2026-08-28: correct by
assumption rather than by construction. A characteristic handle is
enforced by the GATT layer, so the bridge demultiplexes structurally
instead of by inspecting payload content.

The cost initially argued against it — GATT table space — was a
mis-weighing: table space is flash/RAM at init, while the budget that is
actually scarce is per-packet MCU cycles on the hot path (§3). A 1 Hz
frame costs nothing on either count.

**The real cost, named honestly:** the bridge's connection sequence gains
a fourth characteristic to discover and a fourth CCCD to write, in a
sequence with a history of fragility. That is accepted because it fails
*loudly* — telemetry does not arrive — rather than silently misrouting a
command response. It also buys a genuine capability: telemetry has its own
CCCD, so it can be enabled or disabled independently of the command plane
(useful to leave on through a soak and off during a latency-sensitive
test).

`0xFFF3` is therefore unchanged by this spec, and the `0x80` opcode
convention is dropped as unnecessary. The payload's own versioning moves
into the frame itself (§6.2).

### 6.2 Contents

| Off | Group | Field | Type | Source |
|---|---|---|---|---|
| 0 | Header | `telemetry_version` | `uint8` | constant, `1` |
| 1 | Header | `flags` | `uint8` | MCU — see below |
| 2 | Anchor | `anchor_sample_index` | `uint32` | MCU |
| 6 | Anchor | `anchor_timestamp_s` | `uint32` | MCU RTC |
| 10 | Anchor | `anchor_timestamp_sub_s` | `uint16` | MCU RTC |
| 12 | FPGA | `fifo0_overflow_samples` | `uint32` | regbank (new, §6.4) |
| 16 | FPGA | `fifo0_high_water` | `uint16` | regbank (new, §6.4) |
| 18 | MCU | `ring_truncated_samples` | `uint32` | `stream_app.c` |
| 22 | MCU | `flow_off_count` | `uint32` | `s_flowoff_total` |
| 26 | MCU | `stall_time_ms_total` | `uint32` | new, §6.5 |
| 30 | Bridge | `tx_ring_drop_bytes` | `uint32` | `s_drop_bytes` (exists) |
| 34 | Bridge | `tx_ring_drop_frames` | `uint32` | `s_drop_frames` (exists) |

All fields little-endian. **The MCU half is bytes 0–29 (30 bytes) and is
what appears on `0xFFF4`; the bridge appends bytes 30–37, making the
`0xDD 0x22` payload 38 bytes.** Offsets are given because three
independent implementations have to agree on them, and the field order
puts the version byte first so a receiver can dispatch on it before
knowing anything else. Nothing here is aligned for free — `uint32`s sit
at odd-ish offsets 2, 6, 18, 22, 26 — so **every implementation packs and
unpacks byte-wise, never by casting a struct pointer.** On the Cortex-M0+
(both the headstage MCU and the bridge) an unaligned `uint32` load
HardFaults; that is the same class of bug the `aligned(4)` note on
`StreamDataPacket_t` records, and the cost of avoiding it here is ten
lines of explicit little-endian stores on a 1 Hz path.

#### `flags` — bit 0 `fpga_counters_valid`

*Added 2026-09-04, during implementation. Byte 1 was `reserved, must be
0` at agreement.* The two FPGA fields have three possible meanings and
the frame as agreed could express only two of them: a real zero, and a
non-zero count. The third — **"this build cannot read them"** — is the
one that is actually true today and will stay true for as long as step 1
(§6.4's RTL counter) is unbuilt, and reporting it as `0` is exactly the
silent-zero failure §6.3's third rule exists to forbid one level up.

- **bit 0 `fpga_counters_valid`** — `1` when
  `fifo0_overflow_samples` / `fifo0_high_water` were actually read from
  the regbank for this frame. `0` when they were not, in which case both
  fields **must** be transmitted as `0` and a receiver **must not**
  display or accumulate them.
- **bits 1–7 reserved, must be 0.**

A receiver that sees `fpga_counters_valid == 0` for a whole session knows
its FPGA-side loss accounting is *absent*, not *clean* — which is a
different thing, and the distinction is the entire point of §7's
attribution table. Its top row ("`fifo0_overflow_samples` moved →
producer-side loss") is unusable without it: with a silent zero, "did not
move" and "cannot be read" look identical.

This costs nothing on the wire and keeps the frame's size and every other
offset unchanged, which is why it is worth taking now rather than
spending `telemetry_version` 2 on it later.

**The anchor pair is the whole reason absolute time survives leaving the
per-packet header.** `(anchor_sample_index, anchor_timestamp_s/sub_s)`
pins one known stream position to one wall-clock reading; every other
sample's absolute time follows from its index and the mode's rate. This
is strictly better than v0: one RTC read per second instead of one per
packet, no clamp, and the interpolation is over an exactly-known sample
count rather than a jittery packet arrival.

`telemetry_version` exists because this frame is the one place new
counters will want to be added — it is off the hot path, so there is no
pressure to keep it minimal, and a version byte on a 1 Hz frame costs
nothing. Receivers decode the fields their version knows and ignore
trailing bytes, so adding a counter is additive rather than breaking.
The MCU fills every field except the `Bridge` group, which the bridge
appends before emitting `0xDD 0x22`; a bridge that has never seen a
notification on `0xFFF4` must not synthesise one from its own counters
alone.

### 6.3 Rules

- **Counters are cumulative since `START_STREAMING`, never per-interval
  and never reset by a report.** A lost telemetry frame then costs
  resolution, not information: the receiver diffs against the last one it
  actually received.
- **Cadence ~1 Hz.** It does not need to be exact and must not be emitted
  from the hot send path. **Confirmed 2026-09-04** against the obvious
  cheaper alternative (once per minute) — see §6.3.1 for why cost is not
  what sets this.
- A receiver **must not** infer that "no telemetry frame yet" means "no
  loss yet".

#### 6.3.1 Why 1 Hz and not once per minute

*Added 2026-09-04. The original text justified the cadence on cost — one
frame against 474.6 pkt/s is negligible — which answers "why not faster"
and says nothing about "why not slower". Cost does not decide this: 1 Hz
is ~0.2% of packet slots and 1/min is ~0.003%, and both are free. What
the rate buys is **time resolution**, and three things need it.*

Because counters are cumulative, a slower cadence loses no *totals* — it
loses the ability to say which loss episode was which.

1. **Attribution bracket.** §7 attributes a gap by differencing counters
   across it, so the bracket is one telemetry interval wide. The binding
   number is §1.5's measurement: the ~116 ms stalls occurred **five times
   in 22.8 min, minimum spacing 60 s.** At a 1-minute cadence the
   sampling interval *equals* the observed minimum event spacing — two
   independent episodes can land in one bucket with several counters
   moved, and attribution fails exactly when there is something to
   attribute. 1 Hz leaves 60× margin.
2. **Short recordings would carry no anchor.** §6.2's anchor pair is what
   carries absolute time once §3.1 drops the per-packet timestamp. A
   recording that starts and ends between two anchors contains none, and
   has no absolute time at all. At 1/min that is most bench recordings;
   at 1 Hz anything past ~2 s is covered.
3. **Time to detect that telemetry itself is broken.** "No frame yet" and
   "the `0xFFF4` CCCD was never enabled" are indistinguishable until a
   frame arrives — the same ambiguity the rule above this one exists to
   guard. At 1 Hz the pc-app's 2 s status tick surfaces it within one
   refresh; at 1/min the panel shows a stale frame 96% of the time.
   Discovering at t+60 s that loss accounting was never running is a
   materially worse failure in a **one-shot** animal recording, which is
   the case A.7 exists for.

**And not faster than 1 Hz either:** stall episodes are ~100 ms but
spaced ~60 s apart, so 1 Hz already resolves them individually. Finer
buys no attribution and starts consuming mblocks from the same pool the
data stream contends for.

1 Hz therefore sits at ~60× margin on the resolution it needs and ~500×
on cost — a comfortable point rather than a tuned one, which is the right
shape for a diagnostic. `STREAM_TELEMETRY_PERIOD_MS` in `stream_app.c`
if the bench ever argues otherwise.

### 6.4 New RTL requirement

`fifo.v:58` is `else if (wen && !full)` — on full, the write is silently
discarded. There is no counter and no latched flag; `fifo_full` reaches
only `cmd_is_00` as a debug output (`kuntur_fpga.v:118`, itself T3.3's
debug hijack). **This is the single uncontrolled loss point in the
headstage** and it is currently invisible, which is why the 2026-08-27
deficit had to be inferred from delivered-rate arithmetic instead of
read off a counter.

Required: a saturating overflow counter and a high-water mark in `fifo`,
exposed as **read-only regbank words**. The MCU reads them over the
existing `REG_READ16` path that A.1.1g already generalized — no new
mechanism, just a counter and two words. This is a concrete instance of
PLAN.md's open *"FPGA regbank has no read-only registers"* item and
should be built as its first use case rather than separately.

### 6.5 New MCU counters

- `ring_truncated_samples` — the `flow_off:` path clamps its 59-pair push
  to whatever ring room remains and **silently discards the remainder**.
  Those pairs have already been popped out of `fifo0`, so they exist
  nowhere else. Only reachable when the ring is already full, but real and
  uncounted.

  *Correction, 2026-09-04, found while implementing:* this section also
  named `StreamContinuousPollDuringStall` (and by the same shape
  `StreamIngestDuringStall`) as a second discard site. **It is not one.**
  Both clamp their FPGA *read* — `if (n > room) n = room;` before
  `FPGA_SPI_ReadSamples(tmp, n)` — so a short read simply leaves the
  remainder sitting in `fifo0`, which is the intended backpressure and
  loses nothing. The clamp *looks* identical to the `flow_off:` one and is
  not, because in the `flow_off:` case the samples are already in hand.
  There is exactly one MCU-side discard site, and `ring_truncated_samples`
  counts it.
- `stall_time_ms_total` — accumulated time with `s_txFlowOff` set. With
  `flow_off_count` this yields both halves of §1.3's stall duty cycle,
  which is the number nobody currently has and which `m` cannot be chosen
  without.

Backpressure elsewhere in the headstage already behaves correctly and
needs no counter: a full MCU ring stops `StreamIngestDuringStall`, which
pushes pressure back onto `fifo0` rather than dropping.

### 6.6 When the MCU may read the FPGA counters

*Added 2026-09-04, during implementation of step 2.*

§6.4 says the MCU reads the FPGA counters "over the existing `REG_READ16`
path — no new mechanism". That is true about the *primitive* and false
about the *calling context*, and the difference is a real hazard the
agreed text walked past.

**The invariant it collides with.** Every regbank access built so far is
structurally confined to streaming being *stopped*
(`fpga_spi.h`: "never interleaved with an in-progress
`FPGA_SPI_ReadSamples()`. Structural as built — `0xFFF1` rejects these
unless streaming is already stopped, and they execute from
`StreamSendTask`'s stopped branch"; and
`channel-selection-control-plane.md` §5, which exists because an earlier
inline placement hung the MCU). A 1 Hz telemetry frame that reads the
regbank while streaming is, on its face, the first violation of that
rule.

**Why it is nonetheless safe, stated as a construction rather than a
hope.** The invariant's operative clause is *interleaved with an
in-progress `FPGA_SPI_ReadSamples()`* — a bit-banged SPI0 sequence has no
preemption to interleave *within*, so what it actually forbids is issuing
regbank transfers from a context that can land in the middle of one:
a BLE callback, an ISR, or the pre-A.1.1g FSM state where a POP pair
could be left half-open. None of those apply here if, and only if, the
read is issued from **one fixed point: the top of `StreamSendTask`'s send
loop, between two whole packets, with no `FPGA_SPI_ReadSamples()` in
progress and none possible until the loop continues.** A.1.1g's trailing
NOP already guarantees the FSM is clean at that point (it is the same
property `StreamFlushFpgaFifo` relies on), and `s_command_busy` is
untouched because no command is involved.

**The three rules that make it a construction:**

1. **Reads only, never writes.** A `REG_WRITE16` mid-stream can change
   the sampling table under a live conversion; a `REG_READ16` changes no
   FPGA state.
2. **From `StreamSendTask` only, at a packet boundary.** Never from the
   `0xFFF1` callback, never from a timer, never from the flow-off branch
   (`fifo0` is under maximum pressure there — the worst possible moment
   to spend SPI0 time not popping it).
3. **Skipped, not deferred, if the moment is wrong.** If the send loop
   does not reach its top for a whole second (a long stall), that
   second's frame goes out with `fpga_counters_valid = 0` rather than
   forcing the read somewhere less safe. A telemetry frame is worth
   nothing next to the stream it measures.

**Cost.** Two 16-bit transfers per counter word, three words, ~10 µs per
transfer bit-banged ≈ **60 µs per second**, or 0.006% of the send loop's
time — against a packet period of ~2 ms, so at most one packet is
displaced per second, and only if the read straddles a send opportunity.
That is inside the `m` = 5.23% rate margin by three orders of magnitude
(§1.5.2), and it is the reason the cadence is 1 Hz and not faster.

**Until §6.4's RTL lands**, no regbank read is issued at all and the
frame carries `fpga_counters_valid = 0` (§6.2). The MCU code is written
so that turning it on is a single compile-time switch plus the two word
addresses, and the switch is what the RTL step flips — the telemetry
chain does not need re-testing when it does.

### 6.7 The anchor is a loss detector under v0, not only future-proofing

`anchor_sample_index` counts **aggregate samples since
`START_STREAMING`** — 2 per pair, so +118 per full v0 packet — exactly as
§3.1 defines it for the v1 header. Under v0 that field does not appear in
the per-packet header, so nothing on the wire carries it except this
frame.

It is still worth counting from day one, and not only so the counter is
already correct when v1 arrives. A v0 receiver can maintain the *same*
count independently (packets received × `num_pairs` × 2, from stream
start), and **the difference between the MCU's anchor and the receiver's
own count is the total sample loss between them, measured directly.**
That is a whole-path loss figure available immediately, without the v1
header, and it is independent of `seq_num` — which only counts *packets*
and cannot see a short packet or a truncated frame at all.

Where it stays weaker than v1: it says *how many* samples were lost since
stream start, not *where*. §7's positional answer still needs the v1
header.

### 6.8 Implementation status, 2026-09-04

Step 2 (§9) is **built on all three sides and desk-verified; nothing here
has met hardware.** What that means precisely, because "implemented" and
"working" are not the same claim:

| Side | File | Built | Verified how |
|---|---|---|---|
| MCU | `stream.c` / `stream.h` — `0xFFF4` char, CCCD, byte-wise serialiser | ✅ | compiles clean, no new warnings |
| MCU | `stream_app.c` — counters, 1 Hz `StreamTelemetryPoll()` | ✅ | compiles clean |
| Bridge | `vega_bridge_app.c` — discovery, 4th CCCD, `0xDD 0x22` re-framing | ✅ | compiles clean |
| pc-app | `telemetry.py`, `serial_reader.py`, `main_window.py` | ✅ | `test_telemetry.py`, offscreen GUI smoke test |

**Desk-verified** covers the parts that can be: §6.2's byte offsets (a
test builds a frame field-by-field from the table above and asserts every
one back out), the three-way magic dispatch through the real
`SerialReader` thread over a pty, forward-compatibility with a longer
future frame, the `fpga_counters_valid` distinction, and the
loss-differencing arithmetic including a far-end counter reset.

**Not verified, and needing the bench:**

1. **The bridge's connection sequence with a fourth CCCD.** Named in §9 as
   the riskiest part, and unchanged in that assessment: this sequence has
   a history of fragility, and nothing desk-side can exercise it. Bring it
   up per §9 — against a headstage that is *already streaming*, so a
   telemetry failure is unambiguous rather than tangled up in a
   stream-that-never-started.
2. **The 1 Hz notify's real cost on the send loop.** Argued at ~60 µs/s
   in §6.6 and believed negligible, but `μ` was measured without it. A
   before/after packet-rate comparison is nearly free at the same bench
   session and would close it.
3. **`fifo0_overflow_samples` end to end** — blocked on step 1's RTL, by
   construction. Until then every frame carries `fpga_counters_valid = 0`.

**What is deliberately absent.** No FPGA regbank read is issued: the MCU
switch `STREAM_TELEMETRY_FPGA_COUNTERS` is `0` and the two word addresses
are placeholders, because §6.4's counter does not exist in the RTL yet.
Turning it on is that switch plus the addresses — the rest of the chain
does not change, so it does not need re-testing when step 1 lands.

---

## 7. Loss accounting — what replaces the `0x8000` sentinel

**The sentinel is retired.** `0x8000` becomes an ordinary ADC code with
no special meaning, and A.6.4's DECISION 2 resolves as its option *(b)*.

A receiver detects loss structurally:

```
expected = prev_sample_index + prev_payload_samples
gap      = sample_index - expected        (modular, uint32)
gap > 0  ->  exactly `gap` samples are missing, at exactly known positions
```

Attribution, which v0 cannot do at all, comes from differencing §6's
counters across the gap:

| Counters that moved | Loss was |
|---|---|
| `fifo0_overflow_samples` | producer-side: FPGA outran the transport (ρ ≥ 1, or a stall longer than 137 ms) |
| `ring_truncated_samples` | MCU ring overflowed during a flow-off stall |
| `tx_ring_drop_*` | bridge USB-side backlog — *not* a radio problem |
| none of the above | lost on air |

That last row is the one that matters most: `dropped_packets` in the
pc-app currently conflates a USB backlog and a radio problem
(`log/2026-08-28.md` §2.5), and the bridge is the only place that can
tell them apart.

Consequences for existing code:

- `packet_parser.is_fifo_underrun()` — single-sourced on 2026-08-27
  specifically so this decision could land in one place — is **deleted**,
  along with its callers in `graph_widget.py` and `analyze_recording.py`.
  B.3's "single-source the underrun sentinel rule" item closes as
  resolved-by-removal rather than by refactor.
- A.6.4's blocked empirical measurement ("what is the sentinel rate
  against real data?") becomes moot: the question it was trying to answer
  is answered directly by `fifo0_overflow_samples`.

---

## 8. Framing, versioning and migration

### 8.1 Bridge framing is unchanged

`0xAA 0x55` + `uint16 length` + payload for sample data, `0xEE 0x11` for
command responses (`vega_bridge_app.c:40-43`), plus `0xDD 0x22` from §6.
The length field already accommodates a variable payload, so §3.3 needs
no framing change. Magic bytes identify frame *type*, not device — the
multi-device note in PLAN.md's V1 scope still holds.

### 8.2 v0 → v1 discrimination

This is a breaking change and the two cannot coexist on `0xFFF2` without
a discriminator.

**Preferred: fold it into B.6's version/name handshake.** The pc-app
learns the protocol version at connect and selects a parser. B.6 already
tracks replacing the bare `"Kuntur-Headstage"` string match with a
version/name handshake; this makes that item a **prerequisite** of
implementing v1 rather than a nice-to-have, which is a schedule fact
worth surfacing early.

**Fallback if the handshake slips:** byte 7 is `num_pairs` in v0 (always
`59` = `0x3B` in steady state) and `reserved` in v1 (always `0`). A
receiver can discriminate on `byte7 == 0`. This is serviceable but
fragile — it depends on byte 7 staying reserved, which §3.5 commits to
but a future field could reclaim, and a
v0 short final packet could in principle carry `num_pairs == 0`
(`serial_reader.py`'s A.6.1 crash was exactly that case). Use it only as
an interim, and only with the handshake already scheduled.

### 8.3 Relationship to the recording format

`recording-format.md`'s `format_version` (sidecar) and
`vega-recording-format-version` (CSV) are versioned independently of this
wire format and stay that way — a wire change need not change the CSV
column schema, and vice versa. But the sidecar **gains a field**: the
`mode_id` and mode-table entry a recording was captured under, so a
recording remains interpretable when the table grows.

---

## 9. Implementation order

Deliberately phased, because §1.3's λ cannot be chosen until the
telemetry it depends on exists. Do not reorder 1–3.

1. **`fifo0` overflow counter + high-water mark + read-only regbank
   words** (RTL, §6.4). Makes the one uncontrolled loss point visible.
   Smallest change, largest information gain, and the first real use case
   for read-only regbank registers.
2. **Telemetry frame end-to-end** — new `0xFFF4` notify characteristic
   in `stream.c`'s service definition, the bridge's connection sequence
   extended to discover it and write its CCCD, bridge re-framing to
   `0xDD 0x22` with its own counters appended, `serial_reader.py` decode,
   pc-app status line. §6. ✅ **Implemented 2026-09-04, desk-verified,
   not yet bench-verified** — see §6.8. Retires one of the three causes
   currently conflated in `dropped_packets` on its own, independent of
   everything below. The riskiest part is the bridge connection sequence, which has
   a history of fragility — bring it up against a headstage that is
   already streaming, so a telemetry failure is unambiguous.
3. **Measure.** `μ_low` (re-measure the packet-rate ceiling directly —
   the cheapest way to separate an mblock-margin question from a
   per-packet-cost regression) and the stall duty cycle from
   `flow_off_count` / `stall_time_ms_total`. Then set λ and `m` per
   §1.3, and re-tune the PLL to the chosen λ.
4. **v1 header + payload** (§3, §4), behind B.6's version handshake
   (§8.2). Parser, recorder and analysis tools together.
5. **Retire the sentinel** (§7) and the monotonicity clamp.
6. **Mode table entries 2 and 3** — only after 1–5 are stable. Nothing in
   the roadmap modes is blocked by this spec once the format is v1.

Steps 1–3 are pure additions and break nothing. The breaking change is
confined to step 4.

---

## 10. Questions that were open at proposal

**All four blocking questions were closed 2026-08-28** (see the status
block at the top for the decisions and their reasoning):

1. ~~Header CRC in `reserved`?~~ **No** — wrong layer; §3.5.
2. ~~Telemetry on `0xFFF3` or its own characteristic?~~ **Own
   characteristic, `0xFFF4`**; §6.1. *(Raised during the agreement pass,
   not in the original proposal.)*
3. ~~Should `mode_id` changes require streaming stopped?~~ **Yes**,
   matching `SET_CHANNELS`; §3.2.
4. ~~`sample_index` 32-bit wrap at 19.9 h?~~ **Accepted**, with a
   modular-comparison requirement on receivers; §3.1. *(The 19.9 h figure
   was against the superseded 60,000 aggregate; the real worst case is
   **15.9 h**, in the 12-bit modes of §5.3. Decision unchanged.)*
5. ~~Where the logical→physical channel map lives.~~ **Sidecar**, via
   `SET_CHANNELS` — settled by decision 3: channels cannot change
   mid-stream, so the map is constant for a recording and does not belong
   on the wire. §4.

**Two remain, neither blocking implementation:**

- **`T_fill_max` per mode** (§3.3). Does not bind at 2ch/30k — the packet
  always fills in 1.97 ms — so it needs a number only before the first
  low-rate mode ships, which is step 6 at the earliest.
- **Does `μ` depend on payload size at all?** (§5.2). The claim that one
  characterisation covers all modes holds if MCU per-packet cost
  dominates. Confirm it during step 3's measurement rather than assuming
  it; if it turns out false, §5.2's payoff shrinks but nothing in the
  format changes.

---

## 11. Items this spec touches

| Item | Effect |
|---|---|
| A.6.4 DECISION 2 | **Resolved** as option (b), §7 |
| A.6.5 recording format | Sidecar gains `mode_id`; `sample_rate` object already shaped for it |
| B.2 format versioning | Satisfied for the wire format; §8.2 |
| B.3 single-source sentinel | Closes as resolved-by-removal, §7 |
| B.5 bridge TX-ring telemetry | **Superseded** by §6's single frame type |
| B.5 FIFO/ring occupancy telemetry | Specified, §6.4–6.5 |
| B.5 mblock margin + FIFO sizing | Reframed as §1: a margin question, not a depth question |
| B.5 1.7% FPGA FIFO underrun | Becomes directly measurable, §6.4 |
| B.5 SPS overshoot | λ set by §1.3 rather than by a nominal target |
| B.6 version/name handshake | Promoted to a **prerequisite** of step 4, §8.2 |
| B.2 bridge UART CRC | Confirmed as the right layer for integrity, §3.5 — a header CRC was rejected in its favour |
| `stream.c` GATT service | Gains a fourth characteristic, `0xFFF4` notify, §6.1 |
| Bridge connection sequence | Gains a fourth discovery + CCCD write, §6.1 — the accepted cost of `0xFFF4` |
| CLAUDE.md | Deliberately **not** updated until built (working principle 4) |
| B.1 ground-truth audit | `fifo0` "34 ms" is stale in CLAUDE.md; §1.2 |
| T3.3 debug hijacks | `cmd_is_00 = fifo_full` is superseded by §6.4's counter |
