# Channel-selection control plane — interface spec

**Status: REOPENED 2026-08-11.** The FPGA side (section 1) is done and
simulation-verified; the **MCU helpers are being rewritten** against the
A.1.1g SPI0 protocol, and the 2026-08-06 hardware verification does not carry
across that change. See "Status" at the end of this document for the per-hop
state and what must be re-run on the bench. Sections 1, 1a and 4.1 were revised
2026-08-11 and describe the *intended* protocol; sections 2–3 and 4.2–5 are
unchanged as-built.

**Previous status:** implemented and hardware-verified 2026-08-06 (A.2 complete).
Originally written before any code, per the plan's working principle 5
("interface specs outrank subsystem specs — every expensive bug lived at a
boundary"). Sections 4 and 5 were added during implementation as the design
changed under bench evidence; they describe the as-built behaviour. This is a
Phase-A-scoped spec: enough to implement and review against, not the full
Phase B apparatus (permanent requirement IDs, CI traceability) — that
formalization is B.2's job, applied across all interfaces at once.

Bring-up narrative and the bugs found along the way: `log/2026-08-06.md`.
Remaining accepted limitations: `PLAN.md` A.2.

**Purpose:** let the pc-app select which 2 of 128 RHD2164 channels are
streamed, without a hardcoded pair. Full path:

```
pc-app  --(UART, new command frame)-->  WB09KE bridge
        --(BLE GATT write, 0xFFF1)-->   Kuntur MCU
        --(SPI0 register write)-->      Kuntur FPGA regbank (ch_a, ch_b)
```

This spec covers all three hops. Each hop is independently versioned/framed so
one can change without the others (see "Compatibility" per section).

---

## 1. FPGA register protocol (SPI0, MCU ↔ FPGA)

**Where implemented:** MCU side in `fpga_spi.c`; FPGA side in
`main_controller` and `ram` (`components.v`).
**Revised 2026-08-08 (A.1.1g), corrected 2026-08-10, verified in simulation
2026-08-11.** The addressing scheme below supersedes the 2026-08-06 version, in
which `addr` was a direct 6-bit offset into a 64-word window
(`{2'b10, addr}` = words 128–191). That window could reach neither the RHD
command tables nor a full 16-bit value, so it was replaced.

**Verification status:** every claim in this section is exercised by
`kuntur_tb.sv` (QuestaSim, 27/27 checks passing 2026-08-11) — the 16-bit write
path including the staged high byte, the self-addressing read, read settling
across back-to-back and post-write reads, all three write-tag abort paths, the
`FIFO_POP` pair check, and that a `NOP` never swallows the following transfer.
This is *simulation*; the MCU-side implementation and the on-hardware
round-trip are still pending.

**Wire format:** 16-bit word, MSB first, SPI mode 0:

| Bits | Field | Meaning |
|---|---|---|
| `[15:14]` | `opcode` | See table below |
| `[13:8]` | `tag` | **Sequence tag.** `1/2/3` on `REG_WRITE`; **`1` on `REG_READ`**; ignored on `FIFO_POP` and `NOP` |
| `[7:0]` | `data` | Payload byte — **on tag 1 this byte is the RAM address** |

**Tag 1 uniformly means "load `addr_reg` from the data byte"**, on both
`REG_WRITE` and `REG_READ`. One idiom, not two. (Field renamed from `addr` to
`tag` 2026-08-11: it never carried an address, and calling it `addr` while the
*address* travelled in `data` was actively misleading.)

**Opcodes:**

| `opcode` | Name | Action |
|---|---|---|
| `00` | `FIFO_POP` | Pop next sample pair. **2 transfers** — ChA then ChB. The second must also be `FIFO_POP`, so a broken pair aborts rather than half-consuming a FIFO entry |
| `01` | `REG_WRITE` | One step of a **3-transfer** tagged write sequence, see below |
| `10` | `REG_READ` | **1 transfer, self-addressing.** Carries tag 1 and its own 8-bit address in `data`; loads `addr_reg` exactly as `REG_WRITE` transfer 1 does. The value appears on the *next* transfer's MISO (one-transfer-deep pipeline). Does **not** auto-increment |
| `11` | `NOP` | **1 transfer.** No side effect |

Multi-transfer structure exists only where something forces it: `REG_WRITE`
needs three because address + 16-bit data does not fit one word, and `FIFO_POP`
needs two because ChA/ChB is a real pair. `REG_READ` and `NOP` are single
transfers.

**Invariant:** every transfer either starts a new command or is an identified
part of a sequence — **no transfer is ever silently consumed.** All abort paths
(a mismatched write tag, or a `FIFO_POP` whose partner is not a `POP`) land on
`op_nop0`, one clock back to the decoder, so an abort costs exactly the
offending transfer. This makes `NOP` usable as the **resync primitive**: send
one and the FSM is at a known state, always. An earlier revision had `NOP` and
`REG_READ` as mandatory 2-transfer pairs, which meant a lone `NOP` swallowed the
transfer after it — fixed 2026-08-08.

**Indirect register access.** A full 16-bit write needs an 8-bit address and
16-bit data; `2 + 8 + 16 = 26` bits does not fit a 16-bit transfer, so
indirection is forced rather than chosen. A write is three `REG_WRITE`
transfers, tracked by the `main_controller` FSM, each carrying a redundant
sequence tag in `addr`:

| Transfer | `tag` | Effect |
|---|---|---|
| 1 | 1 | `addr_reg <= data` |
| 2 | 2 | `staged_h <= data` |
| 3 | 3 | `ram[addr_reg] <= {staged_h, data}` |

A mismatched tag or a non-`REG_WRITE` opcode mid-sequence aborts to `op_nop0`,
then one clock back to the decoder.

**Reading is a single transfer.** `REG_READ` carries tag 1 and its own address,
loading `addr_reg` itself; the value lands on the following transfer. It does
**not** need a preceding write sequence.

> **Corrected 2026-08-10.** As first built, `REG_READ` ignored its address field
> and returned `ram[addr_reg]` from whatever the last *write* had left there —
> `regbank_port_en` was asserted only on the write branch of `op_decode1`, so
> the address register was never loaded on a read path. A word could therefore
> only be read by first writing it. Found by Manuel, fixed the same session.
> Any description of `REG_READ` requiring a preceding address write is stale.

`addr_reg` and `staged_h` are dedicated registers, not RAM words — a commit
writes the target word and updates state on the same edge, which a
single-write-port array cannot do if the pointer lives in it.

**Why positional with a tag.** SPI0 is already positional — `FIFO_POP` has
always been two transfers, ChA then ChB — so a sequenced write keeps one idiom
across the interface. The tag is what makes a sequence self-describing on a
logic analyzer and turns a transfer lost on the wire into a detected abort
rather than the FSM silently absorbing the next unrelated transfer as the
missing one.

**Consequence:** all 256 RAM words are equally reachable, so `ch_a`, `ch_b` and
`stream_enable` are no longer at privileged offsets — they are ordinary words
written the ordinary way. `ram`'s `addr0` port and
`regbank_addr0 = {2'b11, spi0_drx[13:8]}` are vestigial and slated for removal.

**Breaking change, landed together with the RTL:** `fpga_spi.h`'s dummy TX
word — sent on every sample-pop transfer — was `0xA5A5U`, whose top bits are
`10` by accident; it was never meant to carry opcode meaning. Once `10` meant
`REG_READ`, every streaming transfer would have been misread as a register
read. `FPGA_STREAM_CMD` is now `0x2525U` (top bits `00`). Both halves shipped
in the same change, as required.

**Known register addresses.** These are now RAM word addresses loaded into
`addr_reg` by transfer 1 of a write sequence, not `addr`-field offsets. The map
is defined in `intan.vh` (`RB_CONFIG_BASE`/`RB_SAMPLING_BASE`/`RB_CTRL_BASE`);
`RB_CTRL_BASE` is a layout convention, no longer a decode boundary.

| RAM word | Signal | Notes |
|---|---|---|
| 196 | `ch_a` | 8-bit: `[7:6]` selects one of 4 sample sources (`data_a0`/`data_b0`/`data_a1`/`data_b1`), `[5:0]` selects channel index within that source (`components.v:328-337`). Raw FPGA code — see section 1a for the friendly-index mapping. |
| 197 | `ch_b` | Same encoding as `ch_a`. |
| 228 | `stream_enable` | Bit 0 gates `fifo_wen` inside `ch_sel` (`fifo_wen <= dout_en_0 & stream_enable`), i.e. stops the FPGA ingesting samples at the source. **Reset default `1`** (streaming enabled) — a `0` default would silently kill streaming after every FPGA reset/reprogram until the MCU enabled it. Control words 198–227 are reserved for a future reduced-rate multi-channel mode, hence the gap. Added 2026-08-06, see section 5.3. |
| 192–195 | `rhd2164_sampling_cmd0-3` | Computed by `ram` (`components.v:486-489`, `RB_CTRL_BASE + 0..3`) and wired to the `kuntur_fpga.v` top level, but **not consumed by anything downstream today** — dead-end wires. Confirmed 2026-08-05: reserved as runtime RHD2164 command-injection slots — likely home for the command word(s) fed into the sampling cycle's placeholder state (section 1a), primary use case A.3's impedance-check DAC control (`RHD_ZCHECK_DAC/SEL/EN`). Reserving the address space now avoids a protocol version bump later; wiring tracked as A.1.4 in `PLAN.md`. **Address corrected 2026-08-11** — this row previously read `128-131`, which predates the A.1.1g memory-map rearrangement and was never true of the current RTL. |

Sampling-table words **48–95** and config-table words **0–47** are equally
reachable by the same mechanism. Writing a full 16-bit RHD command word into a
sampling slot is the motivating use case for the 16-bit write path, and is what
the A.1.1g-tb testbench exercises (T2).

### 1a. Channel encoding — friendly index ↔ raw FPGA code

Confirmed against the Intan RHD2164 datasheet (p.9): each chip is two
32-channel modules, module A = channels 0–31, module B = 32–63, matching
`ch_sel`'s 4-way mux (`data_a0`/`data_b0`/`data_a1`/`data_b1` = chip0-A,
chip0-B, chip1-A, chip1-B) and `rhd2164_controller`'s sampling counter, which
cycles the per-module channel index 0–31 (`components.v:855,891`). 4×32 = 128,
matching the plan's "2 channels of 128 available."

**Single source of truth: implement this once in the Kuntur MCU firmware**
(one function, e.g. `channel_to_raw()`), so BLE/pc-app only ever see friendly
indices 0–127, never raw FPGA codes:

```
raw_code = ((n & 0x60) << 1) | (n & 0x1F)     // n = friendly channel, 0-127
```

i.e. insert a zero bit between `n`'s bit 4 and bit 5. Every value 0–127 maps
to a real, distinct amplifier channel — no invalid raw codes are reachable
this way, which is also why validation in section 2 is just a range check.

**Confirmed 2026-08-05:** the sampling counter's max is 32 (33 states,
`components.v:855`), one more than the 32 real per-module channels — the 33rd
state is a deliberate placeholder for an alternate RHD2164 command instead of
a channel conversion (e.g. chip-ID or temperature-sensor read). The datasheet
recommends reserving 3 such slots; this design reduces that to 1. Doesn't
affect the formula above — channel indices only ever use 0–31. Not yet wired
to a consumer; tracked as an A.1 follow-up in `PLAN.md` (likely consumer:
`rhd2164_sampling_cmd0-3` below).

**ChA/ChB pairing invariant — ELIMINATED. Confirmed in simulation
2026-08-11.** Historically `main_controller` toggled the ChA/ChB phase on
*every* SPI0 transfer regardless of opcode (`mcu_dtx_sel`/`mcu_dtx_en` were
driven unconditionally), so any odd number of transfers issued outside
`FPGA_SPI_ReadSamples()` shifted the phase and silently swapped ch0/ch1 in
every subsequent sample read — the same class of bug as the historical "32-bit
FIFO channel swap." It forced two rules: register writes had to be issued in
even-numbered batches, and `FPGA_SPI_Init()` had to prime the phase with a
single transfer at boot.

The A.1.1g FSM rewrite drives the phase **explicitly per state** — write states
select `2'd2` (SRAM), and only `op_pop0`/`op_pop3` select ChA/ChB. A write or
read sequence therefore cannot disturb the pairing at all.

**Evidence** (`kuntur_tb.sv` T5, QuestaSim, 27/27 checks passing): four POP
pairs separated by a 3-transfer write (deliberately odd), a `REG_READ`+`NOP`,
and a lone `NOP`. ChA read `0001, 0002, 0003, 0004` with ChB exactly +1000 on
every pair. The counters *advance*, so the FIFO was genuinely non-empty and
each pair consumed a fresh entry — this is not the underrun sentinel passing by
default. A phase slip would have flipped the delta to −1000 (65 536 − 1000).

**Rules RETIRED — remove from the MCU side:**

- ~~Register writes issued as an even-numbered batch.~~ No longer needed.
- ~~`FPGA_SPI_Init()`'s priming transfer at boot.~~ No longer needed.
- ~~NOP padding to reach an even transfer count.~~ No longer needed.

**Rules that REMAIN live** (unrelated to the pairing phase):

- Register access must not interleave with an in-progress
  `FPGA_SPI_ReadSamples()`. Guaranteed structurally as built (section 5):
  `SET_CHANNELS` only executes while streaming is explicitly stopped, and the
  0xFFF1 event handler does no SPI0 work itself — it validates, stashes, defers.
- Never call these from an ISR.
- A `FIFO_POP` pair must not be split by another command. The RTL now aborts
  such a sequence rather than desyncing, but the abort **costs one FIFO entry**:
  T7 showed the lone POP fire `fifo_ren`, deliver ChA, then abort — ChA jumped
  `0004 → 0006`, with entry `0005`'s ChB never clocked out. Loud, bounded, and
  recoverable, but still a lost sample pair.

A register write also does not pop the FIFO for that transfer — negligible,
momentary effect on drain rate.

## 2. BLE 0xFFF1 command protocol (bridge/phone ↔ Kuntur MCU)

**Where implemented:** `stream.h`/`stream.c` (GATT plumbing, new event
dispatch), `stream_app.c`/`.h` (new `STREAM_APP_OnCommandWrite`, alongside the
existing `STREAM_APP_OnCCCDWrite`).

**Characteristic:** `0xFFF1`, write-without-response. Pre-existing — declared
before this spec (`stream.c:92`, `STREAM_DATA_UUID`), commented "reserved for
future commands," no handler until now. Not a UUID chosen for this feature;
inherited from earlier BLE service setup. No reason found to change it
(write-without-response is the right property for a fire-and-forget command)
but flagging the provenance since it was asked about directly.

**Frame format** (payload of the GATT write):

| Byte(s) | Field | Meaning |
|---|---|---|
| `0` | `cmd` | Command opcode, see table below |
| `1..N` | `payload` | Command-specific |

| `cmd` | Name | Payload | Action |
|---|---|---|---|
| `0x01` | `SET_CHANNELS` | `ch_a` (1 byte, friendly index 0-127), `ch_b` (1 byte, friendly index 0-127) | Validates range, then calls `FPGA_SPI_SetChannels(channel_to_raw(ch_a), channel_to_raw(ch_b))` — see section 1a for `channel_to_raw()` |

Total frame for `SET_CHANNELS` = 3 bytes: `[0x01, ch_a, ch_b]`.

**No protocol version byte.** B.2 already flags this as a gap across *all*
interfaces ("protocol version field, absent today, without which the format
cannot evolve safely once public") — not solved here, tracked there. This spec
reserves `cmd` values `0x02+` for future commands; unknown `cmd` is ignored
(logged, not NAK'd — 0xFFF1 is write-without-response, there is no response
channel).

**Validation:** `len == 3 && cmd == 0x01` required; `ch_a` and `ch_b` must
each be `≤ 127` (friendly index range — every value in range maps to a real
channel per section 1a, so this is the entire validation rule). Out-of-range
or malformed frames are ignored and logged, not partially applied — never
call `FPGA_SPI_SetChannels()` with only one side validated, that would break
the even-transfer-count pairing invariant in section 1.

## 3. Bridge UART command relay (pc-app ↔ WB09KE bridge)

**Where implemented:** `wb09ke-bridge/STM32_BLE/App/vega_uart.c` (RX side, new
— currently TX-only, `vega_uart.c:1-49`), `stm32wb0x_it.c:48-52` (USART1 RX
currently forwards single bytes only to a debug-trace callback,
`UartRxCpltCallback` — needs a second consumer for command frames),
`vega_bridge_app.c` (new: capture the 0xFFF1 value handle during
characteristic discovery, call `aci_gatt_clt_write` — the mechanism already
exists in this file for the 0xFFF2 CCCD write at `vega_bridge_app.c:251-259`,
this is a second use of the same primitive, not new machinery).

**Direction:** this is a new pc-app→bridge direction. The existing documented
frame (`CLAUDE.md`: `0xAA 0x55 + uint16 length + 244-byte payload`) is
bridge→pc-app only and is **not modified** by this spec.

**Frame format** (pc-app → bridge, new):

| Byte(s) | Field | Meaning |
|---|---|---|
| `0-1` | magic | `0xCC 0x33` (distinct from the `0xAA 0x55` data-direction magic, so a framing bug can't cross-interpret the two directions) |
| `2` | length | Payload length in bytes (`N`) |
| `3..3+N-1` | payload | Passed through verbatim as the 0xFFF1 GATT write payload (section 2's frame) |

The bridge does no interpretation of the payload beyond framing — it is a
transparent relay. This keeps the command vocabulary (section 2) defined in
exactly one place (the Kuntur MCU firmware), so the bridge does not need to
change when commands are added.

**Future bridge-native commands** (confirmed 2026-08-05 — `0xCC 0x33` is
final, no change needed): commands like a bridge/headstage version query
(B.6), link-quality query (B.5), forced reconnect, or bridge diagnostic
counters would be answered *by the bridge itself*, not relayed to `0xFFF1` —
unlike `SET_CHANNELS`. That distinction (relay-to-headstage vs.
handled-locally) belongs inside the payload (e.g. a destination/type byte
right after this header) when it's needed, not in the magic bytes — one magic
pair covers "this is a command frame" regardless of how many command types
exist behind it.

**RAM constraint — resolved 2026-08-05, not a blocker.** The "100% RAM" figure
was a measurement artifact: the linker script (`stm32ble-test/client/STM32CubeIDE/STM32WB09KEVX_FLASH.ld`,
via `wb09ke-bridge/Makefile:161`) sets `_Min_Heap_Size=0x0` and places `.stack`
at a fixed address anchored to RAM's top, independent of where the heap
"ends." Actual claimed sections total ~21.5 KB of 64 KB (~33%); ~43 KB between
`.noinit` (the BLE stack's buffer) and `.stack` is genuinely unclaimed (no
`malloc`/`calloc`/`realloc`/`free` anywhere in the bridge firmware). See
`PLAN.md` B.5. Plenty of room for this relay's needs: one fixed-size RX parse
buffer (`VEGA_UART_CMD_MAX_PAYLOAD = 16`), one stored `uint16_t` handle (the 0xFFF1 value
handle, alongside the existing `notify_cccd_hdl` in `s_ctx`).

**No CRC.** B.2 already lists "bridge UART wire format (add CRC)" as a known
gap on the *existing* data-direction frame; this spec doesn't add CRC to
either direction now — same reasoning as the version-byte gap above, tracked
at the B.2 level rather than solved piecemeal per feature.

---

## 4. Readback verification (0xFFF3, Kuntur MCU → bridge → pc-app)

**Added 2026-08-06.** Closes the loop opened by A.2: after `SET_CHANNELS`,
confirm the FPGA regbank was actually written, without waiting for A.1's full
real-signal path (`ch_sel` restructure). Reads back via the FPGA's own
regbank RAM (`REG_READ`, section 1) — **not** by observing streamed sample
values. Today's `ch_sel` doesn't consult `ch_a`/`ch_b` at all (the A.1 gap),
so this verifies "the write landed in the regbank," not "the streamed data
changed" — a deliberately smaller claim that only needs the opcode-decode
RTL work, not the full ramp→real-data restructure.

### 4.1 FPGA transfer sequence (SPI0, MCU side)

**Rewritten 2026-08-11 for A.1.1g.** Supersedes the 2026-08-06 sequence, which
addressed `ch_a`/`ch_b` as offsets 4/5 in a direct-addressed 64-word window.
They are now ordinary RAM words **196** and **197**, reached the same way as
every other word.

Since `REG_READ` is self-addressing (section 1), a readback needs **no**
preceding write sequence. Reading both channels:

| Transfer | TX word | MISO returns |
|---|---|---|
| 1 | `REG_READ(tag=1, data=196)` | stale — discard |
| 2 | `REG_READ(tag=1, data=197)` | `ch_a` (result of transfer 1) |
| 3 | `NOP` | `ch_b` (result of transfer 2) |

Three transfers, down from four. The one-transfer-deep pipeline is unchanged: a
`REG_READ`'s value appears on the *next* transfer's MISO, never the same one.
Reads do not auto-increment, so back-to-back reads of different words are
independent and idempotent — verified in `kuntur_tb.sv` T3, including a read
issued immediately after a write to a *different* address, which is the case
that would expose a stale `addr_reg`.

**Odd transfer counts are now safe.** The 4th padding `NOP` in the old sequence
existed only to keep the batch even for the ChA/ChB phase; that hazard is gone
(section 1a), so the sequence is 3 transfers and no padding is required.

Writing a channel is the standard 3-transfer tagged sequence:

| Transfer | TX word | Effect |
|---|---|---|
| 1 | `REG_WRITE(tag=1, data=196)` | `addr_reg <= 196` |
| 2 | `REG_WRITE(tag=2, data=0x00)` | `staged_h <= 0x00` |
| 3 | `REG_WRITE(tag=3, data=raw)` | `ram[196] <= {0x00, raw}` |

`ch_a`/`ch_b` are 8-bit values in a 16-bit word, so transfer 2 always stages
`0x00`. It cannot be skipped — omitting it aborts the sequence at the tag check
and leaves the target word untouched (verified, T6 case 6a).

`SET_CHANNELS` is therefore 6 transfers (2 words × 3), up from 2. Irrelevant:
it runs only on the paused-stream reconfiguration path (section 5.2), never
during streaming.

As built these run from the deferred pending-command branch while streaming is
stopped (section 5.4), not inline in the GATT event handler, so they are
structurally uninterleaved with `FPGA_SPI_ReadSamples()`.

**Confirmed against the real bitstream 2026-08-06:** the RTL's `REG_READ`
latency does match this 1-transfer-deep pipeline assumption — the full
round-trip returned the exact requested `(ch_a, ch_b)` on hardware, not just
against the earlier host-side model.

**`FPGA_STREAM_CMD`** is `0x2525` (top bits `00`), changed from `0xA5A5`
(top bits `10`, which would collide with `REG_READ`) in the same change that
landed the RTL opcode decode. See section 1.

### 4.2 Friendly-index readback (MCU)

`FPGA_SPI_ReadChannels()` returns raw FPGA codes. Per section 1a's "BLE/pc-app
never see raw codes" rule, the MCU converts back to friendly index before
notifying:

```
friendly = ((raw >> 1) & 0x60) | (raw & 0x1F)
```

Inverse of `channel_to_raw()` — undoes the inserted zero bit. Single source
of truth, same file as `channel_to_raw()`.

### 4.3 0xFFF3 — command-response notify characteristic

New characteristic, mirrors 0xFFF2's existing pattern exactly: notify,
CCCD-gated, same discovery/subscribe flow. Deliberately kept separate from
0xFFF2's sample-data stream — no shared code path, no risk to the hot path
that carries live neural data (which has already caused two documented
regressions from unrelated touches).

**Trigger:** automatic, immediately after every successful `SET_CHANNELS` (no
separate BLE command needed). Not sent for a rejected/malformed
`SET_CHANNELS` (section 2's validation) — nothing was written, nothing to
confirm.

**Payload** (2 bytes): `[ch_a_readback, ch_b_readback]` — friendly indices
(0-127), same shape as `SET_CHANNELS`'s own payload, so the pc-app compares
like-for-like.

### 4.4 Bridge relay (bridge → pc-app, new direction/magic)

Bridge discovers 0xFFF3's value + CCCD handles the same way it already does
for 0xFFF2 (`vega_bridge_discover_all()`), enables notifications on connect.
On `ACI_GATT_CLT_NOTIFICATION_VSEVT_CODE` for the 0xFFF3 handle, relays over
UART using a **third** magic, distinct from both existing ones so the pc-app's
resync loop can tell all three apart at a glance:

| Magic | Direction | Payload |
|---|---|---|
| `0xAA 0x55` | bridge → pc-app | sample data (existing, unchanged) |
| `0xCC 0x33` | pc-app → bridge | command frame (section 3) |
| `0xEE 0x11` | bridge → pc-app | command response (this section) |

Frame: `0xEE 0x11 <len_lo> <len_hi> <payload>` — same 2-byte-length shape as
the existing `0xAA 0x55` data frame (same direction, same convention), even
though this payload is always 2 bytes; consistency over a marginally smaller
header.

### 4.5 pc-app

`SerialReader`'s resync loop recognizes either bridge→pc-app magic and
dispatches accordingly; emits a new `channels_readback` signal
`(ch_a: int, ch_b: int)`. UI: clicking Apply records the requested
`(ch_a, ch_b)`, sends `SET_CHANNELS`, and shows a pending state; on
`channels_readback`, compares to the recorded request — match → green
"✓ Verified", mismatch → red "✗ Mismatch (FPGA has A/B)", and a timeout (no
response within ~2 s) → "✗ ... unsuccessful — no confirmation received".
**Now that the RTL has landed, a timeout usually means a genuinely dropped
command** — most often a bridge USART overrun (see `PLAN.md` A.2 known
limitations) — rather than a missing feature. There is no retry: streaming
still resumes correctly and nothing gets stuck, but the operator must notice
and re-click. Reporting it honestly rather than hiding it is deliberate.

---

## 5. STOP_STREAMING / START_STREAMING, and SET_CHANNELS's new precondition

**Added 2026-08-06**, after bench testing surfaced a real hazard the earlier
design of section 2 didn't account for: `SET_CHANNELS`'s SPI0 write+readback
work (section 1, section 4.1 — 6 blocking transfers plus a GATT notify) has
no location inside the live streaming hot path that's provably safe to run
from. Three MCU-side placements were tried and each eventually hung the MCU
under some condition (inline in the BLE event-handler callback; a standalone
`UTIL_SEQ` task that mysteriously never ran; checked inside the streaming
loop with a debounce, which survived a single call but still hung after
several rapid repeats). Full history in `stream_app.c` comments and
`PLAN.md` A.2. Rather than keep searching for a safe moment to interleave
this work *with* live streaming, this section removes the need to interleave
at all: `SET_CHANNELS` now requires the stream to already be stopped.

### 5.1 New opcodes

| `cmd` | Name | Payload | Action |
|---|---|---|---|
| `0x02` | `STOP_STREAMING` | none | Halts the 0xFFF2 sample stream, disables FPGA sample ingestion at the source, and flushes fifo0 (section 5.3). Ignored (logged) if already stopped. |
| `0x03` | `START_STREAMING` | none | Re-enables FPGA sample ingestion and resumes the 0xFFF2 sample stream. No flush needed here — see 5.3. Ignored (logged) if not currently stopped. |

`0x01` (`SET_CHANNELS`, section 2) is unchanged in frame format, but gains a
precondition: **rejected and logged, not applied, unless streaming is
currently stopped.** No new error/response for this — same as any other
rejected `SET_CHANNELS` frame (section 2's existing "logged, not NAK'd"
rule), the operator sees no readback notify and infers the rejection from
that (or from the debug log, on the bench).

### 5.2 Required sequence

```
pc-app --STOP_STREAMING--> MCU   (streaming halts)
pc-app --SET_CHANNELS----> MCU   (only accepted while stopped)
                            MCU  --readback notify (0xFFF3)--> pc-app
pc-app --START_STREAMING--> MCU  (FIFO flushed, streaming resumes)
```

This is a deliberate design choice, not a stopgap: it moves "is it safe to
touch SPI0 and the BLE stack right now" from an MCU-side timing guess (every
attempt at which has failed) to explicit operator/pc-app sequencing, where
each step is a separate BLE round-trip and therefore naturally spaced apart
— no artificial settle timer needed on the MCU side. The pc-app's Apply
button (section 4.5) orchestrates all three steps as one operator-facing
action; the protocol itself exposes them as three independent commands.

### 5.3 FIFO flush, not preservation — and why

Samples generated while stopped are **not** buffered for later delivery —
they're discarded. This is deliberate, not a shortcut: they're pre-switch
data for a channel selection about to change; nothing downstream wants them
mixed in with post-switch data with no marker of where the transition
happened.

**Revised 2026-08-06 — gate ingestion at the source, not just consumption.**
The first version of this design only stopped the *MCU* from popping
samples; the FPGA kept ingesting at 30 kSPS regardless, so a flush on
`START_STREAMING` had to race a continuously-refilling FIFO. In bench
testing that flush **never once found true empty** — it always hit its
safety cap (tried 4,096, then 16,384 pairs, same result both times) — because
the net drain rate assumption didn't hold up against real conditions
(`BLE_STACK_Tick()`'s own documented occasional 10-22 ms stalls, called
periodically during the flush, could let backlog grow faster than the flush
could catch up). Manuel's fix: gate ingestion itself, in `ch_sel`
(`components.v`) — `fifo_wen <= dout_en_0 & stream_enable`. New regbank
register, `RB_CTRL_BASE + 36` (RAM word 228), bit 0: `1` = ingesting (reset default —
confirmed, an earlier draft of this same change had it backwards, defaulting
to *disabled* on reset, which would have silently gated the stream on every
FPGA reset/reprogram until the MCU explicitly enabled it), `0` = fifo0 gets
no new writes regardless of what the generator/AFE is doing underneath.
MCU-side: `FPGA_SPI_SetStreamEnable(uint8_t)` in `fpga_spi.c`, 2-transfer
batch (`REG_WRITE` + `NOP`, same even-count pairing-invariant rule as
`FPGA_SPI_SetChannels()`). Every write is followed by a readback
(`FPGA_SPI_ReadStreamEnable()`, same `REG_READ` pattern as section 4.1) to
confirm it actually took — not assumed. On `STOP_STREAMING`, a failed
disable skips the flush entirely rather than running it anyway (which would
silently repeat the exact race this design exists to avoid); on
`START_STREAMING`, a failed enable is logged but not fatal (worst case the
stream resumes reading nothing but the empty-FIFO sentinel — safe,
already-handled, and immediately visible in the pc-app's underrun stats).

This moves the flush to `STOP_STREAMING`, not `START_STREAMING`: disable
ingestion first, *then* flush — now draining a **static** backlog, not a
moving target. `START_STREAMING` no longer needs to flush at all: fifo0 has
been empty (and ingestion off) for the entire stopped duration, however long
that was.

**Numbers, still worth having:** at the ~10µs/pair SPI0 pop rate (from
`fpga_spi.c`'s own documented timing) against fifo0's 4,096-pair hardware
cap (further writes simply dropped once full, so backlog never exceeds this
regardless of how long ingestion ran before being disabled), a full flush is
now bounded at ~41 ms worst case (4,096 × ~10µs, no concurrent refill to
fight) — comfortably inside the ~1 s tolerance for this operation, and this
time the loop actually terminates via the empty-FIFO sentinel (`0x8000` on
both channels) rather than always hitting its cap.

Pop-and-discard via the existing `FPGA_SPI_ReadSamples()` until the
sentinel is observed, capped at `FPGA_FIFO_MAX_PAIRS` (16,384 — generous
margin over the ~41 ms estimate, kept as a safety bound against an
unexpected stuck condition rather than the primary termination path now).
`BLE_STACK_Tick()` is still called periodically during the flush (every 64
pairs) — this is also why a second fix was needed alongside the FPGA gate
(section 5.5): those periodic ticks can process a brand-new incoming GATT
command *while the flush hasn't returned yet*, which turned out to be a real
bug independent of the drain-rate question.

### 5.4 Where this runs (MCU implementation note)

The streaming hot loop (`StreamSendTask`'s per-packet `while(1)`) goes back
to its original, un-modified shape apart from one cheap boolean check added
at the top of each iteration (`if (s_streaming_stopped) return;` — no SPI0
or BLE work in the check itself, safe the same way the existing flow-off
check already is). All of `SET_CHANNELS`'s deferred SPI0/notify work,
`STOP_STREAMING`'s disable+flush, and `START_STREAMING`'s re-enable now live
in a separate branch that only runs *while stopped* — which `StreamSendTask`
revisits reliably every ~2 ms via the existing VTIMER fallback (the same
mechanism flow-off recovery already depends on), because the tight loop is
never entered while stopped. This is what the second failed attempt
(checked-at-function-entry) was missing: that attempt still had to contend
with the tight loop never returning during healthy streaming. Here, by
construction, streaming *is* stopped, so function-entry-adjacent checks are
reliably reachable. Within the stopped-branch, the pending checks are
ordered `s_stop_pending` → `s_set_channels_pending` → `s_start_streaming_pending`
— `SET_CHANNELS` must not run until ingestion is actually disabled and
flushed, not just until the `STOP_STREAMING` flag is set (section 5.5's
busy-guard is what actually enforces this is safe even if commands arrive
out of the expected order).

### 5.5 Reentrancy: one command cycle atomic with respect to the next

**Found 2026-08-06, in bench testing — not hypothetical.** The debug log
showed a new `STOP_STREAMING`+`SET_CHANNELS` cycle's prints interleaved
*inside* a still-running previous flush's own prints. Root cause:
`StreamFlushFpgaFifo()`'s periodic `BLE_STACK_Tick()` calls (needed to avoid
one long uninterrupted blocking stretch) can process a brand-new incoming
GATT write while the outer flush call hasn't returned yet — nothing
protected `s_streaming_stopped` / `s_pending_ch_a`/`b` / `s_set_channels_pending`
against a new command overwriting them mid-use by the in-progress one. Exact
symptom matched what the pc-app showed: a `SET_CHANNELS` arriving mid-flush
got silently orphaned (its pending flag set, but streaming resumed before
the tight loop — which doesn't poll that flag — or anything else checked it
again), so that specific click's readback genuinely never arrived, while
the next click (once the MCU wasn't mid-flush) worked normally.

**Fix:** `s_command_busy`, set for the duration of
`SetChannelsTask()`/`StreamFlushFpgaFifo()`/`FPGA_SPI_SetStreamEnable()`
work. `STREAM_APP_OnCommandWrite()` rejects (logged, not applied) any
command that arrives while busy. Makes one full STOP/SET/START cycle atomic
— a too-early re-click now fails safely (rejected → pc-app's existing
timeout) instead of corrupting shared state.

### 5.6 Real MCU-confirmed acks for STOP_STREAMING / START_STREAMING

**Added 2026-08-06.** Until this point the pc-app had no way to know when
the MCU actually *finished* handling `STOP_STREAMING`/`START_STREAMING` —
it fired the command and waited a fixed settle delay (`STOP_STREAMING_SETTLE_MS`
/ `START_STREAMING_SETTLE_MS`), then assumed success and moved on. This is
the same class of gap that section 4 already closed for `SET_CHANNELS`
(fire-and-hope vs. an actual readback), applied to the other two commands in
the sequence.

**MCU side:** `FPGA_SPI_SetStreamEnable(enable)` writes the FPGA's
`stream_enable` regbank bit (address `0x24`, section on the FPGA gate above);
immediately followed by `FPGA_SPI_ReadStreamEnable()`, a readback over the
same SPI0 link, so `success` reflects a confirmed write, not just "the write
call returned." `StreamSendTask`'s stopped-branch (section 5.4) calls
`STREAM_NotifyStreamingAck(cmd, success, ConnectionHandle)` after both the
`s_stop_pending` and `s_start_streaming_pending` branches, whether or not the
readback matched — the pc-app needs to hear about a failed confirmation just
as much as a successful one.

**Payload shape — reuses 0xFFF3, now type-prefixed:** `SET_CHANNELS`'s
existing readback notify (section 4.3) is extended with a leading type byte
so all three command responses can share one characteristic and one pc-app
resync path:

| `type` (byte 0) | Name | Remaining payload | Length |
|---|---|---|---|
| `0x01` | `SET_CHANNELS` readback | `[ch_a, ch_b]` (friendly indices) | 3 bytes |
| `0x02` | `STOP_STREAMING` ack | `[success]` (0 or 1) | 2 bytes |
| `0x03` | `START_STREAMING` ack | `[success]` (0 or 1) | 2 bytes |

`type` values are deliberately the same as the 0xFFF1 command opcodes
(section 2, section 5.1) — a response always self-identifies which command
it's answering, so the pc-app's dispatch is a direct `switch` on byte 0
rather than needing to track which command is outstanding.
`STREAM_RESPONSE_PAYLOAD_SIZE` (stream.h) grew from 2 to 3 bytes to fit the
widest case; the 2-byte ack payloads are simply shorter GATT notifies on the
same characteristic.

**Bridge:** no changes — the existing 0xFFF3 relay (section 4.4) already
forwards the raw payload verbatim over the `0xEE 0x11` UART frame regardless
of its length or contents.

**pc-app:** `SerialReader` gained `stop_streaming_ack(bool)` and
`start_streaming_ack(bool)` signals; the 0xFFF3 dispatch in the resync loop
reads `payload[0]` as the type byte first (previously it assumed
`payload[0]` was always `ch_a`, which the type-prefixed format would have
silently broken) and routes to the matching signal.

`MainWindow`'s Apply sequence (`_apply_channels` and its continuations)
replaces both fixed settle delays with ack-driven waits, each backed by its
own `QTimer` (`_stop_ack_timer` / `_start_ack_timer`, `STREAMING_ACK_TIMEOUT_MS
= 2000` each, same reasoning as section 4.5's verify timeout): STOP_STREAMING
is sent, then `_apply_channels_send_set()` runs either on `stop_streaming_ack`
or on timeout (whichever comes first); the same pattern gates
`_apply_channels_reenable()` after START_STREAMING. A timeout is treated the
same as section 4.5's — a dropped command, not an error to block on.
`APPLY_COOLDOWN_MS = 1000` is layered on *after* the start ack/timeout
resolves, not instead of it — it's a deliberate extra floor against rapid
re-clicking, independent of whether the ack mechanism itself is working.

---

## Resolved 2026-08-05

- Opcode scheme: 4-way (`00` POP / `01` WRITE / `10` READ / `11` NOP), with
  the `FPGA_STREAM_CMD` collision fix required alongside. Agreed as-is;
  RTL side tracked as an A.1 follow-up in `PLAN.md` — section 1.
- Channel encoding: friendly 0–127 index, single formula in MCU firmware,
  BLE/pc-app never see raw codes — section 1a.
- Sampling cycle's 33rd state: confirmed intentional placeholder for an
  alternate RHD2164 command (chip-ID/temperature read), datasheet recommends
  3 slots, reduced to 1 here — section 1a.
- `rhd2164_sampling_cmd0-3`: confirmed as the likely command-word home for
  the placeholder slot above; reserve now, wiring tracked as an A.1
  follow-up in `PLAN.md` — section 1.
- `ch_a`/`ch_b` validation: range check against friendly 0–127 — section 2.
- `0xFFF1`: confirmed keep as-is — section 2.
- Bridge RAM: "100%" was a measurement artifact, not real exhaustion — not a
  blocker for this relay — section 3.
- Command-frame magic bytes: confirmed `0xCC 0x33`, final — future bridge-native
  commands (version query, link-quality query, etc.) extend via a type byte
  inside the payload, not new magic — section 3.
- pc-app UI scope: two friendly-index inputs (0-127) + Apply, per plan's
  explicit Phase-A scope — no further discussion needed.

## Resolved 2026-08-06

- Readback response transport: new `0xFFF3` notify characteristic, not a
  piggyback on the existing `0xFFF2` sample stream — keeps the hot streaming
  path untouched, mirrors an already-working pattern instead of inventing a
  new one. Section 4.3.
- Readback trigger: automatic after every successful `SET_CHANNELS`, no
  separate BLE command — section 4.3.
- Bridge relay magic for the new bridge→pc-app response direction: `0xEE
  0x11`, distinct from both existing magics — section 4.4.
- Verification scope: confirms the FPGA regbank was written, not that the
  streamed sample data changed (that still needs A.1's `ch_sel` restructure)
  — section 4, intro.
- **`SET_CHANNELS` requires streaming already stopped** — after three
  MCU-side placements for its SPI0/notify work each eventually hung the MCU
  under bench testing (inline in the BLE handler; a standalone task that
  never ran; debounced-in-loop, survived one call but not repeats). Decided
  against continuing to search for a safe interleaving point; moved the
  safety question to explicit operator sequencing instead — section 5.
- New opcodes `0x02 STOP_STREAMING` / `0x03 START_STREAMING` — section 5.1.
- Samples generated while stopped are discarded, not buffered — avoids
  feeding an already-open, uninvestigated FPGA FIFO chronic-backlog question
  (section 5.3), and pre-switch data isn't useful once channels change
  anyway.
- FIFO flush via the existing empty-FIFO sentinel (`0x8000`), not a fixed
  pop count or a new detection mechanism — section 5.3.
- **Gate FPGA sample ingestion at the source (Manuel's proposal), not just
  MCU-side consumption** — new regbank register `RB_CTRL_BASE + 36`
  (RAM word 228), bit 0 = `stream_enable`, gates `fifo_wen` directly in
  `ch_sel`. Moves the
  flush to `STOP_STREAMING` (draining a static backlog) instead of
  `START_STREAMING` (which was racing a continuous 30 kSPS producer and, in
  bench testing, never actually won — always hit its safety cap regardless
  of how high the cap was raised). Reset default confirmed `1`
  (ingesting) — an earlier draft had this backwards, caught before it was
  flashed. Section 5.3.
- **Command reentrancy** — a new command arriving via a nested
  `BLE_STACK_Tick()` call *during* a still-in-progress flush was corrupting
  shared pending-state, confirmed in a bench log (not hypothetical). Fixed
  with a busy-guard making one full STOP/SET/START cycle atomic — section
  5.5.
- **Real MCU-confirmed acks for STOP_STREAMING/START_STREAMING**, replacing
  fixed settle-delay guesses — reuses 0xFFF3 with a new type-prefixed payload
  shared with the existing `SET_CHANNELS` readback, confirmed via an SPI0
  readback of `stream_enable` (not just "the write call returned") —
  section 5.6.
- **Rapid-click MCU crash-loop — fixed.** Bench testing found that Apply
  re-enabled the instant a fire-and-forget `START_STREAMING` was sent, letting
  a human sustain close to one full cycle per second and drive the MCU into a
  repeating reset loop. Fixed by the ack-driven sequencing (section 5.6), which
  holds the button inactive until the cycle genuinely completes, plus
  `APPLY_COOLDOWN_MS`. **Re-tested and confirmed 2026-08-06**: sustained
  rapid-click bursts no longer reproduce it — the Verified mark lands *before*
  the button re-enables, confirming the acks gate the button rather than racing
  it; no reset loop, streaming live throughout.
- **Bridge USART1 RX overrun (ORE) silently killing command reception for the
  rest of a session** — found live in bench testing right after section 5.6
  shipped: 2 clicks succeed, then every subsequent command vanishes with zero
  log output on either end, because `stm32wb0x_it.c`'s ISR never cleared the
  USART overrun flag, and per the STM32 reference manual RXNE stops firing
  for new data once ORE latches until it's explicitly cleared. Fixed by
  clearing `ORE` every ISR entry with a log line. Confirmed live the same
  session: the fix converts a fatal, permanent failure into a self-healing,
  single-command loss (a subsequent command sent moments later relays and
  applies normally). Residual gap — a command can still occasionally be lost
  to an overrun with no retry, most often `SET_CHANNELS` specifically since
  the ack-driven design (no deliberate gap between receiving an ack and
  sending the next command) tends to land it right as the bridge is still
  busy relaying the previous ack's GATT notification. Mitigated (not
  eliminated) with `COMMAND_GAP_MS = 15` in `main_window.py`. The pc-app's
  timeout-path messaging was also updated to say "unsuccessful — no
  confirmation received" instead of the older "no response (RTL readback not
  available yet?)," which predates readback actually working and was
  becoming misleading. `PLAN.md` A.2 has full detail.

## Status: REOPENED 2026-08-11 — MCU side rewriting against A.1.1g

A.2 was closed 2026-08-06, hardware-verified across all four hops. **A.1.1g
then changed the SPI0 wire protocol underneath it**, so that verification no
longer carries: "closed" means closed-as-of-2026-08-06, not still-verified.

Current state by hop:

| Hop | State |
|---|---|
| FPGA RTL (section 1) | **Done and simulation-verified** — `kuntur_tb.sv`, 27/27 checks, 2026-08-11 |
| MCU helpers (sections 1a, 4.1, 4.2) | **Being rewritten** — this is the blocking item |
| BLE 0xFFF1 / 0xFFF3 (sections 2, 4.3) | Unchanged — no wire-format change above SPI0 |
| Bridge relay (sections 3, 4.4) | Unchanged |
| pc-app (section 4.5) | Unchanged |

The protocol change is confined to SPI0. Nothing above the MCU sees it, which
is why only `fpga_spi.c` and the three sections above are in scope.

**Re-verification required before A.2 can be called closed again:** flash the
new bitstream and firmware **together**, then re-run the full STOP →
SET_CHANNELS → readback → START round-trip on the bench, including the
repeat-click reliability pass — transfer counts and FSM timing both changed.
Per `PLAN.md`, fold this into the same bench session that starts the A.1.1
ladder rather than spending a separate one on it.

### As-built dependencies on A.1 (RTL)

Landed with A.2: the `REG_READ`/`NOP` opcode decode in `main_controller`, the
`FPGA_STREAM_CMD` `0xA5A5` → `0x2525` fix, and the `stream_enable` regbank
register gating `fifo_wen` — now RAM word **228** (`RB_CTRL_BASE + 36`), not
word 164 as this section previously stated; the A.1.1g memory-map
rearrangement moved it, and section 1's table is the authority.

Still open in A.1, and **not** required by this spec: wiring the
sampling-cycle placeholder command slot (`rhd2164_sampling_cmd0-3`, regbank
words 192–195 — section 1, tracked as A.1.4), and the `ch_sel` restructure that
makes the *streamed sample data itself* reflect the selected channels rather
than a synthetic ramp. Until that lands, this control plane correctly selects
channels that the data path still ignores.
