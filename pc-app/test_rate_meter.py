"""Checks for rate_meter.RateMeter (PLAN.md R7, recording-format.md §3a.2,
median of 10 s windows, decided 2026-11-10) and its use in the window.

    QT_QPA_PLATFORM=offscreen python3 test_rate_meter.py
"""
import sys
import tempfile

from rate_meter import RateMeter


def stream(rate, seconds, slot_rate=29_466.0, pkt=59, lose=(), drop_pkts=(), t0_s=1000):
    """Packets as Kuntur sends them: 59 slots each, at slot_rate (the MCU's
    pull rate); real samples arrive at `rate`, the rest is padding.
    lose: (t_from, t_to, frac) spans where that share of samples vanishes
    inside Kuntur (no seq gap). drop_pkts: packet indices never received."""
    m = RateMeter()
    produced = 0.0
    taken = 0
    dt = pkt / slot_rate
    n = int(seconds / dt)
    for i in range(n):
        t = i * dt
        produced += rate * dt
        for a, b, f in lose:
            if a <= t < b:
                produced -= rate * dt * f
        real = min(pkt, int(produced) - taken)
        taken += real
        if i in drop_pkts:
            continue
        us = int(t0_s * 1e6 + t * 1e6)
        m.add(us // 1_000_000, (us % 1_000_000) * 32 // 1000, i % 256, pkt, pkt - real)
    return m


# 1. Clean 25k and 28k: the median is the rate, padding as expected, no alarm.
for rate in (25_000.0, 28_000.0):
    st = stream(rate, 120).status(rate)
    assert abs(st.rate_all / rate - 1) < 2e-5, st
    assert abs(st.rate_recent / rate - 1) < 2e-5, st
    assert abs(st.padding - (1 - rate / 29_466.0)) < 2e-3, st
    assert st.alarm is None and not st.saturated and st.lost_samples == 0, st
    print(f"pass  clean {rate:,.0f}: measured {st.rate_all:,.2f}, padding {100 * st.padding:.1f}%")

# 2. Wrong setting: 25k streaming with 28k set trips the 0.5% alarm after 10 s.
st = stream(25_000.0, 15).status(28_000.0)
assert st.alarm and "set to 28,000" in st.alarm and "wrong bitstream" in st.alarm, st
assert stream(25_000.0, 8).status(28_000.0).alarm is None   # not before 10 s
print(f"pass  wrong setting: {st.alarm}")

# 3. A wrong PLL solution, 0.1% off: no alarm at 15 s (0.5%), alarm after 60 s (0.05%).
assert stream(25_025.0, 15).status(25_000.0).alarm is None
st = stream(25_025.0, 90).status(25_000.0)
assert st.alarm and "+0.10%" in st.alarm, st
print("pass  0.1% off: silent at 15 s, alarm after 60 s")

# 4. Losses inside Kuntur with no seq gap (the 2026-11-10 picture): the
# median stays on the clock, no alarm, the lost samples are counted.
m = stream(25_000.0, 300, lose=[(41.0, 46.0, 0.3), (203.0, 205.0, 1.0)])
st = m.status(25_000.0)
expect = 25_000 * (5 * 0.3 + 2 * 1.0)
assert abs(st.rate_all / 25_000 - 1) < 5e-5 and st.alarm is None, st
assert abs(st.lost_samples - expect) / expect < 0.05 and st.loss_windows == 2, (st.lost_samples, expect)
assert st.lost_packets == 0
print(f"pass  hidden loss: median {st.rate_all:,.2f}, {st.lost_samples:,} lost (expected {expect:,.0f}), no alarm")

# 5. Dropped packets: counted by seq, filled, rate unbiased.
st = stream(25_000.0, 120, drop_pkts=set(range(1000, 6000, 50))).status(25_000.0)
assert st.lost_packets == 100 and abs(st.rate_all / 25_000 - 1) < 1e-4 and st.lost_samples == 0, st
print(f"pass  {st.lost_packets} dropped packets filled: {st.rate_all:,.2f}")

# 6. Saturated transport (no padding): warning.
st = stream(29_466.0, 30).status(29_999.97)
assert st.saturated, st
print("pass  no padding: saturation warning")

# 7. Midnight: the RTC's seconds-of-day wraps, the meter does not.
st = stream(25_000.0, 60, t0_s=86_400 - 25).status(25_000.0)
assert abs(st.rate_all / 25_000 - 1) < 2e-5 and st.windows >= 5, st
print("pass  across midnight")

# 8. The window: the sidecar of a recording carries the measured keys.
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
_tmp = tempfile.mkdtemp(prefix="vega_rate_test_")
# The window uses QSettings(org, app): NativeFormat, which setDefaultFormat
# does not cover. Redirect the native and INI user paths both (on Linux the
# native format is an INI file under ~/.config).
for _fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
    QSettings.setPath(_fmt, QSettings.Scope.UserScope, _tmp)
app = QApplication.instance() or QApplication(sys.argv)
from main_window import MainWindow
import kuntur_rate
win = MainWindow()
win._rate = kuntur_rate.from_key("25k")
win._rec_meter = stream(25_000.0, 90, lose=[(12.0, 13.0, 1.0)])
win._meter = win._rec_meter
win._update_rec_rate_metadata()
sr = win._recorder.live_metadata["sample_rate"]
assert sr["channel_hz"] == 25_000.0 and abs(sr["measured_channel_hz"] - 25_000) < 1, sr
assert 0.14 < sr["measured_padding"] < 0.17 and sr["measured_lost_packets"] == 0, sr
assert sr["measured_lost_samples_no_gap"] > 20_000, sr
win._update_rate_label()
assert "lost" in win._lbl_rate_meas.text() and "25,000" in win._lbl_rate_meas.text(), win._lbl_rate_meas.text()
print(f"pass  sidecar: {sr['measured_channel_hz']} S/s, padding {sr['measured_padding']}, "
      f"{sr['measured_lost_samples_no_gap']:,} lost no-gap; label: {win._lbl_rate_meas.text()}")

print("ALL RATE-METER CHECKS PASSED")
