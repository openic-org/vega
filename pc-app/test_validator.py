#!/usr/bin/env python3
"""
test_validator.py — headless Vega packet validator / regression harness.

Reads StreamDataPacket_t frames from the WB09KE bridge serial port and reports:
  - effective packet rate and SPS
  - seq_num gaps (dropped BLE packets, counted as gap width mod 256)
  - raw timestamp monotonicity violations (RTC backwards jumps before clamp)
  - framing errors (junk bytes discarded before 0xAA 0x55 re-sync)

Prints a one-line summary every second. On exit prints a final summary and
returns exit code 0 (PASS) or 1 (FAIL: drops > --max-drops or serial error).

Usage:
  python test_validator.py --port /dev/ttyACM0
  python test_validator.py --port /dev/ttyACM0 --duration 30 --max-drops 0
  python test_validator.py --port /dev/ttyACM0 --verbose
"""

import argparse
import signal
import sys
import time

import serial

from packet_parser import MAGIC, parse, SAMPLE_RATE_HZ

BAUD_RATE = 2_000_000


def run(port_name: str, duration: float, max_drops: int, verbose: bool) -> int:
    print(f"Opening {port_name} at {BAUD_RATE} baud ...")
    try:
        port = serial.Serial(port_name, baudrate=BAUD_RATE, timeout=1.0)
        port.reset_input_buffer()   # discard data the kernel buffered before port-open
    except serial.SerialException as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    buf = bytearray()

    total_packets       = 0
    total_drops         = 0
    total_framing_bytes = 0
    total_ts_violations = 0
    expected_seq: int | None = None
    last_ts_us:   int | None = None

    iv_packets = 0
    iv_drops   = 0
    iv_framing = 0

    interrupted = False

    def _on_sigint(sig, frame):
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGINT, _on_sigint)

    t_start  = t_iv = time.monotonic()
    deadline = t_start + duration if duration > 0 else float("inf")

    HDR = f"{'Elapsed':>7}  {'pkt/s':>6}  {'SPS':>7}  {'drops/s':>7}  {'framing':>8}  {'ts_err':>6}"
    print(HDR)
    print("-" * len(HDR))

    while not interrupted and time.monotonic() < deadline:
        try:
            chunk = port.read(512)
        except serial.SerialException as e:
            print(f"\nSerial error: {e}", file=sys.stderr)
            break

        if chunk:
            buf.extend(chunk)

            while True:
                idx = buf.find(MAGIC)
                if idx == -1:
                    junk = max(0, len(buf) - 1)
                    total_framing_bytes += junk
                    iv_framing += junk
                    buf = buf[-1:]
                    break
                if idx > 0:
                    total_framing_bytes += idx
                    iv_framing += idx
                    buf = buf[idx:]
                if len(buf) < 4:
                    break

                frame_len   = int.from_bytes(buf[2:4], "little")
                total_frame = 4 + frame_len
                if len(buf) < total_frame:
                    break

                payload = bytes(buf[4:total_frame])
                buf = buf[total_frame:]

                pkt = parse(payload)
                if pkt is None:
                    continue

                total_packets += 1
                iv_packets    += 1

                # seq_num gap detection
                seq = pkt.header.seq_num
                if expected_seq is not None:
                    gap = (seq - expected_seq) % 256
                    if gap != 0:
                        total_drops += gap
                        iv_drops    += gap
                        if verbose:
                            print(f"  DROP  expected={expected_seq} got={seq}  "
                                  f"gap={gap}  ts_us={int(pkt.timestamps_us[0])}")
                expected_seq = (seq + 1) % 256

                # Raw timestamp monotonicity check (before the clamp applied in the UI)
                ts_us = int(pkt.timestamps_us[0])
                if last_ts_us is not None and ts_us < last_ts_us:
                    total_ts_violations += 1
                    if verbose:
                        print(f"  TS BACKWARDS  {ts_us} < {last_ts_us}  "
                              f"delta={last_ts_us - ts_us} us")
                last_ts_us = ts_us

        # Per-second summary line
        now = time.monotonic()
        if now - t_iv >= 1.0:
            dt      = now - t_iv
            pps     = iv_packets / dt
            sps     = pps * pkt.header.num_pairs if total_packets > 0 else pps * 59
            elapsed = now - t_start
            print(f"{elapsed:7.1f}  {pps:6.1f}  {sps:7.0f}  {iv_drops:7}  "
                  f"{iv_framing:8}  {total_ts_violations:6}")
            iv_packets = iv_drops = iv_framing = 0
            t_iv = now

    port.close()

    elapsed = time.monotonic() - t_start
    avg_pps = total_packets / elapsed if elapsed > 0 else 0.0
    avg_sps = avg_pps * 59

    print("-" * len(HDR))
    print(f"Duration      : {elapsed:.1f} s")
    print(f"Total packets : {total_packets}")
    print(f"Avg pkt/s     : {avg_pps:.1f}")
    print(f"Avg SPS       : {avg_sps:.0f}")
    print(f"Total drops   : {total_drops}")
    print(f"Framing bytes : {total_framing_bytes}")
    print(f"TS violations : {total_ts_violations}")

    if total_drops > max_drops:
        print(f"\nFAIL — {total_drops} drops > allowed {max_drops}", file=sys.stderr)
        return 1
    print(f"\nPASS — {total_drops} drops <= allowed {max_drops}")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Vega headless packet validator / regression harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_validator.py --port /dev/ttyACM0
  python test_validator.py --port /dev/ttyACM0 --duration 30
  python test_validator.py --port /dev/ttyACM0 --duration 60 --max-drops 5 --verbose
        """,
    )
    ap.add_argument("--port", required=True,
                    help="Serial port, e.g. /dev/ttyACM0 or COM3")
    ap.add_argument("--duration", type=float, default=0,
                    help="Stop after this many seconds (0 = run until Ctrl-C)")
    ap.add_argument("--max-drops", type=int, default=0,
                    help="Exit 1 if cumulative seq_num drops exceed this (default 0)")
    ap.add_argument("--verbose", action="store_true",
                    help="Print each individual drop and timestamp violation inline")
    args = ap.parse_args()
    sys.exit(run(args.port, args.duration, args.max_drops, args.verbose))


if __name__ == "__main__":
    main()
