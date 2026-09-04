"""Tests for the 0xDD 0x22 telemetry frame — docs/interfaces/stream-packet-format.md §6.

Two layers:
  1. telemetry.parse() against bytes built here to §6.2's byte table, so a
     drift between the spec table and any of the three implementations shows
     up as a failing offset rather than as a plausible-looking wrong number.
  2. The real SerialReader.run() thread over a pty loopback, with telemetry
     frames interleaved among sample frames — the three-way magic dispatch is
     the part that can regress silently, because a misrouted frame is dropped
     rather than raised.

    QT_QPA_PLATFORM=offscreen python3 test_telemetry.py
"""
import os
import pty
import struct
import sys
import time

from PyQt6.QtCore import QCoreApplication, QTimer

import telemetry
from serial_reader import SerialReader, TELEMETRY_MAGIC

DATA_MAGIC = bytes([0xAA, 0x55])
RESP_MAGIC = bytes([0xEE, 0x11])
OPEN_TIMEOUT_MS = 2000
WATCHDOG_MS = 5000


def make_telemetry_payload(
    version=1, flags=0, anchor=0, ts_s=0, ts_sub=0,
    fifo_ovf=0, fifo_hw=0, ring_trunc=0, flow_off=0, stall_ms=0,
    drop_bytes=0, drop_frames=0, extra_mcu_bytes=b"",
):
    """Build a payload byte-for-byte from §6.2's offsets.

    `extra_mcu_bytes` simulates a future telemetry_version that appended MCU
    counters after offset 29 — the bridge's pair still goes last, which is the
    property the parser's read-from-the-end depends on.
    """
    mcu = struct.pack(
        "<BBIIHIHIII",
        version, flags, anchor, ts_s, ts_sub,
        fifo_ovf, fifo_hw, ring_trunc, flow_off, stall_ms,
    )
    assert len(mcu) == 30, f"§6.2 says the MCU half is 30 bytes, built {len(mcu)}"
    return mcu + extra_mcu_bytes + struct.pack("<II", drop_bytes, drop_frames)


def frame(magic: bytes, payload: bytes) -> bytes:
    return magic + struct.pack("<H", len(payload)) + payload


# ── Layer 1: parser ─────────────────────────────────────────────────────────

# Every field distinct, so a swapped pair of offsets cannot pass.
p = make_telemetry_payload(
    version=1, flags=0x01, anchor=0x11223344, ts_s=0x55667788, ts_sub=0x99AA,
    fifo_ovf=0xBBCCDDEE, fifo_hw=0x0102, ring_trunc=0x03040506,
    flow_off=0x0708090A, stall_ms=0x0B0C0D0E,
    drop_bytes=0x0F101112, drop_frames=0x13141516,
)
assert len(p) == 38, f"full frame should be 38 bytes, got {len(p)}"
t = telemetry.parse(p)
assert t is not None, "a well-formed frame must parse"
assert t.version == 1
assert t.anchor_sample_index == 0x11223344
assert t.anchor_timestamp_s == 0x55667788
assert t.anchor_timestamp_sub_s == 0x99AA
assert t.fifo0_overflow_samples == 0xBBCCDDEE
assert t.fifo0_high_water == 0x0102
assert t.ring_truncated_samples == 0x03040506
assert t.flow_off_count == 0x0708090A
assert t.stall_time_ms_total == 0x0B0C0D0E
assert t.tx_ring_drop_bytes == 0x0F101112
assert t.tx_ring_drop_frames == 0x13141516
assert t.fpga_counters_valid is True
print("field offsets: ok")

# The flag is the whole point of §6.2's amendment: absent must not read as clean.
t = telemetry.parse(make_telemetry_payload(flags=0x00, fifo_ovf=0, fifo_hw=0))
assert t.fpga_counters_valid is False, "flags bit 0 clear must mean 'not measured'"
print("fpga_counters_valid=0: ok")

# Anchor timestamp uses the same RTC encoding as the v0 packet header.
t = telemetry.parse(make_telemetry_payload(ts_s=12, ts_sub=16000))
assert t.anchor_timestamp_us == 12 * 1_000_000 + 16000 * 1000 // 32
print("anchor timestamp decode: ok")

# Short frame — never a partial decode.
assert telemetry.parse(make_telemetry_payload()[:-1]) is None
assert telemetry.parse(b"") is None
print("short frame rejected: ok")

# Version 0 is reserved/invalid; a future version must still decode, with the
# bridge pair read from the END rather than from offset 30.
assert telemetry.parse(make_telemetry_payload(version=0)) is None
t = telemetry.parse(make_telemetry_payload(
    version=2, drop_bytes=0xDEADBEEF, drop_frames=7,
    extra_mcu_bytes=b"\xAA\xBB\xCC\xDD"))
assert t is not None and t.version == 2
assert t.tx_ring_drop_bytes == 0xDEADBEEF, "bridge fields must be read from the end"
assert t.tx_ring_drop_frames == 7
print("version handling + forward compat: ok")


# ── Layer 2: SerialReader three-way dispatch ────────────────────────────────

def make_data_frame(seq_num: int, num_pairs: int) -> bytes:
    header = struct.pack("<IHBB", 100 + seq_num, 0, seq_num, num_pairs)
    return frame(DATA_MAGIC, header + b"\x00\x00\x01\x00" * num_pairs)


def run_case(frames, expected_batches, expected_telemetry):
    master, slave = pty.openpty()
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    reader = SerialReader()
    reader.set_port(os.ttyname(slave))

    got = {"batches": 0, "telemetry": [], "errors": [], "opened": False}

    def maybe_quit():
        if (got["batches"] >= expected_batches
                and len(got["telemetry"]) >= expected_telemetry):
            app.quit()

    def on_batch(_p):
        got["batches"] += 1
        maybe_quit()

    def on_telem(t):
        got["telemetry"].append(t)
        maybe_quit()

    reader.batch_received.connect(on_batch)
    reader.telemetry_received.connect(on_telem)
    reader.error.connect(lambda m: got["errors"].append(m))
    reader.connection_changed.connect(
        lambda c, _p: got.__setitem__("opened", c))
    reader.start()

    deadline = QTimer(); deadline.setSingleShot(True)
    deadline.timeout.connect(app.quit); deadline.start(OPEN_TIMEOUT_MS)
    while not got["opened"] and deadline.isActive():
        app.processEvents(); time.sleep(0.005)
    deadline.stop()
    assert got["opened"], "reader never opened the pty"

    for f in frames:
        os.write(master, f)

    watchdog = QTimer(); watchdog.setSingleShot(True)
    watchdog.timeout.connect(app.quit); watchdog.start(WATCHDOG_MS)
    app.exec()
    watchdog.stop()

    got["thread_alive"] = reader.isRunning()
    got["total_samples"] = reader.total_samples
    got["dropped_packets"] = reader.dropped_packets
    reader.stop(); reader.wait(1000)
    for _ in range(20):
        app.processEvents(); time.sleep(0.005)
    os.close(master)
    return got


# A telemetry frame sandwiched between sample frames must reach its own signal
# without costing a sample packet or a seq_num.
res = run_case([
    make_data_frame(0, 59),
    frame(TELEMETRY_MAGIC, make_telemetry_payload(anchor=118, flow_off=3)),
    make_data_frame(1, 59),
], expected_batches=2, expected_telemetry=1)
print("interleaved telemetry:", {k: v for k, v in res.items() if k != "telemetry"})
assert res["batches"] == 2, f"telemetry stole a sample frame: {res['batches']}"
assert len(res["telemetry"]) == 1
assert res["telemetry"][0].flow_off_count == 3
assert res["dropped_packets"] == 0, "telemetry must not disturb seq_num tracking"
assert res["thread_alive"] and not res["errors"]

# total_samples must count the same aggregate the MCU's anchor counts:
# 2 per pair, so 2 x 59 per full packet (§6.7).
assert res["total_samples"] == 2 * 59 * 2, res["total_samples"]
print("aggregate sample count matches the anchor's definition: ok")

# All three magics back to back, plus leading garbage to force a resync.
res = run_case([
    b"\x00\xFF\x13garbage",
    frame(RESP_MAGIC, bytes([0x03, 1])),
    frame(TELEMETRY_MAGIC, make_telemetry_payload(anchor=1, ring_trunc=42)),
    make_data_frame(0, 4),
    frame(TELEMETRY_MAGIC, make_telemetry_payload(anchor=2, ring_trunc=43)),
], expected_batches=1, expected_telemetry=2)
print("three-way dispatch after garbage:", {k: v for k, v in res.items() if k != "telemetry"})
assert res["batches"] == 1
assert [t.ring_truncated_samples for t in res["telemetry"]] == [42, 43]
assert res["thread_alive"] and not res["errors"]

print("=" * 70)
print("ALL TELEMETRY CHECKS PASSED")
