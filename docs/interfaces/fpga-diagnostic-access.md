# FPGA diagnostic access & the A.1.1 verification ladder — interface spec

**Status: SPEC ONLY, written 2026-08-11. Nothing here is implemented yet.**
Written before code per the plan's working principle 5 ("interface specs
outrank subsystem specs — every expensive bug lived at a boundary").

**Purpose.** Make `PLAN.md` A.1.1 rungs (a)–(d) runnable, repeatable, and
runnable *again* six months from now without hand-editing RTL. The design
constraint set by Manuel 2026-08-11: *"we want to be able to run these tests in
the future by only modifying flags either at the MCU firmware or FPGA RTL."*
This spec goes one step further where it is cheap to — a rung becomes a **script
over a generic register console**, so most future rungs need no firmware edit at
all.

**Lane split, agreed 2026-08-11:**

| Part | Owner |
|---|---|
| §1 — FPGA RTL contract | **Manuel.** This document is the spec; no RTL is written by Claude. |
| §2–§4 — register console (MCU, bridge, pc-app) | Claude |
| §5 — rung procedures | Claude (scripts), Manuel (bench run) |
| §6 — testbench + RHD2164 behavioural model | Claude proposes, Manuel runs QuestaSim |

Companion documents: `docs/interfaces/channel-selection-control-plane.md`
(the SPI0 wire protocol and the 0xFFF1/0xFFF3 control plane this extends),
`PLAN.md` A.1.

---

## 0. Why (a)–(d) cannot run today

Three separate gaps, in the order they bite:

1. **No data path.** `ch_sel` computes `data0_synced`/`data1_synced` from the
   RHD2164s and discards them — `assign dout = {cnt0, cnt0 + 16'd1000}`
   (`components.v:423-425`). Every rung's pass/fail is a number read out of the
   sample stream, and the sample stream is a synthetic ramp. This is A.1.1e,
   already identified in `PLAN.md` as the ladder's gate.
2. **No stable meaning for `ch_a`.** `ch_a[5:0]` is compared against `ch_cnt`,
   which counts the slot *being transmitted*, while the value on MISO answers
   the command sent two slots earlier. The correction is currently a **comment**
   — `ram[RB_CTRL_BASE+4] <= {8'd0,2'd2,6'd3}; // Remember there is a delay of 2
   SPI cycles` (`components.v:623`) — i.e. it is pushed onto whoever writes
   `ch_a`. §1.2 removes it.
3. **No way to drive a rung.** Injecting a command is already possible
   (`reg_write16(48+k, cmd)`, courtesy of A.1.1g) but there is no MCU or pc-app
   surface that exposes it, and `SET_CHANNELS` cannot express what the rungs
   need (§2.1).

§1 closes (1) and (2); §2–§4 close (3).

---

## 1. FPGA RTL contract *(Manuel's lane — spec only)*

> **AS BUILT, 2026-08-11.** Manuel implemented §1.1; §1.2 was tried and
> **deliberately reverted**, and the offset now lives host-side instead. State:
>
> | Item | State |
> |---|---|
> | §1.1 data-source mux + word 229 | **Done.** Ramp moved to `kuntur_fpga.v`, muxed on `data_source_sel`, driven by a new `dout_en_0` output from `ch_sel` (which preserves the old ramp timing exactly). `ch_sel.dout` carries `{ch0, ch1}` latched from `data0_synced`/`data1_synced` — the A.1.1e connection. Word 229 reset default `0` = real. |
> | §1.2 two-counter offset | **Reverted, not needed.** See below. |
> | §1.2a tunable `rsp_delay` | Not built. Still the option if the offset needs sweeping. |
> | §1.3 `CONVERT(k)` at slot `k` | **Withdrawn — the requirement was wrong.** `CONVERT(63)` auto-increments, so slot `k` already converts channel `k`. Leave the table alone. |
> | §1.4 deletions | **Not done** — `rhd2164_sampling_cmd0-3`, `regbank_addr0`, and the `ch_is_16` remnants remain (`dout_en_16` did go). |
>
> **Why §1.2 was dropped, and why that is right.** The `+3` is a *mapping*
> question, not a capacity one — in steady state the RHD pipeline is always
> full, so it needs no slots to live in. With the original 33-slot counter,
> `ch_a = v` observes slot `(v - 3) mod 33`, which is a **bijection over all 33
> slots**: nothing is unreachable, `ch_a = 3` reaches slot 0 and `ch_a = 2`
> reaches the placeholder at slot 32. So the ladder runs with **no RTL change
> at all**, and the offset is two named constants in `pc-app/diagnostics.py`
> (`SLOT_OFFSET`, `FRAME_SLOTS`) applied centrally in `ch_code()`.
>
> An intermediate version extended the frame to 36 slots (`max =
> RB_SAMPLING_MAX+3`, wrapping to `6'd3`). That had a blocking fault — `cnt0`
> never returned to 0, so `ch_is_0_redge` fired only once at boot and
> `fifo_wen` never asserted again, leaving the FIFO permanently empty — and
> even with the wrap corrected to 0 it would have cost ~8.3% of the
> per-channel sample rate (one FIFO entry per frame, 36 slots instead of 33)
> while still leaving `ch_a = slot + 3`. Reverted.
>
> Making `ch_a` name the slot directly (§1.2/§1.2a) remains worth doing, but it
> is a clarity fix, not a correctness one — deferred to Phase B, where T11/T12
> can actually verify it.

### 1.1 Data-source mux — A.1.1e plus the A.1 structural fix

**Requirement.** Extract test-pattern generation out of `ch_sel` into its own
module, and mux at the **top level** behind a named signal, so "am I streaming
real data?" is answerable by reading `kuntur_fpga.v` alone. `ch_sel` emits only
real data. `PLAN.md` A.1 already requires this; A.1.1e is folded into the same
change so `ch_sel` is touched once, not twice.

```
ch_sel        →  {data0_synced, data1_synced}   ─┐
                                                 ├─ mux ─→ fifo_din
test_pattern_gen  →  {cnt, cnt + 1000}          ─┘
                            ▲
                    advances on fifo_wen (same cadence as real samples)
                            ▲
                     data_source_sel  ←  regbank word 229, bits [1:0]
```

**New regbank control word 229** (`RB_CTRL_BASE + 37`), adjacent to
`stream_enable` at 228 because both are stream-plumbing control:

| Bits | Field | Values |
|---|---|---|
| `[1:0]` | `data_source_sel` | `0` = real RHD data (**reset default**), `1` = ramp test pattern, `2`–`3` reserved |
| `[15:2]` | reserved | write 0 |

**The reset default must be `0` (real data), not the test pattern.** This is the
single most important line in this section. A test-pattern default would
reproduce the *exact* failure A.1 exists to fix — a device that streams
convincing synthetic data and reports no error — and it would do so silently
after every FPGA reset or reprogram. Same reasoning that settled
`stream_enable`'s reset default to `1` (control-plane spec §5.3), where an
earlier draft had it backwards.

**Consequence for `kuntur_tb.sv` T5.** Its `ChB - ChA == 1000` pairing invariant
only holds in test-pattern mode. With the default flipped to real data, T5 must
`reg_write16(229, 1)` in its setup. That is a two-line testbench edit and it is
the correct direction: the assertion becomes an explicit statement about
test-pattern mode rather than an accident of `ch_sel` throwing real data away.
`PLAN.md` A.1.1g-tb already flags T5 as needing revisiting when A.1.1e lands.

**Why a runtime regbank word rather than a `` `define ``.** A compile-time flag
would satisfy the letter of "flags in the RTL," but the same mux is what B.6's
`doctor` and B.5's pre-session self-test need in order to push a known pattern
through the real path **on an assembled device that is not going to be
re-synthesised**. One word of regbank buys that; a `` `define `` does not.

### 1.2 Slot↔response alignment — the two-counter reset *(Manuel's design)*

**Requirement.** `ch_cnt` must name the sampling slot whose *answer* is on the
RHD MISO bus at that instant, not the slot being transmitted.

**Mechanism, chosen 2026-08-11 (Manuel):** split `rhd2164_controller`'s single
`cnt0` into two counters that increment together and wrap identically over
`0..RB_SAMPLING_MAX`, differing only in the value they take when the sampling
cycle begins:

| Counter | Start value | Drives |
|---|---|---|
| `cnt_cmd` | **`RHD_RSP_DELAY`** (= 3, see below) | `rb_addr1 = RB_SAMPLING_BASE + cnt_cmd` — which command is transmitted |
| `ch_cnt` | **0** | `ch_sel`'s `ch_is_a`/`ch_is_b`/`ch_is_0` comparators |

The start values are applied at the **config→sampling transition**, not at
`rstb`: `cnt0` is shared with the config phase, which must still walk its table
0→`RB_CONFIG_MAX` with no offset.

Putting the offset here rather than in `ch_sel` is not only cheaper — it is
semantically different in a way that matters. `ch_is_0` drives the frame-sync
latch (`data0_synced`/`data1_synced`), so making `ch_cnt` the *response*
counter aligns frame sync to the frame of data being published. An
`(ch_a + delay) mod 33` comparator inside `ch_sel` would leave frame sync on
the *command* counter, publishing each pair a fixed distance away from where
its own frame boundary is.

Rejected alternative: keeping one counter and comparing
`ch_cnt == (ch_a[5:0] + 2) % 33` inside `ch_sel`. Manuel's version is better —
it costs two reset constants instead of a modulo-33 adder in the comparator
path, and it puts the offset in the one module that already owns frame timing.

**The offset is 3, not 2 — corrected 2026-08-11 after tracing the RX path.**
The RHD's own pipeline is 2 commands, but `ch_sel` does not see the received
word until one slot later still:

- `data_rx_a/b/a1/b1` are **held parallel registers**, not live shift registers
  (`sr_s2p`: `data <= areg` only on `load`, `spi_controllers.v:385-393`).
- `rx_a_load`/`rx_b_load` fire at `csbend1`, near the **end** of the slot in
  which the word was clocked in (`spi_controllers.v:1002-1007`).
- `done` is asserted only in the master's `idle` state, six clocks *after*
  `csbend1`, so `rhd2164_controller` leaves `op1c` and increments its counters
  at `op1d` **after** the load.
- `ch_sel` latches on `ch_is_a_redge`, which fires within the first two clocks
  of the following slot — at which point `data_rx_*` still holds the word
  loaded during the *previous* slot.

Net: one extra slot of pipeline on top of the RHD's two.

**Derivation.** Let slot `i` be one `op1a..op1d` iteration, `c_i` the value of
`cnt_cmd` and `r_i` the value of `ch_cnt` during it. The word `ch_sel` latches
during slot `i` was loaded at `csbend1` of slot `i-1`, and is the RHD's answer
to the command sent in slot `i-3`:

```
latched during slot i   =  answer to ram[48 + c_(i-3)]
want it to equal        =  answer to ram[48 + r_i]
counters run in lockstep:  c_i = c_0 + i,  r_i = r_0 + i   (mod 33)
⇒  r_0 + i = c_0 + i - 3   ⇒   c_0 - r_0 = 3
```

So `cnt_cmd` starts at **3** while `ch_cnt` starts at 0, and then
**`ch_a[5:0] = k` observes sampling slot `k`'s answer for every `k` in `0..32`,
with no correction anywhere.**

**⚠ This number is derived by reading the RTL, not measured.** It disagrees
with `components.v:623`'s existing *"Remember there is a delay of 2 SPI
cycles"* comment, and the `ch_a = {2'd2, 6'd3}` / `ch_b = {2'd2, 6'd2}`
defaults sitting next to it are consistent with the author having reasoned in
terms of 2 (they would name channels 1 and 0 under a `+2` rule). Under the
current single-counter RTL those defaults actually observe slots 0 and 32.
Nobody has ever been in a position to notice, because `dout` has always been
the ramp — which is precisely the class of error this ladder exists to find.

**Rung (b) is the measurement that settles it** (§5.2): five distinct letters
in five consecutive slots, so a wrong offset reads out as a rotation and the
rotation distance *is* the correction. With simulation deferred to Phase B, the
bench is the first place this gets validated — see §1.2a for why the offset
should therefore be tunable rather than a synthesised constant.

Two things this buys beyond tidiness:

- The placeholder slot 32's answer lands at `ch_a[5:0] = 32`. `PLAN.md` A.1.1's
  ordering note currently computes this as `(32+2) mod 33 = 1`, i.e.
  `ch_a = {2'b00, 6'd1}` — that stops being true and the note should be updated
  when this lands.
- `components.v:623`'s *"Remember there is a delay of 2 SPI cycles"* comment and
  the `{2'd2, 6'd3}` default it justifies both go away. New suggested reset
  defaults: `ch_a = {8'd0, 2'd0, 6'd0}`, `ch_b = {8'd0, 2'd0, 6'd1}` — chip0
  module A, channels 0 and 1, which is what those words now literally read as.

### 1.2a Make the offset a regbank word, not a synthesised constant

**Recommended, added 2026-08-11.** Since the offset is now uncertain (2 vs 3,
§1.2) and simulation has moved to Phase B, the first evidence either way comes
from a bench run. A wrong constant then costs a re-synthesis and reflash; a
wrong *register* costs one `REG_WRITE16`, and rung (b) can sweep it until the
letters line up.

This turns out to be a **smaller** RTL change than the two-counter version, not
a larger one — it adds no counter and does not touch the counter block at all:

- Keep `cnt0` exactly as it is. During sampling it now *is* the response
  counter, so `assign ch_cnt = (rhd_dtx_sel) ? cnt0 : 0;` is unchanged.
- Derive the command slot by adding the delay, with one conditional wrap:

```verilog
wire [6:0] slot_sum = {1'b0, cnt0} + {1'b0, rsp_delay};
wire [5:0] slot_cmd = (slot_sum > `RB_SAMPLING_MAX)
                    ? (slot_sum - (`RB_SAMPLING_MAX + 1'b1))
                    : slot_sum[5:0];

assign rb_addr1 = (rhd_dtx_sel) ? (`RB_SAMPLING_BASE + slot_cmd)
                                : (`RB_CONFIG_BASE  + cnt0);
```

- `rsp_delay` is a new 6-bit input, from **regbank word 230**
  (`RB_CTRL_BASE + 38`), reset default `6'd3`.

`cnt0 ≤ 32` and `rsp_delay ≤ 32`, so `slot_sum ≤ 64` and a single conditional
subtract covers the wrap. The adder sits in the **address** path, which has a
whole slot to settle, not in `ch_sel`'s comparator path — which was the reason
to avoid a modulo in the first place.

Changing `rsp_delay` mid-stream costs a frame or two of garbage while the
pipeline realigns. Irrelevant on a diagnostic path, and rung (b) discards the
first pairs after every `START_STREAMING` anyway.

**Trade-off against the two-counter version (§1.2).** Two counters is the
cleaner expression of the idea and costs no adder; a word-addressable offset
costs one adder and one regbank word but is measurable on the bench rather than
re-synthesised. Given the offset is not yet confirmed and Phase A has no
simulation to confirm it with, the tunable version is recommended. Once rung (b)
has pinned the number down, the reset default is the real answer and the
tunability is just insurance.

**Known first-frame artefact, accept and document.** For the first two slots of
the first sampling frame after the config phase, MISO still carries answers to
the last two *config* commands (`RHD_READ(6'd63)` dummies). Slots 0 and 1 of
frame 0 are therefore garbage. Mitigation is at the pc-app, not the RTL: discard
the first 2 sample pairs after every `START_STREAMING` (§4.3).

**Frame-boundary case — flagged for simulation, not assertable on the bench.**
`data0_synced`/`data1_synced` latch on `ch_is_0_redge`, so slots 31 and 32 are
latched into `data0`/`data1` immediately before the frame-sync edge that
publishes them. An off-by-one-*frame* error there is invisible to a bench test
using static known values (a letter that is one frame stale is the same letter).
It is only catchable in simulation, against a model whose responses vary per
frame — see §6.3. `PLAN.md`'s "Watch during (d)" note is correct and this is
where it gets discharged.

### 1.3 Sampling-table reset defaults — **NO CHANGE REQUIRED**

**Withdrawn 2026-08-11.** An earlier revision of this section required
`ram[RB_SAMPLING_BASE + k] = RHD_CONVERT(k)` for `k = 0..31`, on the grounds
that slots 2–31 being thirty consecutive `CONVERT(63)` meant thirty conversions
of channel 63. **That was a misreading, and the table is already correct.**

Per the RHD2164 datasheet — and `intan.vh:24`, which says so in the file —
`C = 63` does not mean "channel 63". It means **cycle through successive
amplifier channels**. So the table works like this:

| Slot | Command | Effect |
|---|---|---|
| 0 | `CONVERT(0)` | anchors the chip's internal channel counter at 0 |
| 1 | `CONVERT(1)` | channel 1 |
| 2–31 | `CONVERT(63)` ×30 | walks the counter 2 → 31 |
| 32 | `RHD_READ(63)` | alternate-command placeholder, no conversion |

**Slot `k` therefore already converts channel `k`**, which is exactly what the
withdrawn requirement was trying to produce — by the datasheet's intended
mechanism rather than by 32 explicit command words. It is also *self-correcting*:
the anchor is re-asserted every frame at slot 0, so any disturbance lasts one
frame at most.

Writing explicit `CONVERT(k)` per slot would be functionally equivalent and
marginally more robust (no dependence on the anchor), but it is a gratuitous
change to a deliberate table and would cost a re-synthesis. **Leave it.**

> **Note for whoever reads this table next.** Thirty consecutive `CONVERT(63)`
> looks like a copy-paste bug, and it is the second thing in this design that
> invites a "fix" which would break it (the first being `stream_enable`'s reset
> default). This section exists so the next person does not spend the same
> hour on it. Confirmed by Manuel, 2026-08-11.

### 1.4 Deletions to make in the same change

- **`rhd2164_sampling_cmd0-3`** — module ports, top-level wires, and the `ram`
  assigns at `components.v:486-489`. Dead-end wires; A.1.1g made the sampling
  table itself the command-injection path. Frees words 192–195. This is the
  A.1.4 remnant, per `PLAN.md`. The control-plane spec's register table lists
  them as reserved and must be updated at the same time.
- **`regbank_addr0` / `ram`'s `addr0` port** (`kuntur_fpga.v:127`) — vestigial
  since A.1.1g; the array address is `addr_reg`. Already flagged in `PLAN.md`.
- **`ch_is_16` / `ch_is_16_redge` / `dout_en_16`** in `ch_sel` — the
  half-frame second-channel path, dead since `fifo_wen <= dout_en_0 &
  stream_enable`.

Not required by this spec but in the same neighbourhood: `mode` hardwired
`2'b00` with `mode1_*`/`mode2_*`/`mode3_*` declared and unwired, and the
`serial_lvds_*` debug hijacks (`PLAN.md` T3.3).

### 1.5 What does **not** change

The SPI0 wire protocol (control-plane spec §1) is untouched — no new opcode, no
new transfer shape. Everything in §2 below is built out of `REG_WRITE`/
`REG_READ` exactly as A.1.1g defines them. `ch_a`/`ch_b`'s *encoding* is
unchanged too (`[7:6]` source, `[5:0]` index); only the **meaning** of `[5:0]`
is pinned down — it was always a slot index, it just now equals the channel
index by construction.

---

## 2. Register console — 0xFFF1 command extensions

**New commands**, alongside `0x01 SET_CHANNELS` / `0x02 STOP_STREAMING` /
`0x03 START_STREAMING` (control-plane spec §2, §5.1):

| `cmd` | Name | Payload | Length | Action |
|---|---|---|---|---|
| `0x04` | `REG_WRITE16` | `addr`(1), `val_lo`(1), `val_hi`(1) | 4 | 3-transfer tagged write of `{val_hi, val_lo}` to RAM word `addr`, then an automatic `REG_READ` of the same word; the readback value is what the response carries |
| `0x05` | `REG_READ16` | `addr`(1) | 2 | Self-addressing `REG_READ` of RAM word `addr` |

**0xFFF3 responses**, extending the type-prefixed payload (control-plane spec
§5.6):

| `type` | Name | Remaining payload | Length |
|---|---|---|---|
| `0x04` | `REG_WRITE16` ack | `addr`, `val_lo`, `val_hi` — **the value read back**, not the value sent | 4 bytes |
| `0x05` | `REG_READ16` response | `addr`, `val_lo`, `val_hi` | 4 bytes |

`STREAM_RESPONSE_PAYLOAD_SIZE` (`stream.h`) grows **3 → 4**.

**The write ack carries the readback, deliberately.** Same principle as
`FPGA_SPI_SetStreamEnable()`'s existing write-then-read (control-plane §5.6):
`success` must mean "the regbank holds this value," never "the write call
returned." It also gives the pc-app script a free per-write verification with no
extra round trip, which matters when a rung rewrites 32 table words (§5.4).
`addr` is echoed so a response can be matched to its request without the pc-app
tracking an outstanding-command slot.

**Preconditions — identical to `SET_CHANNELS`, reusing the existing machinery:**

- Rejected and logged unless streaming is currently **stopped**
  (control-plane §5.1). Register traffic must not interleave with an
  in-progress `FPGA_SPI_ReadSamples()`, and the reason that rule exists has not
  changed.
- Rejected while `s_command_busy` is set (control-plane §5.5).
- Executed from `StreamSendTask`'s stopped-branch as a deferred pending
  command, never inline in the GATT event handler (control-plane §5.4).

No new hazard is introduced: these are the same SPI0 primitives on the same
deferred path as the three existing commands.

### 2.1 Why `SET_CHANNELS` is not enough

Three reasons, each independently sufficient:

- **Slot 32 is unreachable.** `SET_CHANNELS` takes friendly indices 0–127 and
  maps them with `raw = ((n & 0x60) << 1) | (n & 0x1F)` (control-plane §1a), so
  `raw[5:0] ≤ 31` for every input. The alternate-command placeholder slot — the
  slot every one of rungs (a)–(c) reads its answer from — cannot be named. The
  console writes word 196/197 **raw**, bypassing the friendly mapping.
- **No command injection.** Nothing above SPI0 can write a sampling-table word.
- **No general readout.** Rung failures are diagnosed by reading regbank state
  back; only `ch_a`, `ch_b` and `stream_enable` are readable today.

`SET_CHANNELS` stays exactly as it is — it is the *operator* path, with range
validation and friendly indices. The console is the *diagnostic* path, raw and
unvalidated. Keeping them separate means the diagnostic path cannot loosen the
operator path's validation.

### 2.2 Safety

Writes are unrestricted, matching the RTL (`PLAN.md`: *"no RTL write-protection
on any word… partial protection would give a false sense of safety"*). The
console can therefore corrupt the RHD config table and leave the sampling cycle
issuing nonsense until the FPGA is reset. Mitigations, all at the pc-app:

- The console lives behind an explicitly-enabled **Diagnostics** panel, off by
  default (§4.2).
- Every rung script ends with a **restore** step returning the words it touched
  to their reset defaults (§5.5).
- An FPGA reset restores every default unconditionally; this is documented in
  the panel as the recovery action.

Nothing here is protected in firmware. A diagnostic console that lies about what
it can reach is worse than one that is honest and gated.

---

## 3. MCU implementation

### 3.1 New `fpga_spi` helpers

`FPGA_SPI_SetChannels` / `ReadChannels` / `SetStreamEnable` / `ReadStreamEnable`
are already four hand-rolled instances of the same two sequences. Factor the
sequences out and make the existing four thin wrappers — this is a
simplification of existing code, not new machinery:

```c
/* 3-transfer tagged write sequence (control-plane spec §1):
 *   REG_WRITE(tag=1, addr) → REG_WRITE(tag=2, val>>8) → REG_WRITE(tag=3, val)
 * Leaves the FSM at its decode state. */
void     FPGA_SPI_RegWrite16(uint8_t addr, uint16_t value);

/* 2 transfers: REG_READ(tag=1, addr) then NOP to clock the value out.
 * REG_READ is self-addressing; no preceding write sequence. */
uint16_t FPGA_SPI_RegRead16(uint8_t addr);

/* Sampling-slot command injection — ram[RB_SAMPLING_BASE + slot].
 * slot 0..32; values above RB_SAMPLING_MAX are rejected (no write issued). */
void     FPGA_SPI_SetSamplingSlot(uint8_t slot, uint16_t cmd);
```

Calling-context rules are inherited unchanged: never from an ISR, never
interleaved with `FPGA_SPI_ReadSamples()`, structurally guaranteed by running
only on the stopped-branch.

### 3.2 Command handling

`STREAM_APP_OnCommandWrite()` gains `0x04`/`0x05` cases that validate length,
stash `addr`/`value` into new `s_pending_reg_*` statics, and set
`s_reg_access_pending` — the same validate-stash-defer shape the existing three
commands use. `StreamSendTask`'s stopped-branch gains one more pending check,
ordered after `s_set_channels_pending`, guarded by `s_command_busy` for its
duration.

`STREAM_NotifyRegAccess(type, addr, value, conn_handle)` in `stream.c`, mirroring
`STREAM_NotifyStreamingAck()`.

### 3.3 Constants

RAM word addresses (`RB_SAMPLING_BASE = 48`, `ch_a = 196`, `ch_b = 197`,
`stream_enable = 228`, `data_source_sel = 229`) currently exist as literals in
both `intan.vh` and `fpga_spi.c`. Adding a fifth is the point at which they
should be a named block in `fpga_spi.h` with a comment pointing at `intan.vh` as
the authority. Genuine single-sourcing across the Verilog/C boundary is a B.2
problem, not solved here.

---

## 4. Bridge and pc-app

### 4.1 Bridge

**No changes.** The `0xCC 0x33` relay is transparent and the `0xEE 0x11`
response relay forwards the payload verbatim regardless of length
(control-plane §3, §4.4, §5.6). A 4-byte response needs nothing new.

### 4.2 pc-app — Diagnostics panel

`SerialReader` gains `send_reg_write16(addr, value)`, `send_reg_read16(addr)`,
and a `reg_access_response(type: int, addr: int, value: int)` signal, dispatched
from the existing 0xFFF3 type-byte `switch`.

A **Diagnostics** panel, collapsed and disabled by default:

- raw read/write of any of the 256 words, showing the readback;
- a rung runner: pick (a)–(d), press Run, get a numeric pass/fail table;
- the restore action from §5.5.

### 4.3 Pacing, retries, and the first-frame discard

Three things the rung scripts must do, all consequences of documented existing
behaviour rather than new problems:

- **Pace at `COMMAND_GAP_MS`.** Rewriting a 32-entry table is 32 back-to-back
  commands, which is precisely the pattern that provokes the bridge USART1
  overrun documented in control-plane §"Resolved 2026-08-06". The ORE fix made
  that self-healing rather than fatal, but a command can still be lost.
- **Retry on timeout.** Unlike `SET_CHANNELS`, which deliberately has no retry
  because an operator is watching, a 32-word scripted rewrite has nobody
  watching each step. Each console command is ack-gated by construction (§2), so
  retry-on-timeout is a small loop: resend up to 3×, then fail the rung with the
  failing address named. A silently half-written sampling table would produce a
  rung failure that looks like an RTL fault, which is the worst possible
  outcome.
- **Discard the first 2 sample pairs after each `START_STREAMING`** (§1.2's
  first-frame artefact).

---

## 5. The ladder — rungs (a)–(d) as register scripts

Every rung is the same loop:

```
STOP_STREAMING
  REG_WRITE16 …            (inject commands, select observation points)
START_STREAMING
  observe N sample pairs, discard the first 2, take the mode of the rest
STOP_STREAMING             (next configuration, or restore)
```

Taking the **mode** rather than a single sample makes each measurement immune to
a lost packet or a single-frame artefact; the values under test are static, so
any spread at all is itself a finding and should be reported alongside the mode.

Common preamble for every rung: `REG_WRITE16(229, 0x0000)` — assert real data.
The reset default is already 0, so this is a re-assertion, not a change; it also
proves the word is reachable before anything depends on it.

Notation: `SRC` = `ch_a[7:6]` = `0` chip0-A, `1` chip0-B, `2` chip1-A,
`3` chip1-B. `SLOT(k)` = `ch_a[5:0] = k`. Sampling slot `k` is RAM word `48+k`.
An RHD `READ(R)` returns `{8'h00, D}`, so all expected values below are
`0x00xx`.

### 5.1 Rung (a) — link integrity & DDR demux

Register 59 is Intan's purpose-built MISO A/B marker: **53 (0x35) on MISO A,
58 (0x3A) on MISO B**. Asymmetric by design, so an A/B swap fails outright.

Inject into the placeholder slot, which costs no channel:
`REG_WRITE16(48+32, RHD_READ(59))` = `REG_WRITE16(80, 0xFB00)`.

| Config | `ch_a` | `ch_b` | Expect ch0 | Expect ch1 |
|---|---|---|---|---|
| a1 | `{0, 32}` = `0x20` | `{1, 32}` = `0x60` | `0x0035` (53) | `0x003A` (58) |
| a2 | `{2, 32}` = `0xA0` | `{3, 32}` = `0xE0` | `0x0035` (53) | `0x003A` (58) |

Written as `REG_WRITE16(196, 0x0020)` / `REG_WRITE16(197, 0x0060)`, etc.

**Diagnosis table** — this is the rung's real value:

| Observed | Meaning |
|---|---|
| 53 / 58 both configs | Pass. MISO sampling timing, DDR A/B split, and all four `ch_sel` source mappings correct |
| 58 / 53 | A/B demux inverted |
| 53 / 53 | MISO B never demuxed — both edges sampled as A |
| a1 passes, a2 fails | `spi1_miso1` (chip 1) wiring or the second chip |
| `0x0000`, `0xFFFF`, or unstable | MISO sample point wrong, or chip not responding |
| `0x8000` on both | Empty-FIFO sentinel — streaming never started; not an RHD result at all |

### 5.2 Rung (b) — pipeline offset

`INTAN` in registers 40–44 — five distinct values in sequence, so a wrong
offset shows as rotated letters rather than a single ambiguous mismatch.

Inject into slots 28–32 (channels 0–27 keep streaming normally, which is a
useful sanity anchor):

| Slot | RAM word | Command | Expect |
|---|---|---|---|
| 28 | 76 | `RHD_READ(40)` = `0xE800` | `0x0049` `I` |
| 29 | 77 | `RHD_READ(41)` = `0xE900` | `0x004E` `N` |
| 30 | 78 | `RHD_READ(42)` = `0xEA00` | `0x0054` `T` |
| 31 | 79 | `RHD_READ(43)` = `0xEB00` | `0x0041` `A` |
| 32 | 80 | `RHD_READ(44)` = `0xEC00` | `0x004E` `N` |

Three configurations on `SRC = 0`: `(28,29)`, `(30,31)`, `(32,28)` — the last
re-reads slot 28 as a repeat check.

**Pass:** exactly `I N T A N` in slot order. This is the numeric proof that
§1.2's two-counter offset is right. **Off by one slot** in either direction
pushes at least one observation outside 28–32, where it reads a `CONVERT`
result — a 16-bit ADC code, unmistakably not `0x00xx`. Loud by construction.

### 5.3 Rung (c) — chip identity

| Slot | RAM word | Command | Expect | Meaning |
|---|---|---|---|---|
| 30 | 78 | `RHD_READ(63)` = `0xFF00` | `0x0004` | Chip ID, RHD2164 = 4 |
| 31 | 79 | `RHD_READ(62)` = `0xFE00` | `0x0040` | Number of amplifiers = 64 |
| 32 | 80 | `RHD_READ(61)` = `0xFD00` | `0x0001` | Unipolar amplifiers = 1 |

Three configurations, each `ch_a = {0, slot}` (chip0 module A) and
`ch_b = {2, slot}` (chip1 module A) — both chips per configuration.

**⚠ Discrepancy to resolve before this rung is trusted.** `intan.vh:188`
defines `` `RHD_2164_UNIBIAMP 8'd0 ``, while `PLAN.md` A.1.1's known-value table
and the RHD2164 datasheet both say register 61 reads **1**. The constant is
currently unused anywhere in the RTL (grep confirms: defined, never referenced),
so it has never been wrong in a way that mattered — but it is about to be used
by the behavioural model in §6, at which point a sim that passes would prove the
hardware wrong. Manuel to confirm against the datasheet and fix the constant.

This rung is also the FPGA-side half of B.6's `doctor`.

### 5.4 Rung (d) — slot→channel alignment

**The table-correctness half is gone.** An earlier revision split this rung
into (d1) "confirm `CONVERT(k)` at slot `k`" and (d2) the frame-boundary
markers. §1.3 withdrew (d1): the table already maps slot `k` to channel `k` via
the `CONVERT(63)` auto-increment, so there is nothing to confirm that a readback
of the reset defaults would not trivially pass. Table integrity is covered
anyway — every rung's restore rewrites the words it touched, and every
`REG_WRITE16` ack carries the value read back out of the regbank (§2), so a
corrupted table surfaces as a failed restore rather than needing its own rung.

What remains is the frame-boundary check, and it is **bench-testable only in
part.** Place
distinct markers across the wrap and confirm each appears at its own slot:

| Slot | Command | Expect |
|---|---|---|
| 31 | `RHD_READ(40)` | `0x0049` `I` |
| 32 | `RHD_READ(41)` | `0x004E` `N` |
| 0 | `RHD_READ(42)` | `0x0054` `T` |
| 1 | `RHD_READ(43)` | `0x0041` `A` |

Configurations `(31,32)` and `(0,1)`, `SRC = 0`.

**Side effect, harmless but worth knowing.** Slots 0 and 1 are the
`CONVERT(63)` auto-increment anchors (§1.3), so overwriting them with markers
scrambles which channel each `CONVERT` slot samples for the duration of this
rung. The markers themselves are `READ`s and are unaffected. The anchor is
restored with the table, and re-asserted every frame thereafter, so the
disturbance does not outlive the rung.

**What this cannot prove, stated plainly.** A whole-frame skew — slot 32's
answer being published one frame late relative to slot 0's — is invisible here,
because a static letter that is one frame stale is the same letter. Only a model
whose responses vary per frame can catch it, which makes this a **simulation
obligation** (§6.3) — and simulation is Phase B (§6). So in Phase A this is
**not verified at all**, and rung (d) must be reported as *"slot alignment
confirmed; frame-boundary phase not yet verified."* `PLAN.md`'s "Watch during
(d)" note stays open until Phase B discharges it.

### 5.5 Restore

Every rung ends by restoring what it touched:

```
REG_WRITE16(48+k, RHD_CONVERT(k))    for every k in 0..31 that was overwritten
REG_WRITE16(80,   RHD_READ(63))      slot 32 placeholder default
REG_WRITE16(196,  0x0000)            ch_a  → chip0-A ch0
REG_WRITE16(197,  0x0001)            ch_b  → chip0-A ch1
REG_WRITE16(229,  0x0000)            real data
```

An FPGA reset does the same thing unconditionally and is the documented recovery
if a restore itself fails.

### 5.6 Rungs (e) and (f)

Out of scope here. (e) *is* §1.1 — once the mux lands there is no separate rung
to run. (f) — VDD sense on channel 48 — needs `` `RHD_VDD_SENSE_ENABLE ``
(`intan.vh:87`, currently `1'b0`) and is the first rung whose expected value is
analog (≈44,100 at 3.3 V); it fits this same script shape and should be added
once (a)–(d) pass.

---

## 6. Testbench obligations — **DEFERRED TO PHASE B (decided 2026-08-11)**

Phase A runs rungs (a)–(d) on the bench only. Everything in this section is
Phase B work. Three consequences, recorded so they are not rediscovered as
surprises:

1. **Rung (d2)'s frame-boundary phase is unverified in Phase A.** §5.4 already
   says it is not bench-testable; with simulation deferred, it is not tested at
   all until Phase B. Phase A's rung (d) result means *"slot alignment
   confirmed; frame-boundary phase not yet verified."* Not "passed."
2. **The response-delay constant is settled by rung (b) on the bench, not by
   simulation** — which is the argument for §1.2a's tunable `rsp_delay`.
3. **`kuntur_tb.sv` goes stale the moment the A.1.1e bitstream exists.** T5's
   `ChB - ChA == 1000` invariant holds only in test-pattern mode, and word 229
   defaults to real data (§1.1). The two-line `reg_write16(229, 1)` fix is
   known; it just does not get made in Phase A. Anyone running the existing
   testbench against post-A.1.1e RTL should expect T5 to fail for this reason
   and not chase it as a regression.

The content below stands as written; only its phase changed.

### 6.1 The existing RHD model cannot support any of this

`rhd2164_model` (`kuntur_tb.sv:403-488`) drives MISO from two canned 4-word
arrays (`0xe7e6`/`0xe7e7`/… and `0x8181`/…) cycled by a counter. It does not
decode MOSI, has no register file, and has no response pipeline. **Nothing in
(a)–(d) is simulatable against it** — every rung's expected value is a
command-dependent response.

### 6.2 Required: a behavioural RHD2164 model

New `rhd2164_bfm`, replacing `rhd2164_model`:

- decode MOSI as `CONVERT(C)` / `CALIBRATE` / `CLEAR` / `WRITE(R,D)` /
  `READ(R)` per `intan.vh`'s encoding;
- a 64-entry register file, ROM entries preloaded from `intan.vh`'s own
  constants (`RHD_2164_CHIPID`, `RHD_2164_NUMAMP`, `RHD_2164_UNIBIAMP`,
  `RHD_REG40_VAL`..`RHD_REG44_VAL`, `RHD_2164_MISOA_MARKER`/`MISOB_MARKER`) —
  using the same constants the RTL uses means a rung that passes in sim is
  checking the map, not a second hand-typed copy of it;
- **a 2-command response pipeline** — the single most important property, since
  it is what §1.2 exists to compensate for;
- DDR MISO A/B output with **different** values per half, so an A/B swap is
  detectable — reg 59's asymmetric markers are the canonical case;
- `CONVERT(C)` returning a **per-channel deterministic function of `C`**
  (e.g. `0x1000 + C`) so slot→channel alignment is checkable numerically;
- two instances, chip 0 and chip 1, distinguishable.

### 6.3 Required assertions

| ID | Checks | Rung |
|---|---|---|
| T8 | Reg 59 → 53 on A, 58 on B, all four `ch_sel` sources | (a) |
| T9 | Regs 40–44 in slots 28–32 → `INTAN` at `ch_cnt` 28–32 | (b) |
| T10 | Regs 63/62/61 → 4/64/1, both chips | (c) |
| T11 | `CONVERT(k)` at slot `k` → `0x1000+k` observed at `ch_a[5:0]=k`, swept over all 32 | (d1) |
| T12 | **Frame-boundary phase.** `CONVERT` responses carry a frame counter in the high bits; assert slots 31, 32, 0 and 1 all report the **same** frame index in one published sample pair | (d2) |
| T13 | `data_source_sel` — word 229 = 0 streams model values, = 1 streams the ramp, reset default is 0 | §1.1 |
| T14 | Slot 32 → `ram[80]` → MOSI, every frame | A.1.4 remnant |

T12 is the one that cannot be obtained on the bench and is the reason the model
in §6.2 must vary its responses per frame.

Existing T5 needs the two-line `reg_write16(229, 1)` edit from §1.1.

*Simulator note, unchanged:* this design does not run under iverilog (time stops
at t = 60 ns, suspected `rhd2164_controller`'s hand-written sensitivity list,
`components.v:879`). Claude proposes the testbench, Manuel runs QuestaSim.
`PLAN.md` B.1 tracks this as a contributability/CI blocker.

---

## 7. Open issues raised by this spec

- **Reg 61 / `` `RHD_2164_UNIBIAMP `` says 0, plan and datasheet say 1** (§5.3).
  Blocks trusting rung (c) and the §6.2 model. Manuel to confirm.
- **`0x8000` is both the empty-FIFO sentinel and a legal sample.** The sentinel
  (`components.v:792`) was unambiguous while `dout` was a ramp. With `TWOSCMP =
  1` (`intan.vh:106`) a real ADC result of `0x8000` is the full negative rail —
  a genuine value. So "underrun" and "railed input" become indistinguishable the
  moment A.1.1e lands, and the pc-app's underrun statistics start counting
  saturated samples. Not a blocker for (a)–(d), whose expected values are all
  `0x00xx`, but it lands with A.1.1e and should be tracked in `PLAN.md`. The
  cheap fix is a sentinel the ADC cannot produce, which needs a wider FIFO word
  or a status bit — i.e. it is not free, which is why it wants recording rather
  than an offhand decision here.
- **Regbank word-address constants are duplicated** across `intan.vh` and
  `fpga_spi.c` and now this spec (§3.3). B.2's problem; noted so it is not
  rediscovered.
- **`ch_a[5:0]` can name slots 33–63**, which do not exist (`RB_SAMPLING_MAX =
  32`). `ch_is_a` simply never matches and `data0` holds its last value —
  silently stale, not obviously wrong. Worth a defined behaviour eventually;
  out of scope here.

---

## Decisions recorded 2026-08-11

- **Lane split**: Manuel writes all §1 RTL; Claude writes this spec, the
  MCU/bridge/pc-app console, the rung scripts, and the testbench proposal.
- **Rung driver**: a generic register console over the existing 0xFFF1/0xFFF3
  control plane, not an MCU compile-time flag. Chosen over a
  `KUNTUR_DIAG_RUNG` build flag because it makes future rungs scripts rather
  than reflashes — stronger than the "flags only" requirement that prompted it.
- **Pipeline +2 offset**: in the RTL, via two counters with different start
  values (`cnt_cmd` = 2, `ch_cnt` = 0) — Manuel's variant, chosen over a
  `(ch_a + 2) mod 33` comparator in `ch_sel`. `ch_a[5:0]` then names the
  sampling slot whose answer is observed, with no correction anywhere.
- **`data_source_sel` reset default = real data**, test pattern opt-in only.
  A test-pattern default would silently reproduce the A.1 bug after every FPGA
  reset.
- **Test-pattern mux at the top level**, in its own module, not inside
  `ch_sel` — so the answer to "am I streaming real data?" is in
  `kuntur_fpga.v`.
