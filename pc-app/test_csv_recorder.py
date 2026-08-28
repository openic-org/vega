"""Offline checks for CsvRecorder's sidecar (docs/interfaces/recording-format.md)
and analyze_recording.py's dynamic skiprows detection (spec §1a). No hardware,
no Qt — pure filesystem/JSON checks against a scratch directory.

    python3 test_csv_recorder.py
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import csv_recorder as R
from analyze_recording import compute_stats

SAMPLE_METADATA = {
    "sample_rate": {"config": "2ch_v1", "channel_hz": 29999.97, "source": "test"},
    "gain": {"amplifier_uv_per_lsb": 0.195, "source": "test"},
    "channels": {"ch_a": 3, "ch_b": 5, "provenance": "verified_readback"},
    "filter_settings": {"registers": None, "provenance": "unknown"},
    "firmware_version": "unknown",
    "bitstream_version": "unknown",
}


def read_sidecar(csv_path: str) -> dict:
    p = Path(csv_path).with_suffix(".json")
    with open(p) as f:
        return json.load(f)


print("=" * 70)

with tempfile.TemporaryDirectory() as d:
    rec = R.CsvRecorder()
    path = rec.start(d, metadata=SAMPLE_METADATA)
    assert path, "start() should return a path"

    # No .tmp file left behind after the atomic write.
    assert not list(Path(d).glob("*.tmp")), "atomic write left a .tmp file"

    sc = read_sidecar(path)
    assert sc["format_version"] == R.SIDECAR_FORMAT_VERSION
    assert sc["csv_filename"] == Path(path).name
    assert sc["channels"] == SAMPLE_METADATA["channels"]
    assert sc["sample_rate"]["channel_hz"] == 29999.97
    assert "recording_started_utc" in sc
    assert "recording_stopped_utc" not in sc, "stop-time fields must not appear before stop()"
    print(f"start(): sidecar written, fields present: {sorted(sc.keys())}")

    with open(path) as f:
        first_line = f.readline()
        header_line = f.readline()
    assert first_line == f"# vega-recording-format-version: {R.CSV_FORMAT_VERSION}\n", first_line
    assert header_line == "timestamp_us,ch0,ch1,seq_num\n", header_line
    print("CSV version comment + header line OK")

    rec.write_batch([100, 200, 300], [1, 2, 3], [4, 5, 6], seq_num=7)
    rec.stop(auto_stopped=True, auto_stop_reason="low_disk")

    assert not list(Path(d).glob("*.tmp")), "stop()'s atomic rewrite left a .tmp file"
    sc = read_sidecar(path)
    assert sc["auto_stopped"] is True
    assert sc["auto_stop_reason"] == "low_disk"
    assert sc["rows_written"] == 3
    assert "recording_stopped_utc" in sc and "duration_sec" in sc
    # start()-time fields must survive the stop()-time rewrite, not be lost.
    assert sc["channels"] == SAMPLE_METADATA["channels"]
    print(f"stop(): sidecar rewritten with {sorted(set(sc) - set(SAMPLE_METADATA) - {'format_version', 'csv_filename', 'recording_started_utc'})}")

print("-" * 70)

# auto_stop_reason plumbing at both write_batch() call sites.
with tempfile.TemporaryDirectory() as d:
    rec = R.CsvRecorder()
    rec.start(d, metadata=SAMPLE_METADATA)
    saved = R.MAX_DURATION_SEC
    rec._start_time = time.time() - (saved + 1)   # force elapsed >= MAX_DURATION_SEC
    ok = rec.write_batch([1], [1], [1], seq_num=0)
    assert ok is False
    assert rec.info.auto_stop_reason == "max_duration", rec.info.auto_stop_reason
    print("write_batch(): max_duration auto-stop reason OK")

with tempfile.TemporaryDirectory() as d:
    rec = R.CsvRecorder()
    rec.start(d, metadata=SAMPLE_METADATA)
    real_disk_usage = shutil.disk_usage
    shutil.disk_usage = lambda _: real_disk_usage(d)._replace(free=0)
    try:
        ok = rec.write_batch([1], [1], [1], seq_num=0)
    finally:
        shutil.disk_usage = real_disk_usage
    assert ok is False
    assert rec.info.auto_stop_reason == "low_disk", rec.info.auto_stop_reason
    print("write_batch(): low_disk auto-stop reason OK")

print("-" * 70)

# analyze_recording.py: dynamic skiprows, both with and without the new
# version comment line — every pre-A.6.5 recording must still parse.
with tempfile.TemporaryDirectory() as d:
    versioned = Path(d) / "vega_versioned.csv"
    versioned.write_text(
        "# vega-recording-format-version: 1\n"
        "timestamp_us,ch0,ch1,seq_num\n"
        "0,1,2,0\n100,3,4,0\n200,5,6,0\n"
    )
    s = compute_stats(versioned)
    assert s["n"] == 3 and s["has_seq"] is True
    print("compute_stats(): versioned CSV parses (skiprows=2)")

    legacy = Path(d) / "vega_legacy.csv"
    legacy.write_text("timestamp_us,ch0,ch1\n0,1,2\n100,3,4\n200,5,6\n")
    s = compute_stats(legacy)
    assert s["n"] == 3 and s["has_seq"] is False
    print("compute_stats(): pre-A.6.5 (unversioned) CSV still parses unchanged (skiprows=1)")

print("=" * 70)
print("ALL CSV RECORDER / SIDECAR CHECKS PASSED")
