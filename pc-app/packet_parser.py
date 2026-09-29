"""
StreamDataPacket_t parser — mirrors BleGattManager.parseStreamPacket() in Kotlin.

Packet layout (little-endian, 244 bytes total):
  offset 0 : uint32  timestamp_s
  offset 4 : uint16  timestamp_sub_s   (0–31999; each unit = 1/32 ms)
  offset 6 : uint8   seq_num           (rolling 0–255)
  offset 7 : uint8   num_pairs
  offset 8 : int16[] samples           (interleaved ch0, ch1 × num_pairs)

Timestamp decode:
  packet_base_us = timestamp_s × 1_000_000 + timestamp_sub_s × 1_000 // 32
  sample_us[i]   = packet_base_us + i × 1_000_000 // SAMPLE_RATE_HZ
"""

import struct
import numpy as np
from dataclasses import dataclass

HEADER_FMT   = "<IHBBs"   # not used directly — parsed field by field
HEADER_SIZE  = 8
SAMPLE_RATE_HZ  = 30_000
MAGIC        = bytes([0xAA, 0x55])
PACKET_SIZE  = 244
FIFO_EMPTY_SENTINEL = np.int16(-32768)  # 0x8000 — FPGA FIFO underrun marker


def is_fifo_underrun(ch0: np.ndarray, ch1: np.ndarray) -> np.ndarray:
    """True where a sample is a genuine FPGA FIFO-empty marker.

    Single-sourced here (2026-08-27) after graph_widget.py and
    analyze_recording.py were each independently restating this same
    two-line rule — the same failure shape that let the REG13/underrun
    bugs drift. ch0 alone is not a reliable marker: against the A.1
    ramp test pattern (ch1 = ch0 + 1000), ch0 legitimately passes through
    -32768 once per 16-bit wrap while ch1 reads -31768, not -32768.
    Only BOTH channels reading the sentinel matches
    FPGA_SPI_ReadSamples's actual underrun contract.

    NOTE — this rule predates A.1.1e (2026-08-11) connecting real RHD2164
    data. With independent, real channels, a genuinely saturated pair can
    also legitimately read (-32768, -32768) simultaneously, which this
    function cannot distinguish from a true underrun — see PLAN.md A.6.4
    (DECISION 2, unresolved as of 2026-08-27). Do not change this rule
    without resolving that decision; this function exists to make that a
    one-place change when it is resolved, not to imply the ambiguity is
    fixed.
    """
    return (ch0 == FIFO_EMPTY_SENTINEL) & (ch1 == FIFO_EMPTY_SENTINEL)


@dataclass
class PacketHeader:
    timestamp_s:     int
    timestamp_sub_s: int
    seq_num:         int
    num_pairs:       int


@dataclass
class ParsedPacket:
    header:         PacketHeader
    ch0:            np.ndarray   # int16, shape (num_pairs,)
    ch1:            np.ndarray   # int16, shape (num_pairs,)
    timestamps_us:  np.ndarray   # int64, shape (num_pairs,)
    fifo_underruns: int          # samples where ch0 == ch1 == 0x8000 (FPGA FIFO empty)


def parse(data: bytes) -> ParsedPacket | None:
    """Parse a raw 244-byte BLE notification payload. Returns None on error."""
    if len(data) < HEADER_SIZE:
        return None

    timestamp_s,    = struct.unpack_from("<I", data, 0)
    timestamp_sub_s, = struct.unpack_from("<H", data, 4)
    seq_num,        = struct.unpack_from("<B", data, 6)
    num_pairs,      = struct.unpack_from("<B", data, 7)

    min_size = HEADER_SIZE + num_pairs * 4
    if len(data) < min_size:
        return None

    packet_base_us = timestamp_s * 1_000_000 + timestamp_sub_s * 1_000 // 32

    samples = np.frombuffer(data, dtype="<i2", count=num_pairs * 2, offset=HEADER_SIZE)
    ch0 = samples[0::2].copy()
    ch1 = samples[1::2].copy()

    i = np.arange(num_pairs, dtype=np.int64)
    timestamps_us = packet_base_us + i * 1_000_000 // SAMPLE_RATE_HZ

    fifo_underruns = int(np.sum(is_fifo_underrun(ch0, ch1)))

    return ParsedPacket(
        header=PacketHeader(timestamp_s, timestamp_sub_s, seq_num, num_pairs),
        ch0=ch0,
        ch1=ch1,
        timestamps_us=timestamps_us,
        fifo_underruns=fifo_underruns,
    )


# seq_num is one byte, so a gap is only ever known mod 256: a 7,220-packet
# burst reads as 52 and a burst of exactly 256×k reads as zero (PLAN.md A.7
# step 2b). The packet's own RTC timestamp bounds how many packets can have
# been sent in between, which is what decides whether a wrap was possible.
# = f(μ): 256 packets at the measured μ = 499.4 pkt/s take 0.513 s
# (stream-packet-format.md §1.5); 0.4 s leaves ~28% headroom for a backlog
# drain running faster than the mean. Re-derive if μ moves.
SEQ_WRAP_POSSIBLE_US = 400_000
_RTC_DAY_US = 86_400 * 1_000_000   # timestamp_s is time-of-day, wraps at midnight


class SeqGapTracker:
    """Packet-loss accounting from seq_num that knows when it cannot count.

    dropped_packets — sum of seq gaps. Exact only while uncertain_gaps is 0;
                      otherwise a lower bound ("at least N").
    uncertain_gaps  — gaps across which enough RTC time passed for seq_num to
                      have wrapped, so the true loss is gap + 256·k for an
                      unknown k ≥ 0. Includes a zero seq gap across such a
                      pause: that is the "256×k reads as zero" case.

    The real fix is A.7 step 2's cumulative 32-bit telemetry counters; this
    only stops the pc-app presenting a lower bound as a total.
    """

    def __init__(self):
        self.dropped_packets = 0
        self.uncertain_gaps = 0
        self._expected_seq: int | None = None
        self._last_raw_us: int | None = None

    def pause(self):
        """Streaming was stopped on purpose (STOP_STREAMING acked). The MCU
        does not reset seq_num on STOP/START, so seq continuity still holds,
        but the time across the pause says nothing about loss — forget it so
        every channel change is not scored as an uncertain gap."""
        self._last_raw_us = None

    def update(self, header: PacketHeader) -> tuple[int, bool]:
        """Account one packet. Returns (seq gap, uncertain) for this packet."""
        seq = header.seq_num
        # Raw header time, not ParsedPacket.timestamps_us: the reader's
        # monotonicity clamp rewrites those, and this needs the MCU's clock.
        raw_us = header.timestamp_s * 1_000_000 + header.timestamp_sub_s * 1_000 // 32

        gap = 0
        uncertain = False
        if self._expected_seq is not None:
            gap = (seq - self._expected_seq) % 256
            self.dropped_packets += gap
            if self._last_raw_us is not None:
                elapsed = (raw_us - self._last_raw_us) % _RTC_DAY_US
                # A small backwards step (the RTC/CI jitter the reader's clamp
                # exists for) comes out of the modulo as ~24 h. Anything past
                # half a day is that, not a real pause.
                if SEQ_WRAP_POSSIBLE_US <= elapsed < _RTC_DAY_US // 2:
                    uncertain = True
                    self.uncertain_gaps += 1
        self._expected_seq = (seq + 1) % 256
        self._last_raw_us = raw_us
        return gap, uncertain

    def summary(self) -> str:
        """'727' when exact, '≥727 (2 gaps of unknown size)' when not."""
        if not self.uncertain_gaps:
            return str(self.dropped_packets)
        s = "" if self.uncertain_gaps == 1 else "s"
        return f"≥{self.dropped_packets} ({self.uncertain_gaps} gap{s} of unknown size)"
