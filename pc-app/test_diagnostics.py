"""Offline exercise of RungRunner against a fake reader that mimics the MCU.

No hardware, no bridge: the FakeReader implements the contract from
docs/interfaces/fpga-diagnostic-access.md sections 1.2 and 2 — ch_a[5:0]
selects the sampling slot whose answer is observed, and a REG_WRITE16 response
carries what the regbank actually holds. A rung that passes here is checking
the script and the runner, not the FPGA.

    QT_QPA_PLATFORM=offscreen python3 test_diagnostics.py
"""
import sys, types
from pathlib import Path
import numpy as np
from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtSignal

sys.path.insert(0, str(Path(__file__).parent))
import diagnostics as D
from serial_reader import CMD_REG_WRITE16


class FakeReader(QObject):
    batch_received = pyqtSignal(object)
    stop_streaming_ack = pyqtSignal(bool)
    start_streaming_ack = pyqtSignal(bool)
    reg_access_response = pyqtSignal(int, int, int)

    def __init__(self, regbank_values=None, drop_first=0):
        super().__init__()
        self.regs = {}
        self.forced = regbank_values or {}   # addr -> value the "FPGA" really holds
        self.streaming = False
        self.writes = []
        self.drop_first = drop_first         # simulate N lost commands
        self._timer = QTimer(self); self._timer.setSingleShot(True)

    def _later(self, fn):
        QTimer.singleShot(1, fn)

    def send_reg_write16(self, addr, value):
        self.writes.append((addr, value))
        if self.drop_first > 0:
            self.drop_first -= 1
            return True                      # silently dropped, no response
        self.regs[addr] = self.forced.get(addr, value)
        self._later(lambda: self.reg_access_response.emit(
            CMD_REG_WRITE16, addr, self.regs[addr]))
        return True

    def send_stop_streaming(self):
        self.streaming = False
        self._later(lambda: self.stop_streaming_ack.emit(True))
        return True

    def send_start_streaming(self):
        self.streaming = True
        self._later(lambda: self.start_streaming_ack.emit(True))
        self._later(self._pump)
        return True

    def _pump(self):
        """Emit packets carrying whatever the current ch_a/ch_b 'select'."""
        if not self.streaming:
            return
        a = self.regs.get(D.REG_CH_A, 0)
        b = self.regs.get(D.REG_CH_B, 0)
        v0 = self.answer(a)
        v1 = self.answer(b)
        n = 40
        pkt = types.SimpleNamespace(
            ch0=np.full(n, v0, dtype=np.int32),
            ch1=np.full(n, v1, dtype=np.int32))
        self.batch_received.emit(pkt)
        self._later(self._pump)

    def answer(self, ch_code):
        """Model the RTL: ch_a[5:0] is a counter value; the slot whose answer is
        on the bus at that count is (value - SLOT_OFFSET) mod FRAME_SLOTS."""
        slot = ((ch_code & 0x3F) - D.SLOT_OFFSET) % D.FRAME_SLOTS
        cmd = self.regs.get(D.slot_word(slot), 0)
        if (cmd >> 14) == 0b11:              # RHD READ(R) -> {8'h00, D}
            reg = (cmd >> 8) & 0x3F
            rom = {59: 0x35, 40: 0x49, 41: 0x4E, 42: 0x54, 43: 0x41, 44: 0x4E,
                   63: 0x04, 62: 0x40, 61: 0x01}
            src = (ch_code >> 6) & 0x3
            if reg == 59:                    # A/B marker is per-module
                return 0x3A if src in (1, 3) else 0x35
            return rom.get(reg, 0x0000)
        return 0x1000 + slot                 # CONVERT result stand-in


def run_rung(key, **kw):
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    reader = FakeReader(**kw)
    # Preload the sampling table with its reset defaults, as a real FPGA has.
    for addr, val in D.RESET_SAMPLING_TABLE:
        reader.regs[addr] = val
    runner = D.RungRunner(reader)
    out = {}
    runner.finished.connect(lambda k, r, ok: out.update(key=k, results=r, ok=ok, kind="finished"))
    runner.failed.connect(lambda k, r: out.update(key=k, reason=r, kind="failed"))
    runner.finished.connect(lambda *_: app.quit())
    runner.failed.connect(lambda *_: app.quit())
    # Per-run watchdog that is STOPPED afterwards. QTimer.singleShot() would
    # leave a pending timer on the persistent QCoreApplication, and a stale one
    # from an earlier rung then quits a later rung's event loop early — which
    # looks exactly like the later rung hanging.
    wd = QTimer(); wd.setSingleShot(True); wd.timeout.connect(app.quit)
    wd.start(30000)
    runner.run(key)
    app.exec()
    wd.stop()
    return out, reader


# Slot→ch_a mapping must be injective over all 33 sampling slots and fit the
# 6-bit field, whatever SLOT_OFFSET/FRAME_SLOTS are set to. This is the check
# that survives a change to those constants; the rung values below cannot test
# the constant itself, since the FakeReader inverts the same one.
_codes = {s: D.ch_code(0, s) for s in range(D.RB_SAMPLING_MAX_SLOT + 1)}
assert len(set(_codes.values())) == len(_codes), f"slot→ch_a collision: {_codes}"
assert all(0 <= v <= 0x3F for v in _codes.values()), _codes
assert D.SLOT_OFFSET < D.FRAME_SLOTS, "offset must be inside one frame"
print(f"slot→ch_a mapping OK (SLOT_OFFSET={D.SLOT_OFFSET}, "
      f"FRAME_SLOTS={D.FRAME_SLOTS}): slot 0→{_codes[0]}, slot 32→{_codes[32]}")

# Wire format of the new console commands, pinned against the spec's byte
# layout rather than against the code that produces it — fpga-diagnostic-access
# §2 (payload) over channel-selection-control-plane §3 (0xCC 0x33 framing).
# The MCU reads addr at [1] and assembles the value little-endian from [2],[3].
class _FakePort:
    is_open = True
    def __init__(self): self.buf = b""
    def write(self, b): self.buf += bytes(b); return len(b)
    def flush(self): pass

from serial_reader import SerialReader, CMD_REG_READ16
_sr = SerialReader()
_sr._port = _FakePort()
_sr.send_reg_write16(229, 0x0001)          # data_source_sel <- real
_sr.send_reg_read16(80)                    # placeholder slot
_expect = (b"\xCC\x33\x04" + bytes([CMD_REG_WRITE16, 229, 0x01, 0x00])
           + b"\xCC\x33\x02" + bytes([CMD_REG_READ16, 80]))
assert _sr._port.buf == _expect, f"wire format drift:\n got {_sr._port.buf.hex(' ')}\nwant {_expect.hex(' ')}"
# A 16-bit value must split little-endian, not big-endian — the failure this
# catches is silent (0x95A5 arriving as 0xA595 still writes *something*).
_sr._port = _FakePort()
_sr.send_reg_write16(48, 0x95A5)
assert _sr._port.buf[-2:] == b"\xA5\x95", _sr._port.buf.hex(" ")
print(f"wire format OK: REG_WRITE16 -> {_expect[:7].hex(' ')}")

print("=" * 70)
# Rung L: offset-independent by construction. Prove it — it must pass at the
# configured SLOT_OFFSET and at every wrong one, since every slot holds the
# same command.
for probe in (0, 1, 2, 3, 5):
    saved = D.SLOT_OFFSET
    D.SLOT_OFFSET = probe
    out, _ = run_rung("L")
    D.SLOT_OFFSET = saved
    assert out.get("kind") == "finished" and out["ok"], \
        f"rung L must be offset-independent, failed at SLOT_OFFSET={probe}: {out}"
print(f"rung L: offset-independent confirmed (passes at SLOT_OFFSET 0,1,2,3,5)")

# Rung O: the sweep must localise the offset — exactly one probe reads the
# 0x0035 marker, at the ch_a implied by the model's true offset.
out, _ = run_rung("O")
assert out.get("kind") == "finished", out
hits = [r for r in out["results"] if 0x0035 in (r.got_ch0, r.got_ch1)]
assert all(r.info for r in out["results"]), "sweep probes must be informational"
assert len(hits) == 1, f"sweep should localise to one probe, got {len(hits)}"
_want_cha = (32 + D.SLOT_OFFSET) % D.FRAME_SLOTS
assert f"ch_a={_want_cha} " in hits[0].label, \
    f"marker landed at the wrong probe: {hits[0].label}"
print(f"rung O: sweep localises the offset to ch_a={_want_cha} "
      f"(= SLOT_OFFSET {D.SLOT_OFFSET})")

for key in "abcd":
    out, reader = run_rung(key)
    kind = out.get("kind")
    if kind == "finished":
        n_ok = sum(1 for r in out["results"] if r.ok)
        print(f"rung {key}: {kind}  {n_ok}/{len(out['results'])} passed  "
              f"all_passed={out['ok']}  ({len(reader.writes)} writes issued)")
        assert out["ok"], f"rung {key} should pass against a correct model"
    else:
        print(f"rung {key}: {kind}  {out.get('reason')}")
        raise SystemExit(f"rung {key} unexpectedly aborted")

print("-" * 70)
# Negative: FPGA reports a different value than was written -> abort, named word.
out, _ = run_rung("a", regbank_values={D.slot_word(32): 0xDEAD})
print("write-mismatch  ->", out.get("kind"), "|", out.get("reason"))
assert out["kind"] == "failed" and "word 80" in out["reason"]

# Negative: a dropped command must be retried, not fatal.
out, reader = run_rung("a", drop_first=2)
print("2 dropped cmds  ->", out.get("kind"), "| all_passed =", out.get("ok"))
assert out["kind"] == "finished" and out["ok"]

# Negative: wrong DDR demux (both halves return the A marker) -> rung a fails.
class SwappedReader(FakeReader):
    def answer(self, ch_code):
        v = super().answer(ch_code)
        return 0x35 if v == 0x3A else v

app = QCoreApplication.instance() or QCoreApplication(sys.argv)
reader = SwappedReader()
for addr, val in D.RESET_SAMPLING_TABLE:
    reader.regs[addr] = val
runner = D.RungRunner(reader)
res = {}
runner.finished.connect(lambda k, r, ok: res.update(results=r, ok=ok))
runner.finished.connect(lambda *_: app.quit())
runner.failed.connect(lambda *_: app.quit())
_wd = QTimer(); _wd.setSingleShot(True); _wd.timeout.connect(app.quit)
_wd.start(30000)
runner.run("a")
app.exec()
_wd.stop()
print("B-demux broken  -> all_passed =", res.get("ok"),
      "| got", [f"0x{r.got_ch1:04X}" for r in res.get("results", [])])
assert res.get("ok") is False

print("=" * 70)
print("ALL RUNNER CHECKS PASSED")
