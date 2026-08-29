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
import channel_mapping as M


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
# stored value must be what the FPGA actually reported (decoded back to a
# physical channel), not the request. Echo a different, but still
# cleanly-decodable, wire pair.
win = make_window()
mismatch_wire = (10, 15)
expect_phys = tuple(M.wire_to_physical(w) for w in mismatch_wire)
win._reader.send_stop_streaming = lambda: (
    QTimer.singleShot(1, lambda: win._reader.stop_streaming_ack.emit(True)), True)[1]
win._reader.send_set_channels = lambda a, b: (
    QTimer.singleShot(1, lambda: win._reader.channels_readback.emit(*mismatch_wire)), True)[1]
win._reader.send_start_streaming = lambda: (
    QTimer.singleShot(1, lambda: win._reader.start_streaming_ack.emit(True)), True)[1]

win._spin_ch_a.setValue(3)
win._spin_ch_b.setValue(5)
win._apply_channels()
ok = run_until(app, lambda: win._channels_state.get("provenance") == "verified_readback")
assert ok, win._channels_state
assert win._channels_state == {
    "ch_a": expect_phys[0], "ch_b": expect_phys[1], "provenance": "verified_readback",
}, f"mismatch must still store the FPGA's real (decoded) value: {win._channels_state}"
assert "Mismatch" in win._lbl_verify.text()
print(f"mismatched readback: stores FPGA's actual physical {expect_phys}, not the request — OK")

print("-" * 70)

# Unexpected/corrupted readback: a wire value channel_mapping.py's own
# compensation never produces (module-relative remainder 2, e.g. wire=2)
# must not be silently decoded into a fabricated out-of-range "channel" —
# _channels_state must NOT be corrupted with it.
win = make_window()
win._reader.send_stop_streaming = lambda: (
    QTimer.singleShot(1, lambda: win._reader.stop_streaming_ack.emit(True)), True)[1]
win._reader.send_set_channels = lambda a, b: (
    QTimer.singleShot(1, lambda: win._reader.channels_readback.emit(2, 8)), True)[1]
win._reader.send_start_streaming = lambda: (
    QTimer.singleShot(1, lambda: win._reader.start_streaming_ack.emit(True)), True)[1]

win._spin_ch_a.setValue(3)
win._spin_ch_b.setValue(5)
win._apply_channels()
state_before = dict(win._channels_state)
assert state_before["provenance"] == "unverified_requested"
run_until(app, lambda: "Unexpected readback" in win._lbl_verify.text(), timeout_ms=1000)
assert "Unexpected readback" in win._lbl_verify.text(), win._lbl_verify.text()
assert win._channels_state == state_before, \
    f"a corrupted readback must not overwrite _channels_state: {win._channels_state}"
print("corrupted/unexpected readback (wire=2): rejected, state left untouched — OK")

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

# Raw path: physical channel 29 (channel_mapping's dead zone) must go
# through RawChannelSetter (REG_WRITE16 on REG_CH_A/REG_CH_B), never
# SET_CHANNELS — driving the real Apply -> RawChannelSetter -> MainWindow
# wiring end to end, not just channel_mapping.py's own math.
win = make_window()
set_channels_calls = []
reg_writes = []
win._reader.send_stop_streaming = lambda: (
    QTimer.singleShot(1, lambda: win._reader.stop_streaming_ack.emit(True)), True)[1]
win._reader.send_set_channels = lambda a, b: (set_channels_calls.append((a, b)), True)[1]


def fake_reg_write(addr, value):
    reg_writes.append((addr, value))
    QTimer.singleShot(1, lambda: win._reader.reg_access_response.emit(4, addr, value))  # CMD_REG_WRITE16=4
    return True


win._reader.send_reg_write16 = fake_reg_write
win._reader.send_start_streaming = lambda: (
    QTimer.singleShot(1, lambda: win._reader.start_streaming_ack.emit(True)), True)[1]

win._spin_ch_a.setValue(29)
win._spin_ch_b.setValue(5)
win._apply_channels()
ok = run_until(app, lambda: win._channels_state.get("provenance") == "verified_readback")
assert ok, (win._channels_state, win._lbl_verify.text())
assert win._channels_state == {"ch_a": 29, "ch_b": 5, "provenance": "verified_readback"}, \
    win._channels_state
assert set_channels_calls == [], f"raw path must never call SET_CHANNELS: {set_channels_calls}"
assert [addr for addr, _ in reg_writes] == [196, 197], \
    f"expected REG_CH_A then REG_CH_B: {reg_writes}"
assert reg_writes[0][1] == M.physical_to_raw(29)
assert reg_writes[1][1] == M.physical_to_raw(5)
assert "raw" in win._lbl_verify.text().lower()
print(f"raw path (physical channel 29): REG_WRITE16 only, "
      f"{[hex(v) for _, v in reg_writes]}, SET_CHANNELS never called — OK")

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
