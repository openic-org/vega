"""SeqGapTracker — the seq_num byte cannot count a burst; the RTC says when
it might have tried to. PLAN.md A.7 step 2b.

Run: python test_seq_gaps.py
"""
from packet_parser import PacketHeader, SeqGapTracker

PKT_US = 2_000   # ~500 pkt/s, the measured μ


def hdr(seq: int, t_us: int) -> PacketHeader:
    t_us %= 86_400 * 1_000_000
    return PacketHeader(t_us // 1_000_000, (t_us % 1_000_000) * 32 // 1_000, seq % 256, 59)


def feed(tracker: SeqGapTracker, packets) -> list[tuple[int, bool]]:
    return [tracker.update(hdr(s, t)) for s, t in packets]


# Steady stream: nothing lost, nothing uncertain.
t = SeqGapTracker()
feed(t, [(i, 1_000_000 + i * PKT_US) for i in range(600)])
assert (t.dropped_packets, t.uncertain_gaps) == (0, 0)
assert t.summary() == "0"

# A short gap is exact: 3 packets over 8 ms cannot hide a wrap.
t = SeqGapTracker()
res = feed(t, [(0, 0), (1, PKT_US), (5, 5 * PKT_US)])
assert res[-1] == (3, False)
assert t.summary() == "3"

# The 2026-09-08 burst: 7,220 lost reads as 52 from the byte alone.
t = SeqGapTracker()
res = feed(t, [(10, 0), (10 + 7221, 7221 * PKT_US)])
assert res[-1] == (52, True), res
assert t.summary() == "≥52 (1 gap of unknown size)", t.summary()

# Exactly 256 lost: contiguous-looking seq, the case that read as zero.
t = SeqGapTracker()
res = feed(t, [(7, 0), (7 + 257, 257 * PKT_US)])
assert res[-1] == (0, True), res
assert t.summary() == "≥0 (1 gap of unknown size)"

# Worst stall ever measured (116 ms, lossless) must not flag.
t = SeqGapTracker()
res = feed(t, [(0, 0), (1, 116_000)])
assert res[-1] == (0, False)

# Backwards RTC jitter must not come out of the modulo as a day-long pause.
t = SeqGapTracker()
res = feed(t, [(0, 5_000_000), (1, 4_999_000)])
assert res[-1] == (0, False), res

# Midnight: time-of-day wraps, the stream does not pause.
day = 86_400 * 1_000_000
t = SeqGapTracker()
res = feed(t, [(0, day - 1_000), (1, day + 1_000)])
assert res[-1] == (0, False), res

# Deliberate STOP/START: seq continues, the pause is not a loss.
t = SeqGapTracker()
feed(t, [(0, 0), (1, PKT_US)])
t.pause()
res = feed(t, [(2, 30_000_000)])
assert res[-1] == (0, False)
# ...but a seq gap across it is still counted.
t.pause()
res = feed(t, [(9, 60_000_000)])
assert res[-1] == (6, False)
assert t.summary() == "6"

print("ALL SEQ-GAP CHECKS PASSED")
