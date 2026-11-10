# Companion diagnostics console (lvds-tunnel.md O8)

**Status: AGREED 2026-11-10 (Manuel, D1–D5). Nothing is built. Before
building: that port 1 enumerates as a serial port (§2). Balls, VCCIO and
the Radiant configuration setting confirmed.**

## 1. Why

The tunnel spec requires counters at the companion (§5: frames received,
CRC failures, sentinel served, slip repeat/skip, host-write changes, the
mismatch bitmap) and says they are "worthless unless visible" (O8). The
status LEDs (R-C6) show the receiver's state, not numbers. A frame test
between Kuntur and the companion (T5), the A2 bench compare (T9) and the
animal test all need these numbers, logged with time, without RHX.

Requirements, from the tunnel spec:
- **Alive with no cable and Kuntur off** (§6.1): the console runs in the
  12 MHz supervisor domain, not on `TUN_CLK`.
- **Saturating counters, never wrapping** (§5).
- **No data crosses into the datapath**: the console only reads.

## 2. Transport (D1)

The LIFCL-40-EVN's FT2232H already carries JTAG (port 0) for
programming. **Port 1 (channel B) is the console**: its UART pins already
reach the FPGA through the I2C path, which is fitted (Manuel, from the
board, 2026-11-10):

| FTDI pin | UART role | via | Net | via | FPGA | Use |
|---|---|---|---|---|---|---|
| `BDBUS0` | TXD (out) | R20 | `SCL` | R74 | **F20** (PR11B/SCL) | PC → FPGA, unused in v1 |
| `BDBUS1` | RXD (in) | R21 | `SDA` | R73 | **E20** (PR11A/SDA) | **FPGA → PC: the console's output** |
| `BDBUS2` | RTS# (out) | **R22: remove** | `SDA` | | | — |

R18/R19 are 4.7 kΩ pull-ups on `SCL`/`SDA`; harmless (the FPGA drives
`SDA` push-pull, and a UART idles high).

**The one rework: remove R22.** R22 (0 Ω) joins `BDBUS2` to `SDA`, the
usual MPSSE-I2C wiring (data out and data in tied). In UART mode
`BDBUS2` is RTS#, an output the FTDI always drives, so it would fight the
FPGA's console output on `SDA`: whenever they disagree the two outputs
short through 0 Ω (tens of mA), and the line level is undefined. RTS#
cannot be released in UART mode, so no host setting avoids it.
Cost of removing R22: the FTDI can no longer configure the FPGA over I2C
(MPSSE I2C reads through `BDBUS2`); not used, configuration is over JTAG
on port 0. Refitting R22 restores it.

**Conditions:**
- **The FPGA's SDA/SCL balls are dual-purpose configuration pins.** They
  are user I/O only with the slave I2C configuration port disabled.
  **Already so** (checked 2026-11-10): the companion's bitstream report
  (`impl_1/intan_rec_adapter_impl_1.bgn`) has `SLAVE_I2C_PORT = DISABLE`
  (the default; so are the slave SPI/I3C and master SPI ports;
  `JTAG_PORT = ENABLE`), and its pad report lists E20 (`PR11A`,
  `SD3/SDA/USER_SDA`) and F20 (`PR11B`, `SD2/SCL/USER_SCL`) as unused
  user I/O, not `Reserved: sysCONFIG`. To add to the `.pdc` so it does
  not rest on a default: `ldc_set_sysconfig {SLAVE_I2C_PORT=DISABLE}`.
  The console pin is E20, `LVCMOS33`; F20 is unused (or an input) in v1.
- **Bank 1's VCCIO = 3.3 V** (schematic, Manuel 2026-11-10): the console
  pin is `LVCMOS33`, matching the FT2232H's 3.3 V I/O.
- **Linux host (this PC, 2026-11-10):** `/etc/udev/rules.d/95-local.rules`
  (for the Lattice programmer) used to unbind `ftdi_sio` from every port
  of every `0403:6010`, so port 1 never became a serial port. Now it
  unbinds interface 00 only (`ENV{DEVTYPE}=="usb_interface"`,
  `ATTR{bInterfaceNumber}=="00"`), and a line
  `SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6010", MODE="0666"`
  opens the port to the user. The console is
  `/dev/serial/by-id/usb-Lattice_Lattice_CrossLink-NX_Eval_Board_FT6WVUEH-if01-port0`
  (use this name, the `ttyUSB` number changes). Opened at 115,200: works.
- **Port 1 must enumerate as a serial port.** The mode is set by the FTDI
  EEPROM (port 1 normally "RS232 UART" on Lattice boards; port 0 JTAG)
  and by whatever program opens it. On Linux: interface 1 bound to
  `ftdi_sio`, with a `/dev/ttyUSBx`. If not, read the EEPROM
  (`ftdi_eeprom`, or FT_Prog) and set port 1 to UART.

*Not used: the board's dedicated UART path* (`BDBUS0`/`BDBUS1` → R15/R17,
0 Ω DNL → `TXD_UART`/`RXD_UART` on Bank 6, EB-02028 §6.2, whose text
says "R16 and R17", a typo for R15/R17). Fitting those would also join
the I2C nets through `BDBUS0`/`BDBUS1`, so it needs R21 (and R20)
removed as well: more work for the same result.

| Option | For | Against |
|---|---|---|
| **A. FT2232H port 1 via `SDA`, remove R22 (chosen, D1)** | the USB cable already used for programming; nothing hangs off the board. JTAG (port 0) and the UART (port 1) are separate FTDI ports, so Radiant's programmer and the console can be open together | one resistor off; the I2C config pins become user I/O |
| B. External 3.3 V USB-UART on a header I/O | no rework | a second cable and adapter at the bench and in the OR |
| C. Radiant Reveal over JTAG | no rework, no pins | needs Radiant open, not loggable over hours, nothing for the animal test |

## 3. Line format (D2)

Transmit only (FPGA → host); the host sends nothing in v1. **One ASCII
line per second**, fixed field order, `key=value`, ending in a checksum:

```
CMP t=1234 link=up lock=1 ph=140/280 mode=frames rx=37045123 crc=0 sent=12 rep=3 skip=2 gap=0 down=1 hw=7 mm=000000 design=2101 flags=05 snap=ok *5A
```

| Field | Meaning | Source |
|---|---|---|
| `t` | seconds since the companion's configuration | supervisor |
| `link` | `up` / `down` (§7.1 detectors) | supervisor |
| `lock` | receive PLL lock | supervisor (synchronised) |
| `ph` | receive phase, steps / steps per turn | `cdr` |
| `mode` | `pattern` (K4.2 checker, bench build) / `frames` | build |
| `rx` | `frames_received`: `SAMPLE` frames accepted | §5 |
| `crc` | `frames_crc_failed` | §5 |
| `sent` | `frames_sentinel_served` (Intan frames answered `0x8000`) | §5 |
| `rep` / `skip` | `slip_repeat` / `slip_skip` | §5, §9.5 |
| `gap` | `SAMPLE` `frame_index` discontinuities (frames Kuntur sent that never arrived) | new |
| `down` | link-down events (§7.1) | new |
| `hw` | `host_write_changes` | §5, §9.3 |
| `mm` | `host_mismatch_regs`, 22-bit bitmap, hex; `------` until the first `CONFIG` | §5 |
| `design` | `design_id` from the last `STATUS` (variant, release; `docs/releases.md`); `----` until one arrives | §4.4a |
| `flags` | `flags` byte of the last `SAMPLE` (§4.5) | §4.5 |
| `snap` | `ok`, or `stale` when the counters could not be read this second (no `TUN_CLK`, §4) | supervisor |
| `*XX` | XOR of every byte from `C` up to the space before `*`, two hex digits | — |

In the bench build (`mode=pattern`) `rx`/`crc` count K4.2 blocks and
pattern errors instead, so T3/R1a-style link checks use the same console.

All counters 32-bit, saturating at `FFFFFFFF` (decimal in the line). At
~25,000 `SAMPLE` frames/s, `rx` saturates after ~48 h.

**Rate (D3):** 115,200 8N1 from the 12 MHz supervisor clock (÷104 →
115,385 baud, +0.16%, inside a UART's ±2%). A ~170-character line takes
~15 ms, so 1 line/s uses 1.5% of the link.

## 4. Reading counters across clock domains

The counters live in the `TUN_CLK` domain; the console in the 12 MHz
domain. Once per second the supervisor takes a **snapshot**:
1. it toggles `snap_req` (one bit, synchronised into `TUN_CLK`);
2. the `TUN_CLK` side, seeing the toggle, copies every counter into a
   shadow register set in one clock and toggles `snap_ack`;
3. the supervisor, seeing `snap_ack` (synchronised back), reads the shadow,
   which is stable until the next request.

If `snap_ack` does not arrive within 10 ms (no `TUN_CLK`: cable out,
Kuntur off, PLL unlocked), the line still goes out with the last good
shadow and `snap=stale`. So the console never stops, and "no data" is
never shown as zeros. Only the supervisor's own fields (`t`, `link`,
`lock`, `down`) are always current.

## 5. Host side (Claude)

`pc-app/companion_console.py`: opens the FTDI port, checks each line's
checksum (bad lines counted, not used), writes `bench/companion_*.csv`
(host time, every field) and prints changes (a new CRC failure, a link
drop, a slip). The same parser decodes the UART line in the T5
testbench, so the bench and the simulation check the same thing.

## 6. Not in O8

- Commands to the companion (reset counters, set the phase): no RX in v1.
- Showing the counters in pc-app's main window: a separate step once the
  log exists.

## 7. Decisions (Manuel)

- **D1 transport: A**, the USB cable already used to program the
  companion (port 0 JTAG, port 1 console), through the fitted I2C path
  (`BDBUS1` → R21 → `SDA` → R73 → the FPGA's SDA pin). **Rework: remove
  R22** (§2). Decided 2026-11-10 after two earlier versions of this
  section (fit R15/R17; fit R17 and remove R21) were dropped. Still
  to confirm on the board: the `SDA`/`SCL` balls, Bank 1's VCCIO, port 1
  as a serial port (§2 *Conditions*).
- **D2 format: as §3**, one checksummed `key=value` line per second.
- **D3 rate: 115,200 baud.**
- **D4 fields: the §3 table.**
- **D5 snapshot: as §4**, the toggle handshake, `snap=stale` without
  `TUN_CLK`.
