"""Offline checks for channel_mapping.py's offset-compensation math. Pure
functions, no Qt, no hardware — brute-forces all 128 physical channels.

    python3 test_channel_mapping.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import channel_mapping as M

print("=" * 70)

raw_count = 0
for n in range(128):
    value, is_raw = M.physical_to_wire(n)
    assert 0 <= value <= 255, (n, value)
    if is_raw:
        raw_count += 1
        source, idx = divmod(n, 32)
        assert idx == 29, f"only per-module index 29 should be unreachable, got {n} (idx {idx})"
        assert value == source * 64 + 32, (n, value)
        assert M.is_reachable(n) is False
    else:
        assert M.is_reachable(n) is True
        back = M.wire_to_physical(value)
        assert back == n, f"round trip failed: physical_to_wire({n}) -> {value} -> wire_to_physical -> {back}"

assert raw_count == 4, f"expected exactly 4 unreachable channels, got {raw_count}"
print(f"all 128 physical channels: {128 - raw_count} round-trip via friendly SET_CHANNELS, "
      f"{raw_count} need the raw REG_WRITE16 path")
print(f"unreachable-via-friendly channels: {[n for n in range(128) if not M.is_reachable(n)]}")

print("-" * 70)

# Spot-check against the hand-derived table in the plan/spec.
cases = {
    0: (3, False),    # request phys 0 -> friendly 3 (matches diagnostics.py's
                       # ch_code(0, 0) = (0+3)%33 = 3, same SLOT_OFFSET math)
    28: (31, False),
    29: (32, True),    # the dead zone
    30: (0, False),
    31: (1, False),
    32: (35, False),   # source 1 (module B), idx 0 -> 32+3=35
    61: (96, True),    # source 1, idx 29 -> 64+32
    64: (67, False),   # source 2 (chip1-A), idx 0
    93: (160, True),   # source 2, idx 29 -> 128+32
    96: (99, False),   # source 3 (chip1-B), idx 0
    125: (224, True),  # source 3, idx 29 -> 192+32
    127: (97, False),  # source 3, idx 31 -> (31+3)%33=1 -> 96+1=97
}
for n, (expect_value, expect_raw) in cases.items():
    value, is_raw = M.physical_to_wire(n)
    assert is_raw == expect_raw, f"physical {n}: expected is_raw={expect_raw}, got {is_raw}"
    assert value == expect_value, f"physical {n}: expected wire {expect_value}, got {value}"
print("hand-derived spot checks OK")

print("-" * 70)

# The real invariant, checked against two independent ground-truth sources
# rather than just this module's own internal consistency: sending
# physical_to_wire(n)'s friendly value through the REAL firmware formula
# (fpga_spi.c:325-328, copied verbatim below) must produce the same raw
# code diagnostics.py's hardware-confirmed ch_code(source, idx) computes
# for observing sampling slot `idx`.
import diagnostics as D


def firmware_channel_to_raw(n: int) -> int:
    """Exact copy of FPGA_SPI_ChannelToRaw(), fpga_spi.c:325-328."""
    return ((n & 0x60) << 1) | (n & 0x1F)


for n in range(128):
    value, is_raw = M.physical_to_wire(n)
    source, idx = divmod(n, 32)
    if is_raw:
        continue
    raw_sent = firmware_channel_to_raw(value)
    target_raw = D.ch_code(source, idx)
    assert raw_sent == target_raw, \
        f"physical {n}: friendly {value} -> firmware raw 0x{raw_sent:02X}, " \
        f"but diagnostics.ch_code({source},{idx}) wants 0x{target_raw:02X}"
print("cross-checked against the real firmware formula + diagnostics.py's "
      "hardware-confirmed ch_code() on all 124 reachable channels")

print("-" * 70)

try:
    M.physical_to_wire(128)
    raise SystemExit("expected ValueError for out-of-range channel")
except ValueError:
    print("out-of-range physical channel correctly rejected")

print("=" * 70)
print("ALL CHANNEL MAPPING CHECKS PASSED")
