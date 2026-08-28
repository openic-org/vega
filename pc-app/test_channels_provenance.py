"""Offline exercise of MainWindow's channels-state provenance bookkeeping
(docs/interfaces/recording-format.md §2.1) through the real Apply-channels
code path in main_window.py, with SerialReader's send_* methods mocked to
auto-ack (no real port) — same "drive the real state machine, fake only the
wire" approach as test_diagnostics.py's FakeReader, just for main_window.py
instead of diagnostics.py.

    QT_QPA_PLATFORM=offscreen python3 test_channels_provenance.py
"""
import sys
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QTimer
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent))
from main_window import MainWindow


def make_window() -> MainWindow:
    win = MainWindow()
    # Fast timeouts so the timeout-path test doesn't need to sleep 2s for
    # real — same knob a human would turn down for a quick manual retest.
    win._stop_ack_timer.setInterval(30)
    win._verify_timer.setInterval(30)
    win._start_ack_timer.setInterval(30)
    return win


def run_until(app, predicate, timeout_ms=3000):
    wd = QTimer(); wd.setSingleShot(True); wd.timeout.connect(app.quit)
    wd.start(timeout_ms)
    poll = QTimer(); poll.setInterval(5)
    poll.timeout.connect(lambda: predicate() and app.quit())
    poll.start()
    app.exec()
    wd.stop(); poll.stop()
    return predicate()


app = QApplication.instance() or QApplication(sys.argv)

print("=" * 70)

# Success path: Apply click -> unverified_requested immediately -> matching
# readback -> verified_readback with the confirmed pair.
win = make_window()
win._reader.send_stop_streaming = lambda: (
    QTimer.singleShot(1, lambda: win._reader.stop_streaming_ack.emit(True)), True)[1]
win._reader.send_set_channels = lambda a, b: (
    QTimer.singleShot(1, lambda: win._reader.channels_readback.emit(a, b)), True)[1]
win._reader.send_start_streaming = lambda: (
    QTimer.singleShot(1, lambda: win._reader.start_streaming_ack.emit(True)), True)[1]

win._spin_ch_a.setValue(3)
win._spin_ch_b.setValue(5)
win._apply_channels()
assert win._channels_state == {"ch_a": 3, "ch_b": 5, "provenance": "unverified_requested"}, \
    win._channels_state
print("Apply click: immediately unverified_requested — OK")

ok = run_until(app, lambda: win._channels_state.get("provenance") == "verified_readback")
assert ok, f"never reached verified_readback: {win._channels_state}"
assert win._channels_state == {"ch_a": 3, "ch_b": 5, "provenance": "verified_readback"}, \
    win._channels_state
print("matching readback: verified_readback(3, 5) — OK")

print("-" * 70)

# Mismatch path: the FPGA readback disagrees with what was requested — the
# stored value must be what the FPGA actually reported, not the request.
win = make_window()
win._reader.send_stop_streaming = lambda: (
    QTimer.singleShot(1, lambda: win._reader.stop_streaming_ack.emit(True)), True)[1]
win._reader.send_set_channels = lambda a, b: (
    QTimer.singleShot(1, lambda: win._reader.channels_readback.emit(99, 98)), True)[1]
win._reader.send_start_streaming = lambda: (
    QTimer.singleShot(1, lambda: win._reader.start_streaming_ack.emit(True)), True)[1]

win._spin_ch_a.setValue(3)
win._spin_ch_b.setValue(5)
win._apply_channels()
ok = run_until(app, lambda: win._channels_state.get("provenance") == "verified_readback")
assert ok, win._channels_state
assert win._channels_state == {"ch_a": 99, "ch_b": 98, "provenance": "verified_readback"}, \
    f"mismatch must still store the FPGA's real value: {win._channels_state}"
assert "Mismatch" in win._lbl_verify.text()
print("mismatched readback: stores FPGA's actual (99, 98), not the request — OK")

print("-" * 70)

# Timeout path: no readback ever arrives — state stays unverified_requested,
# never silently reverts to "unknown" or keeps a stale prior verified value.
win = make_window()
win._reader.send_stop_streaming = lambda: (
    QTimer.singleShot(1, lambda: win._reader.stop_streaming_ack.emit(True)), True)[1]
win._reader.send_set_channels = lambda a, b: True   # sent, but no readback ever arrives
win._reader.send_start_streaming = lambda: (
    QTimer.singleShot(1, lambda: win._reader.start_streaming_ack.emit(True)), True)[1]

win._spin_ch_a.setValue(7)
win._spin_ch_b.setValue(11)
win._apply_channels()
# Wait for the whole Apply sequence to finish (button re-enabled) rather
# than polling _channels_state, which never changes again in this path.
ok = run_until(app, lambda: win._btn_apply_channels.isEnabled() is False or win._is_connected is False)
run_until(app, lambda: "unsuccessful" in win._lbl_verify.text(), timeout_ms=1000)
assert win._channels_state == {"ch_a": 7, "ch_b": 11, "provenance": "unverified_requested"}, \
    win._channels_state
print("no readback: stays unverified_requested(7, 11) — OK")

print("-" * 70)

# Disconnect must invalidate to "unknown" — a different device (or the same
# one power-cycled) may be on the other end of the next connect.
win = make_window()
win._channels_state = {"ch_a": 3, "ch_b": 5, "provenance": "verified_readback"}
win._filter_settings_state = {"registers": {"4": 1}, "provenance": "verified_readback"}
win._on_connection_changed(False, "")
assert win._channels_state == {"ch_a": None, "ch_b": None, "provenance": "unknown"}, win._channels_state
assert win._filter_settings_state == {"registers": None, "provenance": "unknown"}, win._filter_settings_state
print("disconnect: both states reset to unknown — OK")

print("=" * 70)
print("ALL CHANNELS-PROVENANCE CHECKS PASSED")
