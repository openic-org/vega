"""
plot_gpio_bench.py — plot BLE throughput vs GPIO toggle load from a bench CSV.

Usage:
    python3 pc-app/plot_gpio_bench.py [bench_YYYYMMDD_HHMMSS.csv]

If no file is given, uses the most recent bench_*.csv in the current directory.

The GPIO bench firmware sweeps loop counts every 5 s in this order:
    {0, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096}
Each loop = one PB3 HIGH+LOW toggle pair (~125–187 ns at 32 MHz).
"""

import sys
import csv
import glob
import numpy as np
import matplotlib.pyplot as plt

SWEEP   = [0, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]
STEP_S  = 5.0
NS_PER_PAIR = 156   # ~125–187 ns; mid-estimate at 32 MHz


def load(path):
    elapsed, kbps = [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            elapsed.append(float(row["elapsed_s"]))
            kbps.append(float(row["kbps"]))
    return np.array(elapsed), np.array(kbps)


def loops_at(t):
    """Return the sweep loop count active at elapsed time t."""
    idx = min(int(t / STEP_S), len(SWEEP) - 1)
    return SWEEP[idx]


def main():
    files = sorted(glob.glob("bench_*.csv"))
    path  = sys.argv[1] if len(sys.argv) > 1 else (files[-1] if files else None)
    if not path:
        print("No bench_*.csv found.  Run the pc-app while connected to generate one.")
        return

    elapsed, kbps = load(path)
    if len(elapsed) == 0:
        print(f"No data in {path}")
        return

    # ── Per-step averages ─────────────────────────────────────────────────────
    step_loops, step_kbps_mean = [], []
    for i, loops in enumerate(SWEEP):
        t0, t1 = i * STEP_S, (i + 1) * STEP_S
        mask = (elapsed >= t0) & (elapsed < t1)
        if mask.any():
            step_loops.append(loops)
            step_kbps_mean.append(kbps[mask].mean())

    # ── Plot 1: throughput vs elapsed time ────────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    fig.suptitle(f"BLE throughput vs GPIO toggle load — {path}", fontsize=11)

    ax1.plot(elapsed, kbps, "o-", markersize=3, linewidth=1.2, color="steelblue")
    ax1.set_xlabel("Elapsed time (s)")
    ax1.set_ylabel("Throughput (kbit/s)")
    ax1.grid(True, alpha=0.3)

    y_lo = max(0, kbps.min() - 50)
    y_hi = kbps.max() + 50
    ax1.set_ylim(y_lo, y_hi)

    for i, loops in enumerate(SWEEP):
        t = i * STEP_S
        if t > elapsed[-1]:
            break
        ax1.axvline(t, color="gray", linestyle="--", alpha=0.35, linewidth=0.8)
        ax1.text(t + 0.15, y_hi - 30, f"{loops}", fontsize=7, color="gray")

    # ── Plot 2: mean kbps vs loop count (log-x) ───────────────────────────────
    if step_loops:
        us_per_notify = [l * NS_PER_PAIR / 1000 for l in step_loops]

        ax2.plot(step_loops, step_kbps_mean, "o-", markersize=5,
                 linewidth=1.5, color="steelblue")
        ax2.set_xlabel("Toggle pairs per notify call  (PB3 HIGH+LOW, ~156 ns each)")
        ax2.set_ylabel("Mean throughput (kbit/s)")
        ax2.grid(True, which="both", alpha=0.3)
        ax2.set_xscale("log")

        if step_loops[0] == 0:
            # log-scale can't plot 0; add offset for display only
            ax2.set_xlim(left=4)

        baseline = step_kbps_mean[0] if step_kbps_mean else kbps.max()
        ax2.axhline(baseline * 0.9, color="r", linestyle="--",
                    alpha=0.5, label="90 % of baseline")
        ax2.legend()

        # Secondary x-axis: µs per notify call
        ax2b = ax2.twiny()
        ax2b.set_xlim(ax2.get_xlim())
        ax2b.set_xscale("log")
        ax2b.set_xlabel("Approx. GPIO work per notify call (µs)")
        ticks = [l for l in step_loops if l > 0]
        ax2b.set_xticks(ticks)
        ax2b.set_xticklabels([f"{l * NS_PER_PAIR / 1000:.1f}" for l in ticks],
                             fontsize=8)

    plt.tight_layout()
    out = path.replace(".csv", "_plot.png")
    plt.savefig(out, dpi=150)
    print(f"Saved {out}")
    plt.show()


if __name__ == "__main__":
    main()
