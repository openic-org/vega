"""Tests for chip0_first_err.py against a fake regbank + checker.

    python3 test_chip0_first_err.py
"""

import tempfile
from pathlib import Path

import chip0_first_err as c
import mosi_eye_scan as m


class FakeBoard:
    """Regbank words 80 and 232-249 and a checker that counts only while
    slot 32 holds a checked command and CHK_EN is set (spec §3.3).

    `answers(n)` gives the four halves' answer to the n-th checked READ(40)
    since power-on; time advances by `rate` checks per fake second."""

    def __init__(self, answers, rate=25_000):
        self.answers = answers
        self.rate = rate
        self.mem = {c.SLOT32: c.SLOT32_NORMAL, m.MOSI_SCAN_CTRL: m.SEL_BYPASS}
        self.streaming = True
        self.n = 0
        self.clear()

    def clear(self):
        self.count, self.err, self.first = 0, [0, 0, 0, 0], None

    def run(self, seconds):
        if self.mem[c.SLOT32] != c.SLOT32_CHECK or not (self.mem[m.MOSI_SCAN_CTRL] & m.CHK_EN):
            self.n += int(seconds * self.rate)
            return
        for _ in range(int(seconds * self.rate)):
            ans = self.answers(self.n)
            self.n += 1
            self.count = min(self.count + 1, 0xFFFF)
            for h, a in enumerate(ans):
                if a != c.EXPECTED:
                    self.err[h] = min(self.err[h] + 1, 0xFFFF)
                    if self.first is None:
                        self.first = (a, 0x8000 | h, c.EXPECTED)

    def sleep(self, s):
        self.run(s)

    def stop_streaming(self):
        self.streaming = False
        return True

    def _transact(self, payload, match):
        assert payload == b"\x03"
        self.streaming = True
        return bytes([0x03, 1])

    def write(self, addr, value):
        if addr == m.MOSI_SCAN_CTRL:
            assert not self.streaming, "regbank write while streaming"
            if value & m.CHK_CLEAR:
                self.clear()
            self.mem[addr] = value & ~m.CHK_CLEAR
        else:
            assert not self.streaming, "regbank write while streaming"
            self.mem[addr] = value
        return self.mem[addr]

    def read(self, addr):
        f = self.first or (0, 0, 0)
        return {m.CHK_COUNT: self.count,
                m.ERR_WORDS[0]: self.err[0], m.ERR_WORDS[1]: self.err[1],
                m.ERR_WORDS[2]: self.err[2], m.ERR_WORDS[3]: self.err[3],
                m.FIRST_ERR_ANS: f[0], m.FIRST_ERR_INFO: f[1], m.FIRST_ERR_EXP: f[2],
                }.get(addr, self.mem.get(addr, 0))


GOOD = (0x0049,) * 4


def dies_at(n0, ans, before=None):
    """chip0 answers GOOD until check n0, then `ans`; optional single
    wrong answer `before` = (n, value) on chip0 A."""
    def f(n):
        if before and n == before[0]:
            return (before[1],) + GOOD[1:]
        return (ans, ans, 0x0049, 0x0049) if n >= n0 else GOOD
    return f


def arm(board):
    s = c.arm(board, alive_wait=1.0, log=lambda *_: None, sleep=board.sleep)
    board.streaming = True          # the CLI's start()
    return s


def read(board):
    board.stop_streaming()
    s = c.snapshot(board)
    c.restore(board)
    return s, c.reading(s)[0]


def normal(board):
    return board.mem[c.SLOT32] == c.SLOT32_NORMAL and board.mem[m.MOSI_SCAN_CTRL] == m.SEL_BYPASS


# 1. Command words.
assert c.SLOT32_CHECK == 0xE800 and c.SLOT32_NORMAL == 0xFF00 and c.SLOT32 == 80
assert c.CTRL_ARM == 0x1C and c.CTRL_ARMED == 0x0C
print("pass  words: slot 32 = word 80, READ(40) 0xE800, READ(63) 0xFF00, arm 0x1C -> 0x0C")

# 2. Abrupt death long after arm: 0xFFFF on chip0 A; restore at the end.
b = FakeBoard(dies_at(100_000, 0xFFFF))
s = arm(b)
assert s.count == 25_000 and not any(s.errors)
assert b.count == 0, "second clear missing"
b.run(10)
s, key = read(b)
assert key == "abrupt", (key, s)
assert s.ans == 0xFFFF and s.half == 0 and s.count == 0xFFFF
assert normal(b)
print("pass  abrupt: first error 0xFFFF on chip0 A; slot 32 and CTRL restored")

# 3. Gradual: one bit flip before the flat line.
b = FakeBoard(dies_at(200_000, 0xFFFF, before=(150_000, 0x0048)))
arm(b)
b.run(10)
s, key = read(b)
assert key == "gradual" and s.ans == 0x0048, (key, s)
print("pass  gradual: a single 0x0048 before the death is the first error")

# 4. chip1 first.
b = FakeBoard(lambda n: (0x0049, 0x0049, 0xFFFF, 0x0049) if n >= 60_000 else GOOD)
arm(b)
b.run(5)
assert read(b)[1] == "chip1"
print("pass  chip1 first: reported as not the chip0 failure")

# 5. No error.
b = FakeBoard(lambda n: GOOD)
arm(b)
b.run(5)
assert read(b)[1] == "none"
print("pass  no error: 'none'")

# 6. Dead at arm: refused, restored, streaming left stopped.
b = FakeBoard(dies_at(0, 0xFFFF))
try:
    arm(b)
    raise AssertionError("arm accepted a dead chip0")
except c.ArmError:
    pass
assert normal(b) and not b.streaming
print("pass  dead at arm: refused, restored")

# 7. Checker not counting (old bitstream: slot write takes, count stays 0).
b = FakeBoard(lambda n: GOOD)
b.run = lambda seconds: None
try:
    arm(b)
    raise AssertionError("arm accepted CHK_COUNT = 0")
except c.ArmError as e:
    assert "not counting" in str(e)
assert normal(b)
print("pass  checker not counting: refused, restored")

# 8. FPGA reset (or Get settings) between arm and read: void.
b = FakeBoard(dies_at(100_000, 0xFFFF))
arm(b)
b.mem[c.SLOT32] = c.SLOT32_NORMAL     # 'Get settings' restore / FPGA reset
b.mem[m.MOSI_SCAN_CTRL] = m.SEL_BYPASS
b.run(10)
assert read(b)[1] == "void"
print("pass  slot 32 or CTRL reset since arm: void")

# 9. Log rows and last arm time.
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "log.csv"
    assert c.last_arm_time(p) is None
    c.log_row("arm", c.Snapshot(0xE800, 0x0C, 25000, 0, 0, 0, 0, 0, 0, 0), "x", p)
    c.log_row("read", None, "y", p)
    assert c.last_arm_time(p) is not None
    assert len(p.read_text().splitlines()) == 3
print("pass  log: header once, rows appended, last arm time found")

print("all passed")
