# Stream packet format (v1) — interface spec

**Status: AGREED 2026-08-28, not yet implemented.** Written before any
code, per PLAN.md working principle 5 and the standing project rule that
cross-boundary interfaces get a spec first. This is a **breaking
wire-format change** to the `0xFFF2` notify payload, plus one new
characteristic and one new frame type; it supersedes the format
documented in CLAUDE.md's *BLE Device Protocol* section (here called
**v0**).

CLAUDE.md is deliberately **not** updated to describe any of this yet —
it documents as-built, and none of this is built (working principle 4).

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
- **`sample_index` stays `uint32`** (§3.1), accepting the 19.9 h wrap
  with a modular-comparison requirement on receivers.

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
*accumulating*, not draining. ρ ≥ 1.

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
- **`μ_low` and the stall duty cycle are both currently unmeasured.**
  `μ` = 512 pkt/s is from 2026-05-15, under a different production rate
  and before several RTL and PLL changes; delivery of 499.7 pkt/s on
  2026-08-27 is inconsistent with it still holding. §6's telemetry is the
  prerequisite for setting λ at all — see §9's implementation order.

### 1.4 What is foreclosed

True store-and-forward through multi-second radio outages needs on the
order of 120 kB/s of headstage buffering. The WB09's 64 KB of RAM, most
of it taken by the BLE stack, cannot provide it. **Riding out outages is
a headstage-storage feature, not a tuning parameter** — it would require
adding non-volatile storage to the headstage and is out of scope for v1.
The margin is therefore the only free lever, which is what makes §1.3 an
invariant rather than a preference.

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

**The header stays at exactly 8 bytes, and that is a hard budget, not a
coincidence.** With a 247-byte negotiated ATT MTU the notify value caps
at 244 bytes (251 LL PDU − 4 L2CAP − 3 ATT), so payload `P = 244 − H`.
At the 120,000 B/s aggregate budget:

```
packets/s = 120,000 / P
H = 8  ->  P = 236  ->  508.5 pkt/s
H = 9  ->  P = 235  ->  510.6 pkt/s
```

**Each header byte costs ~2.1 packets/s.** Against ~512 pkt/s of ceiling
and 508.5 of demand there is roughly 3.5 pkt/s of slack — about a byte
and a half. The header cannot grow without spending the margin §1 exists
to buy. Any future field must displace an existing one or go in the
telemetry frame (§6).

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
- **Wrap:** `2³² / 60,000 = 71,583 s ≈ 19.9 h` at the current aggregate
  budget. Past the 10-minute recording cap and any realistic session, but
  it shrinks if the aggregate budget rises. Receivers **must** treat
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
| 60,000 samples/s | 1.97 ms |
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

| `mode_id` | Name | N | SPS/ch (target) | Aggregate | Frame | pkt/s |
|---|---|---|---|---|---|---|
| 0 | *reserved / unknown* | — | — | — | — | — |
| 1 | `2ch_30k` | 2 | 30,000 | 60,000 | 4 B | 508.5 |
| 2 | `4ch_15k` | 4 | 15,000 | 60,000 | 8 B | 508.5 |
| 3 | `8ch_7k5` | 8 | 7,500 | 60,000 | 16 B | 508.5 |

**Per-channel rates in this table are targets, not commitments.** §1.3's
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

| Group | Field | Type | Source |
|---|---|---|---|
| Header | `telemetry_version` | `uint8` | constant, `1` |
| Header | `reserved` | `uint8` | must be 0 |
| Anchor | `anchor_sample_index` | `uint32` | MCU |
| Anchor | `anchor_timestamp_s` | `uint32` | MCU RTC |
| Anchor | `anchor_timestamp_sub_s` | `uint16` | MCU RTC |
| FPGA | `fifo0_overflow_samples` | `uint32` | regbank (new, §6.4) |
| FPGA | `fifo0_high_water` | `uint16` | regbank (new, §6.4) |
| MCU | `ring_truncated_samples` | `uint32` | `stream_app.c` |
| MCU | `flow_off_count` | `uint32` | `s_flowoff_total` |
| MCU | `stall_time_ms_total` | `uint32` | new, §6.5 |
| Bridge | `tx_ring_drop_bytes` | `uint32` | `s_drop_bytes` (exists) |
| Bridge | `tx_ring_drop_frames` | `uint32` | `s_drop_frames` (exists) |

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
- **Cadence ~1 Hz.** At 508.5 pkt/s of data traffic one extra frame per
  second is negligible; it does not need to be exact and must not be
  emitted from the hot send path.
- A receiver **must not** infer that "no telemetry frame yet" means "no
  loss yet".

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

- `ring_truncated_samples` — `stream_app.c:1098-1103`, the `flow_off:`
  path, clamps its 59-pair push to whatever ring room remains and
  **silently discards the remainder**. Only reachable when the ring is
  already full, but real and uncounted. `StreamContinuousPollDuringStall`
  (`:826-835`) has the same clamp shape.
- `stall_time_ms_total` — accumulated time with `s_txFlowOff` set. With
  `flow_off_count` this yields both halves of §1.3's stall duty cycle,
  which is the number nobody currently has and which `m` cannot be chosen
  without.

Backpressure elsewhere in the headstage already behaves correctly and
needs no counter: a full MCU ring stops `StreamIngestDuringStall`, which
pushes pressure back onto `fifo0` rather than dropping.

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
   pc-app status line. §6. Retires one of the three causes currently
   conflated in `dropped_packets` on its own, independent of everything
   below. The riskiest part is the bridge connection sequence, which has
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
   modular-comparison requirement on receivers; §3.1.
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
