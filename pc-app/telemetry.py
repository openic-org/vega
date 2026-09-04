"""
Telemetry frame decode — the ``0xDD 0x22`` frame.

Spec: ``docs/interfaces/stream-packet-format.md`` section 6. This is the
out-of-band loss report: cumulative counters plus an RTC time anchor, sent
~1 Hz on ``0xFFF4`` by the headstage MCU and re-framed by the bridge with its
own TX-ring counters appended.

Wire layout (section 6.2, all little-endian)::

     off  size  field                     filled by
      0     1   telemetry_version         MCU
      1     1   flags                     MCU
      2     4   anchor_sample_index       MCU
      6     4   anchor_timestamp_s        MCU
     10     2   anchor_timestamp_sub_s    MCU
     12     4   fifo0_overflow_samples    MCU (from FPGA regbank)
     16     2   fifo0_high_water          MCU (from FPGA regbank)
     18     4   ring_truncated_samples    MCU
     22     4   flow_off_count            MCU
     26     4   stall_time_ms_total       MCU
     30     4   tx_ring_drop_bytes        bridge
     34     4   tx_ring_drop_frames       bridge

The MCU fields are read from the FRONT at fixed offsets and the bridge fields
from the BACK (last 8 bytes). That asymmetry is deliberate: a future
``telemetry_version`` adds MCU counters at offset 30, which would push the
bridge's pair along. Reading the bridge pair from the end means this parser
keeps working against a newer headstage instead of silently decoding two MCU
counters as drop statistics.
"""

import struct
from dataclasses import dataclass

TELEMETRY_MAGIC = bytes([0xDD, 0x22])

TELEMETRY_VERSION_SUPPORTED = 1

# Bytes the bridge appends, always last — see the module docstring.
BRIDGE_FIELDS_SIZE = 8
# MCU half as of version 1.
MCU_FIELDS_SIZE = 30
MIN_FRAME_SIZE = MCU_FIELDS_SIZE + BRIDGE_FIELDS_SIZE   # 38

# flags, byte 1 — section 6.2.
FLAG_FPGA_COUNTERS_VALID = 0x01


@dataclass
class TelemetryFrame:
    version:                int
    flags:                  int
    anchor_sample_index:    int
    anchor_timestamp_s:     int
    anchor_timestamp_sub_s: int
    fifo0_overflow_samples: int
    fifo0_high_water:       int
    ring_truncated_samples: int
    flow_off_count:         int
    stall_time_ms_total:    int
    tx_ring_drop_bytes:     int
    tx_ring_drop_frames:    int

    @property
    def fpga_counters_valid(self) -> bool:
        """True when the two ``fifo0_*`` fields were actually read from the
        FPGA regbank for this frame.

        When False they are transmitted as zero and mean *nothing was
        measured* — which is a different fact from *nothing was lost*, and the
        one that is true until A.7 step 1's RTL counter exists. Section 7's
        attribution table cannot use a zero it can't tell apart from an absent
        reading, so callers must check this before displaying or accumulating
        either field.
        """
        return bool(self.flags & FLAG_FPGA_COUNTERS_VALID)

    @property
    def anchor_timestamp_us(self) -> int:
        """Wall-clock microseconds for ``anchor_sample_index``.

        Same RTC encoding as the v0 packet header, so the two are directly
        comparable: ``sub_s`` counts 32,000 ticks/s.
        """
        return self.anchor_timestamp_s * 1_000_000 + self.anchor_timestamp_sub_s * 1_000 // 32


def parse(payload: bytes) -> TelemetryFrame | None:
    """Decode one ``0xDD 0x22`` payload. Returns None if it cannot be trusted.

    Rejects a short frame and a version this parser predates. Accepts a
    *longer* frame from a future version: section 6.2 makes added counters
    additive, so the fields below are still where this parser expects them.
    """
    if len(payload) < MIN_FRAME_SIZE:
        return None

    version = payload[0]
    if version < TELEMETRY_VERSION_SUPPORTED:
        # 0 is not a valid version; anything below what we know how to read is
        # not something to guess at.
        return None

    (flags,
     anchor_sample_index,
     anchor_timestamp_s,
     anchor_timestamp_sub_s,
     fifo0_overflow_samples,
     fifo0_high_water,
     ring_truncated_samples,
     flow_off_count,
     stall_time_ms_total) = struct.unpack_from("<BIIHIHIII", payload, 1)

    tx_ring_drop_bytes, tx_ring_drop_frames = struct.unpack_from(
        "<II", payload, len(payload) - BRIDGE_FIELDS_SIZE)

    return TelemetryFrame(
        version=version,
        flags=flags,
        anchor_sample_index=anchor_sample_index,
        anchor_timestamp_s=anchor_timestamp_s,
        anchor_timestamp_sub_s=anchor_timestamp_sub_s,
        fifo0_overflow_samples=fifo0_overflow_samples,
        fifo0_high_water=fifo0_high_water,
        ring_truncated_samples=ring_truncated_samples,
        flow_off_count=flow_off_count,
        stall_time_ms_total=stall_time_ms_total,
        tx_ring_drop_bytes=tx_ring_drop_bytes,
        tx_ring_drop_frames=tx_ring_drop_frames,
    )
