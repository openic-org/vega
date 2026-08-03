"""
correlate_stalls.py — cross-correlate CSV SKP events against a UART stall log
by RTC timestamp, to test which MCU-side transition a residual SKP cluster
lines up with.

Built for the Category B SKP investigation (see
memory/project_skp_investigation.md and log/2026-07-30.md sec. 7.3/8):
Category B residuals sit at a tight +46.0-46.2 ms offset after a flow-off
*resume*, not colocated with it — leading hypothesis is a mirror-image bug
at the ring-buffer *drain* transition in StreamAssemblePacket(). This script
parses both the "LONG STALL ... resumed_at=" lines and the new "ring drained
to 0 at ..." diagnostic line (added stream_app.c, StreamAssemblePacket) from
the same UART capture, and reports which one each SKP sits closest to.

Usage:
    python3 pc-app/correlate_stalls.py <recording.csv> <stall_log.txt>
"""

import re
import sys
from pathlib import Path

import numpy as np

from analyze_recording import compute_stats

RESUME_RE = re.compile(
    r"LONG STALL - flow-off #(\d+) took (\d+) us to resume .*resumed_at=(\d+)\.(\d+)"
)
DRAIN_RE = re.compile(
    r"ring drained to 0 at (\d+)\.(\d+) \(backlog was (\d+) pairs\)"
)


def _rtc_to_us(sec_str: str, sub_str: str) -> float:
    """RTC timestamp -> microseconds, matching StreamGetTimestamp's encoding:
    sub_s is an integer in 0..31999 (32000 ticks/s), NOT a decimal fraction —
    "resumed_at=46.27676" means ts_s=46, ts_sub=27676, not 46.27676 s."""
    return int(sec_str) * 1_000_000.0 + int(sub_str) * 1_000.0 / 32.0


def parse_stall_log(path: Path):
    resumes, drains = [], []
    for line in path.read_text(errors="replace").splitlines():
        m = RESUME_RE.search(line)
        if m:
            resumes.append(_rtc_to_us(m.group(3), m.group(4)))
            continue
        m = DRAIN_RE.search(line)
        if m:
            drains.append((_rtc_to_us(m.group(1), m.group(2)), int(m.group(3))))
    return np.array(sorted(resumes)), sorted(drains)


def nearest_signed_offset(t_events: np.ndarray, t_skp: float):
    """Signed offset (us) from t_skp to the nearest entry in t_events."""
    if len(t_events) == 0:
        return None
    idx = np.searchsorted(t_events, t_skp)
    candidates = []
    if idx > 0:
        candidates.append(t_events[idx - 1])
    if idx < len(t_events):
        candidates.append(t_events[idx])
    best = min(candidates, key=lambda e: abs(t_skp - e))
    return t_skp - best


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 correlate_stalls.py <recording.csv> <stall_log.txt>")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    log_path = Path(sys.argv[2])

    s = compute_stats(csv_path)
    valid = ~s["underrun_mask"]
    t_valid = s["t"][valid]
    c0_valid = s["ch0"][valid].astype(np.int32)
    step = np.diff(c0_valid)
    skp_idx = np.where((step != 0) & (step != 1))[0] + 1  # same logic as compute_stats()
    t_skp = t_valid[skp_idx]

    resume_us, drains = parse_stall_log(log_path)
    drain_us = np.array([d[0] for d in drains])

    print(f"{csv_path.name}: {len(t_skp)} SKP events")
    print(f"{log_path.name}: {len(resume_us)} resume timestamps, {len(drain_us)} ring-drain timestamps")
    if len(drain_us) == 0:
        print("\nNo 'ring drained to 0' lines found — recording predates the Category B "
              "diagnostic, or the ring never got a chance to fully drain in this run.")

    resume_offsets = np.array([nearest_signed_offset(resume_us, t) for t in t_skp], dtype=float) if len(resume_us) else np.full(len(t_skp), np.nan)
    drain_offsets = np.array([nearest_signed_offset(drain_us, t) for t in t_skp], dtype=float) if len(drain_us) else np.full(len(t_skp), np.nan)

    NEAR_RESUME_US = 2_000       # flow_off-adjacent (the already-fixed bug's signature)
    DRAIN_WINDOW_US = (38_000, 43_000)   # +40.0-40.4 ms band, refined 2026-07-31 after
                                          # fixing the ch0-wraparound false-positive bug in
                                          # compute_stats() (was 44.0-48.0 ms, skewed by wrap noise)

    near_resume = np.abs(resume_offsets) < NEAR_RESUME_US
    near_drain_band = (drain_offsets > DRAIN_WINDOW_US[0]) & (drain_offsets < DRAIN_WINDOW_US[1])
    unmatched = ~near_resume & ~near_drain_band

    print(f"\nSKPs within {NEAR_RESUME_US/1000:.0f} ms of a resume     : {int(np.sum(near_resume))}/{len(t_skp)}")
    print(f"SKPs at +{DRAIN_WINDOW_US[0]/1000:.1f}-{DRAIN_WINDOW_US[1]/1000:.1f} ms after a ring-drain : {int(np.sum(near_drain_band))}/{len(t_skp)}")
    print(f"Unmatched by either                        : {int(np.sum(unmatched))}/{len(t_skp)}")

    if len(drain_us):
        band_vals = drain_offsets[near_drain_band]
        if len(band_vals):
            print(f"\nDrain-band offsets (ms): mean={band_vals.mean()/1000:.3f} "
                  f"std={band_vals.std()/1000:.3f} n={len(band_vals)}")

    print("\nPer-event detail (t_skp, jump, offset-to-resume ms, offset-to-drain ms):")
    for t, off_r, off_d in zip(t_skp, resume_offsets, drain_offsets):
        r_str = f"{off_r/1000:+8.3f}" if not np.isnan(off_r) else "     n/a"
        d_str = f"{off_d/1000:+8.3f}" if not np.isnan(off_d) else "     n/a"
        print(f"  t={t/1e6:10.4f}s   resume={r_str} ms   drain={d_str} ms")


if __name__ == "__main__":
    main()
