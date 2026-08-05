# Channel-selection control plane — interface spec

**Status:** Draft, pre-implementation (A.2). Written before code per the plan's
working principle 5 ("interface specs outrank subsystem specs — every
expensive bug lived at a boundary"). This is a Phase-A-scoped spec: enough to
implement and review against, not the full Phase B apparatus (permanent
requirement IDs, CI traceability) — that formalization is B.2's job, applied
across all interfaces at once.

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

**Where implemented:** MCU side in `fpga_spi.c` (new); FPGA side needs a
targeted RTL change to `main_controller` (currently only distinguishes
`opcode==01` from everything else — `components.v:125-232`) plus a new read
path (below). Regbank RAM unchanged — `components.v:406-437`.

**Wire format:** 16-bit word, MSB first, SPI mode 0 (matches the existing
sample-read transfers in `fpga_spi.c`):

| Bits | Field | Meaning |
|---|---|---|
| `[15:14]` | `opcode` | See table below |
| `[13:8]` | `addr` | 6-bit regbank address offset. Actual RAM address = `{2'b10, addr}` = `addr + 128` (`kuntur_fpga.v:114`). |
| `[7:0]` | `data` | Register value (write) or don't-care (read/pop/nop) |

**Opcodes** (decided 2026-08-05 — supersedes the old binary
`opcode==01?write:pop` decode; requires an RTL change to `main_controller`,
not yet made):

| `opcode` | Name | Action | Status |
|---|---|---|---|
| `00` | `FIFO_POP` | Pop next sample pair (existing behavior) | RTL update needed — today this is the implicit "not write" case; needs to become an explicit match instead of a catch-all, see below |
| `01` | `REG_WRITE` | Write `data` to regbank address `addr` (existing behavior, unchanged) | Existing |
| `10` | `REG_READ` | Request register readback at `addr`; value appears on the *next* transfer's MISO output (same one-transfer-deep pipeline pattern as `dtx_mux_reg` today) | **New RTL — proposed, not yet designed/confirmed.** No path from `regbank_dout0` to the TX mux exists today. |
| `11` | `NOP` | No side effect: no FIFO pop, no regbank write/read, TX mux untouched | New — reserved as a safe filler/keepalive transfer |

**Breaking-change alert — fix together with the RTL change:**
`fpga_spi.h`'s `FPGA_STREAM_CMD = 0xA5A5U` (the dummy TX word sent on every
existing sample-pop transfer) has top bits `10` by accident — it was never
meant to carry opcode meaning. Once `10` means `REG_READ`, every existing
streaming transfer would be misread as a register-read request instead of a
FIFO pop. `FPGA_STREAM_CMD` must change to a value with top bits `00` (e.g.
`0x2525`) in the same change that lands the new opcode decode — this is not
optional, the stream breaks otherwise.

**Known register addresses** (`components.v:419-437`):

| `addr` (6-bit) | RAM word | Signal | Notes |
|---|---|---|---|
| `4` | 132 | `ch_a` | 8-bit: `[7:6]` selects one of 4 sample sources (`data_a0`/`data_b0`/`data_a1`/`data_b1`), `[5:0]` selects channel index within that source (`components.v:328-337`). Raw FPGA code — see section 1a for the friendly-index mapping. |
| `5` | 133 | `ch_b` | Same encoding as `ch_a`. |
| `0-3` | 128-131 | `rhd2164_sampling_cmd0-3` | Computed by `ram` and wired to the `kuntur_fpga.v` top level, but **not consumed by anything downstream today** — dead-end wires. Confirmed 2026-08-05: reserved as runtime RHD2164 command-injection slots — likely home for the command word(s) fed into the sampling cycle's placeholder state (section 1a), primary use case A.3's impedance-check DAC control (`RHD_ZCHECK_DAC/SEL/EN`). Reserving the address space now avoids a protocol version bump later; wiring tracked as an A.1 follow-up in `PLAN.md`. |

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

**Hazard — ChA/ChB pairing invariant:** `main_controller`'s FSM toggles an
internal ChA/ChB phase on *every* SPI0 transfer regardless of opcode
(`components.v:213-231`, `mcu_dtx_sel`/`mcu_dtx_en` set unconditionally in
states `op0c`/`op1c`). `FPGA_SPI_ReadSamples()` assumes this phase starts at
"ChA next" and reads in matched pairs; `FPGA_SPI_Init()`'s one priming
transfer establishes that phase once at boot. **Any odd number of SPI0
transfers issued outside of `FPGA_SPI_ReadSamples()` shifts the phase and
silently swaps ch0/ch1 in every subsequent sample read** — this is believed to
be the same class of bug as the historical "32-bit FIFO channel swap" issue.

- **Rule:** register writes MUST always be issued as an even-numbered batch.
  `FPGA_SPI_SetChannels(ch_a, ch_b)` writes both registers in one call (2
  transfers) to satisfy this by construction — never expose a single-register
  write as public API.
- **Rule:** register writes must not be interleaved with an in-progress
  `FPGA_SPI_ReadSamples()` call. Both run in the same cooperative
  single-threaded context (BLE sequencer + `StreamSendTask`), so this holds as
  long as `FPGA_SPI_SetChannels()` is only called from BLE event-handler
  context, never from an ISR.
- A register write also does not pop the FIFO for that transfer (opcode `01`
  suppresses `fifo_ren`, `components.v:190-200`) — negligible, momentary
  effect on drain rate, not expected to be observable against the existing
  ~1.7% chronic underrun rate.

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
buffer (proposed ≤16 bytes), one stored `uint16_t` handle (the 0xFFF1 value
handle, alongside the existing `notify_cccd_hdl` in `s_ctx`).

**No CRC.** B.2 already lists "bridge UART wire format (add CRC)" as a known
gap on the *existing* data-direction frame; this spec doesn't add CRC to
either direction now — same reasoning as the version-byte gap above, tracked
at the B.2 level rather than solved piecemeal per feature.

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

## Status: spec finalized, ready for implementation

All open questions resolved. Remaining RTL-side work (item 1 below) is
tracked in `PLAN.md` A.1 and does not block MCU/BLE/bridge/pc-app
implementation against `REG_WRITE` alone.

## Dependency on A.1 (RTL, not blocking)

The `REG_READ`/`NOP` opcode decode in `main_controller`, the `FPGA_STREAM_CMD`
fix, and wiring the sampling-cycle placeholder slot are tracked in `PLAN.md`
A.1 (your side). MCU/BLE/bridge/pc-app implementation (mine) can proceed
against `REG_WRITE` alone in the meantime — `REG_READ` isn't required for
`SET_CHANNELS` itself, only useful for verification/readback later.
