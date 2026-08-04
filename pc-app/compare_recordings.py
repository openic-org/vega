"""
compare_recordings.py — before/after diff for two vega_*.csv recordings.

Built for the 512-vs-1024-pair FIFO depth experiment: run the same test
before and after the FPGA change, then diff the two recordings to see
whether SKP (overflow) and underrun (rate-mismatch) rates actually moved,
and by how much.

Usage:
    python3 pc-app/compare_recordings.py <before.csv> <after.csv>
"""

import sys
from pathlib import Path

import numpy as np

from analyze_recording import compute_stats


def pct_change(before, after):
    if before == 0:
        return "n/a" if after == 0 else "+inf"
    return f"{100 * (after - before) / before:+.0f}%"


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 compare_recordings.py <before.csv> <after.csv>")
        sys.exit(1)

    before_path = Path(sys.argv[1])
    after_path  = Path(sys.argv[2])
    b = compute_stats(before_path)
    a = compute_stats(after_path)

    print(f"before : {before_path.name}  ({b['n']} samples, {b['duration_s']:.2f}s)")
    print(f"after  : {after_path.name}  ({a['n']} samples, {a['duration_s']:.2f}s)")
    print()

    rows = [
        ("rate (SPS)",        f"{b['sps']:.0f}",         f"{a['sps']:.0f}"),
        ("underruns",         f"{b['n_underrun']} ({b['underrun_pct']:.1f}%)",
                               f"{a['n_underrun']} ({a['underrun_pct']:.1f}%)"),
        ("ch0 DUP",           f"{b['n_dup']} ({b['dup_pct']:.2f}%)",
                               f"{a['n_dup']} ({a['dup_pct']:.2f}%)"),
        ("ch0 SKP",           f"{b['n_skp']} ({b['skp_pct']:.3f}%)",
                               f"{a['n_skp']} ({a['skp_pct']:.3f}%)"),
    ]

    hdr = f"{'metric':<16} {'before':<22} {'after':<22} {'change':<8}"
    print(hdr)
    print("-" * len(hdr))
    for label, bv, av in rows:
        # pull the leading int out of the "N (x%)" strings for pct_change
        b_n = int(bv.split()[0])
        a_n = int(av.split()[0])
        change = pct_change(b_n, a_n) if label != "rate (SPS)" else pct_change(float(bv), float(av))
        print(f"{label:<16} {bv:<22} {av:<22} {change:<8}")

    print()
    # exclude sawtooth-wraparound outliers (large negative jumps) from the summary —
    # they're a counter-overflow artifact, not part of the SKP/overflow signal
    b_fwd = b["skp_jumps"][(b["skp_jumps"] > 0) & (b["skp_jumps"] < 1000)]
    a_fwd = a["skp_jumps"][(a["skp_jumps"] > 0) & (a["skp_jumps"] < 1000)]
    if len(b_fwd) and len(a_fwd):
        print(f"SKP jump size (forward only) — before: median {np.median(b_fwd):.1f}, "
              f"mean {b_fwd.mean():.1f}, max {b_fwd.max()}  (n={len(b_fwd)})")
        print(f"SKP jump size (forward only) — after : median {np.median(a_fwd):.1f}, "
              f"mean {a_fwd.mean():.1f}, max {a_fwd.max()}  (n={len(a_fwd)})")

    print()
    print("Verdict:")
    if b["skp_pct"] == 0:
        print("  before had 0 SKP — nothing to compare against.")
    elif a["skp_pct"] < b["skp_pct"] * 0.3:
        print("  SKP dropped sharply (>70%) -> looks like a capacity/burst-overflow issue.")
        print("  Bigger FIFO is a valid fix; keep it.")
    elif a["skp_pct"] > b["skp_pct"] * 0.7:
        print("  SKP essentially unchanged -> NOT a capacity issue.")
        print("  Points to a synchronous logic hazard in main_controller/fifo0 pointer logic —")
        print("  worth simulating, or exposing live FIFO occupancy via the regbank read path.")
    else:
        print("  SKP dropped but not sharply -> inconclusive; capacity may be A factor but")
        print("  probably not the whole story. Consider a bigger jump (e.g. 1024 -> 2048) to")
        print("  see if it keeps scaling down, which would confirm capacity as the driver.")


if __name__ == "__main__":
    main()
