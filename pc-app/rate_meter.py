"""
rate_meter.py — the per-channel rate Kuntur actually produces, measured
live from the packets (PLAN.md R7, recording-format.md §3a.2), independent
of the operator's setting.

Method (revised 2026-11-10, Manuel): per packet, the MCU's RTC time at
assembly (the header, not the pc-app's clamped timestamps), the real
samples (slots minus FIFO-empty 0x8000 padding) and seq_num. Packets are
grouped into windows of WINDOW_S; a window's rate is its real samples over
the time to the next window's first packet, with seq_num gaps filled by
the window's mean real samples per packet. The rate is the **median** of
the window rates.

Why a median and not the agreed least-squares fit: samples can be lost
inside Kuntur with no seq_num gap (MCU ring truncation during a BLE stall,
or fifo0 overflow). On the first 25k recording (2026-11-10, 938 s) a fit
read -0.154% while every clean 60 s window read 25,000.1 S/s. A loss only
ever pulls a window down, so the median stays on the clock; and a window
well below the median is reported as samples lost without a seq_num gap.
The median needs at least 3 windows (30 s) to outvote one lossy window;
before that a loss pulls the estimate down, which is why the early alarm
is only the coarse 0.5% (D3).

Only meaningful while the transport keeps up: with almost no padding the
FIFO may be overflowing and the result is a lower bound (saturation
warning). The time base is the MCU's LSE, the FPGA's is the HSE: both tens
of ppm.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import median

WINDOW_S = 10.0
RECENT_S = 60.0
# A window below the median by more than this is counted as a loss.
# Clean 10 s windows agree to a few ppm (packet-granular counts, 31 µs RTC
# steps); 0.05% is the 60 s alarm tolerance.
LOSS_FRAC = 0.0005
# Alarm thresholds, agreed 2026-11-04 (D3).
ALARM_EARLY_S, ALARM_EARLY_FRAC = 10.0, 0.005
ALARM_LATE_S, ALARM_LATE_FRAC = 60.0, 0.0005
SATURATED_PADDING = 0.005
DAY_US = 86_400_000_000


@dataclass
class Window:
    t0_us: int
    t1_us: int
    real: float          # real samples, seq gaps filled
    gaps: int            # packets missing by seq_num

    @property
    def rate(self) -> float:
        return self.real / ((self.t1_us - self.t0_us) / 1e6)


@dataclass
class RateStatus:
    rate_all: float | None      # median of all windows, S/s
    rate_recent: float | None   # median of the windows in the last RECENT_S
    padding: float | None       # share of slots that were padding (all)
    padding_recent: float | None
    windows: int
    elapsed_s: float
    lost_packets: int           # by seq_num gaps
    lost_samples: int           # without a seq_num gap (windows below the median)
    loss_windows: int
    alarm: str | None           # mismatch with the setting
    saturated: bool


@dataclass
class RateMeter:
    window_s: float = WINDOW_S
    windows: list = field(default_factory=list)
    _t_first: int | None = None
    _t_last: int | None = None
    _day: int = 0                 # RTC seconds-of-day wraps at midnight
    _w_t0: int | None = None
    _w_real: int = 0
    _w_pkts: int = 0
    _w_gaps: int = 0
    _last_seq: int | None = None
    _slots: deque = field(default_factory=deque)   # (t_us, slots, padding), last RECENT_S
    _slots_total: int = 0
    _pad_total: int = 0

    def add(self, ts_s: int, ts_sub: int, seq: int, num_pairs: int, padding: int) -> None:
        """One packet: header RTC fields, seq_num, slots, padding slots."""
        t = ts_s * 1_000_000 + ts_sub * 1_000 // 32 + self._day
        if self._t_last is not None and t < self._t_last - DAY_US // 2:
            self._day += DAY_US
            t += DAY_US
        gaps = 0
        if self._last_seq is not None:
            gaps = (seq - self._last_seq - 1) % 256
        self._last_seq = seq
        if self._t_first is None:
            self._t_first = t
        self._t_last = t
        self._slots_total += num_pairs
        self._pad_total += padding
        self._slots.append((t, num_pairs, padding))
        while self._slots and t - self._slots[0][0] > RECENT_S * 1e6:
            self._slots.popleft()

        if self._w_t0 is None:
            self._w_t0 = t
        elif t - self._w_t0 >= self.window_s * 1e6:
            # close the window at this packet's time; gaps inside it filled
            # with its mean real samples per packet
            mean = self._w_real / self._w_pkts if self._w_pkts else 0.0
            self.windows.append(Window(self._w_t0, t, self._w_real + mean * self._w_gaps,
                                       self._w_gaps))
            self._w_t0, self._w_real, self._w_pkts, self._w_gaps = t, 0, 0, 0
        self._w_real += num_pairs - padding
        self._w_pkts += 1
        self._w_gaps += gaps

    def status(self, setting_hz: float | None = None) -> RateStatus:
        ws = self.windows
        elapsed = (self._t_last - self._t_first) / 1e6 if self._t_first is not None else 0.0
        rate_all = median(w.rate for w in ws) if ws else None
        recent = [w for w in ws if w.t1_us >= self._t_last - RECENT_S * 1e6] if ws else []
        rate_recent = median(w.rate for w in recent) if recent else None
        lost = 0
        nloss = 0
        if rate_all:
            for w in ws:
                short = rate_all * (w.t1_us - w.t0_us) / 1e6 - w.real
                if short > LOSS_FRAC * w.real:
                    lost += short
                    nloss += 1
        pad = self._pad_total / self._slots_total if self._slots_total else None
        rs = sum(s for _, s, _ in self._slots)
        pad_recent = sum(p for _, _, p in self._slots) / rs if rs else None

        alarm = None
        if setting_hz and rate_all:
            off = rate_all / setting_hz - 1
            tol = (ALARM_LATE_FRAC if elapsed >= ALARM_LATE_S and len(ws) >= 5
                   else ALARM_EARLY_FRAC if elapsed >= ALARM_EARLY_S else None)
            if tol is not None and abs(off) > tol:
                alarm = (f"measured {rate_all:,.0f} S/s, set to {setting_hz:,.0f}: "
                         f"wrong bitstream or wrong setting ({100 * off:+.2f}%)")
        saturated = pad_recent is not None and pad_recent < SATURATED_PADDING and rs > 0
        return RateStatus(rate_all, rate_recent, pad, pad_recent, len(ws), elapsed,
                          sum(w.gaps for w in ws), int(round(lost)), nloss, alarm, saturated)
