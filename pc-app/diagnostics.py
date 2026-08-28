"""
A.1.1 verification ladder — rung definitions and runner.

Spec: docs/interfaces/fpga-diagnostic-access.md sections 2, 4 and 5.

Each rung is *data*: a list of setup writes, a list of observations with their
expected values, and a restore list. The runner below is generic, so adding
rung (f) — or any rung invented in six months — is a table entry here, not a
firmware change and not an RTL edit. That is the whole point of driving these
over a register console rather than a build flag.

Requires the A.1.1e RTL (real data on `dout`, regbank word 229, the two-counter
slot offset). Against an older bitstream every rung fails with the ramp values
it streams instead, which is a correct and legible result: the ladder reports
what it saw.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from serial_reader import CMD_REG_READ16, CMD_REG_WRITE16

# ── FPGA regbank map ────────────────────────────────────────────────────────
# Authority is intan.vh (RB_CONFIG_BASE 0 / RB_SAMPLING_BASE 48 /
# RB_CTRL_BASE 192). Duplicated here and in fpga_spi.c; single-sourcing across
# the Verilog/C/Python boundary is a B.2 problem.
RB_SAMPLING_BASE = 48
RB_SAMPLING_MAX_SLOT = 32          # slot 32 = alternate-command placeholder
REG_CH_A = 196
REG_CH_B = 197
REG_STREAM_ENABLE = 228
REG_DATA_SOURCE = 229              # [1:0]: 0 = real RHD data, 1 = ramp

DATA_SOURCE_REAL = 0
DATA_SOURCE_RAMP = 1


def rhd_read(reg: int) -> int:
    """RHD2164 READ(R) — {2'b11, R[5:0], 8'd0}. Response is {8'h00, D}."""
    return 0xC000 | ((reg & 0x3F) << 8)


def rhd_convert(channel: int) -> int:
    """RHD2164 CONVERT(C) — {2'b00, C[5:0], 8'd0}."""
    return (channel & 0x3F) << 8


# ── Slot→ch_a mapping, as built ─────────────────────────────────────────────
# The RHD returns a command's result two commands later, and ch_sel sees it one
# slot later still (data_rx_* are held registers loaded at the SPI master's
# csbend1, while ch_sel latches at the start of the following slot). Total 3.
#
# The RTL leaves that correction to the host: rhd2164_controller's cnt0 runs
# 0..RB_SAMPLING_MAX (33 slots) and ch_cnt == cnt0 during sampling, so
#   ch_a[5:0] = (slot + SLOT_OFFSET) mod FRAME_SLOTS
# i.e. ch_a = 3 observes sampling slot 0, and ch_a = 2 observes slot 32 (the
# alternate-command placeholder). The map is a bijection over all 33 slots —
# nothing is unreachable, which is why no RTL change is needed to run the
# ladder.
#
# SLOT_OFFSET = 3 is CONFIRMED ON HARDWARE, 2026-08-11. Friendly channel 66
# (source 2, index 2) reads a constant 4 — that is slot (2-3) mod 33 = 32, the
# alternate-command placeholder holding READ(63), whose answer is the RHD2164
# chip ID. Under an offset of 2 that channel would have shown slot 0's live
# signal instead. Neighbouring channel 65 shows signal, as predicted.
#
# So components.v:627's "Remember there is a delay of 2 SPI cycles" is wrong:
# the RHD's own pipeline is 2 commands, but data_rx_* are held registers loaded
# at the SPI master's csbend1 while ch_sel latches at the start of the FOLLOWING
# slot, adding one more. Never observable before A.1.1e, because dout was always
# the ramp.
#
# THESE TWO CONSTANTS REMAIN THE FLAG — if the RTL ever changes the counter or
# the latch timing, change SLOT_OFFSET here and every rung follows.
#
# If the RTL is later changed so ch_a names the slot directly (spec 1.2's
# two-counter form, or 1.2a's tunable rsp_delay), set SLOT_OFFSET = 0.
SLOT_OFFSET = 3
FRAME_SLOTS = RB_SAMPLING_MAX_SLOT + 1      # 33: cnt0 spans 0..RB_SAMPLING_MAX


def ch_code(source: int, slot: int) -> int:
    """ch_a/ch_b raw code: [7:6] source, [5:0] the counter value to match.

    source: 0 = chip0 module A, 1 = chip0 module B,
            2 = chip1 module A, 3 = chip1 module B.

    `slot` is the sampling-slot index whose *answer* you want to observe; the
    SLOT_OFFSET correction is applied here so callers never do it by hand — the
    whole point of centralising it. Note slot 32 is expressible and is NOT
    expressible through SET_CHANNELS's friendly 0-127 mapping, which is one of
    the three reasons this console exists (spec §2.1).
    """
    value = (slot + SLOT_OFFSET) % FRAME_SLOTS
    return ((source & 0x3) << 6) | (value & 0x3F)


def ch_raw(source: int, value: int) -> int:
    """ch_a/ch_b with NO offset correction — `value` is the raw counter value
    to match against ch_cnt. Used only by the offset-measuring rung, which
    exists precisely to find out what the correction should be."""
    return ((source & 0x3) << 6) | (value & 0x3F)


def slot_word(slot: int) -> int:
    return RB_SAMPLING_BASE + slot


SOURCE_NAMES = {0: "chip0-A", 1: "chip0-B", 2: "chip1-A", 3: "chip1-B"}

# Which RHD2164 the ladder probes when it only needs one.
#
# Bench evidence 2026-08-11 (rung L): source 2/3 (spi1_miso1, "chip1") returns
# the reg-59 markers 0x0035/0x003A perfectly, while source 0/1 (spi1_miso0,
# "chip0") reads 0xFFFF on both halves — a line sitting high for the whole
# frame. Both chips share csb/sck/mosi, so the command path is proven good by
# chip1; only miso0 differs. The RTL's own ch_a/ch_b reset defaults also select
# source 2, which suggests one populated device rather than a fault.
#
# THIS IS THE FLAG: set to 0 if chip0 becomes the device under test.
PRIMARY_SRC = 2
SECONDARY_SRC = 0


# ── Rung definitions ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Observation:
    """One (ch_a, ch_b) configuration and what the stream must carry."""
    ch_a: int
    ch_b: int
    expect_ch0: int
    expect_ch1: int
    label: str
    # Informational: record and report the values, but do not pass/fail on
    # them. For measurements where the expected value is the unknown.
    info: bool = False


@dataclass(frozen=True)
class Rung:
    key: str
    title: str
    setup: list[tuple[int, int]]          # (regbank addr, value)
    observations: list[Observation]
    restore: list[tuple[int, int]] = field(default_factory=list)
    note: str = ""
    diagnosis: dict[str, str] = field(default_factory=dict)


# The FPGA's reset defaults, read out of components.v. Restore must put back
# exactly what was there, otherwise "restore" silently reconfigures the
# instrument.
#
# DO NOT "FIX" THE CONVERT(63) RUN. Thirty consecutive CONVERT(63) reads like a
# bug — thirty conversions of channel 63 — and it is not. Per the RHD2164
# datasheet (and intan.vh:24), C=63 means "cycle through successive amplifier
# channels": slot 0's CONVERT(0) and slot 1's CONVERT(1) anchor the chip's
# internal channel counter, and the thirty CONVERT(63) walk it 2→31. So slot k
# already converts channel k, and the anchor is re-asserted every frame at slot
# 0, making it self-correcting after any disturbance. Confirmed by Manuel
# 2026-08-11. Writing explicit CONVERT(k) per slot would be equivalent, but it
# is a gratuitous change to a deliberate table.
RESET_SAMPLING_TABLE: list[tuple[int, int]] = (
    [(slot_word(0), rhd_convert(0)), (slot_word(1), rhd_convert(1))]
    + [(slot_word(k), rhd_convert(63)) for k in range(2, 32)]
    + [(slot_word(32), rhd_read(63))]
)

# ch_a = {2'd2, 6'd3} = chip1-A, counter value 3 -> sampling slot 0 (channel 0).
# ch_b = {2'd2, 6'd2} = chip1-A, counter value 2 -> slot 32, the alternate-
# command placeholder, which holds READ(63) -> a constant chip ID of 4.
# Both select chip1, which is the module that actually answers (see
# PRIMARY_SRC) — so the defaults are a sensible bring-up pair, not an accident.
RESET_CH_A = 0x83
RESET_CH_B = 0x82

# Restore common to every rung. An FPGA reset does the same thing
# unconditionally and is the recovery if a restore itself fails (spec §5.5).
_DEFAULT_RESTORE: list[tuple[int, int]] = RESET_SAMPLING_TABLE + [
    (REG_CH_A, RESET_CH_A),
    (REG_CH_B, RESET_CH_B),
    (REG_DATA_SOURCE, DATA_SOURCE_REAL),
]

# Every rung asserts real data first. Word 229's reset default is already 0, so
# this is a re-assertion rather than a change — and it proves the word is
# reachable before anything depends on it.
_ASSERT_REAL = [(REG_DATA_SOURCE, DATA_SOURCE_REAL)]


# ── Rung (L) — link integrity, offset-independent ───────────────────────────
# Every slot carries READ(59), so whatever ch_a matches, the answer is the A/B
# marker. That makes this the ONLY rung whose result cannot be confounded by a
# wrong SLOT_OFFSET — which is why it runs first. If it fails, the problem is
# below the offset question entirely: MISO timing, the DDR split, or wiring.
RUNG_LINK = Rung(
    key="L",
    title="A.1.1a-0 — Link integrity (offset-independent, RUN FIRST)",
    note=(
        "Every one of the 33 sampling slots is loaded with READ(59), Intan's "
        "MISO A/B marker: 53 (0x35) on MISO A, 58 (0x3A) on MISO B. Because "
        "every slot carries the same command, the slot→ch_a offset cannot "
        "affect the result — any ch_a lands on a READ(59). This isolates the "
        "physical link from every other variable in the ladder.\n"
        "If this fails, nothing further in the ladder is interpretable: fix "
        "the link first."
    ),
    setup=_ASSERT_REAL + [(slot_word(k), rhd_read(59)) for k in range(33)],
    observations=[
        Observation(ch_raw(0, 0), ch_raw(1, 0), 0x0035, 0x003A, "chip0 MISO A/B"),
        Observation(ch_raw(2, 0), ch_raw(3, 0), 0x0035, 0x003A, "chip1 MISO A/B"),
    ],
    restore=_DEFAULT_RESTORE,
    diagnosis={
        "58/53": "A/B demux inverted",
        "53/53": "MISO B never demuxed — both DDR edges sampled as A",
        "chip0 passes, chip1 does not": "spi1_miso1 wiring, or the second chip",
        "0x0000 / 0xFFFF / unstable": "MISO sample point wrong, or chip not responding",
        "0x8000 / 0x8000": "empty-FIFO sentinel — no data flowing; check STREAM/stream_enable",
    },
)

# ── Rung (O) — measure SLOT_OFFSET ──────────────────────────────────────────
# Every slot carries READ(63) (-> 0x0004) EXCEPT slot 32, which carries
# READ(59) (-> 0x0035). Sweeping raw ch_a values finds the single one that
# returns 0x0035; that value identifies the offset directly:
#     SLOT_OFFSET = (ch_a_that_matched - 32) mod 33
# Informational by design — the expected value here is the unknown.
RUNG_OFFSET = Rung(
    key="O",
    title="A.1.1b-0 — Measure the slot→ch_a offset (RUN SECOND)",
    note=(
        "Slot 32 carries READ(59) -> 0x0035; every other slot carries "
        "READ(63) -> 0x0004. Exactly one raw ch_a value will report 0x0035 "
        "(or 0x003A on a B module). Read it off the table below:\n"
        "    SLOT_OFFSET = (matching ch_a - 32) mod 33\n"
        "Then set SLOT_OFFSET in pc-app/diagnostics.py and re-run. Current "
        f"setting is {SLOT_OFFSET}, i.e. ch_a = {(32 + SLOT_OFFSET) % FRAME_SLOTS} "
        "is expected to be the one that matches.\n"
        "This is the measurement that settles a value derived by reading RTL "
        "but never confirmed on hardware — see spec 1.2."
    ),
    setup=_ASSERT_REAL
    + [(slot_word(k), rhd_read(63)) for k in range(33)]
    + [(slot_word(32), rhd_read(59))],
    observations=[
        Observation(ch_raw(PRIMARY_SRC, a), ch_raw(PRIMARY_SRC, b), 0x0035, 0x0035,
                    f"ch_a={a} (offset {(a - 32) % 33}) / ch_a={b} (offset {(b - 32) % 33})",
                    info=True)
        for a, b in ((32, 0), (1, 2), (3, 4), (5, 6))
    ],
    restore=_DEFAULT_RESTORE,
    diagnosis={
        "exactly one 0x0035": "that ch_a gives SLOT_OFFSET = (ch_a - 32) mod 33",
        "all 0x0004": "offset is outside the swept range 0-7 — widen the sweep",
        "all 0x0000 or garbage": "link problem, not an offset problem — run rung L first",
    },
)


RUNG_A = Rung(
    key="a",
    title="A.1.1a — Link integrity & DDR demux",
    note=(
        "Register 59 is Intan's purpose-built MISO A/B marker: 53 (0x35) on "
        "MISO A, 58 (0x3A) on MISO B. Asymmetric by design, so an A/B swap "
        "fails outright rather than looking plausible. Injected into the "
        "placeholder slot 32, which costs no channel."
    ),
    setup=_ASSERT_REAL + [(slot_word(32), rhd_read(59))],
    observations=[
        Observation(ch_code(0, 32), ch_code(1, 32), 0x0035, 0x003A, "chip0 A/B"),
        Observation(ch_code(2, 32), ch_code(3, 32), 0x0035, 0x003A, "chip1 A/B"),
    ],
    restore=_DEFAULT_RESTORE,
    diagnosis={
        "58/53": "A/B demux inverted",
        "53/53": "MISO B never demuxed — both DDR edges sampled as A",
        "chip1 only": "spi1_miso1 wiring, or the second chip",
        "0x0000 / 0xFFFF / unstable": "MISO sample point wrong, or chip not responding",
        "0x8000 / 0x8000": "empty-FIFO sentinel — streaming never started; not an RHD result",
    },
)

# INTAN in registers 40-44: five distinct values in sequence, so a wrong offset
# shows as rotated letters rather than one ambiguous mismatch. Slots 28-32 are
# used so channels 0-27 keep streaming normally as a sanity anchor.
_INTAN = [(40, 0x0049, "I"), (41, 0x004E, "N"), (42, 0x0054, "T"),
          (43, 0x0041, "A"), (44, 0x004E, "N")]

RUNG_B = Rung(
    key="b",
    title="A.1.1b — Pipeline offset",
    note=(
        "The numeric proof that the two-counter slot offset (spec §1.2) is "
        "right. Off by one slot in either direction pushes at least one "
        "observation outside slots 28-32, where it reads a CONVERT result — a "
        "16-bit ADC code, unmistakably not 0x00xx. Loud by construction."
    ),
    setup=_ASSERT_REAL + [
        (slot_word(28 + i), rhd_read(reg)) for i, (reg, _, _) in enumerate(_INTAN)
    ],
    observations=[
        Observation(ch_code(PRIMARY_SRC, 28), ch_code(PRIMARY_SRC, 29), 0x0049, 0x004E, "slots 28,29 = I,N"),
        Observation(ch_code(PRIMARY_SRC, 30), ch_code(PRIMARY_SRC, 31), 0x0054, 0x0041, "slots 30,31 = T,A"),
        Observation(ch_code(PRIMARY_SRC, 32), ch_code(PRIMARY_SRC, 28), 0x004E, 0x0049, "slots 32,28 = N,I (repeat)"),
    ],
    restore=_DEFAULT_RESTORE,
    diagnosis={
        "rotated letters": "response pipeline offset is wrong by the rotation distance",
        "a 16-bit non-0x00xx value": "observation landed on a CONVERT slot — offset out by ≥1",
    },
)

RUNG_C = Rung(
    key="c",
    title="A.1.1c — Chip identity",
    note=(
        "Also the FPGA-side half of B.6's `doctor`. Each observation reads the "
        "Runs on PRIMARY_SRC only (chip1 as of 2026-08-11), pairing two "
        "registers per observation rather than the same register on two chips "
        "— chip0 does not respond, so probing it here would only reproduce "
        "rung a's failure with a less specific diagnosis. Chip 0's identity "
        "therefore remains UNKNOWN: we cannot even confirm it is an RHD2164 "
        "until its MISO path works."
    ),
    setup=_ASSERT_REAL + [
        (slot_word(30), rhd_read(63)),
        (slot_word(31), rhd_read(62)),
        (slot_word(32), rhd_read(61)),
    ],
    observations=[
        Observation(ch_code(PRIMARY_SRC, 30), ch_code(PRIMARY_SRC, 31), 0x0004, 0x0040,
                    "reg 63 chip ID = 4, reg 62 num amps = 64"),
        Observation(ch_code(PRIMARY_SRC, 32), ch_code(PRIMARY_SRC, 30), 0x0001, 0x0004,
                    "reg 61 unipolar = 1, reg 63 re-read = 4"),
    ],
    restore=_DEFAULT_RESTORE,
    diagnosis={
        "chip0 passes, chip1 does not": "second RHD2164 absent, unpowered, or spi1_miso1 miswired",
        "both 0x0000": "no chip responding at all — check rung (a) first",
    },
)

# Rung (d) splits in two and the halves are NOT equally strong. d1 verifies the
# sampling table itself; d2 places markers across the frame wrap. A whole-frame
# skew is invisible to a static known value and is a SIMULATION obligation
# (spec §5.4, §6.3) — reported as such, never claimed as a bench pass.
RUNG_D = Rung(
    key="d",
    title="A.1.1d — Slot→channel alignment (frame boundary)",
    note=(
        "Markers placed across the frame wrap: slots 31, 32, 0, 1. Confirms "
        "each slot's answer appears at its own ch_cnt.\n"
        "Side effect, harmless: slots 0 and 1 are the CONVERT(63) "
        "auto-increment anchors, so overwriting them scrambles which channel "
        "each CONVERT slot samples for the duration of this rung. The markers "
        "are READs and are unaffected, and the anchor is restored — and "
        "re-asserted every frame — as soon as the table goes back.\n"
        "LIMIT, stated up front: a whole-FRAME skew — slot 32's answer "
        "published one frame late relative to slot 0's — is invisible here, "
        "because a static letter one frame stale is the same letter. Only a "
        "model whose responses vary per frame catches it, i.e. simulation "
        "(kuntur_tb.sv T12), which is Phase B. Report this rung as 'slot "
        "alignment confirmed; frame-boundary phase not yet verified.'"
    ),
    setup=_ASSERT_REAL + [
        (slot_word(31), rhd_read(40)),
        (slot_word(32), rhd_read(41)),
        (slot_word(0), rhd_read(42)),
        (slot_word(1), rhd_read(43)),
    ],
    observations=[
        Observation(ch_code(PRIMARY_SRC, 31), ch_code(PRIMARY_SRC, 32), 0x0049, 0x004E, "slots 31,32 = I,N"),
        Observation(ch_code(PRIMARY_SRC, 0), ch_code(PRIMARY_SRC, 1), 0x0054, 0x0041, "slots 0,1 = T,A"),
    ],
    restore=_DEFAULT_RESTORE,
    diagnosis={
        "I,N correct but T,A wrong": "the wrap itself — ch_cnt is not restarting cleanly at 0",
        "everything shifted by one": "cnt_cmd/ch_cnt start values are not 2/0",
    },
)

# Order matters and is the running order: L isolates the link with no offset
# dependence, O measures the offset, and only then are (a)-(d) interpretable.
RUNGS = {r.key: r for r in (RUNG_LINK, RUNG_OFFSET, RUNG_A, RUNG_B, RUNG_C, RUNG_D)}


# ── Runner ──────────────────────────────────────────────────────────────────

ACK_TIMEOUT_MS = 2000        # same as the Apply sequence's STREAMING_ACK_TIMEOUT_MS
# Bridge USART1 overrun mitigation (spec §4.3). Raised 15 -> 30 after the first
# bench run, where 2 of the 34 back-to-back setup writes in rung L timed out and
# had to be retried. The retries worked, so this is not a correctness fix — but
# a 6% per-command loss rate across 34-write rung setups makes a spurious abort
# likely eventually, and ~1 s more per rung is not worth arguing about.
COMMAND_GAP_MS = 30
WRITE_RETRIES = 3
OBSERVE_PAIRS = 64           # sample pairs collected per observation
DISCARD_PAIRS = 2            # first-frame artefact after START_STREAMING (spec §1.2)


@dataclass
class Result:
    label: str
    got_ch0: int
    got_ch1: int
    expect_ch0: int
    expect_ch1: int
    spread: int              # distinct values seen; >1 is itself a finding
    ok: bool
    info: bool = False       # measurement, not a verdict — excluded from pass/fail


class RungRunner(QObject):
    """Sequences one rung over the register console.

    Every step is ack-gated — the MCU's REG_WRITE16 response carries the value
    read back out of the regbank, so a write is verified for free with no extra
    round trip. That matters most for the 33-word table restore, where nobody
    is watching each step: a silently half-written sampling table would produce
    a rung failure that looks like an RTL fault, which is the worst possible
    outcome. Hence retry-on-timeout here, unlike SET_CHANNELS which
    deliberately has none because an operator is watching it.
    """

    progress = pyqtSignal(str)
    finished = pyqtSignal(str, list, bool)   # rung key, [Result], all_passed
    failed = pyqtSignal(str, str)            # rung key, reason

    def __init__(self, reader, parent=None):
        super().__init__(parent)
        self._reader = reader
        self._rung: Rung | None = None
        self._queue: list = []
        self._results: list[Result] = []
        self._collect: list[tuple[int, int]] | None = None
        self._pending_addr: int | None = None
        self._pending_value: int | None = None
        self._retries = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._running = False

    # -- public -------------------------------------------------------------

    def run(self, key: str) -> bool:
        if self._running:
            return False
        rung = RUNGS.get(key)
        if rung is None:
            return False
        self._rung = rung
        self._results = []
        self._running = True

        # STOP → setup writes → (per observation: ch_a/ch_b writes, START,
        # collect, STOP) → restore writes → START.
        q: list = [("stop", None)]
        q += [("write", wv) for wv in rung.setup]
        for obs in rung.observations:
            q.append(("write", (REG_CH_A, obs.ch_a)))
            q.append(("write", (REG_CH_B, obs.ch_b)))
            q.append(("start", None))
            q.append(("collect", obs))
            q.append(("stop", None))
        q += [("write", wv) for wv in rung.restore]
        q.append(("start", None))
        self._queue = q

        self._connect()
        self.progress.emit(f"{rung.title}: starting ({len(q)} steps)")
        self._next()
        return True

    def abort(self, reason: str = "aborted") -> None:
        if not self._running:
            return
        self._finish_failed(reason)

    # -- plumbing -----------------------------------------------------------

    def _connect(self) -> None:
        self._reader.reg_access_response.connect(self._on_reg_response)
        self._reader.stop_streaming_ack.connect(self._on_stop_ack)
        self._reader.start_streaming_ack.connect(self._on_start_ack)
        self._reader.batch_received.connect(self._on_batch)

    def _disconnect(self) -> None:
        for sig, slot in (
            (self._reader.reg_access_response, self._on_reg_response),
            (self._reader.stop_streaming_ack, self._on_stop_ack),
            (self._reader.start_streaming_ack, self._on_start_ack),
            (self._reader.batch_received, self._on_batch),
        ):
            try:
                sig.disconnect(slot)
            except TypeError:
                pass

    def _next(self) -> None:
        self._timer.stop()
        if not self._queue:
            self._finish_ok()
            return
        # COMMAND_GAP_MS between every command: a 33-word table rewrite is
        # exactly the back-to-back pattern that provokes the bridge USART1
        # overrun (control-plane spec, Resolved 2026-08-06).
        QTimer.singleShot(COMMAND_GAP_MS, self._dispatch)

    def _dispatch(self) -> None:
        if not self._running or not self._queue:
            return
        kind, arg = self._queue[0]
        if kind == "write":
            addr, value = arg
            self._pending_addr, self._pending_value = addr, value
            self._reader.send_reg_write16(addr, value)
            self._timer.start(ACK_TIMEOUT_MS)
        elif kind == "stop":
            self._reader.send_stop_streaming()
            self._timer.start(ACK_TIMEOUT_MS)
        elif kind == "start":
            self._reader.send_start_streaming()
            self._timer.start(ACK_TIMEOUT_MS)
        elif kind == "collect":
            self._collect = []
            self._timer.start(ACK_TIMEOUT_MS * 3)   # streaming must actually flow

    def _pop(self) -> None:
        self._queue.pop(0)
        self._retries = 0
        self._next()

    # -- signal handlers ----------------------------------------------------

    def _on_reg_response(self, rtype: int, addr: int, value: int) -> None:
        if not self._running or not self._queue or self._queue[0][0] != "write":
            return
        if rtype not in (CMD_REG_WRITE16, CMD_REG_READ16) or addr != self._pending_addr:
            return   # a stale response for some other address
        self._timer.stop()
        if value != self._pending_value:
            self._finish_failed(
                f"word {addr}: wrote 0x{self._pending_value:04X}, "
                f"regbank holds 0x{value:04X}")
            return
        self._pop()

    def _on_stop_ack(self, success: bool) -> None:
        if self._running and self._queue and self._queue[0][0] == "stop":
            self._timer.stop()
            if not success:
                self._finish_failed("STOP_STREAMING ack reported failure "
                                    "(stream_enable write did not take)")
                return
            self._pop()

    def _on_start_ack(self, success: bool) -> None:
        if self._running and self._queue and self._queue[0][0] == "start":
            self._timer.stop()
            if not success:
                self._finish_failed("START_STREAMING ack reported failure "
                                    "(stream_enable write did not take)")
                return
            self._pop()

    def _on_batch(self, packet) -> None:
        if not self._running or self._collect is None:
            return
        if not self._queue or self._queue[0][0] != "collect":
            return
        for a, b in zip(packet.ch0, packet.ch1):
            self._collect.append((a & 0xFFFF, b & 0xFFFF))
        if len(self._collect) < OBSERVE_PAIRS + DISCARD_PAIRS:
            return
        self._timer.stop()
        obs: Observation = self._queue[0][1]
        self._record(obs, self._collect[DISCARD_PAIRS:])
        self._collect = None
        self._pop()

    def _record(self, obs: Observation, pairs: list[tuple[int, int]]) -> None:
        # Mode, not a single sample: immune to a lost packet or a one-frame
        # artefact. The values under test are static, so any spread at all is
        # itself a finding and is reported alongside.
        got_ch0, _ = Counter(p[0] for p in pairs).most_common(1)[0]
        got_ch1, _ = Counter(p[1] for p in pairs).most_common(1)[0]
        spread = max(len({p[0] for p in pairs}), len({p[1] for p in pairs}))
        ok = got_ch0 == obs.expect_ch0 and got_ch1 == obs.expect_ch1
        self._results.append(Result(obs.label, got_ch0, got_ch1,
                                    obs.expect_ch0, obs.expect_ch1, spread, ok,
                                    obs.info))
        if obs.info:
            # A measurement, not a verdict: report the value and say nothing
            # about right or wrong. Marking a sweep probe "FAIL" because it is
            # not the one that matched would be actively misleading.
            self.progress.emit(
                f"  ....  {obs.label}: got 0x{got_ch0:04X} / 0x{got_ch1:04X}"
                + (f"  (spread {spread})" if spread > 1 else ""))
            return
        mark = "PASS" if ok else "FAIL"
        self.progress.emit(
            f"  {mark}  {obs.label}: got 0x{got_ch0:04X}/0x{got_ch1:04X}, "
            f"expected 0x{obs.expect_ch0:04X}/0x{obs.expect_ch1:04X}"
            + (f"  (spread {spread} distinct values)" if spread > 1 else ""))

    def _on_timeout(self) -> None:
        if not self._running or not self._queue:
            return
        kind, arg = self._queue[0]
        if kind == "collect":
            self._finish_failed("no sample data arrived after START_STREAMING")
            return
        self._retries += 1
        if self._retries > WRITE_RETRIES:
            what = f"word {self._pending_addr}" if kind == "write" else kind.upper()
            self._finish_failed(f"{what}: no response after {WRITE_RETRIES} retries")
            return
        self.progress.emit(f"  timeout, retry {self._retries}/{WRITE_RETRIES}")
        self._dispatch()

    # -- termination --------------------------------------------------------

    def _finish_ok(self) -> None:
        self._running = False
        self._timer.stop()
        self._disconnect()
        key = self._rung.key if self._rung else "?"
        verdicts = [r for r in self._results if not r.info]
        # An all-informational rung (the offset sweep) has no verdict to give;
        # completing it IS the result. Reporting it as "0/0 passed" would read
        # as a failure.
        all_passed = all(r.ok for r in verdicts) if verdicts else True
        self.finished.emit(key, self._results, all_passed)

    def _finish_failed(self, reason: str) -> None:
        self._running = False
        self._timer.stop()
        self._disconnect()
        key = self._rung.key if self._rung else "?"
        # Leave the FPGA streaming rather than stopped — a failed rung should
        # not also leave the instrument silent. An FPGA reset restores every
        # default if the restore list never ran.
        self._reader.send_start_streaming()
        self.failed.emit(key, reason)


# ── "Get Settings" — RHD2164 filter/bandwidth register read ────────────────
# docs/interfaces/recording-format.md §2.1/§2.1a. Same register-console
# primitives as RungRunner (rhd_read, slot_word, ch_code, the ack-gated
# queue), but a different shape: RungRunner's setup writes the WHOLE
# sampling table up front and always restores to hardcoded FPGA defaults;
# this reads one register at a time through the dedicated command slot 32
# only (never slots 0-31, never REG_CH_B) and restores the operator's own
# live channel selection via SET_CHANNELS — the same command Apply uses —
# rather than a raw register poke, so restoration is verified the same way
# Apply already is.
FILTER_REGISTERS = [4, 8, 9, 10, 11, 12, 13]

# Slot 32's value at reset / in normal operation (components.v: ram[80]
# initial value) — what "Get Settings" puts back once it's done using the
# slot for its own reads. Not a full RESET_SAMPLING_TABLE restore: slots
# 0-31 are never touched in the first place, so there is nothing else to
# put back.
SLOT32_RESET_CMD = rhd_read(63)


@dataclass
class FilterSettingsResult:
    registers: dict[str, int]     # {"4": value, "8": value, ...}
    ok: bool
    reason: str = ""              # set when ok is False


class FilterSettingsReader(QObject):
    """Runs the 'Get Settings' sequence: STOP -> read FILTER_REGISTERS one
    at a time through slot 32 -> put slot 32 back -> SET_CHANNELS(orig) ->
    verified readback -> START. Only REG_CH_A and regbank word 80 (slot 32)
    are ever written.
    """

    progress = pyqtSignal(str)
    finished = pyqtSignal(object)   # FilterSettingsResult
    failed = pyqtSignal(str)        # reason

    def __init__(self, reader, parent=None):
        super().__init__(parent)
        self._reader = reader
        self._queue: list = []
        self._results: dict[str, int] = {}
        self._collect: list[int] | None = None
        self._pending_addr: int | None = None
        self._pending_value: int | None = None
        self._orig_channels: tuple[int, int] | None = None
        self._retries = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._running = False

    # -- public -------------------------------------------------------------

    def run(self, orig_ch_a: int, orig_ch_b: int) -> bool:
        """orig_ch_a/orig_ch_b are the operator's current live channels
        (friendly 0-127 indices) — restored via SET_CHANNELS at the end,
        exactly like the Apply button would."""
        if self._running:
            return False
        self._orig_channels = (orig_ch_a, orig_ch_b)
        self._results = {}
        self._running = True

        q: list = [("stop", None)]
        for reg in FILTER_REGISTERS:
            q.append(("write", (slot_word(32), rhd_read(reg))))
            q.append(("write", (REG_CH_A, ch_code(PRIMARY_SRC, 32))))
            q.append(("start", None))
            q.append(("collect", reg))
            q.append(("stop", None))
        q.append(("write", (slot_word(32), SLOT32_RESET_CMD)))
        q.append(("set_channels", (orig_ch_a, orig_ch_b)))
        q.append(("start", None))
        self._queue = q

        self._connect()
        self.progress.emit(f"Get Settings: reading {len(FILTER_REGISTERS)} registers")
        self._next()
        return True

    def abort(self, reason: str = "aborted") -> None:
        if not self._running:
            return
        self._finish_failed(reason)

    # -- plumbing -----------------------------------------------------------

    def _connect(self) -> None:
        self._reader.reg_access_response.connect(self._on_reg_response)
        self._reader.stop_streaming_ack.connect(self._on_stop_ack)
        self._reader.start_streaming_ack.connect(self._on_start_ack)
        self._reader.batch_received.connect(self._on_batch)
        self._reader.channels_readback.connect(self._on_channels_readback)

    def _disconnect(self) -> None:
        for sig, slot in (
            (self._reader.reg_access_response, self._on_reg_response),
            (self._reader.stop_streaming_ack, self._on_stop_ack),
            (self._reader.start_streaming_ack, self._on_start_ack),
            (self._reader.batch_received, self._on_batch),
            (self._reader.channels_readback, self._on_channels_readback),
        ):
            try:
                sig.disconnect(slot)
            except TypeError:
                pass

    def _next(self) -> None:
        self._timer.stop()
        if not self._queue:
            self._finish_ok()
            return
        # Same COMMAND_GAP_MS pacing as RungRunner — back-to-back commands
        # provoke the bridge USART1 overrun (control-plane spec, Resolved
        # 2026-08-06).
        QTimer.singleShot(COMMAND_GAP_MS, self._dispatch)

    def _dispatch(self) -> None:
        if not self._running or not self._queue:
            return
        kind, arg = self._queue[0]
        if kind == "write":
            addr, value = arg
            self._pending_addr, self._pending_value = addr, value
            self._reader.send_reg_write16(addr, value)
            self._timer.start(ACK_TIMEOUT_MS)
        elif kind == "stop":
            self._reader.send_stop_streaming()
            self._timer.start(ACK_TIMEOUT_MS)
        elif kind == "start":
            self._reader.send_start_streaming()
            self._timer.start(ACK_TIMEOUT_MS)
        elif kind == "collect":
            self._collect = []
            self._timer.start(ACK_TIMEOUT_MS * 3)   # streaming must actually flow
        elif kind == "set_channels":
            ch_a, ch_b = arg
            self._reader.send_set_channels(ch_a, ch_b)
            self._timer.start(ACK_TIMEOUT_MS)

    def _pop(self) -> None:
        self._queue.pop(0)
        self._retries = 0
        self._next()

    # -- signal handlers ----------------------------------------------------

    def _on_reg_response(self, rtype: int, addr: int, value: int) -> None:
        if not self._running or not self._queue or self._queue[0][0] != "write":
            return
        if rtype not in (CMD_REG_WRITE16, CMD_REG_READ16) or addr != self._pending_addr:
            return
        self._timer.stop()
        if value != self._pending_value:
            self._finish_failed(
                f"word {addr}: wrote 0x{self._pending_value:04X}, "
                f"regbank holds 0x{value:04X}")
            return
        self._pop()

    def _on_stop_ack(self, success: bool) -> None:
        if self._running and self._queue and self._queue[0][0] == "stop":
            self._timer.stop()
            if not success:
                self._finish_failed("STOP_STREAMING ack reported failure")
                return
            self._pop()

    def _on_start_ack(self, success: bool) -> None:
        if self._running and self._queue and self._queue[0][0] == "start":
            self._timer.stop()
            if not success:
                self._finish_failed("START_STREAMING ack reported failure")
                return
            self._pop()

    def _on_channels_readback(self, ch_a: int, ch_b: int) -> None:
        if not self._running or not self._queue or self._queue[0][0] != "set_channels":
            return
        want_a, want_b = self._queue[0][1]
        self._timer.stop()
        if (ch_a, ch_b) != (want_a, want_b):
            self._finish_failed(
                f"restore mismatch: wanted ch_a={want_a}/ch_b={want_b}, "
                f"FPGA now holds ch_a={ch_a}/ch_b={ch_b}")
            return
        self._pop()

    def _on_batch(self, packet) -> None:
        if not self._running or self._collect is None:
            return
        if not self._queue or self._queue[0][0] != "collect":
            return
        self._collect.extend(int(v) & 0xFFFF for v in packet.ch0)
        if len(self._collect) < OBSERVE_PAIRS + DISCARD_PAIRS:
            return
        self._timer.stop()
        reg: int = self._queue[0][1]
        pairs = self._collect[DISCARD_PAIRS:]
        self._collect = None
        # Majority vote, same reasoning as RungRunner._record: the value
        # under read is static, so any spread is itself a finding.
        value, _ = Counter(pairs).most_common(1)[0]
        self._results[str(reg)] = value & 0xFF
        self.progress.emit(f"  reg {reg}: 0x{value & 0xFF:02X}")
        self._pop()

    def _on_timeout(self) -> None:
        if not self._running or not self._queue:
            return
        kind, arg = self._queue[0]
        if kind == "collect":
            self._finish_failed("no sample data arrived after START_STREAMING")
            return
        self._retries += 1
        if self._retries > WRITE_RETRIES:
            what = f"word {self._pending_addr}" if kind == "write" else kind.upper()
            self._finish_failed(f"{what}: no response after {WRITE_RETRIES} retries")
            return
        self.progress.emit(f"  timeout, retry {self._retries}/{WRITE_RETRIES}")
        self._dispatch()

    # -- termination --------------------------------------------------------

    def _finish_ok(self) -> None:
        self._running = False
        self._timer.stop()
        self._disconnect()
        self.finished.emit(FilterSettingsResult(registers=dict(self._results), ok=True))

    def _finish_failed(self, reason: str) -> None:
        self._running = False
        self._timer.stop()
        self._disconnect()
        # Same philosophy as RungRunner: never leave the instrument silent.
        # If the failure happened before the channel restore ran, this
        # leaves REG_CH_A pointed at slot 32 rather than the operator's
        # channel — the operator must re-Apply to recover, same recovery
        # path as any other failed command sequence.
        self._reader.send_start_streaming()
        self.failed.emit(reason)
