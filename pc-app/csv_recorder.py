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
"""

import os
import shutil
import time
from pathlib import Path
from dataclasses import dataclass, field

MAX_DURATION_SEC = 600      # 10 minutes
MIN_FREE_MB      = 200


@dataclass
class RecordingInfo:
    is_recording: bool  = False
    elapsed_sec:  int   = 0
    estimated_mb: int   = 0
    auto_stopped: bool  = False
    file_path:    str   = ""


class CsvRecorder:
    BYTES_PER_ROW = 23   # conservative estimate for MB counter

    def __init__(self):
        self._file = None
        self._start_time  = 0.0
        self._rows_written = 0
        self.info = RecordingInfo()

    def start(self, directory: str = ".") -> str:
        if self.info.is_recording:
            return ""
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = str(Path(directory) / f"vega_{ts}.csv")
        self._file = open(path, "w", buffering=1 << 16)
        self._file.write("timestamp_us,ch0,ch1,seq_num\n")
        self._start_time   = time.time()
        self._rows_written = 0
        self.info = RecordingInfo(is_recording=True, file_path=path)
        return path

    def write_batch(self, timestamps_us, ch0, ch1, seq_num: int) -> bool:
        """Write a batch of samples. Returns False if recording should stop."""
        if not self.info.is_recording or self._file is None:
            return False

        elapsed = int(time.time() - self._start_time)
        self.info.elapsed_sec  = elapsed
        self.info.estimated_mb = self._rows_written * self.BYTES_PER_ROW // (1024 * 1024)

        # Auto-stop checks
        if elapsed >= MAX_DURATION_SEC:
            self.stop(auto_stopped=True)
            return False

        free_mb = shutil.disk_usage(self._file.name).free // (1024 * 1024)
        if free_mb < MIN_FREE_MB:
            self.stop(auto_stopped=True)
            return False

        for t, c0, c1 in zip(timestamps_us, ch0, ch1):
            self._file.write(f"{t},{c0},{c1},{seq_num}\n")
        self._rows_written += len(ch0)
        return True

    def stop(self, auto_stopped: bool = False):
        if not self.info.is_recording:
            return
        if self._file:
            self._file.close()
            self._file = None
        self.info.is_recording = False
        self.info.auto_stopped  = auto_stopped
