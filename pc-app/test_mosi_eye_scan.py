"""Tests for mosi_eye_scan.py against a fake regbank with known windows.

    python3 test_mosi_eye_scan.py
"""

import tempfile
from pathlib import Path

import mosi_eye_scan as m


AFTER_RESET = 54_321     # CHK_COUNT the fake reads after a reset: no row may carry it


class FakeRegbank:
    """The eye-scan RTL as the spec describes it (§3.1-3.4), with two chips
    whose MOSI windows are given in ns of Δ.

    The launch is worked out from clock edges, not from mosi_eye_scan's
    formula: clk_tx rises at φT + kT; the register takes the source on the
    first edge after the source changes at its offset o. An edge closer
    than T/4 to the change is unsafe, and every half then errs, so a scan
    that uses a forbidden pair shows it.
    """

    def __init__(self, rate_k, windows, spt=None, fail_after=None, b_only=None, reset_after=None):
        r = m.RATES[rate_k]
        self.T = 1000.0 / r["clk_mhz"]
        self.spt = spt or r["spt"]
        self.windows = windows          # {"c0": (lo, hi), "c1": (lo, hi)}
        self.b_only = b_only            # (half, lo, hi): extra errors on one half only
        self.mem = {m.SAMPLING_BASE + k: 0x1000 + k for k in range(m.SAMPLING_N)}
        self.mem[m.MOSI_SCAN_CTRL] = m.SEL_BYPASS
        self.pos = 0
        self.counts = None
        self.commands = 0
        self.fail_after = fail_after
        self.forbidden_used = 0
        # An FPGA reset (rstb) after this many commands: PHASE_POS goes to
        # 0, the PLL keeps its phase (spec §3.2). clkos_off is CLKOS's
        # phase minus PHASE_POS.
        self.reset_after = reset_after
        self.clkos_off = 0
        self.steps_after_reset = 0

    def _tick(self):
        self.commands += 1
        if self.fail_after is not None and self.commands > self.fail_after:
            self.fail_after = None          # fail once, then let the restore run
            raise TimeoutError("fake: no response")
        if self.reset_after is not None and self.commands > self.reset_after:
            self.reset_after = None
            self.clkos_off = self.pos
            self.pos = 0
            # whatever the counters read from now on, marked
            self.counts = (AFTER_RESET, [0, 0, 0, 0])

    def stop_streaming(self):
        self._tick()
        return True

    def launch(self, sel):
        """(Δ in ns, safe) for mosi_sel at the current phase."""
        o = m.SOURCE_OFFSET[sel] * self.T
        phi_t = ((self.pos + self.clkos_off) % self.spt) / self.spt * self.T
        k = 0
        while phi_t + k * self.T <= o:
            k += 1
        while phi_t + (k - 1) * self.T > o:
            k -= 1
        edge = phi_t + k * self.T
        return edge, (edge - o) >= self.T / 4 - 1e-9 and (edge - o) <= 3 * self.T / 4 + 1e-9

    def _measure(self):
        sel = self.mem[m.MOSI_SCAN_CTRL] & 0x7
        n = 12_345
        errs = [0, 0, 0, 0]
        if sel != m.SEL_BYPASS:
            d, safe = self.launch(sel)
            if not safe:
                self.forbidden_used += 1
            for i, h in enumerate(m.HALVES):
                lo, hi = self.windows[h[:2]]
                bad = not safe or not (lo <= d <= hi)
                if self.b_only and self.b_only[0] == h and self.b_only[1] <= d <= self.b_only[2]:
                    bad = True
                errs[i] = n if bad else 0
        self.counts = (n, errs)

    def write(self, addr, value):
        self._tick()
        if addr == m.PHASE_STEP_CMD:
            assert value & 0x8000 == 0, "advancing step used"
            self.pos = (self.pos + (value & 0x3FF)) % self.spt
            if self.clkos_off:
                self.steps_after_reset += 1
            self.mem[addr] = value
        elif addr == m.MOSI_SCAN_CTRL:
            self.mem[addr] = value
            if value & m.CHK_CLEAR:
                self._measure()
        else:
            self.mem[addr] = value
        return self.mem[addr]

    def read(self, addr):
        self._tick()
        if addr == m.PHASE_INFO:
            return self.spt
        if addr == m.PHASE_POS:
            return self.pos
        if addr == m.CHK_COUNT:
            return self.counts[0] if self.counts else 0
        if addr in m.ERR_WORDS:
            return self.counts[1][m.ERR_WORDS.index(addr)] if self.counts else 0
        if addr in (m.FIRST_ERR_ANS, m.FIRST_ERR_INFO, m.FIRST_ERR_EXP):
            return 0
        return self.mem.get(addr, 0)


def run(fake, rate_k=25, dwell=10_000):
    rows = []
    m.scan(fake, rate_k, dwell, rows, log=lambda *_: None)
    return rows


def restored(fake):
    return (fake.pos == 0
            and fake.mem[m.MOSI_SCAN_CTRL] == m.SEL_BYPASS
            and all(fake.mem[m.SAMPLING_BASE + k] == 0x1000 + k for k in range(m.SAMPLING_N)))


# 1. Wide windows: PASS, Δ* in the middle of the overlap, margins ≥ T/2.
fake = FakeRegbank(25, {"c0": (-14.0, 26.0), "c1": (-12.0, 30.0)})
rows = run(fake)
assert len(rows) == 672, len(rows)
assert fake.forbidden_used == 0, "the scan used a forbidden (phase, mosi_sel) pair"
for r in rows:   # Δ as the script records it = the fake's own launch time
    fake.pos = r.phase_pos
    assert abs(fake.launch(r.mosi_sel)[0] - r.delta_ns) < 1e-3, (r, fake.launch(r.mosi_sel))
fake.pos = 0
v = m.analyze(rows, 10_000)
assert v.ok, v.text
assert abs(v.overlap[0] - (-12.0)) < 0.1 and abs(v.overlap[1] - 26.0) < 0.1, v.overlap
assert abs(v.delta_star - 7.0) < 0.1, v.delta_star
assert v.margin_lo >= v.T / 2 and v.margin_hi >= v.T / 2
assert abs(v.windows["c0a"][0] - (-14.0)) < 0.1 and abs(v.windows["c1b"][1] - 30.0) < 0.1
assert v.ab_disagree == {"c0": 0, "c1": 0}
assert restored(fake)
sel, steps, err = m.star_setting(v.delta_star, 25)
assert abs(err) <= v.T / 336 + 1e-9, err
print(f"pass  wide windows: 672 points, overlap {v.overlap[0]:+.2f}…{v.overlap[1]:+.2f}, "
      f"Δ* {v.delta_star:+.2f} ns -> mosi_sel {sel}, phase {steps}/336")

# 2. chip0's window narrow, near Δ = 0 (the hypothesis): FAIL, the margin is reported.
fake = FakeRegbank(25, {"c0": (-1.0, 6.0), "c1": (-15.0, 28.0)})
v = m.analyze(run(fake), 10_000)
assert not v.ok and v.overlap is not None
assert abs(v.delta_star - 2.5) < 0.1 and v.margin_lo < v.T / 2
assert restored(fake)
print(f"pass  narrow chip0 window: FAIL, margins {v.margin_lo:.2f} / {v.margin_hi:.2f} ns < {v.T / 2:.2f}")

# 3. No overlap.
fake = FakeRegbank(28, {"c0": (-15.0, -5.0), "c1": (5.0, 25.0)})
rows = run(fake, 28)
assert len(rows) == 592
v = m.analyze(rows, 10_000)
assert not v.ok and v.overlap is None and v.delta_star is None
print("pass  28k, windows that do not overlap: no Δ*, FAIL")

# 4. A and B of chip1 disagree somewhere: flagged as MISO.
fake = FakeRegbank(25, {"c0": (-14.0, 26.0), "c1": (-12.0, 30.0)}, b_only=("c1b", 0.0, 2.0))
v = m.analyze(run(fake), 10_000)
assert v.ab_disagree["c1"] > 0 and v.ab_disagree["c0"] == 0
assert "suspect MISO" in v.text
print(f"pass  A/B disagreement on chip1 flagged ({v.ab_disagree['c1']} points)")

# 4b. The early edge beyond the map (2026-11-10 bench: chip windows from
# below -3T/4 to ~+28.5 ns): PASS on the bound, today's launch meets G5,
# and A/B of one chip ending one step apart is an edge, not MISO.
fake = FakeRegbank(25, {"c0": (-99.0, 28.5), "c1": (-99.0, 28.5)}, b_only=("c0a", 28.5 - 0.075, 28.5))
v = m.analyze(run(fake), 10_000)
assert v.ok, v.text
assert v.margin_lo is None and v.bound_lo >= v.T / 2 and v.margin_hi >= v.T / 2, v.text
assert "edge beyond the map" in v.text and "already meets" in v.text
assert v.bypass_ok and v.bypass_lo_open and not v.bypass_hi_open, v.text
assert "no MOSI phase change is needed" in v.text
assert v.ab_disagree == {"c0": 0, "c1": 0} and v.ab_edge["c0"] >= 1, (v.ab_disagree, v.ab_edge)
assert "suspect MISO" not in v.text
print(f"pass  edge beyond the map: PASS on the bound (≥ {v.bound_lo:.2f} ns), "
      f"Δ = 0 meets G5, {v.ab_edge['c0']} A/B edge point(s) not flagged")

# 4c. Same, but the scanned part is too short for G5 on the open side: FAIL.
fake = FakeRegbank(25, {"c0": (-99.0, -8.0), "c1": (-99.0, -8.0)})
v = m.analyze(run(fake), 10_000)
assert not v.ok and v.margin_lo is None and v.bound_lo < v.T / 2, v.text
assert "does not reach" in v.text and v.bypass_ok is not True
print(f"pass  edge beyond the map, bound {v.bound_lo:.2f} ns < G5: FAIL")

# 4d. The restore says streaming is left stopped.
fake = FakeRegbank(25, {"c0": (-14.0, 26.0), "c1": (-12.0, 30.0)})
said = []
m.scan(fake, 25, 10_000, [], log=lambda s, *_: said.append(s))
assert any("STREAMING IS STOPPED" in s for s in said), said[-3:]
print("pass  restore announces that streaming is left stopped")

# 5. Wrong build: SPT does not match the rate; nothing is touched.
fake = FakeRegbank(25, {"c0": (-14.0, 26.0), "c1": (-12.0, 30.0)}, spt=296)
try:
    run(fake, 25)
    raise AssertionError("no error on an SPT mismatch")
except m.ScanError as e:
    assert "SPT" in str(e)
assert restored(fake)
print("pass  SPT mismatch stops the scan before any write")

# 6. The link fails mid-scan: the board is still restored, rows so far kept.
fake = FakeRegbank(25, {"c0": (-14.0, 26.0), "c1": (-12.0, 30.0)}, fail_after=2000)
rows = []
try:
    m.scan(fake, 25, 10_000, rows, log=lambda *_: None)
    raise AssertionError("no error")
except TimeoutError:
    pass
assert 0 < len(rows) < 672 and restored(fake), (len(rows), fake.pos)
print(f"pass  failure mid-scan: restored, {len(rows)} rows kept")

# 6b. An FPGA reset mid-scan: PHASE_POS jumps to 0, CLKOS does not. The
# scan stops, keeps no row measured after the reset, does not step back.
for at in (2000, 2003, 2007, 2011):     # land in different parts of a point
    fake = FakeRegbank(25, {"c0": (-14.0, 26.0), "c1": (-12.0, 30.0)}, reset_after=at)
    rows = []
    try:
        m.scan(fake, 25, 10_000, rows, log=lambda *_: None)
        raise AssertionError("no error")
    except m.PhaseDesync:
        pass
    assert fake.clkos_off > 0 and fake.steps_after_reset == 0, (at, fake.clkos_off, fake.steps_after_reset)
    assert rows and all(r.count != AFTER_RESET for r in rows), at
    assert all(r.phase_pos <= fake.clkos_off for r in rows), (at, rows[-1].phase_pos, fake.clkos_off)
    assert fake.mem[m.MOSI_SCAN_CTRL] == m.SEL_BYPASS
    assert all(fake.mem[m.SAMPLING_BASE + k] == 0x1000 + k for k in range(m.SAMPLING_N))
print("pass  FPGA reset mid-scan: PhaseDesync, no row after it, no stepping back, bypass and table restored")

# 7. CSV round trip and --analyze.
fake = FakeRegbank(25, {"c0": (-14.0, 26.0), "c1": (-12.0, 30.0)})
rows = run(fake)
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "scan.csv"
    m.write_csv(p, rows, "test")
    back = m.read_csv(p)
    assert back == rows
    assert m.main(["--analyze", str(p)]) == 0
    fake = FakeRegbank(25, {"c0": (-1.0, 6.0), "c1": (-15.0, 28.0)})
    m.write_csv(p, run(fake), "test")
    assert m.main(["--analyze", str(p)]) == 1
print("pass  CSV round trip; --analyze exits 0 / 1")

# 8. Points: two per phase, Δ covers [-3T/4, 5T/4) evenly, both rates.
for k, r in m.RATES.items():
    pts = m.points(r["spt"])
    ds = sorted(p[2] for p in pts)
    step = 1 / r["spt"]
    assert len(pts) == 2 * r["spt"]
    assert abs(ds[0] + 0.75) < 1e-9 and abs(ds[-1] - (1.25 - step)) < 1e-9
    assert all(abs(b - a - step) < 1e-9 for a, b in zip(ds, ds[1:]))
print("pass  points: 2 per phase, Δ from -3T/4 to 5T/4 in steps of T/SPT")

print("all passed")
