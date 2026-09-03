# LVDS tunnel — Kuntur FPGA ↔ companion FPGA — interface spec

**Status: DRAFT 2026-09-02, not implemented.** Written before any RTL, per
PLAN.md working principle 5 and the standing rule that cross-boundary
interfaces get a spec first. This is PLAN.md **A.4**'s first checkbox
("Interface spec, written before implementation — framing, clocking,
link-loss detection, latency budget, CRC"). It is the long pole for both
**A2** (dual-path bench validation) and **A3** (in-vivo), and it is the
one A.4 item that never depended on the companion hardware arriving.

The LIFCL-40-EVN and the IAM Electronic FMC LPC breakout **arrived**
(confirmed 2026-09-02), which closes PLAN.md's standing "Schedule risk,
unconfirmed" note and unblocks A.4's RTL checkboxes behind this document.

**Four architecture decisions were taken by Manuel** and are settled inputs
here, not re-argued:

1. **Kuntur owns AFE configuration, exclusively.** The Intan controller is
   *a visualiser of the data the Kuntur FPGA gets*, not a second
   configuration master. Kuntur's real RHD2164 register state is
   **replicated downstream** so the Intan controller sees the true
   configuration rather than a fiction of its own writes. §2.3, §4.4, §9.
2. **Free-running, with sync markers** — Kuntur keeps its own PLL off
   `clkin` whether or not the cable is attached. §6.1, §10.
3. **All 128 channels cross downstream.** §3.2.
   *(1–3 decided 2026-09-02.)*
4. **Unidirectional, synchronous link — one pair Data, one pair forwarded
   Clock** (2026-09-03). The Intan controller is only a visualiser used to
   verify the wireless path, so bidirectionality is not needed; spending
   the second pair on a forwarded clock rather than a return channel makes
   the link source-synchronous and **removes the line code entirely**.
   §1.3, §6.

A true SPI bridge (Intan as sole master, Kuntur relaying) is **feasible**
and is **deferred as out of scope**, not ruled out — it belongs to a
different product configuration, a wired-only headstage with no wireless
mode. §2.1 Case B records the analysis so a future revisit does not repeat
it.

---

## 0. Scope, and what this is not

**In scope:** the wire contract on the two differential pairs between the
Kuntur FPGA (`LIFCL-17-8UWG72C`) and the companion FPGA
(`LIFCL-40-9BG400C` on LIFCL-40-EVN) across the uHDMI cable — framing,
line coding, clocking, CRC, link-loss detection and behaviour, latency
budget, and the emulation contract the companion must honour toward the
Intan controller.

**Out of scope, deliberately:**

- The companion FPGA's *internal* RTL structure. This spec pins what
  crosses the cable and what the companion must present on the Omnetics
  connector; how it gets there is implementation.
- Intan RHX / Open Ephys host-software behaviour beyond the RHD2164
  register contract in §9.1.
- The `kuntur144-ecl` PCB. Nothing here needs a board change — see §1.3,
  which is the one place that could have needed one and does not.

**This spec does not change the BLE path.** The tunnel is a **read-only
tap** on data `ch_sel` already sees (§2.5). No byte of the
`ch_sel → fifo0 → spi0 → MCU → BLE` chain changes, and A.6.5's recorded
`sample_rate` and A.7's λ stay valid untouched — which is the whole point
of decision 2.

---

## 1. Physical layer — what the hardware actually gives us

Everything in this section is read out of the shipped PCB and a real
Radiant build, not from a datasheet recollection. Sources are named so
each number is re-checkable.

### 1.1 Two differential pairs, and only two

From `kuntur144-ecl.kicad_pcb`, connector `J1`
(`openic:HDMI_Micro-D_Molex_46765-0x01`, micro-HDMI 19-position):

| J1 pad | Net | FPGA ball (`U2`) |
|---|---|---|
| 3 | `FPGA_LVDS1P` | **G9** |
| 5 | `FPGA_LVDS1M` | **F9** |
| 6 | `FPGA_LVDS2P` | **E9** |
| 8 | `FPGA_LVDS2M` | **E8** |
| 4, 7, 10, 13, 16, SH | `GND2` | — |
| 9, 11 | *unconnected* (`D0+`/`D0-`) | — |
| 1, 2 | `VCC2` | — |
| 12, 15 | `GND1` | — |
| 14, 17 | `VCC1` | — |
| 18, 19 | `VSTIMp` / `VSTIMm` | — |

**Two pairs. Not three.** A third HDMI differential pair (`D0±`, pads
9/11) exists on the connector body but is **unrouted on this board**. This
is the single most constraining fact in this document, and §6 follows from
it:

> Two pairs must cover everything. Spend them on *data + return channel*
> and neither end has a clock, so both must recover timing from the data —
> which forces a line code, since RHD2164 samples cannot self-clock (§6.3).
> Spend them on *data + forwarded clock* and the link is source-synchronous
> with **no line code at all**. §1.3 takes the second option, on the
> strength of decision 4: nothing functional needs to travel upstream.

The connector also carries power (`VCC1`/`VCC2`) and the stimulator rails
(`VSTIMp`/`VSTIMm`) alongside the two pairs. Noted here because it means
the uHDMI cable is **not** a signal-only cable, and the hand-made pigtail
(PLAN.md A.0) must not accidentally bridge `VSTIM*` into the FMC breakout.
See §11, open item O5.

### 1.2 Both pairs are bottom-bank, and true LVDS output is available

From `impl_1/kuntur_fpga_impl_1.pad` (Radiant, build of 2026-08-31,
`PART TYPE: LIFCL-17`, `PACKAGE: WLCSP72`):

| Port | Pin/Bank | Site | Dual function |
|---|---|---|---|
| `serial_lvds_tx` | G9/**5** | **PB18A** | `PCLKT5_0`/`LLC_GPLL0T_MFGOUT2`/`CDR_RXP1`/`ADC_CP1`/`COMP2P` |
| *(complement)* | F9/5 | **PB18B** | `PCLKC5_0`/`CDR_RXN1`/`ADC_CN1`/`COMP2N` |
| `serial_lvds_rx` | E9/**5** | **PB16A** | `LLC_GPLL0T_MFGOUT1`/`CDR_RXP0`/`VREF5_1`/`ADC_CP0`/`COMP1P` |
| *(complement)* | E8/5 | **PB16B** | `CDR_RXN0`/`ADC_CN0`/`COMP1N` |

Three things follow, all confirmed rather than assumed:

- **`PB##A`/`PB##B` are the two halves of one true differential site.**
  G9/F9 = `PB18`, E9/E8 = `PB16`. These are real pairs, not two
  independent single-ended pins that happen to be adjacent.
- **Bank 5 supports true `LVDS_OUT` on this exact device, package and
  speed grade.** Not inferred from the CrossLink-NX datasheet's bottom-I/O
  rule — *demonstrated* by the current build, in which `spi2_csb` (G5/5,
  `PB30A`) and `spi2_sck` (F7/5, `PB26A`) both come out of PAR as
  `LVDS_OUT` with `DIFFDRIVE:3.5`. PLAN.md A.0's note that true
  differential LVDS output lives only on the Bottom bank is consistent
  with this; here we have the stronger form of the evidence.
- **G9/F9 (`PB18`) is a primary-clock input pair** — `PCLKT5_0` /
  `PCLKC5_0`; E9/E8 (`PB16`) is not. Recorded because it mattered to an
  earlier bidirectional draft. Under decision 4 Kuntur receives nothing,
  so this capability is **unused** — but the equivalent constraint is real
  on the *companion* side, where the forwarded clock must land on a
  clock-capable input (O1).

Both ports are today declared `IO_TYPE=LVCMOS18H` and **single-ended**, so
F9 and E8 currently show as `unused, PULL:DOWN` in the same report. They
are free.

### 1.3 Pair allocation — Data + forwarded Clock, both outbound

**Decided 2026-09-03 (Manuel):** *"If we only need the Intan controller as
a visualizer to verify the wireless path, which it is the case, then we
don't need bidirectionality. Let's use both lines as Data and forwarded
Clk so we have a synchronous link."*

| Pair | Kuntur balls | Direction | Carries |
|---|---|---|---|
| `FPGA_LVDS1` | G9 (P) / F9 (N) | **out** | **`TUN_DATA`** — the serial sample stream |
| `FPGA_LVDS2` | E9 (P) / E8 (N) | **out** | **`TUN_CLK`** — forwarded word clock (`SCLK`) |

This supersedes an earlier draft that required the two ports to swap so
Kuntur could receive on the clock-capable pair. **That requirement is
gone**: with no upstream path, Kuntur receives nothing, and G9/F9's
`PCLKT5_0`/`PCLKC5_0` clock-*input* capability is simply unused. Both
ports stay **outputs**, exactly as `kuntur_fpga.v` already declares them.

Two consequences, both good:

- **No port-direction change, and no "do it before the pigtail is
  soldered" deadline.** The only Kuntur-side change is `IO_TYPE=LVDS` on
  both ports in `impl_1.pdc` (they are `LVCMOS18H` today), which promotes
  F9 and E8 from `unused, PULL:DOWN` to the complement halves of their
  pairs. Renaming the ports (`tun_data_p` / `tun_clk_p`) is still worth
  doing, since `serial_lvds_rx` is a misleading name for an output.
- **The clock-capable-input constraint moves to the companion side**, and
  becomes part of O1: the LIFCL-40 FMC pair receiving `TUN_CLK` must land
  on a clock-capable input pair that can drive a PLL and the edge-clock
  network. The pair receiving `TUN_DATA` needs only LVDS input.

### 1.4 I/O and resource budget on the Kuntur side

From the same build's `kuntur_fpga_impl_1.mrp`:

| Resource | Used now | Total | After the tunnel |
|---|---|---|---|
| Registers | 545 | 13,941 (4%) | ample |
| LUT4s | 543 | 13,824 (4%) | ample |
| Block RAMs | 10 | 24 (42%) | 14 free; the tunnel needs ~1 |
| **PLLs** | **1** | **2** | **one free — and, per §6.3, the tunnel does not need it** |
| **IDDR/ODDR/TDDR** | **0** | **102** | gearing primitives all free |
| **PIOs** | **31** | **39 (79%)** | **33/39 after promoting both pairs to differential** |

The two facts that matter: **the gearing primitives and DDR resources are
entirely untouched** (0 of 102), and **PIO headroom is the tight
resource**, at 33 of 39 after this change. A second PLL is also free, but
§6.3 resolves that the tunnel does not need it — all three tunnel clocks
come off `pll0`'s existing VCO on integer dividers.
Nothing here needs new pins — both pairs are already routed — but any
future feature wanting pins should know the budget is nearly spent.

### 1.5 The companion side — RESOLVED (O1, 2026-09-03)

Source: **FPGA-EB-02028-1.6, *CrossLink-NX Evaluation Board User Guide***,
Table 8.1 (FMC LPC header → LIFCL-40 ball) and Table 3.1 (VCCIO), joined
against an **authoritative Radiant pad report** for `LIFCL-40-9BG400C`
`CABGA400` — generated by building a two-pin probe design in Radiant
2025.2.1 rather than by reading site names out of the schematic PDF, whose
multi-column text extraction interleaves rows and cannot be trusted.

#### 1.5.1 Every FMC LA pair is a true differential bottom-bank pair

All 34 `LA` pairs plus `FMC_CLK0`/`FMC_CLK1` map to `PB##A`/`PB##B` sites —
true differential pairs, all on **`PB` (bottom) sites**, in **banks 3, 4
and 5**. This matches the board schematic's own sheet label
(*"10 — FMC-LPC (Bank3/4/5)"*) and **confirms PLAN.md A.0's claim** that
the FMC LPC is the connector wired to bottom-bank balls.

Under decision 4 the companion is **receive-only**, so the true-LVDS-*output*
capability that motivated A.0's choice is not actually needed here. It is
recorded because it is exactly what §2.1 Case B would need if the deferred
SPI bridge is ever revisited.

**`VCCIO3`, `VCCIO4` and `VCCIO5` are fixed at 1.8 V** (Table 3.1 — "N/A"
for 3.3 V, "Fixed" for 1.8 V; no jumper, no selection). That matches the
Kuntur side, which runs its banks at 1.8 V throughout. There is no 3.3 V
mismatch to design around. `VADJ` (jumpers JP6/JP7/JP8, default all open)
supplies the *mezzanine*, not the FPGA banks, and the passive IAM breakout
should not need it — confirm before power-on, O5.

#### 1.5.2 The trap: FMC's `_CC` pins are **not** FPGA clock-capable here

The intuitive choice — take the clock on an FMC pin named `_CC` — is
**wrong on this board**:

| FMC pair | LIFCL-40 site | Bank | FPGA clock-capable? |
|---|---|---|---|
| `FMC_LA00_CC` | `PB56A`/`PB56B` | 3 | **NO** |
| `FMC_LA01_CC` | `PB60A`/`PB60B` | 3 | **NO** |
| `FMC_LA18_CC` | `PB28A`/`PB28B` | 4 | **NO** |

FMC's "CC" designation describes the *carrier's* clock distribution, not
the FPGA's `PCLK` capability, and Lattice did not route these to `PCLK`
pins. The pairs that **are** FPGA clock-capable are `FMC_CLK0`, `FMC_CLK1`,
and nine ordinary `LA` pairs: `LA02`, `LA04`, `LA05`, `LA07`, `LA10`,
`LA14`, `LA20`, `LA24`, `LA26`.

#### 1.5.3 Recommended allocation

| Signal | FMC pin | LIFCL-40 ball | Site | Bank | Why |
|---|---|---|---|---|---|
| **`TUN_CLK`** | **H7 / H8** (`FMC_LA02_P/N`) | **Y2 / Y3** | `PB8A`/`PB8B` | 5 | `PCLKT5_1`/`PCLKC5_1` **and `LLC_GPLL0T_IN`** — a primary-clock input *and* a direct PLL reference input |
| **`TUN_DATA`** | **H10 / H11** (`FMC_LA04_P/N`) | **V1 / W1** | `PB6A`/`PB6B` | 5 | plain LVDS input, adjacent site, same bank |

`FMC_LA02` is the standout because of **`LLC_GPLL0T_IN`**: §6.6 has the
companion multiply the received word clock ×4 to recover `ECLK`, and this
pin feeds a PLL directly rather than via fabric routing. Of the eleven
clock-capable pairs it is the only one carrying a genuine PLL *input*
function (`FMC_LA04`'s `LLC_GPLL0T_MFGOUT1` is a manufacturing test
*output*, not an input — the same function that appears on Kuntur's E9 and
is equally unusable there).

Both pairs sit in **bank 5** at a fixed 1.8 V, on **adjacent sites**
(`PB6`, `PB8`), and on **adjacent connector pins** in the same `H` row,
three positions apart — which matters for a hand-made pigtail, where
pair-to-pair length matching between `TUN_CLK` and `TUN_DATA` is the one
skew that a source-synchronous link actually cares about.

**Alternates**, if layout makes the above awkward: `FMC_LA05` (R5/R6,
`PB10A/B`, bank 5, `PCLKT5_2`) for the clock, with any bank-5 pair for
data. Staying inside one bank is worth more than any individual pin
choice — it keeps `VCCIO`, the edge-clock resources and the PLL in the
same quadrant.

---

## 2. Topology and ownership

### 2.1 Why the companion emulates rather than bridges

**Corrected 2026-09-03.** An earlier draft of this section claimed a
transparent SPI bridge was "physically impossible" on a `tMISO` = 12 ns
argument. **That argument was wrong** and is recorded here rather than
quietly deleted, because the error is instructive: `tMISO` is an *AC
parameter* — how fast the chip drives MISO after a clock edge once it
holds the data — not the protocol's data latency. The RHD2164 protocol is
**pipelined two commands deep** (`rhd2164_defs.vh`: *"Result is sent to
Master two commands later"*; `regbank.v`: *"Remember there is a delay of 2
SPI cycles"* — a fact §9.2 of this same document already relied on). The
real budget is two full SPI transactions, **1333–1405 ns**, against a
tunnel round trip of **281–703 ns**. Latency is not the obstacle.

The Intan controller is the **SPI master**, confirmed from
`kuntur144-omnetics.kicad_pcb`, connector `J1` — the 12-pin Omnetics that
mates with the Intan controller's headstage cable:

```
T1 CSbp   B1 CSbm      T4 MISO0p  B4 MISO0m
T2 SCLKp  B2 SCLKm     T5 MISO1p  B5 MISO1m
T3 MOSIp  B3 MOSIm     T6 VDD1    B6 GND1
```

With that established, "bridge" splits into two genuinely different
architectures with different answers.

#### Case A — both masters execute on the real chip. Ruled out by physics.

Not latency: **bus saturation**.

| | transactions/s |
|---|---|
| RHD2164 bus capacity (46 clk/transaction @ 45.539955 MHz) | 989,999 |
| Kuntur's own sampling frame (33 slots × 29,999.97) | 989,999 |
| **Bus utilisation today** | **100.0%** |
| Intan controller demand (35 cmd/frame × 30 kSPS) | 1,050,000 |
| **Combined** | **2,039,999 = 2.06× capacity** |

There is no relief available. `sck` is already `clk`/2 = 22.77 MHz against
the RHD2164's published 24 MHz ceiling — **5.4% headroom, not 106%**.
Serving both masters would require roughly halving Kuntur's own sample
rate, which destroys the thing the comparison exists to validate.

#### Case B — Intan sole master, Kuntur relays. Feasible; deferred as out of scope.

One master, no contention, and the latency fits with 2–5× margin. **This
is a real and sound architecture** — and Manuel's original conception of
the bridge, for a *different product configuration*: a wired-only
headstage with no wireless mode.

It is **deferred, on scope grounds rather than technical ones**
(Manuel, 2026-09-03): *"It is definitely worth doing but not as part of
this project: it adds complexity for a goal that is different than the
verification that it needs to be."* Building it here would mean creating
a second architecture in order to verify the first one.

Recorded so a future revisit starts from the real consequences rather than
re-deriving them. Case B would:

- make Kuntur a slave, contradicting §2.3's ownership decision;
- make the RHD2164 sampling cadence the Intan controller's, so the **BLE
  stream's sample rate would differ between wired and wireless mode** —
  invalidating A.6.5's recorded `sample_rate` and A.7's λ, and contradicting
  §6.1's free-running decision;
- make **cable loss fatal to the wireless recording**. Today the tunnel is
  a tap (§2.5) and an unplugged cable is harmless. In Case B, pulling the
  cable stops the AFE. In vivo, that is a serious regression;
- make **CRC on the command path unaffordable**. PLAN.md's CRC requirement
  exists precisely because *"a corrupted RHD2164 command during surgery
  silently changes what the operator sees"* — but Case B carries commands
  inside a ~1.3 µs budget, with no time for store-and-forward CRC over a
  frame and no time to retry a corrupted command. The one path the plan
  most wanted protected would be the least protectable.

That last point is worth keeping: in Case C, Intan-originated commands
never cross the cable at all, so the risk does not exist to be mitigated.

#### Case C — Kuntur sole master, companion emulates. What this spec specifies.

No bus contention, **no latency requirement on the tunnel whatsoever**,
and link loss cannot touch the wireless path. The companion answers the
Intan controller from a continuously replicated local buffer:

> The companion FPGA is an **RHD2164 emulator backed by a replicated
> buffer**. It does not fetch on demand — not because it could not, but
> because it does not need to: Kuntur is already converting every channel
> every frame, so every value the Intan controller can ask for is already
> in hand before it asks.

### 2.2 The resulting topology

```
                      Kuntur headstage                    │  companion (LIFCL-40-EVN)
                                                          │
 RHD2164 ×2 ─SPI1─► spi_master_rhd2164x2 ─┬─► ch_sel ─► fifo0 ─► spi0 ─► MCU ─► BLE ─► bridge ─► pc-app
   (real                                  │             (2 selected channels, unchanged)
    AFE)                                  │
                                          └─► tunnel TX ═══ E9/E8 ═══► tunnel RX ─► frame buffer
                                              (all 128 ch)   uHDMI          │        (128 ch × 1 frame)
                                                                            ▼
                                              tunnel RX ◄══ G9/F9 ═══ tunnel TX   RHD2164 emulator
                                              (link status)                            │ SPI slave
                                                                                       ▼
                                                                            Omnetics ─► Intan controller
                                                                                        (SPI master)
```

Two independent readouts of **one** AFE, which is precisely what PLAN.md's
"Why the wired path is worth the effort" argues for: one signal, one AFE,
two readouts, sample-for-sample comparable.

### 2.3 Ownership — Kuntur owns configuration, exclusively

**Decision, Manuel, 2026-09-02.** The Intan controller is a visualiser.
Kuntur configures the RHD2164 pair; that configuration is *replicated*
into the companion so the Intan controller's register reads return the
**true, live state of the real chips**, not an echo of what the Intan host
last wrote.

This settles PLAN.md **A.5** ("RHD2164 bus arbitration — two masters want
the AFE") by construction rather than by mechanism:

| A.5 requirement | How this discharges it |
|---|---|
| "Explicit ownership model" | Kuntur owns, always, unconditionally. There is no arbiter, no handover, no mode in which ownership is ambiguous. |
| "If the Intan controller reconfigures gain/bandwidth mid-session, the BLE recording silently changes meaning and the file has no record of it" | **It cannot.** No path exists from the Intan controller to the RHD2164 registers. §4.4's `CONFIG` frame makes the information flow strictly one-way. |
| "Live RHD2164 register state captured into the recording metadata" | Same `CONFIG` frame content, same source of truth, also fed to A.6.5's sidecar. §9.4. |

The cost, stated plainly: **the operator configures via Vega, not via the
Intan software.** Register writes issued by RHX / Open Ephys are absorbed
by the emulator and reported, not applied (§9.3). This is a real workflow
change from PLAN.md's de-risking ladder rung 1, where the Intan controller
was the only thing present and naturally owned the chip. It must be
written into the bench procedure and the animal-test runbook, not
discovered on the day. Tracked as open item **O6**.

### 2.4 What the Intan controller may and may not do

| Operation | Allowed | Behaviour |
|---|---|---|
| `CONVERT(C)` | yes | Answered from the replicated frame buffer, §9.2 |
| `READ(R)` | yes | Answered from the replicated register state, §9.1 |
| `WRITE(R,D)` | **absorbed** | Correct RHD2164 ack returned so the host's protocol never stalls; the write is **not applied**; counted and reported at the companion's own console, §9.3 |
| `CALIBRATE` / `CLEAR` | **absorbed** | Datasheet-correct response returned; not forwarded. §9.3 |

The emulator always returns a *protocol-valid* answer. Silently stalling
the Intan host, or answering with something it does not expect, converts a
policy decision into a mysterious hardware fault at the bench.

### 2.5 The tunnel is a read-only tap

The downstream payload is taken from `spi_master_rhd2164x2`'s existing
outputs `data_rx_a`, `data_rx_b`, `data_rx_a1`, `data_rx_b1`
(`kuntur_fpga.v`), at the same point `ch_sel` reads them. It adds **no**
electrical load to the RHD2164 SPI bus, **no** logic in the
`ch_sel → fifo_din_mux0 → fifo0` path, and **no** new SPI transactions.

**This is a hard requirement, not an implementation nicety**, and §11's
open item **O3** is about protecting it: SPI1 on this board has a known,
unresolved marginal-timing story (the chip0 / SCK-MOSI board-level trace
asymmetry, PLAN.md B.5 and the 2026-08-31 log). Adding a fast serialiser
and a new PLL near those pins is exactly the kind of change that has
regressed it twice. The standing rule from that investigation applies
verbatim here:

> Any new placement constraint must be added **alongside**
> `mregion0`–`mregion7`, never by removing them.

---

## 3. What has to cross, and how much of it

### 3.1 The Kuntur sampling frame — verified numbers

All from source, cross-checked against each other:

| Quantity | Value | Source |
|---|---|---|
| `clk` | 45.539955 MHz (21.9587393093 ns) | `pll0/constraints/pll0.ldc` `CLKOP_FREQ_ACTUAL`; `impl_1.sdc` |
| SPI1 `sck` | `clk`/2 = 22.769978 MHz | `spi_master_controller` — one `clk` high (`sckNb`), one low (`sckNd`) |
| Bits per SPI slot | 16 | `spi_master_rhd2164x2`, `localparam n = 16` |
| `clk` per slot | **46** | `idle`+`op0`+`op1` + 32 sck states + 8 `csbend` states |
| Slots per sampling frame | **33** | `RB_SAMPLING_MAX = 6'd32` → `cnt0` = 0…32 |
| `clk` per frame | **1518** | 33 × 46 |
| **Frame rate** | **29,999.97 Hz** | 45,539,955 / 1518 |

That last figure is the independent confirmation this section exists for:
**29,999.97 Hz** is exactly the `sample_rate.channel_hz` A.6.5's sidecar
already writes (`recording-format.md` §2.1, sourced from the 2026-08-27
PLL retune). Two entirely separate derivations agreeing is worth more than
either alone.

Of the 33 slots, **32 are channel conversions** and one is the alternate
command slot (`rhd2164_controller`'s header: "32 channel conversions +
1 alternate-command placeholder").

### 3.2 Downstream payload — all 128 channels

Per SPI slot the RHD2164 pair returns four 16-bit halves —
`data_rx_a`/`data_rx_b` (chip 0) and `data_rx_a1`/`data_rx_b1` (chip 1) —
because each RHD2164's MISO is DDR, A launched on the SCLK rising edge and
B on the falling.

```
32 conversion slots × 4 halves × 16 bit = 2048 bit = 256 byte per frame
256 B × 29,999.97 frame/s            = 7.68 MB/s = 61.44 Mbit/s
```

**61.44 Mbit/s** is the number the link must carry, before framing, CRC
and line coding. 128 channels × 29,999.97 SPS × 16 bit gives the same
figure from the other direction.

### 3.3 There is no upstream payload

Decision 4 removes the return channel. Nothing flows from the companion to
Kuntur — not sample data, not commands, not status.

The diagnostics an earlier draft sent upstream (link state, CRC-failure
count, rate-slip counters, absorbed-write reports) do not disappear; they
move to **the companion's own interface**. The LIFCL-40-EVN is a
development board with its own USB and UART, and a counter read there is
strictly more accessible than one relayed through Kuntur → BLE → bridge →
pc-app. §5 and §9.4.

One consequence to be explicit about: **Kuntur cannot detect that the
companion has stopped listening.** That is acceptable, and §7.2 explains
why — the tunnel is a tap, so nothing Kuntur does depends on the answer.

### 3.4 Channel numbering, and a duplication hazard worth naming now

The tunnel carries **slot-indexed raw halves**, not channel-indexed
samples. Mapping slot → physical channel is the same mapping already
specified in `channel-selection-control-plane.md` §1a (the 4-way split:
chip0-A = 0–31, chip0-B = 32–63, chip1-A = 64–95, chip1-B = 96–127) and
§1a-addendum (the hardware-confirmed `SLOT_OFFSET = 3` pipeline
correction, from the RHD2164 returning a `CONVERT` result two commands
later — see also `regbank.v`'s own comment, *"Remember there is a delay of
2 SPI cycles"*).

**The hazard:** that correction currently lives in the pc-app
(`channel_mapping.py`'s `physical_to_wire()`), added 2026-08-29 under an
explicit instruction not to touch firmware. If the companion FPGA
implements it too, the same hardware fact will exist in **three** places —
`diagnostics.py`'s `SLOT_OFFSET`, `channel_mapping.py`, and new RTL — with
`FPGA_SPI_ChannelToRaw()` in the MCU still not applying it at all. That
divergence is what produced the offset bug in the first place: two
documents and one implementation that were never reconciled.

**Recommendation, before companion RTL is written:** fix the offset at its
source (RTL or MCU) and delete the compensations, or if it must stay
compensated, make this spec the single normative statement and have every
consumer cite it. Do not let the companion become the third copy. Tracked
as open item **O4**.

For v1 the tunnel's contract is deliberately dumb and therefore safe:

> `SAMPLE` payload slot *s* carries exactly what the SPI master captured
> in conversion slot *s*, in acquisition order, with no reordering and no
> offset correction applied. Interpretation is the receiver's job.

---

## 4. Frame format (Kuntur → companion, `TUN_DATA` on G9/F9)

### 4.1 Common frame structure

Every frame is: **4-byte preamble, 8-byte header, variable payload,
4-byte CRC-32.** All multi-byte fields are **little-endian**, matching the
BLE stream packet format and the RHD2164 register conventions already in
use across this project. Offsets below are relative to the end of the
preamble.

| Offset | Size | Field | Notes |
|---|---|---|---|
| −4 | 4 | `preamble` | `0xA5 0x5A 0xA5 0x5A` — frame delineation, §6.6. Not covered by the CRC. |
| 0 | 1 | `frame_type` | §4.2 |
| 1 | 1 | `flags` | §4.5 |
| 2 | 4 | `frame_index` | `uint32`, Kuntur sampling frames since reset. §10 |
| 6 | 2 | `payload_len` | `uint16`, payload bytes, excluding header and CRC |
| 8 | *n* | payload | |
| 8+*n* | 4 | `crc32` | §4.6 |

`frame_index` is deliberately the same shape and the same reasoning as
`stream-packet-format.md` §3.1's `sample_index`: a `uint32` at ~30 kHz
wraps in **39.8 hours**, well past any plausible session, and receivers
must compare it modularly rather than with `<`.

### 4.2 Frame types

| Value | Name | Direction | Cadence |
|---|---|---|---|
| `0x01` | `SAMPLE` | ↓ | one per sampling frame, 29,999.97 Hz |
| `0x02` | `CONFIG` | ↓ | on change, plus a full refresh every 1000 frames (~33 ms) |
| `0x03` | `STATUS` | ↓ | every 300 frames (~10 ms) |

`0x81`/`0x82` were upstream types in the bidirectional draft and are now
**permanently reserved** — never emitted, never accepted — so that a
future revisit cannot silently reuse a value with prior meaning.

Types `0x00` and `0xFF` are reserved and must never be emitted, so that a
stuck-low or stuck-high line cannot forge a valid `frame_type`.

### 4.3 `SAMPLE` (`0x01`) — 256-byte payload

Slot-major, then half-major within a slot:

```
payload[0..255]:
  for s in 0..31:                       # conversion slot index
    uint16  data_rx_a  [chip 0, MISO A]  # bytes 8s+0, 8s+1
    uint16  data_rx_b  [chip 0, MISO B]  # bytes 8s+2, 8s+3
    uint16  data_rx_a1 [chip 1, MISO A]  # bytes 8s+4, 8s+5
    uint16  data_rx_b1 [chip 1, MISO B]  # bytes 8s+6, 8s+7
```

`payload_len` = 256, always. The values are **raw**, exactly as captured:
two's complement (`RHD_TWOSCMP = 1'b1`, `rhd2164_defs.vh`), no offset
correction (§3.4), no scaling, no sentinel substitution.

The 33rd slot — the alternate-command slot — is **not** carried. It holds
whatever `RB_SAMPLING_BASE + 32` was configured with, which is control
plane traffic, not signal. If a future mode needs it (an aux-channel or
temperature read), it becomes `payload_len` = 264 with a `flags` bit
announcing it, which is why `payload_len` exists as a field rather than
being implied by `frame_type`.

### 4.4 `CONFIG` (`0x02`) — configuration replication

This is decision 1's mechanism (§2.3): the companion's answer to any
Intan-controller `READ(R)` comes from here.

```
payload[0]      uint8   chip_mask        # bit0 = chip0, bit1 = chip1
payload[1]      uint8   reg_count        # number of (reg, val) pairs following
payload[2..]    { uint8 reg; uint8 val_chip0; uint8 val_chip1; } × reg_count
```

Rules:

- **Kuntur is the sole source.** A `CONFIG` frame is emitted whenever
  Kuntur's regbank configuration table changes, and unconditionally as a
  full refresh every 1000 frames so a companion that joined late, or lost
  sync, converges within ~33 ms without any request/response handshake
  existing to go wrong.
- The values must be Kuntur's **real** register state — the config table
  actually walked by `rhd2164_controller` out of `RB_CONFIG_BASE` — not a
  compile-time constant table. A replicated fiction is worse than no
  replication, because it looks authoritative.
- The **ROM registers 40–44, 59–63 are included** even though they are
  constants, so the companion has exactly one code path for answering
  reads. §9.1.
- Read-back verification is not part of this frame. Whether Kuntur's
  regbank matches what the silicon actually holds is A.1.1's ladder
  question and `fpga-diagnostic-access.md`'s, and it is not made truer by
  copying it across a cable.

### 4.5 `flags`

| Bit | Name | Meaning |
|---|---|---|
| 0 | `STREAM_ENABLE` | mirrors the regbank `stream_enable` bit; when 0 the BLE path is stopped but the tunnel keeps running |
| 1 | `TEST_PATTERN` | `data_source_sel` selects `test_pattern_gen0` — **the samples are synthetic** |
| 2 | `CONFIG_DIRTY` | configuration changed within this frame; a `CONFIG` frame follows |
| 3 | `FIFO_OVERFLOW` | `fifo0` discarded a write since the last frame (A.7 step 1) |
| 4–7 | reserved, zero | |

Bit 1 is not optional bookkeeping. PLAN.md A.1's original defect was
precisely that *"every metric in the entire SKP/throughput investigation
measured a synthetic ramp"* with nothing on the wire saying so. A readout
that can be compared against a reference instrument must state, in band,
whether it is showing real silicon. Bit 3 is the tunnel's view of A.7
step 1's overflow counter and should be wired from the same source, not a
second one.

### 4.6 CRC-32

**CRC-32** (IEEE 802.3 polynomial `0x04C11DB7`, initial value
`0xFFFFFFFF`, reflected in and out, final XOR `0xFFFFFFFF`) computed over
**header and payload**, i.e. bytes 0 … 7+*n*.

`stream-packet-format.md` §3.5 argued against a header CRC on the BLE hop
and was right: BLE already CRCs and retransmits that hop, so the check
would have protected something already protected. **The opposite holds
here.** This is a raw LVDS pair on a hand-made pigtail with no
retransmission, no link-layer FEC, and no other integrity mechanism
anywhere in the path. It is the least-protected hop in the entire system
and it feeds a reference instrument whose whole value is being
trustworthy.

Cost is negligible: 268 bytes at 29,999.97 Hz is 8.04 MB/s of CRC input,
a byte-serial CRC-32 at the ~15–23 MHz symbol clock of §6.2, a few dozen
LUTs against the 4% currently used.

**On CRC failure the companion must not serve the frame.** See §7.3 — the
rule is that a corrupt frame becomes a visible gap, never silently
repeated previous data.

---

## 5. There is no upstream frame format

Removed by decision 4. This section is kept as a heading so the numbering
of every later section stays stable against earlier drafts and against
PLAN.md's references.

The counters that would have travelled upstream are **still required** —
they are how link health and rate slip get quantified rather than
asserted, which is the standard this project holds everywhere else
(A.7's whole premise). They are simply reported at the companion, over its
own USB/UART:

| Counter | Meaning |
|---|---|
| `frames_received` | `SAMPLE` frames accepted |
| `frames_crc_failed` | frames rejected on CRC |
| `frames_sentinel_served` | Intan frames answered with `0x8000` because no valid data was held (§7.3) |
| `slip_repeat` | an Intan frame was served a repeated Kuntur frame (§9.5) |
| `slip_skip` | a Kuntur frame was never served to Intan (§9.5) |
| `host_writes_absorbed` | Intan register writes absorbed and not applied (§9.3) |

All **saturating, never wrapping** — same convention A.7 step 1 sets for
the FPGA overflow counter, and for the same reason: a wrapped counter
reading zero is indistinguishable from a healthy link.

## 6. Clocking and rate — a source-synchronous link

### 6.1 Free-running — decision 2, and what it buys

**Kuntur's `clk` continues to come from `pll0` off `clkin` (the MCU's
32 MHz MCO3/PB14), always, whether or not the companion is attached.**

The rejected alternative was loop timing — Kuntur locking its sampling
frame to a reference recovered from the companion. It was rejected because
it makes Kuntur's **master sampling clock source depend on whether a cable
is plugged in**, so the BLE stream's real sample rate would differ between
wireless and wired mode, colliding with A.6.5's recorded `sample_rate` and
A.7 step 3's premise of choosing λ against a measured µ.

Decision 4 makes this cleaner than it was. The link is now **loop-timed in
the other direction**: Kuntur forwards its own clock and the companion
derives everything from it. Kuntur is the timing master of both the AFE
and the cable; the companion has no clock of its own in the datapath.

Consequences accepted, handled in §9.5 and §10:

- Kuntur's frame rate (29,999.97 Hz, its own crystal via `clkin`) and the
  Intan controller's frame rate (its own crystal) differ by their combined
  tolerance. At ±100 ppm the relative drift is **~1 frame every 5.6 s**,
  ~107 frames over a 10-minute run, ~3.6 ms accumulated skew.
- Dealt with by a one-frame elastic buffer plus **counted** slip in the
  companion (§9.5) — never silent repetition — and a shared physical
  marker for absolute alignment (§10).

### 6.2 No line code — what decision 4 bought

An earlier draft specified 8b/10b and paid 25% for it. With a forwarded
clock, **none of the four things 8b/10b provides is still needed here**:

| Property | Still needed? |
|---|---|
| **DC balance** (bounded running disparity) | **No.** That is for AC-coupled links. This one is DC-coupled — verified from `kuntur144-ecl.kicad_pcb`: each of the four tunnel nets has exactly **two pads**, an FPGA ball and a connector pad. No series capacitor, resistor or termination component anywhere. |
| **Guaranteed transition density** | **No.** Only required when the receiver recovers its clock from the data. It does not — the clock arrives on its own pair. |
| **Comma / word alignment** | **No comma symbol needed.** The forwarded clock *is* the word boundary (§6.4). |
| **Code-violation detection** | **No.** Redundant with the CRC-32 that §4.6 already requires. |

Worth recording *why* it was needed in the bidirectional design, since it
is a real property of this data: **RHD2164 samples cannot self-clock under
any circumstances.** The `0x8000` link-loss sentinel is fifteen zeros and a
one; a quiet or railed channel produces long runs with no edges. A
self-clocked link would have lost lock exactly when the signal went quiet —
the worst possible moment. That risk is now designed out rather than
mitigated.

### 6.3 Gearing — `ODDRX4`, one byte per word

With the line code gone, the natural gearing changes with it. 10:1
(`ODDRX5`) existed only because an 8b/10b symbol is ten bits. Raw data is
**byte-oriented**, and so is every frame field in §4 — so 8:1 is the right
ratio:

- **`ODDRX4`** — hardened 8:1 output gearbox, `D0..D7`, `SCLK` = `ECLK`/4,
  DDR on `ECLK`. **One byte per `SCLK` cycle**, so §4's frame maps onto
  words 1:1 with no bit-packing logic at either end.
- **`IDDRX4`** — the matching 1:8 deserialiser on the companion.

Confirmed present in the installed Radiant 2025.2.1 LIFCL primitive
library (`cae_library/simulation/verilog/lifcl/`), alongside `ODDRX1`
(2:1), `ODDRX2` (4:1), `ODDR71` (7:1) and `ODDRX5` (10:1). O2's original
question — is 10:1 hardened, or is an 8→10 fabric gearbox needed — is moot
now that 8b/10b is gone, but the answer was *hardened*, and it is what
would be reached for if a line code ever returns.

### 6.4 The clocks — and no new PLL output

| Clock | Source | Frequency | Role |
|---|---|---|---|
| `clk` | `pll0` `CLKOP`, `FVCO`/35 | 45.5399554 MHz | existing sampling domain, **unchanged** |
| **`ECLK`** | **`clk`** | **45.5399554 MHz** | tunnel edge clock; DDR → **91.079911 Mbps** on `TUN_DATA` |
| **`SCLK`** | **`ECLKDIV`, `ECLK_DIV=4`** | **11.3849888 MHz** | word clock — one byte per cycle; also what is forwarded on `TUN_CLK` |

**`ECLK` is `clk` itself.** No new PLL output is required at all — the
second PLL stays free *and* `pll0`'s four spare outputs stay spare. This
is the direct consequence of Manuel's observation (2026-09-03) that a
serialiser clock at 2 × `clk` = 91.08 Mbps already clears the requirement.

`SCLK` cannot come from the PLL — it would be `FVCO`/140, and `O_DIV` caps
at **128** (`ip/lifcl/pll/plugin/plugin.py`, `PARAM_RANGE`). It comes from
**`ECLKDIV`** instead, whose `ECLK_DIV` parameter accepts
`{2, 3P5, 4, 5}` — **÷4 is supported**, verified in the primitive library.
Because `ECLKDIV` is fed by `ECLK`, the PLL divider limit never applies.

`ECLKSYNC` is likely needed to get `clk` onto the edge-clock network
cleanly; that is an implementation check, not an assumption (O2a).

**Everything in the tunnel is therefore an integer division of `clk`,**
which is what §2.5's read-only tap needs: the serialiser reads
`spi_master_rhd2164x2`'s capture registers with no synchroniser, no async
FIFO, and no CDC exception in the `.sdc`.

### 6.5 Rate — the arithmetic

```
payload      128 ch x 29,999.97 SPS x 16 bit                 = 61.44 Mbit/s
frame        4 preamble + 8 header + 256 payload + 4 CRC     = 272 byte
required     272 B x 29,999.97 Hz x 8                        = 65.28 Mbit/s
delivered    2 x ECLK  (no line code, so line rate = data)   = 91.08 Mbit/s
headroom                                                     = 1.40x
```

Per sampling frame there are `SCLK`/29,999.97 = **379.5 byte slots**, of
which 272 carry the frame and **107.5 are spare (28%)** for `CONFIG`,
`STATUS` and idle. The fractional 0.5 is not a problem: idle padding
absorbs it and the phase pattern repeats every two frames.

*(An earlier draft treated "integer byte slots per sampling frame" as a
requirement and built a divider ladder around it. It is not one — idle
padding absorbs a fractional remainder by construction, and with `SCLK` an
integer division of `clk` the relationship is a counter, not a
clock-domain crossing.)*

The 25% that 8b/10b would have cost is what makes 91.08 Mbps comfortable
where it would otherwise have been marginal: the same payload under 8b/10b
needed an 80.40 Mbps *coded minimum*, leaving almost nothing.

### 6.6 Word alignment, training and lock

No comma symbols exist, so alignment works differently from the
bidirectional draft:

- **Byte alignment is free.** `TUN_CLK` carries `SCLK`, and its edge *is*
  the word boundary. The companion recovers `ECLK` by multiplying it ×4 in
  its own PLL, choosing a phase that centres the data eye. At 91.08 Mbps
  the bit period is **10.98 ns** — a wide eye for a short DC-coupled link,
  and the reason a fixed phase relationship is sufficient rather than a
  per-lane training sweep.
- **Frame alignment** comes from a **4-byte preamble** (`0xA5 0x5A 0xA5
  0x5A`) plus fixed cadence. Raw binary data can coincidentally contain
  the preamble, so the preamble alone is not trusted: the receiver
  declares lock only after **two consecutive frames whose CRC-32 validates
  and whose `frame_index` increments by one**, and thereafter tracks by
  cadence rather than by re-searching.
- **No handshake, no negotiation, no capability exchange.** Kuntur
  transmits from reset regardless of whether anything is listening; the
  companion locks whenever it can. A cable plugged in mid-session
  therefore just works, and there is no state machine that can deadlock.

## 7. Link loss — detection and required behaviour

This is the section with the safety content in it. The failure mode being
designed against is not "the link breaks" — it is **"the link breaks and
the Intan controller keeps displaying plausible-looking data"**, during a
procedure, on an anaesthetised animal.

### 7.1 Detection, companion side — and the forwarded clock makes it better

The companion declares the link **down** when any of:

- **`TUN_CLK` stops toggling** for more than 8 `SCLK` periods (~700 ns).
  This is new, and it is the strongest detector in the design: under
  decision 4 the clock is a *continuous, data-independent carrier*, so its
  absence is unambiguous and near-instant. A self-clocked link could only
  ever infer link loss from *absent data*, which is exactly what a quiet
  signal also looks like.
- No valid `SAMPLE` frame accepted for **1 ms** (≈ 30 frames) — an order
  of magnitude above ordinary jitter, far below human reaction time.
- 16 consecutive CRC failures.

A cable pulled mid-session breaks `TUN_CLK` and `TUN_DATA` together, so
in practice the first condition fires first, and the sentinel of §7.3 is
being served within a microsecond of the disconnection.

### 7.2 Kuntur side — nothing to detect, and nothing to do

Kuntur has no receiver (§3.3, §5). It cannot tell whether the companion is
listening, powered, or connected, and **it does not need to**:

- The tunnel is a **read-only tap** (§2.5). Kuntur keeps sampling,
  streaming over BLE and recording exactly as it would with no cable.
- Kuntur transmits unconditionally from reset (§6.6), so there is no state
  to recover and no reconnection sequence to run.

This is a genuine simplification over the bidirectional draft, which
needed a 10 ms heartbeat timeout and a status bit whose only purpose was
to be ignored. The safety-critical direction is the other one, §7.3.

### 7.3 Required behaviour on the Intan side — the important one

When the downstream link is down, or a frame fails CRC, the companion
**must** serve the sentinel `0x8000` to the Intan controller, on every
channel, for exactly as long as it has no valid data.

It must **never**:

- repeat the last good frame,
- interpolate, hold, or smooth,
- freeze on the last value,
- or fall back to a synthesised pattern.

`0x8000` is chosen for two reasons, both of which matter:

- **It is already this project's underrun sentinel.** `fifo.v` returns
  `{2{16'h8000}}` on read-while-empty, and the pc-app already understands
  it (`recording-format.md`, and the 0.4% genuine underrun measured on the
  2026-08-31 recording was found by counting exactly this value). Reusing
  a convention beats inventing a second one.
- **Under `RHD_TWOSCMP = 1` it is full-scale negative**, so on the Intan
  controller's own display it appears as a hard rail on every channel at
  once — visually unmistakable, and impossible to mistake for signal. A
  repeated-frame fallback would instead look like a *quiet, stable
  recording*, which is the worst possible appearance for a dead link.

Every sentinel-served frame increments `frames_sentinel_served`
(§5), so the gap is quantified and not merely visible.

### 7.4 Cable insertion and removal

The link must survive both, at any time, in either order, without either
end requiring a reset. §6.4's handshake-free bring-up is what makes this
true; §7.1/§7.2's timeouts are what make it detected.

---

## 8. Latency budget

PLAN.md A.4 asks for a latency budget; A.3 notes end-to-end latency is
unmeasured and safety-relevant for surgical use. These are **design
targets to be confirmed on hardware**, not measurements.

| Stage | Estimate | Basis |
|---|---|---|
| RHD2164 conversion → captured in `data_rx_*` | ≤ 1 slot = **1.01 µs** | 46 `clk` @ 45.539955 MHz |
| Frame assembly (32 slots complete) | **33.33 µs** | one sampling frame; a frame cannot be sent before it exists |
| Kuntur serialisation, 272 B @ 11.385 MB/s | **23.89 µs** | §6.5 |
| Cable propagation | **< 10 ns** | ~2 m at ~5 ns/m |
| Companion deserialise + CRC validate | **23.89 µs** | symmetric; the frame must be CRC-valid before it may be served (§7.3) |
| Companion elastic buffer | **0 – 33.33 µs** | up to one frame, phase-dependent (§9.5) |
| Intan controller SPI readout | its own frame period | not ours to budget |
| **Kuntur ADC → available at the Omnetics connector** | **≈ 82 – 115 µs** | sum of the above |

Three observations:

- **Frame assembly and serialisation dominate**, and neither is a link
  design problem. Sub-frame latency would mean sending partial frames,
  which is not worth the complexity for a 33 µs gain.
- **The lower line rate costs latency.** At the 8b/10b draft's higher
  symbol rate the two serialisation terms were smaller; 91.08 Mbps makes
  each ~24 µs. That is the honest price of §6.5's rate choice, and it is
  the right trade — 30 µs of extra latency is irrelevant to a visualiser,
  whereas switching noise beside a µV-scale AFE is not.
- **The tunnel still adds ~0.1 ms against the BLE path's tens of
  milliseconds.** For A2's purposes the wired path is effectively
  instantaneous relative to the wireless one — and the two latencies are
  so different that §10's alignment work cannot be skipped by assuming
  simultaneity.

## 9. The Intan-side emulation contract

What the companion must present on the Omnetics connector. This is the
half of A.4's third checkbox ("Companion FPGA RTL: deserialise, reassemble
SPI, drive the Intan controller") that is an *interface* obligation rather
than an implementation choice.

### 9.1 The registers that must answer, or the host will not proceed

The Intan host software identifies a headstage by reading ROM registers.
All values below are from `rhd2164_defs.vh` and are what the real chips on
`kuntur144-nil` return:

| Register | Value | Meaning |
|---|---|---|
| 40–44 | `0x49 0x4E 0x54 0x41 0x4E` | `"INTAN"` company designation |
| 59 | `0x35` on MISO A, `0x3A` on MISO B | **DDR MISO A/B marker — this is what identifies the part as an RHD2164 rather than an RHD2132** |
| 60 | die revision | |
| 61 | `1` | unipolar amplifiers |
| 62 | `64` | number of amplifiers |
| 63 | `4` | Intan chip ID, RHD2164 |

Register 59 deserves emphasis: returning **different** values on MISO A
and MISO B is how a host distinguishes a 64-channel DDR part from a
32-channel one. An emulator that drives both MISO lines identically will
be detected as the wrong chip. These are the same `0x0035` / `0x003A`
values A.1.1's ladder rung `L` checks and that passed on real hardware on
2026-08-31 — the emulator can be validated against the very same rung.

Registers 0–21 (configuration) are answered from the replicated `CONFIG`
state, §4.4.

### 9.2 Answering `CONVERT` — decode, do not count

**The emulator must decode the `CONVERT(C)` command word on MOSI and
answer with channel `C`. It must not infer the channel from a slot
counter.**

This is a deliberate robustness requirement, and it is what makes the
emulator independent of the Intan controller's frame layout, frame length,
command ordering and sample rate — none of which this project controls,
and none of which need to be documented here as a result. Kuntur's frame
is 33 slots; the Intan controller's is its own; the emulator never needs
to know.

The emulator must also reproduce the RHD2164's **two-command pipeline**:
the result of `CONVERT(C)` is returned two transactions later, not
immediately (`rhd2164_defs.vh`: *"Result is sent to Master two commands
later"*; `regbank.v`: *"Remember there is a delay of 2 SPI cycles"*). A
host that pipelines its reads — and Intan's does — will otherwise receive
every sample two slots early and misattribute all 64 channels.

`CONVERT(63)` has the special meaning "cycle through successive
channels"; if the Intan host uses it, the emulator must maintain the same
internal advance the real chip does.

### 9.3 Absorbed writes

`WRITE(R,D)` returns the datasheet-correct acknowledgement —
`{8'b11111111, D}`, per `RHD_WRITE_RSPND_TOPBYTE` — so the host's protocol
completes normally. The write is **not applied**, the replicated state is
**not modified**, and `host_writes_absorbed` (§5) counts it at the
companion's console.

`CALIBRATE` and `CLEAR` likewise return their datasheet responses
(`RHD_CALIBRATE_RSPND_*`, `RHD_CLEAR_RSPND_*`) and are not forwarded.

The subsequent `READ(R)` will return Kuntur's real value, not the value
the host just wrote. **This is intended and is the entire point of
decision 1** — but it will look like a fault to anyone who does not know,
so it must appear in the runbook (open item **O6**) and, ideally, in the
companion's own status output.

### 9.4 Surfacing absorbed writes to the operator

Under decision 4 there is no upstream path, so absorbed writes are
reported at **the companion's own USB/UART** (§5) rather than relayed
through Kuntur's telemetry.

This is a downgrade in one respect worth stating plainly: "the Intan
software tried to change the bandwidth and we ignored it" no longer
reaches the Vega pc-app, where the operator is already looking. It reaches
a second console instead. The mitigation is procedural, not technical, and
belongs with O6's runbook item.

A.5's *"live RHD2164 register state captured into the recording
metadata"* is unaffected — that state originates in **Kuntur's** regbank,
not in anything the companion reports, so A.6.5's sidecar takes it
directly from the same source that feeds the `CONFIG` frame. One source of
truth, two consumers.

### 9.5 Rate slip — bounded, and counted

Kuntur produces frames at 29,999.97 Hz; the Intan controller consumes at
its own rate. The companion holds the most recent complete `SAMPLE` frame
and serves from it:

- **Intan faster than Kuntur** → a Kuntur frame is served twice.
  Increment `slip_repeat`.
- **Intan slower than Kuntur** → a Kuntur frame is never served.
  Increment `slip_skip`.

At ±100 ppm combined this is ~1 event every 5.6 s (§6.1) — small, slow,
and *entirely expected*. It is specified here so that it is understood as
designed behaviour rather than rediscovered as a defect, and counted so
that "how much did the two recordings actually diverge" has a number
instead of an argument.

The elastic buffer is **one frame deep, not more**. Deeper buffering trades
latency for a slip rate that is already negligible, and hides the
divergence this project wants measured.

---

## 10. Time alignment for A2 — the sync marker

Free-running clocks (§6.1) mean the two recordings share no clock. For
A2's claim — *"sample-for-sample agreement is calibration against an
established instrument"* — they must be alignable to a known accuracy.

Three mechanisms, in increasing order of strength; v1 should implement the
first two and specify the third:

1. **`frame_index`** (§4.1) gives the companion an exact Kuntur frame
   number for every sample it serves. The companion can log, for each
   Intan frame it answers, which `frame_index` fed it. That is a complete
   alignment record — but it lives on the companion, not in either
   recording, so it needs somewhere to go (the companion's own debug
   interface, out of scope here).

2. **`slip_repeat` / `slip_skip`** (§5) give the accumulated drift as a
   count, so a post-hoc resampling correction is measured rather than
   assumed.

3. **A shared physical marker — recommended, and nearly free.** The
   RHD2164's own impedance-check DAC (registers 5–7: `RHD_ZCHECK_DAC`,
   `RHD_ZCHECK_SEL`, `RHD_ZCHECK_EN`) injects a known signal into a
   selected channel **with no external hardware**, which PLAN.md A.3
   already identifies as the tier-1 stimulus. Because Kuntur owns
   configuration (§2.3), Kuntur can pulse it at a known `frame_index`.

   The resulting edge appears in **both** recordings, on the same physical
   AFE, in the same channel — the wireless CSV and the Intan file — giving
   an unambiguous common time origin that no clock relationship is needed
   to establish. Repeat it periodically and the drift between markers *is*
   the drift measurement, directly, without trusting either crystal.

   This costs a few register writes and reuses hardware that is already
   present, on the board, powered, and specified. It should be the primary
   alignment mechanism, with 1 and 2 as corroboration.

---

## 11. Open items — resolve before the RTL they gate

| ID | Item | Gates | Owner |
|---|---|---|---|
| ~~**O1**~~ | ~~FMC LPC `LA` pair → LIFCL-40 ball mapping~~ — **RESOLVED 2026-09-03**, §1.5. All FMC `LA` pairs are true differential `PB` (bottom) pairs in banks 3/4/5, `VCCIO` fixed at 1.8 V. Recommended: **`TUN_CLK` on `FMC_LA02`** (H7/H8 → Y2/Y3 → `PB8A/B`, `PCLKT5_1` + `LLC_GPLL0T_IN`) and **`TUN_DATA` on `FMC_LA04`** (H10/H11 → V1/W1 → `PB6A/B`), both bank 5, adjacent sites and adjacent connector pins. Note the trap: FMC's `_CC` pins are **not** FPGA clock-capable on this board. | — | done |
| ~~**O2**~~ | ~~LIFCL OSERDES/ISERDES gearing ratios~~ — **RESOLVED 2026-09-02**, and **superseded 2026-09-03**. The original question (is 10:1 hardened for 8b/10b, or is an 8→10 fabric gearbox needed?) is moot now the line code is gone. Answer for the record: `ODDRX5`/`IDDRX5` are hardened 10:1. The design now uses **`ODDRX4`/`IDDRX4`, hardened 8:1**, one byte per word. §6.3. | — | done |
| **O2a** | **Does `clk` reach the edge-clock network cleanly as `ECLK`, and is `ECLKSYNC` required?** `ECLKDIV ÷4` for `SCLK` is confirmed available; this is the remaining clocking unknown. Implementation detail, not a contract change. | Kuntur RTL | Claude |
| **O3** | **Does adding the tunnel perturb SPI1?** The chip0 / SCK-MOSI marginal timing is unresolved (PLAN.md B.5). Decision 4 reduces this risk materially — **no new PLL output, no second PLL, and 91.08 Mbps instead of 227.7** — but a serialiser near those pins is still the class of change that regressed it twice. Any new placement constraint goes **alongside** `mregion0`–`mregion7`, never by removing them. | Kuntur RTL bring-up | Manuel |
| **O4** | **`SLOT_OFFSET` duplication.** Fix at source, or make this spec normative, before the companion becomes the third implementation of one hardware fact. §3.4. | Companion RTL | Joint |
| **O5** | **Pigtail wiring must not bridge `VSTIMp`/`VSTIMm` (J1 pads 18/19) or `VCC1`/`VCC2` into the FMC breakout.** The uHDMI carries power and stimulator rails alongside the two pairs. §1.1. | Pigtail assembly | Manuel |
| **O6** | **Runbook: the operator configures via Vega, not via the Intan software.** Sharpened by decision 4 — absorbed writes are now reported only at the companion's own console (§9.4), not in the pc-app where the operator is looking. | Bench procedure, animal-test runbook | Joint |
| **O7** | **Confirm 91.08 Mbps on the real pigtail.** Step up by raising `ECLK` if the byte-slot budget proves short; there is no need to step down, since the rate is already set by `clk` itself. §6.5. | Link bring-up | Joint |
| **O8** | **Companion diagnostics console.** §5's counters need somewhere to be read. Scope: is a UART print enough, or does this want a small host-side reader? Not on A2's critical path but the counters are worthless unless visible. | Companion RTL | Claude |

## 12. Implementation order

Sequenced so each step is independently verifiable and nothing waits on a
decision it could have been given earlier.

1. ~~Resolve O1~~ — **done 2026-09-03** (§1.5). The pigtail's FMC end is
   now fully specified: `TUN_CLK` on `FMC_LA02` (H7/H8), `TUN_DATA` on
   `FMC_LA04` (H10/H11).
2. **Kuntur `.pdc` change** — promote both ports to `IO_TYPE=LVDS` and
   rename them (`tun_data_p`, `tun_clk_p`). **No port-direction change and
   no PCB change**; both were outputs already. Re-run PAR and confirm SPI1
   margins are unchanged — O3's first checkpoint, and the cheapest one.
3. **Build the pigtail** (O5) once step 1 fixes which FMC pairs to use.
4. **Physical layer alone** — `TUN_CLK` toggling and a fixed test pattern
   on `TUN_DATA`; confirm the companion locks at 91.08 Mbps (O7, O2a).
   Worth doing on its own, because it proves the cable and the clock
   recovery independently of any protocol.
5. **`SAMPLE` frames + CRC**, companion counting `frames_received` and
   `frames_crc_failed`. Verifiable against Kuntur's `test_pattern_gen0`
   ramp with `flags` bit 1 set — a synthetic pattern with an exact
   expected value is the right thing to bring a link up on.
6. **Link-loss behaviour** (§7), including the `0x8000` sentinel and the
   `TUN_CLK`-absence detector. Test by unplugging the cable, which is the
   actual failure being designed against.
7. **`CONFIG` replication and the RHD2164 emulator** (§9), validated with
   the A.1.1 ladder's own rung `L` against the emulator instead of the
   real chip — the expected values (`0x0035`/`0x003A`) are already known
   and already passing on hardware.
8. **Connect the Intan controller.** Confirm headstage detection, then a
   simultaneous dual-path capture with the §10 ZCHECK marker — **A2**.

Steps 1–4 do not need the Intan controller present. Steps 5–7 do not need
an animal, an electrode, or the attenuation network. Only step 8 needs the
full bench, which is the point: bench time is the constraint (PLAN.md,
"Team & ownership"), and this ordering spends as little of it as possible.
