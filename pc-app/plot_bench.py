"""
plot_bench.py — plot BLE throughput vs CPU burn loops from bench.log

Usage:
    cat /dev/ttyACM0 | tee bench.log          # capture while firmware runs
    python3 pc-app/plot_bench.py bench.log    # plot after (or pipe live)
"""

import sys
import re
import matplotlib.pyplot as plt

def parse(path):
    loops, notifs = [], []
    with open(path) as f:
        for line in f:
            m = re.search(r'BENCH t=\d+ loops=(\d+) notifs/s=(\d+)', line)
            if m:
                loops.append(int(m.group(1)))
                notifs.append(int(m.group(2)))
    return loops, notifs

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "bench.log"
    loops, notifs = parse(path)
    if not loops:
        print("No BENCH lines found in", path)
        return

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(loops, notifs, 'o-', markersize=4)
    ax.set_xlabel("Burn loops per invocation (~15.6 ns/loop at 64 MHz)")
    ax.set_ylabel("BLE notifications / second")
    ax.set_title("BLE throughput vs CPU burn load")
    ax.set_xscale("log")
    ax.grid(True, which="both", alpha=0.3)

    # annotate baseline
    if notifs:
        baseline = max(notifs[:5]) if len(notifs) >= 5 else notifs[0]
        ax.axhline(baseline * 0.9, color='r', linestyle='--', alpha=0.5,
                   label='90 % baseline')
        ax.legend()

    # add µs axis on top
    ax2 = ax.twiny()
    ax2.set_xlim(ax.get_xlim())
    ax2.set_xscale("log")
    ax2.set_xlabel("Approx. burn time per invocation (µs)")
    ticks = [100, 1000, 10000, 100000]
    ax2.set_xticks(ticks)
    ax2.set_xticklabels([f"{t*15.6/1000:.0f}" for t in ticks])

    plt.tight_layout()
    out = path.replace(".log", "_plot.png")
    plt.savefig(out, dpi=150)
    print(f"Saved {out}")
    plt.show()

if __name__ == "__main__":
    main()
