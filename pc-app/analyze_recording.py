"""
analyze_recording.py — sample-level QA for a vega_*.csv recording.

Reports FIFO underrun rate, ch0 step continuity (DUP/SKP), the
ch1-ch0 offset distribution (channel-swap detector), and — for
recordings that carry the seq_num column — whether SKP events line
up with dropped/resynced BLE packets. Saves a 4-panel plot to
pc-app/analysis/.

Usage:
    python3 pc-app/analyze_recording.py pc-app/recordings/vega_20260728_063543.csv

compute_stats() is also used by compare_recordings.py to diff two
recordings (e.g. before/after a FIFO depth change).
"""

import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

FIFO_EMPTY_SENTINEL = np.int16(-32768)  # 0x8000 — FPGA FIFO underrun marker


def compute_stats(path: Path) -> dict:
    with open(path) as f:
        header = f.readline().strip().split(",")
    has_seq = "seq_num" in header

    names = ["t", "ch0", "ch1", "seq"] if has_seq else ["t", "ch0", "ch1"]
    data = np.genfromtxt(path, delimiter=",", skip_header=1,
                          dtype=np.int64, names=names)
    t   = data["t"]
    ch0 = data["ch0"].astype(np.int16)
    ch1 = data["ch1"].astype(np.int16)
    n   = len(t)

    duration_s = (t[-1] - t[0]) / 1e6
    sps = n / duration_s

    underrun_mask = (ch0 == FIFO_EMPTY_SENTINEL)
    n_underrun = int(np.sum(underrun_mask))

    valid = ~underrun_mask
    c0 = ch0[valid]
    c1 = ch1[valid]
    diff = c1.astype(np.int32) - c0.astype(np.int32)
    # ch1 = ch0 + 1000 (mod 65536): unwrap the same way, otherwise the ~1000
    # samples/cycle where ch1 has wrapped but ch0 hasn't read as a spurious
    # -64536 "channel swap" signature instead of the expected +1000.
    diff = ((diff + 32768) % 65536) - 32768

    step = np.diff(c0.astype(np.int32))
    # ch0 is a 16-bit ramp (int16) that wraps every 65536 samples; unwrap the
    # diff modulo 65536 so a normal wrap (e.g. 32767 -> -32768) reads as the
    # expected +1 instead of a spurious ~-65535 "SKP". A real skip that
    # straddles the wrap boundary still shows its true small magnitude.
    step = ((step + 32768) % 65536) - 32768
    skp_idx = np.where((step != 0) & (step != 1))[0] + 1  # index into c0/valid-space
    skp_jumps = step[skp_idx - 1]
    n_dup = int(np.sum(step == 0))
    n_skp = len(skp_idx)
    n_ok  = len(step) - n_dup - n_skp

    vals, counts = np.unique(diff, return_counts=True)
    order = np.argsort(-counts)
    diff_top5 = list(zip(vals[order][:5].tolist(), (100 * counts[order][:5] / len(diff)).tolist()))

    stats = dict(
        path=path, t=t, ch0=ch0, ch1=ch1, diff=diff, underrun_mask=underrun_mask,
        n=n, duration_s=duration_s, sps=sps,
        n_underrun=n_underrun, underrun_pct=100 * n_underrun / n,
        n_dup=n_dup, dup_pct=100 * n_dup / len(step),
        n_skp=n_skp, skp_pct=100 * n_skp / len(step),
        skp_jumps=skp_jumps,
        n_ok=n_ok, ok_pct=100 * n_ok / len(step),
        diff_top5=diff_top5,
        has_seq=has_seq,
    )

    if has_seq:
        seq = data["seq"][valid].astype(np.int32)
        seq_diff = np.diff(seq)
        boundary_idx = np.where(seq_diff != 0)[0] + 1  # rows where a new packet starts
        # packets dropped between this boundary and the previous one (0 = none)
        dropped_at_boundary = (seq_diff[boundary_idx - 1] - 1) % 256
        seq_gap_idx = boundary_idx[dropped_at_boundary != 0]

        n_seq_gaps = int(len(seq_gap_idx))
        n_packets_lost = int(dropped_at_boundary[dropped_at_boundary != 0].sum())
        matched = np.intersect1d(skp_idx, seq_gap_idx)
        stats.update(
            n_seq_gaps=n_seq_gaps,
            n_packets_lost=n_packets_lost,
            n_skp_matched_seq_gap=int(len(matched)),
        )

    return stats


def analyze(path: Path):
    s = compute_stats(path)
    t, ch0, ch1, diff, underrun_mask, n = s["t"], s["ch0"], s["ch1"], s["diff"], s["underrun_mask"], s["n"]

    print(f"{path.name}")
    print(f"  samples          : {n}  ({s['duration_s']:.2f} s)")
    print(f"  rate             : {s['sps']:.0f} SPS")
    print(f"  underruns        : {s['n_underrun']} ({s['underrun_pct']:.1f}%)")
    print(f"  ch0 step OK      : {s['ok_pct']:.1f}%")
    print(f"  ch0 DUP          : {s['n_dup']} ({s['dup_pct']:.2f}%)")
    print(f"  ch0 SKP          : {s['n_skp']} ({s['skp_pct']:.2f}%)")
    print("  ch1-ch0 diff (top 5):")
    for v, pct in s["diff_top5"]:
        print(f"    {v:+6d}: {pct:5.1f}%")

    if s["has_seq"]:
        print(f"  seq_num gaps     : {s['n_seq_gaps']} resync points, {s['n_packets_lost']} packets lost total")
        print(f"  SKP <-> seq gap  : {s['n_skp_matched_seq_gap']}/{s['n_skp']} SKPs coincide with a seq_num gap"
              f"   |   {s['n_skp_matched_seq_gap']}/{s['n_seq_gaps']} seq gaps coincide with a SKP")
    else:
        print("  seq_num gaps     : n/a (recording predates the seq_num column)")

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle(path.name)

    window = min(2000, n)
    tw = (t[:window] - t[0]) / 1000.0
    axes[0, 0].plot(tw, ch0[:window], label="ch0", linewidth=0.8)
    axes[0, 0].plot(tw, ch1[:window], label="ch1", linewidth=0.8)
    axes[0, 0].set_title(f"First {window} samples")
    axes[0, 0].set_xlabel("ms")
    axes[0, 0].legend()
    axes[0, 0].grid(alpha=0.3)

    axes[0, 1].hist(diff, bins=100)
    axes[0, 1].set_title("ch1 - ch0 distribution (valid samples)")
    axes[0, 1].set_yscale("log")
    axes[0, 1].grid(alpha=0.3)

    bucket_s = 1.0
    bucket_idx = ((t - t[0]) / 1e6 / bucket_s).astype(int)
    n_buckets = bucket_idx[-1] + 1
    underrun_per_s = np.bincount(bucket_idx, weights=underrun_mask, minlength=n_buckets)
    total_per_s = np.bincount(bucket_idx, minlength=n_buckets)
    axes[1, 0].plot(np.arange(n_buckets), 100 * underrun_per_s / np.maximum(total_per_s, 1))
    axes[1, 0].set_title("Underrun % per second")
    axes[1, 0].set_xlabel("s")
    axes[1, 0].set_ylabel("%")
    axes[1, 0].grid(alpha=0.3)

    axes[1, 1].plot(np.arange(n_buckets), total_per_s)
    axes[1, 1].set_title("Samples per second")
    axes[1, 1].set_xlabel("s")
    axes[1, 1].grid(alpha=0.3)

    plt.tight_layout()
    out_dir = Path(__file__).parent / "analysis"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{path.stem}_analysis.png"
    plt.savefig(out_path, dpi=150)
    print(f"\nSaved {out_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 analyze_recording.py <vega_*.csv>")
        sys.exit(1)
    analyze(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
