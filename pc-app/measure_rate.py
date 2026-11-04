"""
measure_rate.py — the per-channel sample rate Kuntur actually produced,
measured from a vega_*.csv recording.

PLAN.md R1, task #6 bench check: after flashing a new bitstream, confirm
that `clk` is what the build says (25,000 S/s for variants 2/3, 28,000 for
variant 1) before anything else is built on it.

What it measures, and why the pc-app's own timestamps cannot be used:
inside a packet the pc-app spaces samples by its hard-coded
packet_parser.SAMPLE_RATE_HZ, so per-sample timestamps only echo that
constant. This uses the first row of each packet only (the MCU's RTC at
packet assembly) and counts real samples, i.e. not the (0x8000, 0x8000)
pairs the FPGA returns when its FIFO is empty. The rate is the slope of a
least-squares fit of cumulative real samples against packet time. Every
packet carries the samples produced since the previous one, so dropped
packets would bias it low: gaps found in seq_num are filled with the mean
real count per packet, and reported.

Only valid while the transport keeps up (λ < μ, about 29,466 S/s
measured, A.7): then the FIFO stays near empty and some slots are padding.
With no padding the FPGA may be discarding samples on overflow, and the
result is the delivered rate, a lower bound; the script says so. Both
test rates are below μ (padding ≈ 15% at 25k, ≈ 5% at 28k).

Accuracy: the time base is the MCU's 32.768 kHz LSE, a different crystal
from the 32 MHz HSE the FPGA's clock comes from; both are tens of ppm,
well inside the ±0.05% (500 ppm) default tolerance. Record at least a
minute.

Usage:
    python3 pc-app/measure_rate.py RECORDING.csv [--expect 25000] [--tol 0.05]

Exit status 0 if within tolerance of --expect (or no --expect given),
1 if not, 2 if the recording cannot be used.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

from packet_parser import is_fifo_underrun

PAIRS_PER_PACKET = 59          # STREAM_PAIRS_PER_PACKET, stream_app.h
MIN_SPAN_S = 60.0


def load(path: Path):
    """t (µs), ch0, ch1, seq from a recording with the seq_num column."""
    with open(path) as f:
        first = f.readline()
        skiprows = 1
        header_line = first
        if first.startswith("#"):
            header_line = f.readline()
            skiprows = 2
    header = header_line.strip().split(",")
    if "seq_num" not in header:
        raise ValueError("no seq_num column: packets cannot be told apart")
    dtype = np.dtype({"names": ["t", "ch0", "ch1", "seq"],
                      "formats": [np.int64] * 4})
    d = np.loadtxt(path, delimiter=",", skiprows=skiprows, dtype=dtype, ndmin=1)
    return d["t"], d["ch0"].astype(np.int16), d["ch1"].astype(np.int16), d["seq"]


def packets(t, ch0, ch1, seq):
    """Per packet: base time (µs), real-sample count, seq.

    A packet is a run of rows with one seq_num, at most PAIRS_PER_PACKET
    long (a run of 256·k lost packets can leave two neighbours with the
    same seq).
    """
    real = ~is_fifo_underrun(ch0, ch1)
    starts = [0]
    run = 1
    for i in range(1, len(seq)):
        if seq[i] != seq[i - 1] or run == PAIRS_PER_PACKET:
            starts.append(i)
            run = 1
        else:
            run += 1
    starts = np.array(starts)
    base = t[starts]
    n_real = np.add.reduceat(real.astype(np.int64), starts)
    return base, n_real, seq[starts]


def measure(base, n_real, pseq):
    """Rate (S/s per channel) and diagnostics from per-packet data."""
    if len(base) < 3:
        raise ValueError("fewer than 3 packets")
    span_s = (base[-1] - base[0]) / 1e6
    gaps = (np.diff(pseq) - 1) % 256
    dt = np.diff(base)
    med_dt = float(np.median(dt[dt > 0])) if np.any(dt > 0) else 0.0
    # A gap the time says is much longer than its seq count may hide whole
    # wraps of seq_num: report it, the fill below is then a lower bound.
    uncertain = int(np.sum((med_dt > 0) & (dt > (gaps + 1 + 128) * med_dt)))
    mean_real = float(np.mean(n_real))
    filled = n_real[1:] + gaps * mean_real   # samples since the previous packet
    cum = np.concatenate(([0.0], np.cumsum(filled)))
    x = (base - base[0]) / 1e6
    slope, _ = np.polyfit(x, cum, 1)
    return {
        "rate": float(slope),
        "endpoints_rate": float(cum[-1] / span_s) if span_s > 0 else float("nan"),
        "span_s": span_s,
        "packets": int(len(base)),
        "lost_packets": int(np.sum(gaps)),
        "uncertain_gaps": uncertain,
        "padding": 1.0 - float(np.sum(n_real)) / (len(base) * PAIRS_PER_PACKET),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("csv", type=Path)
    ap.add_argument("--expect", type=float, help="expected S/s per channel, e.g. 25000")
    ap.add_argument("--tol", type=float, default=0.05, help="tolerance in %% (default 0.05)")
    a = ap.parse_args(argv)

    try:
        r = measure(*packets(*load(a.csv)))
    except (ValueError, OSError) as e:
        print(f"{a.csv}: {e}", file=sys.stderr)
        return 2

    print(f"{a.csv.name}")
    print(f"  rate          {r['rate']:,.2f} S/s per channel (fit)")
    print(f"                {r['endpoints_rate']:,.2f} S/s (first to last packet)")
    print(f"  span          {r['span_s']:.1f} s, {r['packets']} packets")
    print(f"  lost packets  {r['lost_packets']} (filled with the mean real count)"
          + (f", {r['uncertain_gaps']} gaps may hide seq wraps" if r["uncertain_gaps"] else ""))
    print(f"  padding       {100 * r['padding']:.1f}% of slots were FIFO-empty 0x8000")
    saturated = r["padding"] < 0.005
    if saturated:
        print("  warning       almost no padding: the transport may be saturated and"
              " fifo0 overflowing; the rate is then a lower bound")
    if r["span_s"] < MIN_SPAN_S:
        print(f"  warning       under {MIN_SPAN_S:.0f} s: record longer for a ±0.05% answer")
    if a.expect is None:
        return 0
    err = 100.0 * (r["rate"] - a.expect) / a.expect
    ok = abs(err) <= a.tol and r["uncertain_gaps"] == 0 and not saturated
    print(f"  expected      {a.expect:,.0f} S/s: {err:+.3f}% -> {'PASS' if ok else 'FAIL'}"
          f" (tolerance ±{a.tol}%)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
