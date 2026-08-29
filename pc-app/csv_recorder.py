"""
CSV recorder — PC-app format extends the shared Android format
(timestamp_us,ch0,ch1) with a trailing seq_num column so BLE packet
drops / UART framing resyncs can be correlated against sample-level
gaps after the fact. seq_num is the packet's rolling header byte,
repeated for every row that came from the same packet.

Writes every row verbatim, including FIFO-underrun sentinel samples
(ch0/ch1 == -32768) — analyze_recording.py needs them to measure the
true underrun rate. GraphWidget filters sentinels separately for live
display; this recorder must not also filter them or underrun stats
become unmeasurable after the fact.

Auto-stops at MAX_DURATION_SEC or MIN_FREE_MB free disk space.

Metadata sidecar — docs/interfaces/recording-format.md. Every CSV gets a
same-basename .json sidecar, written in two passes (start()/stop()) so a
crash mid-recording still leaves a sidecar next to a good CSV (only the
stop()-time fields are lost). Both passes write atomically
(tmp file + os.replace) so a crash mid-write never leaves a torn sidecar.
The CSV itself carries a leading '# vega-recording-format-version: 1'
comment line (spec §1a), independent of the sidecar's own format_version.
"""

import json
import os
import shutil
import time
import datetime
from pathlib import Path
from dataclasses import dataclass, field

MAX_DURATION_SEC = 4000     # ~66 minutes
MIN_FREE_MB      = 200

MAX_DURATION_STR = f"{MAX_DURATION_SEC // 60}:{MAX_DURATION_SEC % 60:02d}"

CSV_FORMAT_VERSION = 1
SIDECAR_FORMAT_VERSION = 1


@dataclass
class RecordingInfo:
    is_recording:     bool  = False
    elapsed_sec:       int   = 0
    estimated_mb:      int   = 0
    auto_stopped:      bool  = False
    auto_stop_reason:  str | None = None   # "max_duration" | "low_disk" | None
    file_path:         str   = ""
    sidecar_path:       str   = ""


def _atomic_write_json(path: Path, data: dict) -> None:
    """open(tmp, 'w') -> json.dump() -> close() -> os.replace(tmp, final) —
    a SIGKILL or crash mid-dump must never leave a torn sidecar next to a
    good CSV (spec §1)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CsvRecorder:
    BYTES_PER_ROW = 23   # conservative estimate for MB counter

    def __init__(self):
        self._file = None
        self._sidecar_path: Path | None = None
        self._sidecar_data: dict = {}
        self._start_time  = 0.0
        self._rows_written = 0
        self.info = RecordingInfo()

    def start(self, directory: str = ".", metadata: dict | None = None) -> str:
        """Start a new recording. `metadata` carries everything known at
        start time (sample_rate, gain, channels, filter_settings,
        firmware_version, bitstream_version — see
        docs/interfaces/recording-format.md §2) and is written into the
        sidecar verbatim, alongside format_version/csv_filename/
        recording_started_utc which this method fills in itself."""
        if self.info.is_recording:
            return ""
        ts = time.strftime("%Y%m%d_%H%M%S")
        csv_filename = f"vega_{ts}.csv"
        path = Path(directory) / csv_filename
        sidecar_path = path.with_suffix(".json")

        self._file = open(path, "w", buffering=1 << 16)
        self._file.write(f"# vega-recording-format-version: {CSV_FORMAT_VERSION}\n")
        self._file.write("timestamp_us,ch0,ch1,seq_num\n")
        self._file.flush()   # header must be on disk even if the app dies
        # before the first write_batch() flushes anything else — matches
        # the sidecar's own start()-time write, spec §1's crash-resilience
        # intent extended to the CSV's own header.

        self._sidecar_data = {
            "format_version": SIDECAR_FORMAT_VERSION,
            "csv_filename": csv_filename,
            "recording_started_utc": _utc_now_iso(),
            **(metadata or {}),
        }
        self._sidecar_path = sidecar_path
        _atomic_write_json(sidecar_path, self._sidecar_data)

        self._start_time   = time.time()
        self._rows_written = 0
        self.info = RecordingInfo(
            is_recording=True, file_path=str(path), sidecar_path=str(sidecar_path)
        )
        return str(path)

    def write_batch(self, timestamps_us, ch0, ch1, seq_num: int) -> bool:
        """Write a batch of samples. Returns False if recording should stop."""
        if not self.info.is_recording or self._file is None:
            return False

        elapsed = int(time.time() - self._start_time)
        self.info.elapsed_sec  = elapsed
        self.info.estimated_mb = self._rows_written * self.BYTES_PER_ROW // (1024 * 1024)

        # Auto-stop checks
        if elapsed >= MAX_DURATION_SEC:
            self.stop(auto_stopped=True, auto_stop_reason="max_duration")
            return False

        free_mb = shutil.disk_usage(self._file.name).free // (1024 * 1024)
        if free_mb < MIN_FREE_MB:
            self.stop(auto_stopped=True, auto_stop_reason="low_disk")
            return False

        for t, c0, c1 in zip(timestamps_us, ch0, ch1):
            self._file.write(f"{t},{c0},{c1},{seq_num}\n")
        self._rows_written += len(ch0)
        return True

    def stop(self, auto_stopped: bool = False, auto_stop_reason: str | None = None):
        if not self.info.is_recording:
            return
        duration_sec = time.time() - self._start_time
        if self._file:
            self._file.close()
            self._file = None
        if self._sidecar_path is not None:
            self._sidecar_data.update({
                "recording_stopped_utc": _utc_now_iso(),
                "duration_sec": round(duration_sec, 1),
                "rows_written": self._rows_written,
                "auto_stopped": auto_stopped,
                "auto_stop_reason": auto_stop_reason,
            })
            _atomic_write_json(self._sidecar_path, self._sidecar_data)
        self.info.is_recording      = False
        self.info.auto_stopped       = auto_stopped
        self.info.auto_stop_reason   = auto_stop_reason
