"""Tests for measure_rate.py on synthetic recordings with a known rate.

    python3 test_measure_rate.py
"""

import tempfile
from pathlib import Path

import numpy as np

import measure_rate as mr

SENT = -32768


def synth(rate, seconds=90.0, mu=29_466.0, drop_every=0, clamp=False, seed=1):
    """Rows (t, ch0, ch1, seq) as the pc-app records them.

    Packets leave at the transport's pace (59 slots each, mu slots/s, in
    bursts); each carries the real samples produced since the previous one,
    the rest is 0x8000 padding.
    """
    rng = np.random.default_rng(seed)
    n_pkt = int(seconds * mu / mr.PAIRS_PER_PACKET)
    # bursty departure times around the mean pace
    dt = rng.exponential(mr.PAIRS_PER_PACKET / mu, n_pkt)
    tx = np.cumsum(dt)
    rows, backlog, produced_prev, last_ts = [], 0.0, 0.0, 0
    for k in range(n_pkt):
        produced = rate * tx[k]
        backlog += produced - produced_prev
        produced_prev = produced
        n = int(min(backlog, mr.PAIRS_PER_PACKET))
        backlog -= n
        seq = k % 256
        if drop_every and k % drop_every == drop_every - 1:
            continue                    # lost on air: its samples are gone
        base = int(round(tx[k] * 1e6 / 1000)) * 1000   # ms-ish RTC resolution
        if clamp and base <= last_ts:
            base = last_ts + 33
        for i in range(mr.PAIRS_PER_PACKET):
            v = 100 if i < n else SENT
            rows.append((base + 33 * i, v, v, seq))
        last_ts = base + 33 * (mr.PAIRS_PER_PACKET - 1)
    a = np.array(rows, dtype=np.int64)
    return a[:, 0], a[:, 1].astype(np.int16), a[:, 2].astype(np.int16), a[:, 3]


# 1. the rate comes back at both test rates, with the expected padding
for rate in (25_000.0, 28_000.0):
    r = mr.measure(*mr.packets(*synth(rate)))
    assert abs(r["rate"] - rate) / rate < 2e-4, r
    assert r["lost_packets"] == 0
    assert abs(r["padding"] - (1 - rate / 29_466.0)) < 0.01, r
    print(f"{rate:.0f}: measured {r['rate']:.1f}, padding {100 * r['padding']:.1f}%")

# 2. packets lost on air are found in seq_num and filled
r = mr.measure(*mr.packets(*synth(25_000.0, drop_every=50)))
assert r["lost_packets"] > 0
assert abs(r["rate"] - 25_000.0) / 25_000.0 < 1e-3, r
print(f"1 packet in 50 lost: {r['lost_packets']} found, measured {r['rate']:.1f}")

# 3. the pc-app's monotonicity clamp on burst timestamps does not bias it
r = mr.measure(*mr.packets(*synth(28_000.0, clamp=True)))
assert abs(r["rate"] - 28_000.0) / 28_000.0 < 5e-4, r
print(f"clamped timestamps: measured {r['rate']:.1f}")

# 4. the command line: PASS at the right rate, FAIL at the wrong one
t, c0, c1, s_ = synth(25_000.0)
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "rec.csv"
    with open(p, "w") as f:
        f.write("# vega-recording-format-version: 1\ntimestamp_us,ch0,ch1,seq_num\n")
        for row in zip(t, c0, c1, s_):
            f.write("%d,%d,%d,%d\n" % row)
    assert mr.main([str(p), "--expect", "25000"]) == 0
    assert mr.main([str(p), "--expect", "28000"]) == 1

print("=" * 70)
print("ALL MEASURE-RATE CHECKS PASSED")
