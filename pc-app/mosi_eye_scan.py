"""
mosi_eye_scan.py — map each RHD2164's MOSI window and choose the launch
point (task #6a). Spec: docs/interfaces/spi1-mosi-eye-scan.md §5.

Drives the eye-scan RTL over the register console: REG_WRITE16 /
REG_READ16 through the bridge to the FPGA regbank, streaming stopped. No
new firmware. One run is one full turn of the MOSI launch clock (clk_tx,
the PLL's CLKOS) at one rate, on that rate's build:

  1. STOP_STREAMING; check PHASE_INFO (steps per turn, SPT, as the rate
     says: 336 at 25k, 296 at 28k; not busy) and PHASE_POS = 0.
  2. Save the sampling table (words 48-80) and MOSI_SCAN_CTRL, load the
     known-answer pattern, CHK_EN = 1.
  3. For each PHASE_POS, for the two mosi_sel values allowed there
     (§3.1): set mosi_sel, clear the checker, wait for DWELL checked
     transfers, read the counters, check PHASE_POS (a row is kept only
     if it is still where the scan put it). Then one delaying step.
  4. Put everything back (also on Ctrl-C or an error): mosi_sel = 4,
     CHK_EN = 0, finish the turn (PHASE_POS = 0), the saved table.
     Then power-cycle Kuntur before any recording (§5.3).
     If PHASE_POS jumped (an FPGA reset or a lock drop clears the counter,
     not the PLL's phase: §3.2), it does not step back, and says to
     power-cycle before the next scan.

PHASE_POS = 0 at the start does not prove CLKOS is at its static phase
(an earlier FPGA reset would also read 0): start from a power-cycled
Kuntur (§5.1).

Writes one CSV row per point and prints the map's verdict (§5.4): each
half's error-free window, the overlap of all four, the chosen Δ* and its
margin to the nearest error on each side (≥ T/2 needed, the G5 rule), and
whether A and B of each chip agree (they see the same MOSI; if they
disagree, suspect MISO). `--analyze FILE.csv` re-reads a run.

Δ is the MOSI launch time relative to today's (mosi_sel = 4), in ns,
positive later, up to the fixed delay of the clk_tx path: the map shifts
by it as a whole, the window widths and Δ* do not.

Usage:
    python3 mosi_eye_scan.py --port /dev/ttyACM0 --rate 25 [--dwell 10000] [--out FILE]
    python3 mosi_eye_scan.py --analyze bench/mosi_scan_25k_....csv

Exit status 0 if the overlap holds a Δ* with the G5 margin on both
sides, 1 if not, 2 if the scan could not run.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path

# ── Regbank words (spec §3.4) ───────────────────────────────────────────────
SAMPLING_BASE = 48           # intan.vh RB_SAMPLING_BASE; entries 48..80
SAMPLING_N = 33
MOSI_SCAN_CTRL = 232         # [2:0] mosi_sel, [3] CHK_EN, [4] CHK_CLEAR
PHASE_STEP_CMD = 233         # [9:0] N steps, [15] direction (0 = delay)
PHASE_POS = 240
PHASE_INFO = 241             # [15] busy, [11:0] SPT
CHK_COUNT = 242
ERR_WORDS = (243, 244, 245, 246)   # chip0 A, chip0 B, chip1 A, chip1 B
FIRST_ERR_ANS, FIRST_ERR_INFO, FIRST_ERR_EXP = 247, 248, 249

SEL_BYPASS = 4
CHK_EN = 1 << 3
CHK_CLEAR = 1 << 4
HALVES = ("c0a", "c0b", "c1a", "c1b")

# ── Rates (#6 PLL IPs) ──────────────────────────────────────────────────────
# clk = CLKOP_FREQ_ACTUAL; SPT = 8 x (DIVOS_ACTUAL_STR + 1), TN-02095 §14.6.1.
RATES = {
    25: {"clk_mhz": 37.949963, "spt": 336},
    28: {"clk_mhz": 42.504012, "spt": 296},
}

# Offsets o of the four sources, in units of T (spec §3.1).
SOURCE_OFFSET = {0: -1.0, 1: -0.5, 2: 0.0, 3: 0.5}


def rhd_write(reg: int, data: int) -> int:
    return 0x8000 | (reg << 8) | data          # rhd2164_defs.vh RHD_WRITE


def rhd_read(reg: int) -> int:
    return 0xC000 | (reg << 8)                 # rhd2164_defs.vh RHD_READ


# The 33 sampling entries (spec §5.1 step 2): repeats every 8, entry 32 =
# READ(44). Register 6 is the Zcheck DAC value, inert with the DAC off.
PATTERN_8 = [rhd_write(6, 0x55), rhd_read(40), rhd_write(6, 0xAA), rhd_read(41),
             rhd_write(6, 0x00), rhd_read(42), rhd_write(6, 0xFF), rhd_read(43)]
PATTERN = (PATTERN_8 * 4) + [rhd_read(44)]


def points(spt: int):
    """(phase_pos, mosi_sel, delta in T) for every allowed scan point.

    x = (phi*T - o) mod T must be in [T/4, 3T/4); Δ = o + x (§3.1). The
    half-open interval gives exactly two sources per phase: 0 and 2, or 1
    and 3. Together they cover Δ in [-3T/4, 5T/4).
    """
    out = []
    for pos in range(spt):
        phi = pos / spt
        for sel in (0, 1, 2, 3):
            o = SOURCE_OFFSET[sel]
            x = (phi - o) % 1.0
            if 0.25 <= x < 0.75:
                out.append((pos, sel, o + x))
    return out


# ── Transport ───────────────────────────────────────────────────────────────

class SerialRegPort:
    """REG_WRITE16 / REG_READ16 / STOP_STREAMING over the bridge's USB serial.

    Framing as serial_reader.py: commands 0xCC 0x33 <len> <payload>;
    responses 0xEE 0x11 <u16 len> <payload>, payload[0] echoing the
    command. Sample (0xAA 0x55) and telemetry (0xDD 0x22) frames are
    skipped. One command in flight at a time: the MCU rejects a second.
    """

    CMD_MAGIC = bytes([0xCC, 0x33])
    MAGICS = (bytes([0xEE, 0x11]), bytes([0xAA, 0x55]), bytes([0xDD, 0x22]))

    def __init__(self, port: str, timeout: float = 1.0, retries: int = 3):
        import serial                       # only needed on the bench
        self._s = serial.Serial(port, baudrate=2_000_000, timeout=0.05)
        self._timeout = timeout
        self._retries = retries
        self._buf = bytearray()
        self.commands = 0

    def close(self):
        self._s.close()

    def _responses(self, deadline: float):
        """Yield response payloads until the deadline."""
        while time.monotonic() < deadline:
            self._buf.extend(self._s.read(512))
            while True:
                found = [(self._buf.find(m), m) for m in self.MAGICS]
                found = [(i, m) for i, m in found if i != -1]
                if not found:
                    del self._buf[:-1]
                    break
                i, m = min(found)
                del self._buf[:i]
                if len(self._buf) < 4:
                    break
                n = 4 + int.from_bytes(self._buf[2:4], "little")
                if len(self._buf) < n:
                    break
                payload = bytes(self._buf[4:n])
                del self._buf[:n]
                if m == self.MAGICS[0]:
                    yield payload

    def _transact(self, payload: bytes, match) -> bytes:
        for _ in range(self._retries):
            self._s.write(self.CMD_MAGIC + bytes([len(payload)]) + payload)
            self.commands += 1
            for r in self._responses(time.monotonic() + self._timeout):
                if match(r):
                    return r
        raise TimeoutError(f"no response to {payload.hex()} after {self._retries} tries")

    def stop_streaming(self) -> bool:
        r = self._transact(b"\x02", lambda r: len(r) >= 2 and r[0] == 0x02)
        return bool(r[1])

    def write(self, addr: int, value: int) -> int:
        """Write a word; returns what the regbank holds after it."""
        r = self._transact(bytes([0x04, addr, value & 0xFF, value >> 8]),
                           lambda r: len(r) >= 4 and r[0] == 0x04 and r[1] == addr)
        return r[2] | (r[3] << 8)

    def read(self, addr: int) -> int:
        r = self._transact(bytes([0x05, addr]),
                           lambda r: len(r) >= 4 and r[0] == 0x05 and r[1] == addr)
        return r[2] | (r[3] << 8)


# ── Scan ────────────────────────────────────────────────────────────────────

@dataclass
class Row:
    rate_k: int
    spt: int
    phase_pos: int
    mosi_sel: int
    delta_ns: float
    count: int
    c0a: int
    c0b: int
    c1a: int
    c1b: int
    first_err_ans: int
    first_err_info: int
    first_err_exp: int


class ScanError(Exception):
    pass


class PhaseDesync(ScanError):
    """PHASE_POS is not where the scan put it: an FPGA reset (rstb) or a
    lock drop reset the counter, or a step was lost. CLKOS may be anywhere;
    only reconfiguring the FPGA brings the two back together (spec §3.2)."""


def check_pos(port, want: int) -> None:
    got = port.read(PHASE_POS)
    if got != want:
        raise PhaseDesync(f"PHASE_POS {got}, expected {want}: FPGA reset, lock drop or lost step; "
                          "CLKOS and PHASE_POS may disagree")


def wait_steps_done(port, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while port.read(PHASE_INFO) & 0x8000:
        if time.monotonic() > deadline:
            raise ScanError("PHASE_INFO stays busy")


def step(port, n: int) -> None:
    """n delaying steps (PHASE_STEP_CMD [9:0], direction 0)."""
    while n > 0:
        k = min(n, 1023)
        port.write(PHASE_STEP_CMD, k)
        wait_steps_done(port)
        n -= k


def scan(port, rate_k: int, dwell: int, rows: list, log=print, max_dwell_s: float = 5.0):
    """One full turn, appending to rows (kept if it stops early). Restores
    the board in any case."""
    r = RATES[rate_k]
    T = 1000.0 / r["clk_mhz"]

    if not port.stop_streaming():
        raise ScanError("STOP_STREAMING not confirmed")
    info = port.read(PHASE_INFO)
    spt = info & 0x0FFF
    if spt != r["spt"]:
        raise ScanError(f"PHASE_INFO says SPT {spt}, {rate_k}k expects {r['spt']}: wrong build?")
    if info & 0x8000:
        raise ScanError("phase stepper busy at start")
    pos0 = port.read(PHASE_POS)
    if pos0 != 0:
        raise ScanError(f"PHASE_POS = {pos0}, not 0: power-cycle Kuntur first")

    saved_table = [port.read(SAMPLING_BASE + k) for k in range(SAMPLING_N)]
    saved_ctrl = port.read(MOSI_SCAN_CTRL)
    pos = 0
    desync = False
    try:
        for k, cmd in enumerate(PATTERN):
            if port.write(SAMPLING_BASE + k, cmd) != cmd:
                raise ScanError(f"sampling entry {k} did not take {cmd:04x}")
        pts = points(spt)
        log(f"{rate_k}k: T = {T:.3f} ns, SPT {spt}, {len(pts)} points, dwell {dwell}")
        t0 = time.monotonic()
        for i, (p, sel, d) in enumerate(pts):
            if p != pos:
                step(port, p - pos)
                pos = p
                check_pos(port, pos)
            port.write(MOSI_SCAN_CTRL, sel | CHK_EN)
            # A separate write after the mosi_sel change: by then (a BLE
            # round trip) the 2-deep command history holds only commands
            # sent with the new launch.
            port.write(MOSI_SCAN_CTRL, sel | CHK_EN | CHK_CLEAR)
            deadline = time.monotonic() + max_dwell_s
            while (count := port.read(CHK_COUNT)) < dwell:
                if time.monotonic() > deadline:
                    break
            errs = [port.read(a) for a in ERR_WORDS]
            row = Row(rate_k, spt, p, sel, round(d * T, 3), count, *errs,
                      port.read(FIRST_ERR_ANS), port.read(FIRST_ERR_INFO),
                      port.read(FIRST_ERR_EXP))
            # Still where the scan put it? A reset during the dwell would
            # make this row's Δ wrong: drop the row rather than keep it.
            check_pos(port, pos)
            rows.append(row)
            if i % 50 == 0 or i == len(pts) - 1:
                el = time.monotonic() - t0
                log(f"  {i + 1}/{len(pts)}  pos {p}  sel {sel}  Δ {row.delta_ns:+8.3f} ns  "
                    f"errors {errs}  ({el:.0f} s, ~{el / (i + 1) * (len(pts) - i - 1):.0f} s left)")
    except PhaseDesync:
        desync = True
        raise
    finally:
        log("restoring: mosi_sel 4, CHK_EN 0, PHASE_POS 0, sampling table")
        port.write(MOSI_SCAN_CTRL, SEL_BYPASS)
        if desync:
            # The counter no longer says where CLKOS is, so stepping "back
            # to 0" would put it somewhere arbitrary. mosi_sel 4 does not
            # use clk_tx: harmless until the next scan.
            log("WARNING: PHASE_POS lost track of CLKOS; not stepping back. "
                "Power-cycle Kuntur (reconfigures the FPGA) before the next scan")
            end = 0
        else:
            # From where the stepper is, not where the loop thinks it is: a
            # failure right after a step write leaves the two apart.
            step(port, (spt - port.read(PHASE_POS)) % spt)
            end = port.read(PHASE_POS)
        for k, w in enumerate(saved_table):
            port.write(SAMPLING_BASE + k, w)
        if saved_ctrl & 0x7 != SEL_BYPASS:
            log(f"note: MOSI_SCAN_CTRL was {saved_ctrl:04x} before the scan; left at bypass")
        if end != 0:
            log(f"WARNING: PHASE_POS = {end} after the turn, expected 0")
        # STOP_STREAMING above is not undone on purpose: §5.3 asks for a
        # power cycle before any recording, and that restarts streaming.
        log("STREAMING IS STOPPED (the scan does not restart it): power-cycle "
            "Kuntur before any recording (spec §5.3); pc-app shows no data until then")


# ── Map → verdict (spec §5.4) ───────────────────────────────────────────────

@dataclass
class Verdict:
    ok: bool
    T: float
    windows: dict           # half -> (lo, hi) of its longest error-free run, ns, or None
    overlap: tuple | None   # (lo, hi) ns, all four halves error-free
    delta_star: float | None
    margin_lo: float | None  # Δ* minus the nearest error below it (None: no error below)
    margin_hi: float | None
    ab_disagree: dict       # chip -> points where A and B disagree away from a window edge
    invalid: int            # points with fewer checked transfers than the dwell
    text: str
    # With no error on a side inside the scan, that side's margin is only
    # bounded: at least the distance to the end of the map.
    bound_lo: float | None = None   # Δ* minus the lowest Δ scanned, when margin_lo is None
    bound_hi: float | None = None
    ab_edge: dict | None = None      # chip -> disagreements at a window edge (not flagged)
    bypass_ok: bool | None = None    # Δ = 0 (today's launch) has the G5 margin
    bypass_lo: float | None = None   # its margin below (or bound, see bypass_lo_open)
    bypass_hi: float | None = None
    bypass_lo_open: bool = False
    bypass_hi_open: bool = False


def margins(d, deltas, clean):
    """Margin from Δ = d to the nearest unclean point on each side, as
    (lo, lo_open, hi, hi_open): when no error lies on a side, the margin
    is the distance to the end of the map and *_open is True (a lower
    bound, the edge was not reached)."""
    bad = [x for x, c in zip(deltas, clean) if not c]
    below = [x for x in bad if x < d]
    above = [x for x in bad if x > d]
    lo, lo_open = (d - max(below), False) if below else (d - deltas[0], True)
    hi, hi_open = (min(above) - d, False) if above else (deltas[-1] - d, True)
    return lo, lo_open, hi, hi_open


def ab_split(valid, chip):
    """(away, edge): points where exactly one of chip's A, B erred. A run
    of at most 2 such points next to a point where both erred is the two
    halves' windows ending a step or two apart, normal at an edge; any
    other disagreement is flagged."""
    a = [getattr(r, chip + "a") == 0 for r in valid]
    b = [getattr(r, chip + "b") == 0 for r in valid]
    dis = [x != y for x, y in zip(a, b)]
    both_bad = [not x and not y for x, y in zip(a, b)]
    away = edge = 0
    i = 0
    while i < len(dis):
        if not dis[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(dis) and dis[j + 1]:
            j += 1
        n = j - i + 1
        at_edge = (i > 0 and both_bad[i - 1]) or (j + 1 < len(dis) and both_bad[j + 1])
        if n <= 2 and at_edge:
            edge += n
        else:
            away += n
        i = j + 1
    return away, edge


def longest_run(deltas, good):
    """(lo, hi) of the longest run of consecutive good points, by Δ."""
    best, cur = None, None
    for d, g in zip(deltas, good):
        if g:
            cur = (cur[0], d) if cur else (d, d)
            if best is None or cur[1] - cur[0] > best[1] - best[0]:
                best = cur
        else:
            cur = None
    return best


def analyze(rows: list[Row], dwell: int | None = None) -> Verdict:
    rows = sorted(rows, key=lambda r: r.delta_ns)
    rate_k = rows[0].rate_k
    T = 1000.0 / RATES[rate_k]["clk_mhz"]
    need = dwell if dwell is not None else max(r.count for r in rows)
    valid = [r for r in rows if r.count >= need]
    invalid = len(rows) - len(valid)
    deltas = [r.delta_ns for r in valid]

    windows = {h: longest_run(deltas, [getattr(r, h) == 0 for r in valid]) for h in HALVES}
    clean = [all(getattr(r, h) == 0 for h in HALVES) for r in valid]
    overlap = longest_run(deltas, clean)

    g5 = T / 2
    star = mlo = mhi = blo = bhi = None
    ok = False
    if overlap:
        star = (overlap[0] + overlap[1]) / 2
        lo, lo_open, hi, hi_open = margins(star, deltas, clean)
        mlo, blo = (None, lo) if lo_open else (lo, None)
        mhi, bhi = (None, hi) if hi_open else (hi, None)
        # An edge beyond the map still passes when the part of the window
        # that was scanned already gives the G5 margin.
        ok = lo >= g5 and hi >= g5

    # Today's launch: Δ = 0 is mosi_sel 4 (§3.1), up to the fixed delay of
    # the clk_tx path, which shifts the whole map.
    byp = None
    bypass_ok = byp_clean = None
    if deltas and deltas[0] <= 0.0 <= deltas[-1]:
        byp = margins(0.0, deltas, clean)
        byp_clean = clean[min(range(len(deltas)), key=lambda i: abs(deltas[i]))]
        bypass_ok = byp_clean and byp[0] >= g5 and byp[2] >= g5

    ab, ab_edge = {}, {}
    for chip in ("c0", "c1"):
        ab[chip], ab_edge[chip] = ab_split(valid, chip)

    lines = [f"{rate_k}k: T = {T:.3f} ns, {len(rows)} points"
             + (f", {invalid} short of the dwell (ignored)" if invalid else ""),
             f"  scan covers Δ {deltas[0]:+.3f} … {deltas[-1]:+.3f} ns" if deltas else "  no valid points"]
    for h in HALVES:
        w = windows[h]
        lines.append(f"  {h}  window " + (f"{w[0]:+8.3f} … {w[1]:+8.3f} ns ({w[1] - w[0]:.3f} ns)"
                                          if w else "none: errors at every point"))
    def side(m_, b_, where):
        return f"{m_:.3f} ns {where}" if m_ is not None else f"≥ {b_:.3f} ns {where} (edge beyond the map)"

    if overlap:
        lines.append(f"  overlap  {overlap[0]:+8.3f} … {overlap[1]:+8.3f} ns ({overlap[1] - overlap[0]:.3f} ns)")
        lines.append(f"  Δ*       {star:+8.3f} ns; margin to the nearest error "
                     + side(mlo, blo, "below") + ", " + side(mhi, bhi, "above")
                     + f"; G5 needs ≥ {g5:.3f} ns each side")
    else:
        lines.append("  overlap  none: no Δ where all four halves are clean")
    if byp is not None:
        lo, lo_open, hi, hi_open = byp
        lines.append("  Δ = 0    (mosi_sel 4, today's launch, ± the clk_tx path offset): "
                     + ("clean; margin " + side(None if lo_open else lo, lo, "below") + ", "
                        + side(None if hi_open else hi, hi, "above")
                        + (" → meets G5" if bypass_ok else " → short of G5")
                        if byp_clean else "errors there"))
    for chip in ("c0", "c1"):
        if ab[chip]:
            lines.append(f"  {chip}: A and B disagree at {ab[chip]} points away from a window edge: "
                         "suspect MISO, not MOSI")
        if ab_edge[chip]:
            lines.append(f"  {chip}: A and B differ at {ab_edge[chip]} edge point(s): their windows end "
                         "a step apart (normal)")
    if overlap and (mlo is None or mhi is None):
        lines.append("  an edge lies beyond the map: that side's margin is a lower bound, "
                     "which " + ("already meets" if ok else "does not reach") + " G5")
    lines.append("  " + ("PASS: Δ* has the G5 margin on both sides" if ok else
                         "FAIL: no Δ* with the G5 margin on both sides (a finding, report it; §5.4)"))
    if ok and bypass_ok:
        lines.append("  today's launch (mosi_sel 4) also meets G5: no MOSI phase change is needed")
    lines.append("  a pass at Δ* afterwards is not evidence; this map is (A.1.2)")
    return Verdict(ok, T, windows, overlap, star, mlo, mhi, ab, invalid, "\n".join(lines),
                   bound_lo=blo, bound_hi=bhi, ab_edge=ab_edge, bypass_ok=bypass_ok,
                   bypass_lo=byp[0] if byp else None, bypass_hi=byp[2] if byp else None,
                   bypass_lo_open=byp[1] if byp else False, bypass_hi_open=byp[3] if byp else False)


def star_setting(delta_star_ns: float, rate_k: int) -> tuple[int, int, float]:
    """Δ* -> (mosi_sel, static CLKOS phase in steps, error in ns): the
    allowed point nearest to it (§3.1, §5.4)."""
    r = RATES[rate_k]
    T = 1000.0 / r["clk_mhz"]
    best = min(points(r["spt"]), key=lambda p: abs(p[2] * T - delta_star_ns))
    return best[1], best[0], best[2] * T - delta_star_ns


# ── CSV ─────────────────────────────────────────────────────────────────────

def write_csv(path: Path, rows: list[Row], header: str) -> None:
    with open(path, "w", newline="") as f:
        f.write("# " + header + "\n")
        w = csv.writer(f)
        names = [fl.name for fl in fields(Row)]
        w.writerow(names)
        for r in rows:
            w.writerow([getattr(r, n) for n in names])


def read_csv(path: Path) -> list[Row]:
    with open(path) as f:
        lines = [l for l in f if not l.startswith("#")]
    rd = csv.DictReader(lines)
    out = []
    for d in rd:
        out.append(Row(**{fl.name: (float(d[fl.name]) if fl.name == "delta_ns" else int(d[fl.name]))
                          for fl in fields(Row)}))
    return out


def report(rows: list[Row], dwell: int | None) -> int:
    v = analyze(rows, dwell)
    print(v.text)
    if v.delta_star is not None:
        sel, steps, err = star_setting(v.delta_star, rows[0].rate_k)
        spt = RATES[rows[0].rate_k]["spt"]
        print(f"  setting  mosi_sel {sel}, static CLKOS phase {steps} of {spt} steps "
              f"({360 * steps / spt:.2f}°), {err:+.3f} ns from Δ*")
    return 0 if v.ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="bridge serial port, e.g. /dev/ttyACM0")
    ap.add_argument("--rate", type=int, choices=sorted(RATES), help="25 or 28 (kS/s): the build flashed")
    ap.add_argument("--dwell", type=int, default=10_000, help="checked transfers per point (default 10000)")
    ap.add_argument("--out", type=Path, help="CSV (default bench/mosi_scan_<rate>k_<time>.csv)")
    ap.add_argument("--analyze", type=Path, metavar="CSV", help="re-read a run, scan nothing")
    a = ap.parse_args(argv)

    if a.analyze:
        try:
            rows = read_csv(a.analyze)
        except (OSError, KeyError, ValueError) as e:
            print(f"{a.analyze}: {e}", file=sys.stderr)
            return 2
        return report(rows, a.dwell)

    if not (a.port and a.rate):
        ap.error("--port and --rate are needed for a scan")
    out = a.out or Path(__file__).parent / "bench" / f"mosi_scan_{a.rate}k_{datetime.now():%Y%m%d_%H%M%S}.csv"
    try:
        port = SerialRegPort(a.port)
    except Exception as e:
        print(f"cannot open {a.port}: {e}", file=sys.stderr)
        return 2
    rows: list[Row] = []
    stopped = None
    try:
        scan(port, a.rate, a.dwell, rows)
    except (ScanError, TimeoutError) as e:
        stopped = f"scan stopped: {e}"
    except KeyboardInterrupt:
        stopped = "interrupted"
    finally:
        port.close()
    if rows:
        out.parent.mkdir(parents=True, exist_ok=True)
        write_csv(out, rows, f"mosi_eye_scan {a.rate}k dwell {a.dwell} "
                             f"{datetime.now().isoformat(timespec='seconds')} {port.commands} commands"
                             + (f" PARTIAL ({stopped})" if stopped else ""))
        print(f"wrote {out}" + (" (partial)" if stopped else ""))
    if stopped:
        print(stopped, file=sys.stderr)
        return 2
    return report(rows, a.dwell)


if __name__ == "__main__":
    sys.exit(main())
