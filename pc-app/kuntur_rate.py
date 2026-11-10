"""
kuntur_rate.py — the per-channel sample rate the pc-app works with, set by
the operator (PLAN.md R7, docs/interfaces/recording-format.md §3a.1).

Kuntur runs at one of two rates, chosen by the bitstream (#6,
docs/releases.md): 25,000 S/s (variants 2/3, clk 37.95 MHz) and 28,000
(variant 1, clk 42.504 MHz). The 45.54 MHz impl_1 build (30 kS/s) stays
selectable as "legacy" until it is retired (§3a.5 D1).

One value replaces every rate constant the pc-app used to hard-code:
sample spacing inside a packet (packet_parser.parse), the reader's
monotonicity clamp, ChannelHealthMonitor's dead-run length, GraphWidget's
window, and the sidecar's sample_rate.channel_hz/source.

There is no default (§3a.5 D2): the first session must choose, and the
choice is then remembered (QSettings, see main_window).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class KunturRate:
    key: str          # stored in QSettings
    label: str        # shown in the selector
    channel_hz: float  # nominal per-channel rate the build is designed for
    source: str       # sidecar sample_rate.source


RATES = (
    KunturRate("25k", "25 kS/s", 25_000.0,
               "operator setting: 25 kS/s (variant 2/3 build, clk 37.95 MHz, docs/releases.md)"),
    KunturRate("28k", "28 kS/s", 28_000.0,
               "operator setting: 28 kS/s (variant 1 build, clk 42.504 MHz, docs/releases.md)"),
    KunturRate("30k", "30 kS/s (legacy)", 29_999.97,
               "operator setting: 30 kS/s legacy (impl_1, clk 45.54 MHz, "
               "docs/interfaces/stream-packet-format.md §1.1)"),
)

BY_KEY = {r.key: r for r in RATES}


def from_key(key) -> "KunturRate | None":
    """The rate stored under key, or None (nothing chosen yet, or a key
    from a build of the pc-app that offered a rate this one does not)."""
    return BY_KEY.get(key) if isinstance(key, str) else None
