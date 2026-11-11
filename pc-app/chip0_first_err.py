"""
chip0_first_err.py — catch the first wrong MISO answer before chip0 dies
(A.1.2). Procedure and reading: log/2026-11-11.md, "chip0 margin tests,
part 2: first-error capture".

The question: when chip0 dies, does MISO0 give wrong bits first (gradual:
a marginal link, worth a MISO capture sweep) or go straight to 0xFFFF
(abrupt: a contact or the chip; a sweep would not help)?

How: the MOSI eye-scan checker (spi1-mosi-eye-scan.md §3.3) runs on every
SPI1 transfer, streaming or not, and keeps the first wrong answer since its
last clear. The normal sampling table gives it nothing to check, so `arm`
puts READ(40) (expected 0x0049 on all four halves) into sampling slot 32,
the alternate-command placeholder (regbank word 80, normally READ(63)):
one checked transfer per frame, no amplifier sample lost. mosi_sel stays 4
(bypass), so the stream is today's design. Nothing persists: any FPGA reset
(power-on, reprogram, the rstb button) restores READ(63) and CHK_EN = 0.

    arm      STOP; slot 32 = READ(40); clear + CHK_EN; alive check (chip0
             and chip1 error-free for --alive-wait s); clear again; START.
    read     STOP; read the checker; print the reading; restore slot 32 =
             READ(63) and MOSI_SCAN_CTRL = 4. Leaves streaming STOPPED.
    restore  STOP; restore only (if a run is abandoned).

pc-app must be closed while this runs (it holds the serial port). Do not
press pc-app's "Get settings" between arm and read: it puts READ(63) back
in slot 32 and the checker goes blind (`read` detects that).

Every run appends a row to bench/chip0_first_err.csv.

Usage:
    python3 chip0_first_err.py arm  --port /dev/ttyACM1 [--alive-wait 1.0]
    python3 chip0_first_err.py read --port /dev/ttyACM1
    python3 chip0_first_err.py restore --port /dev/ttyACM1

Exit status: 0 done; 1 arm refused (chip already erring, or the checker not
counting) or read void; 2 could not talk to the board.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

from mosi_eye_scan import (CHK_CLEAR, CHK_COUNT, CHK_EN, ERR_WORDS, FIRST_ERR_ANS,
                           FIRST_ERR_EXP, FIRST_ERR_INFO, MOSI_SCAN_CTRL, SAMPLING_BASE,
                           SEL_BYPASS, SerialRegPort, rhd_read)

SLOT32 = SAMPLING_BASE + 32          # regbank word 80
SLOT32_NORMAL = rhd_read(63)         # 0xFF00, regbank.v initial value
SLOT32_CHECK = rhd_read(40)          # 0xE800, answer 0x0049 ("I")
EXPECTED = 0x0049
CTRL_ARM = SEL_BYPASS | CHK_EN | CHK_CLEAR    # 0x1C; reads back 0x0C
CTRL_ARMED = SEL_BYPASS | CHK_EN              # 0x0C
CTRL_NORMAL = SEL_BYPASS                      # 0x04, reset value
HALF_NAMES = ("chip0 A", "chip0 B", "chip1 A", "chip1 B")

LOG = Path(__file__).parent / "bench" / "chip0_first_err.csv"


class ArmError(Exception):
    pass


@dataclass
class Snapshot:
    """The checker's state as read from the regbank (words 80, 232, 242-249)."""
    slot32: int
    ctrl: int
    count: int
    c0a: int
    c0b: int
    c1a: int
    c1b: int
    ans: int
    info: int
    exp: int

    @property
    def errors(self):
        return (self.c0a, self.c0b, self.c1a, self.c1b)

    @property
    def valid(self) -> bool:
        return bool(self.info & 0x8000)

    @property
    def half(self) -> int:
        return self.info & 0x3


def snapshot(port) -> Snapshot:
    return Snapshot(
        slot32=port.read(SLOT32),
        ctrl=port.read(MOSI_SCAN_CTRL),
        count=port.read(CHK_COUNT),
        c0a=port.read(ERR_WORDS[0]), c0b=port.read(ERR_WORDS[1]),
        c1a=port.read(ERR_WORDS[2]), c1b=port.read(ERR_WORDS[3]),
        ans=port.read(FIRST_ERR_ANS), info=port.read(FIRST_ERR_INFO),
        exp=port.read(FIRST_ERR_EXP),
    )


def reading(s: Snapshot) -> tuple[str, str]:
    """(verdict key, one-line reading) for a snapshot taken at `read`.
    Keys: void, none, abrupt, gradual, chip1."""
    if s.slot32 != SLOT32_CHECK or not (s.ctrl & CHK_EN):
        return ("void", f"not armed at read (slot 32 = {s.slot32:#06x}, MOSI_SCAN_CTRL = "
                        f"{s.ctrl:#06x}): an FPGA reset (power, reprogram, rstb) or "
                        "'Get settings' since arm. Result void.")
    if s.count == 0:
        return ("void", "CHK_COUNT = 0: the checker counted nothing since the clear. Result void.")
    if not s.valid:
        return ("none", "no wrong answer on any half since the clear. If the health monitor saw "
                        "chip0 die, the death is not on MISO (stream path, ch_sel or pc-app).")
    where = HALF_NAMES[s.half]
    if s.half >= 2:
        return ("chip1", f"first error on {where} ({s.ans:#06x} for {s.exp:#06x}): chip1 failed "
                         "first, not the chip0 failure. Stop and look.")
    if s.ans == 0xFFFF:
        return ("abrupt", f"first error on {where} is 0xFFFF (for {s.exp:#06x}): abrupt, no wrong "
                          "bit seen before the line went flat. Contact or chip; a MISO sweep "
                          "would not help.")
    flips = bin(s.ans ^ s.exp).count("1")
    return ("gradual", f"first error on {where} is {s.ans:#06x} for {s.exp:#06x} ({flips} bit(s) "
                       "differ): gradual, MISO0 gave wrong bits before going flat. Supports a "
                       "marginal MISO0 link; the MISO capture sweep is worth building.")


def log_row(action: str, s: Snapshot | None, note: str, path: Path = LOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = ["time", "action"] + [f.name for f in fields(Snapshot)] + ["note"]
    new = not path.exists()
    row = {"time": datetime.now().astimezone().isoformat(timespec="seconds"), "action": action}
    row.update(asdict(s) if s else {})
    row["note"] = note
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=names)
        if new:
            w.writeheader()
        w.writerow(row)


def last_arm_time(path: Path = LOG) -> datetime | None:
    if not path.exists():
        return None
    t = None
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            if r["action"] == "arm":
                t = datetime.fromisoformat(r["time"])
    return t


def expect(got: int, want: int, what: str) -> None:
    if got != want:
        raise ArmError(f"{what} reads back {got:#06x}, expected {want:#06x}")


def restore(port) -> None:
    """Slot 32 and MOSI_SCAN_CTRL back to their reset values, verified."""
    expect(port.write(SLOT32, SLOT32_NORMAL), SLOT32_NORMAL, "slot 32 restore")
    expect(port.write(MOSI_SCAN_CTRL, CTRL_NORMAL), CTRL_NORMAL, "MOSI_SCAN_CTRL restore")


def arm(port, alive_wait: float = 1.0, log=print, sleep=time.sleep) -> Snapshot:
    """Raises ArmError (after restoring) if the checker does not count or a
    half already errs. Returns the alive-check snapshot."""
    if not port.stop_streaming():
        log("warning: STOP_STREAMING ack says stream_enable did not read back 0")
    before = port.read(SLOT32)
    if before not in (SLOT32_NORMAL, SLOT32_CHECK):
        log(f"warning: slot 32 held {before:#06x}, not READ(63); overwriting")
    expect(port.write(SLOT32, SLOT32_CHECK), SLOT32_CHECK, "slot 32")
    expect(port.write(MOSI_SCAN_CTRL, CTRL_ARM), CTRL_ARMED, "MOSI_SCAN_CTRL")
    sleep(alive_wait)
    s = snapshot(port)
    try:
        if s.count == 0:
            raise ArmError("CHK_COUNT = 0 after the alive wait: the checker is not counting "
                           "(a bitstream without it?)")
        if any(s.errors) or s.valid:
            first = (f"; first {HALF_NAMES[s.half]} {s.ans:#06x} for {s.exp:#06x}"
                     if s.valid else "")
            raise ArmError(f"errors at arm time {s.errors}{first}: a chip is not answering "
                           "now; the run is void for this question")
    except ArmError:
        restore(port)
        raise
    expect(port.write(MOSI_SCAN_CTRL, CTRL_ARM), CTRL_ARMED, "MOSI_SCAN_CTRL (second clear)")
    return s


def start(port) -> bool:
    r = port._transact(b"\x03", lambda r: len(r) >= 2 and r[0] == 0x03)
    return bool(r[1])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("arm", "read", "restore"))
    ap.add_argument("--port", required=True, help="bridge serial port, e.g. /dev/ttyACM1")
    ap.add_argument("--alive-wait", type=float, default=1.0,
                    help="seconds of error-free checking required at arm (default 1.0)")
    a = ap.parse_args(argv)

    try:
        port = SerialRegPort(a.port)
    except Exception as e:
        print(f"cannot open {a.port}: {e} (is pc-app still open?)", file=sys.stderr)
        return 2
    try:
        if a.action == "arm":
            try:
                s = arm(port, a.alive_wait)
            except ArmError as e:
                log_row("arm-refused", None, str(e))
                print(f"arm refused: {e}\nslot 32 and MOSI_SCAN_CTRL restored; streaming stopped.",
                      file=sys.stderr)
                return 1
            ok = start(port)
            note = (f"alive check {a.alive_wait:g} s: {s.count} checked, 0 errors; cleared; "
                    + ("streaming started" if ok else "START ack 0"))
            log_row("arm", s, note)
            print(f"armed at {datetime.now():%H:%M:%S}. {note}.\n"
                  "Now open pc-app, recording on, apply the channels. Do not press 'Get settings'.")
            return 0

        port.stop_streaming()
        if a.action == "restore":
            restore(port)
            log_row("restore", None, "restore only")
            print("slot 32 = READ(63), MOSI_SCAN_CTRL = 4. Streaming left STOPPED.")
            return 0

        s = snapshot(port)
        key, text = reading(s)
        armed_at = last_arm_time()
        since = f"{(datetime.now().astimezone() - armed_at).total_seconds() / 60:.1f} min after the last arm" \
            if armed_at else "no arm row in the log"
        restore(port)
        log_row("read", s, f"{key}: {text}")
        print(f"read {since}:\n"
              f"  CHK_COUNT {s.count}{' (saturated)' if s.count == 0xFFFF else ''}; errors "
              f"chip0 A/B {s.c0a}/{s.c0b}, chip1 A/B {s.c1a}/{s.c1b}\n"
              f"  first error: " + (f"{HALF_NAMES[s.half]}, {s.ans:#06x} for {s.exp:#06x}"
                                    if s.valid else "none") + "\n"
              f"  -> {text}\n"
              "Restored slot 32 = READ(63), MOSI_SCAN_CTRL = 4. Streaming left STOPPED: "
              "power-cycle Kuntur before any recording that matters.")
        return 1 if key == "void" else 0
    except (TimeoutError, ArmError) as e:
        print(f"{a.action} failed: {e}", file=sys.stderr)
        return 2
    finally:
        port.close()


if __name__ == "__main__":
    sys.exit(main())
