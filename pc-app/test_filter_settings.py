"""Offline exercise of FilterSettingsReader ("Get Settings") against a fake
reader that mimics the MCU — same shape as test_diagnostics.py, extended
with a fake SET_CHANNELS/channels_readback round trip so the restore step
can be modelled too.

Proves the queue sequencing, retry/timeout handling, and — critically —
that only regbank word 80 (slot 32) and REG_CH_A are ever written: slots
0-31 and REG_CH_B must come out of a run byte-for-byte what they went in
as. Cannot prove the real RHD2164 register values decode correctly; that
needs a bench.

    QT_QPA_PLATFORM=offscreen python3 test_filter_settings.py
"""
import sys, types
from pathlib import Path
import numpy as np
from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtSignal

sys.path.insert(0, str(Path(__file__).parent))
import diagnostics as D
import channel_mapping as M
from test_diagnostics import FakeReader as _BaseFakeReader

FILTER_ROM = {4: 0x1F, 8: 0x50, 9: 0x51, 10: 0x52, 11: 0x53, 12: 0x0A, 13: 0x0B}


class FakeReader(_BaseFakeReader):
    """Adds SET_CHANNELS: the real MCU translates a friendly 0-127 index to
    a raw ch_code and writes it into REG_CH_A/REG_CH_B; the exact
    translation is opaque to the pc-app (the whole reason Get Settings
    restores via send_set_channels rather than a raw poke) so the fake
    just stores the friendly value directly as the 'raw' register content
    — sufficient to prove the round trip, not the real translation."""
    channels_readback = pyqtSignal(int, int)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.set_channels_calls = []

    def answer(self, ch_code):
        slot = ((ch_code & 0x3F) - D.SLOT_OFFSET) % D.FRAME_SLOTS
        cmd = self.regs.get(D.slot_word(slot), 0)
        if (cmd >> 14) == 0b11:
            reg = (cmd >> 8) & 0x3F
            if reg in FILTER_ROM:
                return FILTER_ROM[reg]
        return super().answer(ch_code)

    def send_set_channels(self, ch_a, ch_b):
        self.set_channels_calls.append((ch_a, ch_b))
        self.regs[D.REG_CH_A] = ch_a
        self.regs[D.REG_CH_B] = ch_b
        self._later(lambda: self.channels_readback.emit(ch_a, ch_b))
        return True


def run_get_settings(orig_ch_a=5, orig_ch_b=9, **kw):
    """orig_ch_a/orig_ch_b are PHYSICAL channel numbers — FilterSettingsReader
    compensates them (channel_mapping.py) before ever touching the wire, same
    as MainWindow's Apply flow."""
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    reader = FakeReader(**kw)
    for addr, val in D.RESET_SAMPLING_TABLE:
        reader.regs[addr] = val
    reader.regs[D.REG_CH_A] = orig_ch_a
    reader.regs[D.REG_CH_B] = orig_ch_b
    runner = D.FilterSettingsReader(reader)
    out = {}
    runner.finished.connect(lambda r: out.update(result=r, kind="finished"))
    runner.failed.connect(lambda r: out.update(reason=r, kind="failed"))
    runner.finished.connect(lambda *_: app.quit())
    runner.failed.connect(lambda *_: app.quit())
    wd = QTimer(); wd.setSingleShot(True); wd.timeout.connect(app.quit)
    wd.start(30000)
    runner.run(orig_ch_a, orig_ch_b)
    app.exec()
    wd.stop()
    return out, reader


print("=" * 70)

out, reader = run_get_settings(orig_ch_a=5, orig_ch_b=9)
assert out.get("kind") == "finished", out
result = out["result"]
assert result.ok, result.reason
print(f"registers read: {result.registers}")
assert result.registers == {str(k): v for k, v in FILTER_ROM.items()}, \
    f"decoded values don't match the model: {result.registers}"

# Only slot 32 and REG_CH_A may ever be written — never slots 0-31, never
# REG_CH_B (spec: "channel-selection registers and sampling table should
# not be touched", i.e. transient use of slot 32 / REG_CH_A is fine, but
# nothing else).
bad_writes = [(a, v) for a, v in reader.writes
              if a == D.REG_CH_B or D.slot_word(0) <= a <= D.slot_word(31)]
assert not bad_writes, f"touched forbidden registers: {bad_writes}"
print(f"no writes to slots 0-31 or REG_CH_B ({len(reader.writes)} writes total)")

# Restore must go through SET_CHANNELS (the same command Apply uses),
# compensated (channel_mapping.py) the same way Apply's own SET_CHANNELS
# call is, and land back on exactly the original PHYSICAL pair (5, 9) once
# decoded — not the raw wire values.
wire_5, raw_5 = M.physical_to_wire(5)
wire_9, raw_9 = M.physical_to_wire(9)
assert not raw_5 and not raw_9, "5 and 9 should both be friendly-reachable"
assert reader.set_channels_calls == [(wire_5, wire_9)], reader.set_channels_calls
assert reader.regs[D.REG_CH_A] == wire_5 and reader.regs[D.REG_CH_B] == wire_9
assert M.wire_to_physical(reader.regs[D.REG_CH_A]) == 5
assert M.wire_to_physical(reader.regs[D.REG_CH_B]) == 9
assert reader.streaming, "must resume streaming when done"
print(f"restore: SET_CHANNELS({wire_5}, {wire_9}) issued "
      f"(decodes back to physical 5, 9), streaming resumed")

print("-" * 70)

# Restore for a channel channel_mapping.py marks unreachable via the
# friendly path (physical 29) must go through raw REG_WRITE16 instead of
# SET_CHANNELS — a single SET_CHANNELS call would silently overwrite
# whichever of the pair *was* friendly-reachable back to the wrong value.
out, reader = run_get_settings(orig_ch_a=29, orig_ch_b=9)
assert out.get("kind") == "finished" and out["result"].ok, out
assert reader.set_channels_calls == [], \
    f"restore must not use SET_CHANNELS when either channel is raw-only: {reader.set_channels_calls}"
raw_29 = M.physical_to_raw(29)
raw_9_direct = M.physical_to_raw(9)
assert reader.regs[D.REG_CH_A] == raw_29, hex(reader.regs[D.REG_CH_A])
assert reader.regs[D.REG_CH_B] == raw_9_direct, hex(reader.regs[D.REG_CH_B])
assert reader.streaming
print(f"restore (raw path): REG_CH_A=0x{raw_29:02X}, REG_CH_B=0x{raw_9_direct:02X} "
      f"written directly, streaming resumed, SET_CHANNELS never called")

print("-" * 70)
# Negative: a dropped write must be retried, not fatal.
out, reader = run_get_settings(drop_first=2)
assert out.get("kind") == "finished" and out["result"].ok
print("2 dropped cmds  -> recovered via retry")

# Negative: FPGA reports a mismatched value on a write -> abort, named word.
out, _ = run_get_settings(regbank_values={D.slot_word(32): 0xDEAD})
print("write-mismatch  ->", out.get("kind"), "|", out.get("reason"))
assert out["kind"] == "failed" and "word 80" in out["reason"]

print("=" * 70)
print("ALL FILTER-SETTINGS CHECKS PASSED")
