"""
RHD2164 friendly-channel offset compensation — pc-app side.

Ground truth, verified directly against source, 2026-08-28:

- `docs/interfaces/channel-selection-control-plane.md` §1a's friendly-index
  formula (`raw_code = ((n & 0x60) << 1) | (n & 0x1F)`) was written
  2026-08-05 and implemented verbatim as `FPGA_SPI_ChannelToRaw()` in
  `/data/projects/kuntur/kuntur144/mcu/kuntur-mcu/Core/Src/fpga_spi.c:325-328`.
- A.1.1e later confirmed on hardware (2026-08-11, `pc-app/diagnostics.py`'s
  `SLOT_OFFSET = 3`) that the RHD2164's own 2-command response pipeline plus
  one more cycle of latch timing means the raw code that must be written to
  *observe* sampling slot `k`'s answer is `(k + 3) mod 33`, not `k` itself.
- `FPGA_SPI_ChannelToRaw()` was never updated after that discovery. It still
  sends the friendly index's low bits straight through with zero correction.
  So today, requesting friendly channel `n` actually captures physical RHD
  channel `(n - 3) mod 32` within its module — not `n`.

Fixed here rather than in firmware, per the 2026-08-28 decision: correct the
124 of 128 channels per chip pair that are reachable by sending an
*adjusted* friendly index through the existing SET_CHANNELS path (still
validated/range-checked by the MCU exactly as today). The remaining 4 — one
per 32-channel module, at physical index 29 — need raw code
`source*64 + 32`, which `FPGA_SPI_ChannelToRaw()` can never produce for any
friendly input (its output's bit 5 is always clear by construction: the
formula inserts a literal zero there). Those 4 must go through a direct
`REG_WRITE16` on `REG_CH_A`/`REG_CH_B` (196/197) instead.

`n` throughout this module is the *physical* RHD channel, 0-127 — what the
operator selects and what the recording sidecar records.
"""

MODULE_SIZE = 32
FRAME_SLOTS = 33          # matches diagnostics.py's FRAME_SLOTS
SLOT_OFFSET = 3            # matches diagnostics.py's SLOT_OFFSET

# Physical per-module index that lands on the unreachable raw code (32) —
# the FPGA's reserved command slot, structurally outside the friendly
# encoding's range. One such physical channel per 32-channel module.
UNREACHABLE_MODULE_INDEX = (FRAME_SLOTS - SLOT_OFFSET) % MODULE_SIZE  # 29


def _check_range(n: int) -> None:
    if not 0 <= n <= 127:
        raise ValueError(f"physical channel must be 0-127, got {n}")


def physical_to_raw(n: int) -> int:
    """The true raw FPGA regbank code (source<<6 | corrected) for physical
    channel n, regardless of whether it's expressible via a friendly
    SET_CHANNELS index. Needed whenever writing REG_CH_A/REG_CH_B directly
    — including for a channel that *would* be reachable via SET_CHANNELS on
    its own, if it's being set alongside one of the 4 that isn't (a single
    SET_CHANNELS call sets both registers together, so if either needs the
    raw path, both must use it)."""
    _check_range(n)
    source, idx = divmod(n, MODULE_SIZE)
    corrected = (idx + SLOT_OFFSET) % FRAME_SLOTS
    return (source << 6) | corrected


def physical_to_wire(n: int) -> tuple[int, bool]:
    """n: physical RHD channel, 0-127.

    Returns (value, is_raw):
      is_raw=False -> value is the friendly index to send via SET_CHANNELS.
      is_raw=True  -> value is the raw FPGA regbank code (source<<6 | 32)
                       for a direct REG_WRITE16 on REG_CH_A/REG_CH_B.
    """
    _check_range(n)
    source, idx = divmod(n, MODULE_SIZE)
    corrected = (idx + SLOT_OFFSET) % FRAME_SLOTS
    if corrected == MODULE_SIZE:
        return source * 64 + MODULE_SIZE, True
    return source * MODULE_SIZE + corrected, False


def wire_to_physical(friendly_value: int) -> int:
    """Inverse of the is_raw=False branch — decodes a SET_CHANNELS readback
    (always friendly-space; the raw REG_WRITE16 path never produces a
    channels_readback event) back to the physical channel number.

    Raises ValueError for the one wire value per module (corrected mod 32
    == 2) that physical_to_wire() never produces and decodes to a slot
    outside the 32 real per-module channels — a genuine readback should
    never land here; if one does, it's a corrupted/unexpected response,
    not a real physical channel, and must not be silently reported as one
    (the arithmetic alone would produce a nonsensical >127 result)."""
    _check_range(friendly_value)
    source, corrected = divmod(friendly_value, MODULE_SIZE)
    idx = (corrected - SLOT_OFFSET) % FRAME_SLOTS
    if idx >= MODULE_SIZE:
        raise ValueError(
            f"wire value {friendly_value} decodes to slot {idx}, outside "
            f"the 32 real per-module channels — physical_to_wire() never "
            f"produces this value, so a genuine readback should never "
            f"report it; treat as a corrupted/unexpected response")
    return source * MODULE_SIZE + idx


def is_reachable(n: int) -> bool:
    """True if n can be selected via the friendly SET_CHANNELS path alone."""
    return not physical_to_wire(n)[1]
