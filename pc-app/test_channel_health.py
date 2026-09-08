"""Tests for the RHD2164 channel-liveness detector (channel_health.py).

The fault it detects — chip0 going flat at 0xFFFF mid-session and recovering
spontaneously — was observed on 2026-09-08 and is recorded in
log/chip0-temperature-trials.md. These tests pin the three properties that
make the detector trustworthy rather than merely present:

  1. it does not fire on a real signal that passes through -1,
  2. it DOES fire when underrun sentinels are sprinkled through a dead
     channel, which is the configuration the A.7 PLL retune creates, and
  3. transition timestamps are backdated to where the run began, not to
     where the threshold was crossed.

    python3 test_channel_health.py
"""
import numpy as np

from channel_health import (
    ChannelHealthMonitor, DEAD_VALUE, ALIVE, DEAD, UNKNOWN,
)

RATE = 28_000
STEP_US = 1_000_000 / RATE
PAIRS = 59
UNDERRUN = -32768


def batches(mon, ch0_val, ch1_val, n_batches, start_us=0, underrun_every=0):
    """Feed n_batches of PAIRS samples; returns all transitions and the last ts."""
    out = []
    ts = start_us
    for b in range(n_batches):
        ch0 = np.full(PAIRS, ch0_val, dtype=np.int16)
        ch1 = np.full(PAIRS, ch1_val, dtype=np.int16)
        if underrun_every and (b % underrun_every == 0):
            # One underrun pair per Nth batch — both channels, which is the
            # only thing packet_parser.is_fifo_underrun counts.
            ch0[0] = UNDERRUN
            ch1[0] = UNDERRUN
        t = (ts + np.arange(PAIRS) * STEP_US).astype(np.int64)
        out += mon.update(ch0, ch1, t)
        ts += PAIRS * STEP_US
    return out, ts


# ── 1. a live channel never trips ───────────────────────────────────────────
mon = ChannelHealthMonitor(RATE)
rng = np.random.default_rng(0)
ts = 0
for _ in range(400):
    ch0 = rng.integers(-500, 500, PAIRS).astype(np.int16)
    ch1 = rng.integers(-500, 500, PAIRS).astype(np.int16)
    ch0[0] = DEAD_VALUE          # real signal touches -1 every batch
    t = (ts + np.arange(PAIRS) * STEP_US).astype(np.int64)
    for tr in mon.update(ch0, ch1, t):
        assert tr.to_state != DEAD, "noise touching -1 must not trip the detector"
    ts += PAIRS * STEP_US
# A healthy channel must reach ALIVE even though it touches -1 in every single
# batch — the first implementation used a consecutive-alive duration and this
# case pinned it at `unknown` forever.
assert mon.state("ch0") == ALIVE, "a live channel that touches -1 must still read alive"
assert mon.state("ch1") == ALIVE
assert not mon.any_dropouts()
print("live channel with -1 excursions in every batch: alive, no false positive")


# ── 2. a dead channel is detected, and only that channel ────────────────────
mon = ChannelHealthMonitor(RATE)
trans, ts = batches(mon, 100, 100, 60)          # both alive first
assert mon.state("ch0") == ALIVE
trans, ts = batches(mon, DEAD_VALUE, 100, 200, start_us=ts)
assert len(trans) == 1, f"expected exactly one transition, got {trans}"
assert trans[0].channel == "ch0" and trans[0].to_state == DEAD
assert mon.state("ch0") == DEAD, "ch0 must read dead"
assert mon.state("ch1") == ALIVE, "ch1 must be unaffected"
assert mon.dropouts("ch0") == 1 and mon.dropouts("ch1") == 0
print("dead channel detected, neighbour unaffected")


# ── 3. recovery is detected, and dropouts stay sticky ───────────────────────
trans, ts = batches(mon, 100, 100, 60, start_us=ts)
assert len(trans) == 1 and trans[0].to_state == ALIVE
assert mon.state("ch0") == ALIVE
assert mon.dropouts("ch0") == 1, "a channel that died and recovered is not one that never died"
assert mon.dead_seconds("ch0") > 0
print(f"recovery detected; dead for {mon.dead_seconds('ch0'):.2f} s, dropouts sticky at 1")


# ── 4. underrun sentinels must not mask a dead channel ──────────────────────
# This is the A.7 case: after the PLL retune, lambda < mu means ~5% of samples
# are 0x8000 underrun padding by design. If those counted as "alive" they would
# reset the dead-run counter and the detector would never fire.
mon = ChannelHealthMonitor(RATE)
batches(mon, 100, 100, 60)
trans, _ = batches(mon, DEAD_VALUE, 100, 200, underrun_every=1)
assert any(t.to_state == DEAD and t.channel == "ch0" for t in trans), \
    "underrun sentinels sprinkled through a dead channel must not mask it"
print("underrun sentinels do not mask a dead channel")


# ── 5. transitions are backdated to where the run began ─────────────────────
mon = ChannelHealthMonitor(RATE)
_, ts_alive_end = batches(mon, 100, 100, 60)
trans, _ = batches(mon, DEAD_VALUE, 100, 200, start_us=ts_alive_end)
t = [x for x in trans if x.to_state == DEAD][0]
# The dead run started at the first dead sample, i.e. right at ts_alive_end.
# Allow one batch of slack for run bookkeeping.
slack_us = PAIRS * STEP_US
assert abs(t.sample_timestamp_us - ts_alive_end) <= slack_us, (
    f"transition backdated to {t.sample_timestamp_us}, dead run began ~{ts_alive_end}")
# And it must be well BEFORE the moment the threshold was crossed.
detected_at = ts_alive_end + mon._dead_enter * STEP_US
assert t.sample_timestamp_us < detected_at - slack_us, \
    "timestamp must predate the detection point, not equal it"
print(f"transition backdated correctly ({t.sample_timestamp_us} vs detection ~{int(detected_at)})")


# ── 6. summary shape, as the sidecar will carry it ──────────────────────────
s = mon.summary()
assert s["detector_version"] == 1 and s["dead_value"] == DEAD_VALUE
assert s["channels"]["ch0"]["dropouts"] == 1
assert s["channels"]["ch0"]["state"] == DEAD
assert len(s["transitions"]) >= 1
import json; json.dumps(s)     # must be JSON-serialisable for the sidecar
print("summary is sidecar-ready and JSON-serialisable")


# ── 7. degenerate input must not crash (A.6.1 shape) ────────────────────────
mon = ChannelHealthMonitor(RATE)
assert mon.update(np.array([], dtype=np.int16), np.array([], dtype=np.int16),
                  np.array([], dtype=np.int64)) == []
assert mon.update(np.array([UNDERRUN], dtype=np.int16),
                  np.array([UNDERRUN], dtype=np.int16),
                  np.array([0], dtype=np.int64)) == []
assert mon.state("ch0") == UNKNOWN
print("empty and all-underrun batches handled without crashing")

print("=" * 70)
print("ALL CHANNEL-HEALTH CHECKS PASSED")
