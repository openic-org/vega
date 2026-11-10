"""Checks for the Kuntur rate setting (PLAN.md R7, recording-format.md §3a.1,
§3a.3): in-packet spacing, the reader's clamp, and the window's selector,
connect guard, persistence and sidecar.

    QT_QPA_PLATFORM=offscreen python3 test_kuntur_rate.py
"""
import os
import pty
import struct
import sys
import tempfile
import time

import numpy as np
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

import kuntur_rate
from packet_parser import parse, sample_offsets_us

# Keep the operator's real settings out of it: QSettings in a temp dir.
_tmp = tempfile.mkdtemp(prefix="vega_rate_test_")
# The window uses QSettings(org, app): NativeFormat, which setDefaultFormat
# does not cover. Redirect the native and INI user paths both (on Linux the
# native format is an INI file under ~/.config).
for _fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
    QSettings.setPath(_fmt, QSettings.Scope.UserScope, _tmp)

app = QApplication.instance() or QApplication(sys.argv)


def packet(seq=0, n=59, ts_s=100, ts_sub=0) -> bytes:
    return struct.pack("<IHBB", ts_s, ts_sub, seq, n) + b"\x01\x00\x02\x00" * n


# 1. Rates on offer, lookup.
keys = [r.key for r in kuntur_rate.RATES]
assert keys == ["25k", "28k", "30k"], keys
assert kuntur_rate.from_key("28k").channel_hz == 28_000.0
assert kuntur_rate.from_key(None) is None and kuntur_rate.from_key("31k") is None
assert kuntur_rate.from_key(28) is None
print("pass  rates: 25k, 28k, 30k legacy; unknown or missing key -> None")

# 2. In-packet spacing: rounded, not an integer step (§3a.1).
p = parse(packet(), 25_000)
assert list(np.diff(p.timestamps_us)) == [40] * 58
p = parse(packet(), 28_000)
last = int(p.timestamps_us[-1] - p.timestamps_us[0])
assert last == round(58 * 1e6 / 28_000) == 2071, last        # was 58 * 35 = 2030
assert set(np.diff(p.timestamps_us)) <= {35, 36}
assert abs(last - 58 * 1e6 / 28_000) <= 0.5
p = parse(packet(), 30_000)
assert int(p.timestamps_us[-1] - p.timestamps_us[0]) == round(58 * 1e6 / 30_000)
assert list(sample_offsets_us(3, 28_000)) == [0, 36, 71]
print(f"pass  in-packet spacing: 40 µs at 25k; 28k last sample at {last} µs (was 2030)")


# 3. The reader's clamp uses the rate: two packets with the same RTC base
# (a BLE burst) at 28k continue one step after the first packet's last.
def read_two(rate_hz):
    master, slave = pty.openpty()
    from serial_reader import SerialReader
    rd = SerialReader()
    rd.set_port(os.ttyname(slave))
    rd.set_sample_rate(rate_hz)
    got, opened = [], []
    rd.batch_received.connect(lambda pk: got.append(pk.timestamps_us.copy()))
    rd.connection_changed.connect(lambda c, _p: opened.append(c))
    rd.start()
    t = time.monotonic() + 2
    while not opened and time.monotonic() < t:
        app.processEvents()
        time.sleep(0.005)
    for seq in (0, 1):
        pl = packet(seq)
        os.write(master, bytes([0xAA, 0x55]) + struct.pack("<H", len(pl)) + pl)
    t = time.monotonic() + 3
    while len(got) < 2 and time.monotonic() < t:
        app.processEvents()
        time.sleep(0.005)
    rd.stop()
    rd.wait(1000)
    os.close(master)
    return got


got = read_two(28_000)
assert len(got) == 2, len(got)
a, b = got
assert b[0] == a[-1] + round(1e6 / 28_000), (a[-1], b[0])
assert int(b[-1] - b[0]) == 2071, int(b[-1] - b[0])
print(f"pass  clamp at 28k: second packet starts {int(b[0] - a[-1])} µs after the first's last")

# 4. The window: no default, connect refused, choice remembered, sidecar.
from main_window import MainWindow, SETTINGS_ORG, SETTINGS_APP, RATE_SETTING_KEY

win = MainWindow()
assert win._rate is None and win._rate_combo.currentData() is None
win._port_combo.clear()
win._port_combo.addItem("/dev/null-test")
started = []
win._reader.start = lambda *a: started.append(1)
win._btn_connect.setChecked(True)
win._toggle_connection(True)
assert not started and not win._btn_connect.isChecked(), "connected with no rate"
assert "Kuntur rate" in win.statusBar().currentMessage()
print("pass  first start: no rate chosen, connect refused")

win._rate_combo.setCurrentIndex(win._rate_combo.findData("28k"))
assert win._rate.channel_hz == 28_000.0
assert QSettings(SETTINGS_ORG, SETTINGS_APP).value(RATE_SETTING_KEY) == "28k"
assert win._graph._sps == 28_000
md = win._build_sidecar_metadata()["sample_rate"]
assert md["channel_hz"] == 28_000.0 and "28 kS/s" in md["source"], md
win._toggle_connection(True)
assert started == [1] and win._reader._rate_hz == 28_000.0
assert not win._rate_combo.isEnabled(), "rate changeable while connected"
assert win._health._dead_enter == int(0.25 * 28_000)
win._reader.stop = lambda *a: None
win._toggle_connection(False)
assert win._rate_combo.isEnabled()
print("pass  28k chosen: remembered, graph, reader, liveness, sidecar; fixed while connected")

win2 = MainWindow()
assert win2._rate.key == "28k" and win2._rate_combo.currentData() == "28k"
print("pass  next start: 28k restored from the setting")

print("ALL KUNTUR-RATE CHECKS PASSED")
