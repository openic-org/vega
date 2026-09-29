"""ambient_logger decode + dew point. Run: python3 test_ambient_logger.py"""
from ambient_logger import decode_h5075, dew_point_c


def payload(temp_c: float, rh: float, batt: int, error: bool = False) -> bytes:
    v = round(abs(temp_c) * 10) * 1000 + round(rh * 10)
    if temp_c < 0:
        v |= 0x800000
    return bytes([0x00, v >> 16 & 0xFF, v >> 8 & 0xFF, v & 0xFF, (0x80 if error else 0) | batt])


r = decode_h5075(payload(23.4, 45.6, 87))
assert (r.temp_c, r.rh_pct, r.battery_pct, r.error) == (23.4, 45.6, 87, False), r
r = decode_h5075(payload(-5.2, 80.0, 50, error=True))
assert (r.temp_c, r.rh_pct, r.battery_pct, r.error) == (-5.2, 80.0, 50, True), r
assert decode_h5075(b"\x00\x01") is None
assert abs(dew_point_c(20, 50) - 9.3) < 0.1, dew_point_c(20, 50)
assert dew_point_c(20, 0) is None
print("ALL AMBIENT-LOGGER CHECKS PASSED")
