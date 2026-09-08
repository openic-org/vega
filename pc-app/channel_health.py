"""
Per-channel liveness detection — the RHD2164 "chip stopped responding" fault.

**Why this exists.** On 2026-09-08 chip0 was observed to fail ~2 minutes into
a session and recover spontaneously ~88 minutes later, board powered and
streaming throughout (`log/chip0-temperature-trials.md`). The fault is not a
boot-time coin flip: it **cycles while running**. A recording that straddles a
transition loses a channel partway through, silently, gets it back, and nothing
in the system notices.

That is an experiment-integrity problem rather than a bench annoyance — the
animal test is one-shot — so the pc-app has to notice on its own. A pre-session
self-test is insufficient by construction: it would pass and the channel could
still vanish twenty minutes later.

**The signature.** A non-responding RHD2164 leaves MISO undriven, so every bit
reads 1 and the sample decodes as `0xFFFF` = −1. On the graph that is a flat
trace at essentially zero (−1 LSB ≈ −0.2 µV), which is easy to mistake for a
quiet channel — the whole reason it went unnoticed for weeks.

**Underrun samples are neutral, not alive.** When the FPGA FIFO runs dry both
channels read `0x8000`, and after the A.7 PLL retune that is expected on ~5%
of samples by design (λ < µ). Those samples carry no information about whether
a chip is responding, so they are **excluded** from the runs rather than
counted as evidence of life — without this, a 5% sprinkle of sentinels would
reset the dead-run counter forever and the detector would never fire against
exactly the configuration the project is moving to. The underrun rule is
imported from `packet_parser` rather than restated, per the single-sourcing
note there.

**Hysteresis is asymmetric, and the two directions are not even the same kind
of rule.** Dead requires a long *continuous* run of −1, because that is what a
stuck MISO line actually produces and a real signal cannot sustain it. Alive
requires only a handful of non-−1 samples, because **a single sample that is
not −1 is positive proof the chip is driving MISO** — nothing else can produce
one. Making the alive side a duration was the first implementation's bug: a
noisy signal that touches −1 once per packet resets a consecutive-alive
counter forever, so a perfectly healthy channel would have sat at `unknown`
indefinitely. Caught by the first test written against it.
"""

from dataclasses import dataclass, field
import datetime

import numpy as np

from packet_parser import is_fifo_underrun

# 0xFFFF as int16. An RHD2164 that is not driving MISO reads as all ones.
DEAD_VALUE = -1

# Declare dead only after this much *continuous* evidence, so a real signal
# passing through −1 cannot trip it. At 28 kSPS this is ~7,000 samples.
DEAD_ENTER_SEC = 0.25
# Declare alive again after this many non-dead samples. A COUNT, not a
# duration: any sample that is not −1 already proves the chip is driving MISO,
# so this only needs to be large enough that a single corrupted read cannot
# flap the state. Keeping it small also timestamps the recovery edge tightly,
# which the 2026-09-08 episode showed is the harder edge to catch.
ALIVE_ENTER_SAMPLES = 16

ALIVE = "alive"
DEAD = "dead"
UNKNOWN = "unknown"


@dataclass
class HealthTransition:
    """One state change, timestamped at the sample where it actually began —
    not where it was noticed, which is up to DEAD_ENTER_SEC later."""
    channel: str                      # "ch0" | "ch1"
    to_state: str                     # ALIVE | DEAD
    sample_timestamp_us: int
    wall_time_utc: str
    prior_state_duration_s: float | None   # None for the first transition


@dataclass
class _ChannelRuns:
    state: str = UNKNOWN
    dead_run: int = 0
    alive_run: int = 0
    state_since_us: int | None = None
    dropouts: int = 0
    total_dead_us: int = 0


class ChannelHealthMonitor:
    """Feed it every batch; it reports state changes.

    Deliberately Qt-free and numpy-only so it can be tested without a UI and
    reused by offline analysis of an existing recording.
    """

    def __init__(self, sample_rate_hz: int,
                 dead_enter_sec: float = DEAD_ENTER_SEC,
                 alive_enter_samples: int = ALIVE_ENTER_SAMPLES):
        self._step_us = 1_000_000 / sample_rate_hz
        self._dead_enter = max(1, int(dead_enter_sec * sample_rate_hz))
        self._alive_enter = max(1, int(alive_enter_samples))
        self._ch = {"ch0": _ChannelRuns(), "ch1": _ChannelRuns()}
        self.transitions: list[HealthTransition] = []

    # ── queries ───────────────────────────────────────────────────────────
    def state(self, channel: str) -> str:
        return self._ch[channel].state

    def dropouts(self, channel: str) -> int:
        """Times this channel has gone dead since reset. Sticky: a channel that
        died and recovered is not the same as one that never died, and the
        distinction is what a recording needs to carry."""
        return self._ch[channel].dropouts

    def dead_seconds(self, channel: str, now_us: int | None = None) -> float:
        """Cumulative time dead, including the current episode if still dead."""
        c = self._ch[channel]
        total = c.total_dead_us
        if c.state == DEAD and c.state_since_us is not None and now_us is not None:
            total += max(0, now_us - c.state_since_us)
        return total / 1_000_000.0

    def any_dropouts(self) -> bool:
        return any(c.dropouts for c in self._ch.values())

    def summary(self, now_us: int | None = None) -> dict:
        """Compact dict for the recording sidecar — see
        docs/interfaces/recording-format.md §2.2."""
        return {
            "detector_version": 1,
            "dead_value": DEAD_VALUE,
            "dead_enter_sec": self._dead_enter * self._step_us / 1_000_000.0,
            "channels": {
                name: {
                    "state": c.state,
                    "dropouts": c.dropouts,
                    "dead_seconds": round(self.dead_seconds(name, now_us), 3),
                }
                for name, c in self._ch.items()
            },
            "transitions": [
                {
                    "channel": t.channel,
                    "to_state": t.to_state,
                    "sample_timestamp_us": int(t.sample_timestamp_us),
                    "wall_time_utc": t.wall_time_utc,
                    "prior_state_duration_s": t.prior_state_duration_s,
                }
                for t in self.transitions
            ],
        }

    def reset(self) -> None:
        for c in self._ch.values():
            c.__init__()          # type: ignore[misc]
        self.transitions.clear()

    # ── the hot path ──────────────────────────────────────────────────────
    def update(self, ch0: np.ndarray, ch1: np.ndarray,
               timestamps_us: np.ndarray) -> list[HealthTransition]:
        """Consume one packet. Returns any state changes it caused.

        Called at ~475 packets/s, so this stays numpy-vectorised and allocates
        nothing per sample.
        """
        if len(ch0) == 0 or len(ch0) != len(ch1) or len(timestamps_us) != len(ch0):
            return []

        # Underruns say nothing about chip liveness — drop them from both
        # channels' evidence (see the module docstring).
        keep = ~is_fifo_underrun(ch0, ch1)
        if not keep.any():
            return []

        out: list[HealthTransition] = []
        last_ts = int(timestamps_us[-1])
        for name, values in (("ch0", ch0), ("ch1", ch1)):
            t = self._update_one(name, values[keep], last_ts)
            if t is not None:
                out.append(t)
                self.transitions.append(t)
        return out

    def _update_one(self, name: str, values: np.ndarray,
                    last_ts_us: int) -> HealthTransition | None:
        c = self._ch[name]
        is_dead = values == DEAD_VALUE
        n = len(values)

        # Extend or reset the trailing runs. Only the trailing run matters:
        # a state change is only real if it is still true at the end of the
        # batch, and anything earlier has already been accounted for.
        if is_dead.all():
            c.dead_run += n
            c.alive_run = 0
        elif not is_dead.any():
            c.alive_run += n
            c.dead_run = 0
        else:
            last_alive = int(np.flatnonzero(~is_dead)[-1])
            last_dead = int(np.flatnonzero(is_dead)[-1])
            c.dead_run = n - 1 - last_alive
            c.alive_run = n - 1 - last_dead

        if c.state != DEAD and c.dead_run >= self._dead_enter:
            return self._transition(c, name, DEAD, last_ts_us, c.dead_run)
        if c.state != ALIVE and c.alive_run >= self._alive_enter:
            return self._transition(c, name, ALIVE, last_ts_us, c.alive_run)
        return None

    def _transition(self, c: _ChannelRuns, name: str, to_state: str,
                    last_ts_us: int, run_len: int) -> HealthTransition:
        # Backdate to where the run actually started, not where the threshold
        # was crossed — otherwise every timestamp is late by DEAD_ENTER_SEC and
        # correlating a dropout against a stall or a command becomes guesswork.
        began_us = int(last_ts_us - run_len * self._step_us)

        prior = None
        if c.state_since_us is not None:
            prior = round((began_us - c.state_since_us) / 1_000_000.0, 3)
        if c.state == DEAD and c.state_since_us is not None:
            c.total_dead_us += max(0, began_us - c.state_since_us)
        if to_state == DEAD:
            c.dropouts += 1

        c.state = to_state
        c.state_since_us = began_us
        return HealthTransition(
            channel=name,
            to_state=to_state,
            sample_timestamp_us=began_us,
            wall_time_utc=datetime.datetime.now(
                datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            prior_state_duration_s=prior,
        )
