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
