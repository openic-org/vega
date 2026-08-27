"""Regression test for the SerialReader num_pairs=0 crash (PLAN.md A.6.1).

Runs the real SerialReader.run() thread against a pty loopback and feeds it
actual wire-framed packets (MAGIC + length + payload, exactly as the bridge
sends them) rather than calling packet_parser.parse() directly — the bug was
in the reader's monotonicity-clamp indexing, not in parse() itself, so a unit
test against parse() alone would not have caught it.

Confirmed (2026-08-27) that this reproduces the original crash: reverting
serial_reader.py's `len(packet.timestamps_us) > 0` guard makes this test fail
with the exact IndexError found 2026-08-06 (serial_reader.py:214, indexing
timestamps_us[0] on an empty array).

Signal-driven with a watchdog timeout, not fixed sleeps — an earlier fixed-
sleep version of this test was flaky (batch delivery crosses a real QThread,
so how much of a short sleep window is "enough" depends on OS scheduling,
not on the code under test). See test_diagnostics.py for the same pattern
already used in this repo.

    QT_QPA_PLATFORM=offscreen python3 test_serial_reader.py
"""
import os
import pty
import struct
import sys
import time

from PyQt6.QtCore import QCoreApplication, QTimer

from serial_reader import SerialReader

MAGIC = bytes([0xAA, 0x55])
OPEN_TIMEOUT_MS = 2000
BATCH_TIMEOUT_MS = 5000


def make_data_frame(seq_num: int, num_pairs: int, ts_s: int = 100, ts_sub: int = 0) -> bytes:
    """Build a real wire frame: MAGIC + uint16 length + header + samples."""
    header = struct.pack("<IHBB", ts_s, ts_sub, seq_num, num_pairs)
    samples = b"\x00\x00\x01\x00" * num_pairs  # ch0=0, ch1=1 per pair — arbitrary
    payload = header + samples
    return MAGIC + struct.pack("<H", len(payload)) + payload


def run_case(frames: list[bytes], expected_batches: int) -> dict:
    """Feed `frames` to a fresh SerialReader over a pty loopback; return
    what arrived and whether the reader thread survived.

    Deterministic up to BATCH_TIMEOUT_MS: returns as soon as
    expected_batches have arrived, blocks no longer than the watchdog on
    failure (crash, drop, or hang)."""
    master, slave = pty.openpty()
    slave_name = os.ttyname(slave)

    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    reader = SerialReader()
    reader.set_port(slave_name)

    result = {"batches": 0, "errors": [], "opened": False}

    def on_batch(_pkt):
        result["batches"] += 1
        if result["batches"] >= expected_batches:
            app.quit()

    reader.batch_received.connect(on_batch)
    reader.error.connect(lambda msg: result["errors"].append(msg))
    reader.connection_changed.connect(lambda connected, _port: result.__setitem__("opened", connected))

    reader.start()

    # Wait for run() to actually have the port open before writing — without
    # this, a write can race the thread's own port-open and be silently lost
    # before it ever starts reading (this is what fixed-sleep pumping was
    # papering over at short durations).
    open_deadline = QTimer()
    open_deadline.setSingleShot(True)
    open_deadline.timeout.connect(app.quit)
    open_deadline.start(OPEN_TIMEOUT_MS)
    while not result["opened"] and open_deadline.isActive():
        app.processEvents()
        time.sleep(0.005)
    open_deadline.stop()
    assert result["opened"], "reader never opened the pty within the timeout"

    for frame in frames:
        os.write(master, frame)

    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(app.quit)
    watchdog.start(BATCH_TIMEOUT_MS)
    app.exec()
    watchdog.stop()

    result["thread_alive"] = reader.isRunning()
    result["dropped_packets"] = reader.dropped_packets

    reader.stop()
    reader.wait(1000)
    for _ in range(20):  # drain the connection_changed(False) queued signal
        app.processEvents()
        time.sleep(0.005)
    os.close(master)
    return result


# --- Test 1: a header-only (num_pairs=0) frame sandwiched between two real
#     packets must not kill the reader thread, and seq/drop tracking must
#     stay correct straddling it. This is the exact 2026-08-06 crash shape. ---
res = run_case([
    make_data_frame(seq_num=0, num_pairs=2, ts_s=100, ts_sub=0),
    make_data_frame(seq_num=1, num_pairs=0, ts_s=101, ts_sub=0),  # the crash trigger
    make_data_frame(seq_num=2, num_pairs=2, ts_s=102, ts_sub=0),
], expected_batches=3)
print("sandwiched zero-pair frame:", res)
assert res["batches"] == 3, f"expected all 3 frames to reach the UI, got {res['batches']}"
assert res["thread_alive"], "reader thread died on a header-only frame"
assert not res["errors"], f"reader emitted error signal(s): {res['errors']}"
assert res["dropped_packets"] == 0, "seq 0,1,2 has no real gap — drop tracking broke across the empty frame"

# --- Test 2: a header-only frame as the very first frame received (before
#     _last_ts_us is ever set) exercises the `_last_ts_us > 0` short-circuit
#     combined with the empty-array guard in the other order. ---
res = run_case([
    make_data_frame(seq_num=0, num_pairs=0, ts_s=200, ts_sub=0),  # first frame ever, zero pairs
    make_data_frame(seq_num=1, num_pairs=2, ts_s=201, ts_sub=0),
], expected_batches=2)
print("leading zero-pair frame:", res)
assert res["batches"] == 2, f"expected both frames to reach the UI, got {res['batches']}"
assert res["thread_alive"], "reader thread died on a leading header-only frame"
assert not res["errors"], f"reader emitted error signal(s): {res['errors']}"
assert res["dropped_packets"] == 0

print("=" * 70)
print("ALL SERIAL_READER CHECKS PASSED")
