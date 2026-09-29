#!/usr/bin/env python3
"""
ambient_logger.py — room temperature / humidity record for the chip0 trials.

Listens for a Govee H5075 thermo-hygrometer's BLE advertisements and appends
one row per --interval to bench/ambient_YYYYMMDD_HHMMSS.csv, on the same
wall_time_utc timebase as the pc-app's bench/health_*.csv, so a dead/alive
edge can be joined to the room conditions it happened in. PLAN.md A.1.2:
every temperature statement in the trial log so far is an inference from a
thermostat one floor up; this is the first measurement where the board is.

A separate process on purpose — it must keep logging while the headstage is
powered off overnight, which is when the pc-app is closed.

Decode (PLAN.md A.1.2, "Model confirmed: Govee H5075"): manufacturer data
under company ID 0xEC88 is [0x00, b1, b2, b3, batt]; base = b1b2b3 big-endian,
bit 23 = negative, v = base & 0x7FFFFF, T = ±(v // 1000) / 10 °C,
RH = (v % 1000) / 10 %. Battery = batt & 0x7F; batt & 0x80 is an error flag,
logged rather than dropped — a sensor reporting an error must not silently
become an ambient record. The raw payload is logged too, so any decode
question can be re-answered from the file.

Needs an ACTIVE scan (the payload rides in the scan response); bleak's
default is active.

Usage:
  python3 ambient_logger.py --discover        # list Govee sensors in range, then exit
  python3 ambient_logger.py                   # log the first H5075 heard
  python3 ambient_logger.py --address A4:C1:38:xx:xx:xx --interval 10
"""

import argparse
import asyncio
import csv
import datetime
import math
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

GOVEE_COMPANY_ID = 0xEC88
BENCH_DIR = Path(__file__).parent / "bench"


@dataclass
class Reading:
    temp_c: float
    rh_pct: float
    battery_pct: int
    error: bool


def decode_h5075(mfr: bytes) -> Reading | None:
    """Decode manufacturer data under 0xEC88. None if it is not the H5075 shape."""
    if len(mfr) < 5:
        return None
    base = (mfr[1] << 16) | (mfr[2] << 8) | mfr[3]
    neg = base & 0x800000
    v = base & 0x7FFFFF
    temp = (v // 1000) / 10
    return Reading(
        temp_c=-temp if neg else temp,
        rh_pct=(v % 1000) / 10,
        battery_pct=mfr[4] & 0x7F,
        error=bool(mfr[4] & 0x80),
    )


def dew_point_c(temp_c: float, rh_pct: float) -> float | None:
    """Magnus–Alduchov–Eskridge. None at RH 0 (log undefined)."""
    if rh_pct <= 0:
        return None
    g = math.log(rh_pct / 100) + 17.625 * temp_c / (243.04 + temp_c)
    return 243.04 * g / (17.625 - g)


def utc_now() -> str:
    # Same format as channel_health.py's wall_time_utc.
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def discover(seconds: float) -> int:
    from bleak import BleakScanner

    seen: dict[str, str] = {}

    def cb(device, adv):
        if device.address in seen:
            return
        if GOVEE_COMPANY_ID in adv.manufacturer_data or (adv.local_name or "").startswith("GV"):
            seen[device.address] = adv.local_name or ""
            keys = ", ".join(f"0x{k:04X}" for k in adv.manufacturer_data)
            r = decode_h5075(adv.manufacturer_data.get(GOVEE_COMPANY_ID, b""))
            print(f"{device.address}  {adv.local_name or '?':16}  RSSI {adv.rssi:4}  "
                  f"mfr keys [{keys}]  {r if r else 'no 0xEC88 payload yet'}")

    print(f"Scanning {seconds:.0f} s for Govee sensors (active scan) ...")
    async with BleakScanner(detection_callback=cb, scanning_mode="active"):
        await asyncio.sleep(seconds)
    if not seen:
        print("None found. Check the sensor has a battery and is within range, and "
              "that no other app is holding the adapter.", file=sys.stderr)
        return 1
    return 0


async def log(address: str | None, interval: float) -> int:
    from bleak import BleakScanner

    BENCH_DIR.mkdir(exist_ok=True)
    path = BENCH_DIR / f"ambient_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv"
    f = open(path, "w", newline="")
    w = csv.writer(f)
    w.writerow(["wall_time_utc", "temp_c", "rh_pct", "dew_point_c",
                "battery_pct", "sensor_error", "rssi_dbm", "address", "raw_hex"])
    f.flush()

    target = address.upper() if address else None
    last_row = -math.inf
    rows = 0
    stop = asyncio.Event()

    def cb(device, adv):
        nonlocal target, last_row, rows
        mfr = adv.manufacturer_data.get(GOVEE_COMPANY_ID)
        if mfr is None:
            return
        if target is None:
            target = device.address.upper()
            print(f"Logging {target} ({adv.local_name or '?'}) → {path}")
        if device.address.upper() != target:
            return
        now = asyncio.get_running_loop().time()
        if now - last_row < interval:
            return
        r = decode_h5075(mfr)
        if r is None:
            return
        last_row = now
        dp = dew_point_c(r.temp_c, r.rh_pct)
        w.writerow([utc_now(), f"{r.temp_c:.1f}", f"{r.rh_pct:.1f}",
                    "" if dp is None else f"{dp:.1f}", r.battery_pct,
                    int(r.error), adv.rssi, target, bytes(mfr).hex()])
        f.flush()   # an unattended overnight run must survive being killed
        rows += 1
        if r.error:
            print(f"{utc_now()}  SENSOR ERROR FLAG SET — row logged and marked", file=sys.stderr)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    print(f"Waiting for {'the first H5075' if target is None else target} ... Ctrl-C to stop.")
    async with BleakScanner(detection_callback=cb, scanning_mode="active"):
        # Status line every minute, and a loud warning if the sensor goes
        # quiet — a gap in this file must be visible as a gap, not assumed.
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass
            silent = loop.time() - last_row
            if rows and silent > max(120, 4 * interval):
                print(f"{utc_now()}  WARNING: nothing from {target} for {silent:.0f} s",
                      file=sys.stderr)
            elif rows:
                print(f"{utc_now()}  {rows} rows")
    f.close()
    print(f"Stopped. {rows} rows in {path}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Govee H5075 → bench/ambient_*.csv")
    ap.add_argument("--discover", action="store_true", help="list Govee sensors in range and exit")
    ap.add_argument("--address", help="sensor MAC (default: first H5075 heard)")
    ap.add_argument("--interval", type=float, default=10.0, help="seconds between rows (default 10)")
    ap.add_argument("--scan-seconds", type=float, default=15.0, help="--discover duration")
    a = ap.parse_args()
    try:
        import bleak  # noqa: F401
    except ImportError:
        sys.exit("bleak is not installed: pip install --user bleak")
    if a.discover:
        sys.exit(asyncio.run(discover(a.scan_seconds)))
    sys.exit(asyncio.run(log(a.address, a.interval)))


if __name__ == "__main__":
    main()
