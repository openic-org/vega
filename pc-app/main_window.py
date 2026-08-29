"""
MainWindow — top-level PyQt6 window for the Vega PC app.
"""

import csv
import datetime
import time
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QGroupBox, QGridLayout,
    QFileDialog, QStatusBar, QSpinBox, QFrame,
)
from PyQt6.QtGui import QFont, QPixmap

from serial_reader import SerialReader
from graph_widget  import GraphWidget
from csv_recorder  import CsvRecorder, MAX_DURATION_STR
from diagnostics   import RUNGS, RungRunner, FilterSettingsReader, RawChannelSetter
import channel_mapping
import rhd2164_units

RECORDINGS_DIR = Path(__file__).parent / "recordings"
BENCH_DIR      = Path(__file__).parent / "bench"
LOGO_PATH      = Path(__file__).parent / "assets" / "openic_logo.png"
DEFAULT_PORT   = "/dev/ttyACM1"

# The real chip/module split (docs/interfaces/channel-selection-control-plane.md
# §1a) is 4-way (0-31/32-63/64-95/96-127, module A/B within each chip), but
# the Intan datasheet numbers each chip's 64 channels as one block and the
# operator doesn't need the module split — 2026-08-28 decision.
CHIP_RANGE_TEXT = "Chip 0: channels 0-63   •   Chip 1: channels 64-127"

# Measured at ~4 500 SPS with current CI (~13 ms). Update when CI is tightened to 7.5 ms.
DELIVERED_SPS = 5_000

# FPGA production rate, per-channel, current firmware — see
# docs/interfaces/stream-packet-format.md §1.1 (2026-08-27 PLL retune).
# Recorded into every sidecar's sample_rate.channel_hz (see
# _build_sidecar_metadata below). PLAN.md A.7 step 3 is expected to set
# the actual streaming rate below this deliberately (rate margin) — update
# this constant when that lands, not before.
SAMPLE_RATE_CHANNEL_HZ = 29_999.97

# How long to wait for a real STOP_STREAMING/START_STREAMING acknowledgment
# (section 5.6) before giving up and proceeding anyway — same reasoning as
# the existing SET_CHANNELS readback timeout below. Once section 5.6 landed,
# this replaced fixed settle delays as the primary gate between steps: a
# real ack already proves the previous command was relayed and processed,
# so no artificial spacing is needed on the success path.
STREAMING_ACK_TIMEOUT_MS = 2000

# Minimum pause after a full Apply cycle completes before the button
# re-enables — a real, separate gap from the settle delays above. Found
# 2026-08-06: START_STREAMING is fire-and-forget (no confirmation the MCU
# actually finished), so the button was re-enabling the instant the bytes
# were sent, letting a human sustain close to 1 cycle/second by clicking at
# a normal pace. That rate matched a repeating MCU crash/reset loop observed
# in bench testing under rapid clicking. This cooldown makes that rate
# physically impossible to sustain, independent of whatever the underlying
# cause turns out to be (scoped as a known limitation for now, not chased
# further — see PLAN.md A.2).
APPLY_COOLDOWN_MS = 1000

# Small deliberate gap between receiving an ack and firing the next command
# in the STOP/SET/START sequence. Found 2026-08-06: sending the next command
# the instant an ack arrives (zero gap, the whole point of the ack-driven
# redesign) means it lands right as the bridge is still busy processing/
# relaying the GATT notification event for the ack it just sent — a window
# where its UART RX ISR can be delayed long enough to overrun at 2 Mbaud
# (~5 us/byte), silently corrupting the in-flight command (see the bridge's
# new ORE handling in stm32wb0x_it.c). This costs a few ms of latency to
# reduce how often that collision happens; it doesn't replace the ORE fix,
# which already makes any single loss self-healing rather than fatal.
COMMAND_GAP_MS = 15


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vega — PC Data Viewer")
        self.resize(1200, 700)

        self._reader   = SerialReader(self)
        self._recorder = CsvRecorder()
        self._rate_ts   = 0.0
        self._rate_pkts = 0
        self._drops_prev = 0      # drops seen at previous status update
        self._total_underruns = 0 # cumulative FPGA FIFO underrun samples

        # SET_CHANNELS readback verification (section 4) — the pair we're
        # waiting to see echoed back on 0xFFF3, or None if nothing pending.
        self._pending_channels: tuple[int, int] | None = None
        self._verify_timer = QTimer(self)
        self._verify_timer.setSingleShot(True)
        self._verify_timer.setInterval(2000)
        self._verify_timer.timeout.connect(self._on_verify_timeout)

        # STOP_STREAMING/START_STREAMING real-ack waits (section 5.6) — each
        # flag is True only while genuinely waiting for that specific ack, so
        # a stale/unsolicited one (or a timeout firing after the ack already
        # arrived) is a harmless no-op, same pattern as _pending_channels above.
        self._awaiting_stop_ack = False
        self._awaiting_start_ack = False
        self._stop_ack_timer = QTimer(self)
        self._stop_ack_timer.setSingleShot(True)
        self._stop_ack_timer.setInterval(STREAMING_ACK_TIMEOUT_MS)
        self._stop_ack_timer.timeout.connect(self._on_stop_ack_timeout)
        self._start_ack_timer = QTimer(self)
        self._start_ack_timer.setSingleShot(True)
        self._start_ack_timer.setInterval(STREAMING_ACK_TIMEOUT_MS)
        self._start_ack_timer.timeout.connect(self._on_start_ack_timeout)

        # Channel values captured at the moment Apply is clicked, carried
        # through the STOP/SET/START sequence (section 5) via QTimer.singleShot
        # callbacks — captured once up front so a spinbox edit mid-sequence
        # doesn't change what actually gets sent.
        self._apply_ch_a = 0
        self._apply_ch_b = 0
        self._is_connected = False

        # Recording-metadata sidecar state — docs/interfaces/recording-format.md
        # §2.1. "unknown" until a real hardware confirmation lands; a change in
        # flight (Apply clicked, Get Settings running) downgrades to
        # "unverified_requested"/stays "unknown" rather than keeping a stale
        # verified value.
        self._channels_state = {"ch_a": None, "ch_b": None, "provenance": "unknown"}
        self._filter_settings_state = {"registers": None, "provenance": "unknown"}

        self._filter_settings_reader = FilterSettingsReader(self._reader, self)
        self._filter_settings_reader.progress.connect(self._on_get_settings_progress)
        self._filter_settings_reader.finished.connect(self._on_get_settings_finished)
        self._filter_settings_reader.failed.connect(self._on_get_settings_failed)
        self._get_settings_orig: tuple[int, int] | None = None

        # channel_mapping.py's offset compensation (docs/interfaces/
        # channel-selection-control-plane.md §1a-addendum) — 4 of 128
        # physical channels can't be expressed via SET_CHANNELS's friendly
        # index and need a direct REG_WRITE16 on REG_CH_A/REG_CH_B instead.
        self._raw_channel_setter = RawChannelSetter(self._reader, self)
        self._raw_channel_setter.finished.connect(self._on_raw_channels_set)
        self._raw_channel_setter.failed.connect(self._on_raw_channels_failed)

        # GPIO bench logging — opened on BLE connect, closed on disconnect
        self._bench_log: "csv.writer | None" = None
        self._bench_file = None
        self._bench_start = 0.0
        self._bench_path = ""

        self._build_ui()
        self._update_graph_titles()   # "Channel —" initial state, replacing the static "CH0"/"CH1" default
        self._connect_signals()

        # Rate + recording update timer
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(2000)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start()

        self._refresh_ports()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        root.addLayout(self._build_controls())
        root.addLayout(self._build_channel_controls())
        root.addWidget(self._build_debug_panel())
        root.addWidget(self._build_diagnostics_panel())
        self._graph = GraphWidget(DELIVERED_SPS)
        root.addWidget(self._graph, stretch=1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Disconnected")

    def _build_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)

        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(160)
        row.addWidget(QLabel("Port:"))
        row.addWidget(self._port_combo)

        self._btn_refresh = QPushButton("↻")
        self._btn_refresh.setFixedWidth(32)
        self._btn_refresh.clicked.connect(self._refresh_ports)
        row.addWidget(self._btn_refresh)

        self._btn_connect = QPushButton("Connect")
        self._btn_connect.setCheckable(True)
        row.addWidget(self._btn_connect)

        self._btn_rec = QPushButton("● REC")
        self._btn_rec.setCheckable(True)
        self._btn_rec.setEnabled(False)
        row.addWidget(self._btn_rec)

        self._lbl_rec_path = QLabel("")
        self._lbl_rec_path.setStyleSheet("color: #B71C1C; font-size: 11px;")
        row.addWidget(self._lbl_rec_path, stretch=1)

        row.addWidget(self._build_logo_label())

        return row

    def _build_logo_label(self) -> QLabel:
        """openIC wordmark, top-right. Full-color on transparency (navy/red/
        grey, pixel-verified), so unlike the previous icon-only mark it
        reads fine directly against this app's light background — no
        backdrop needed, just scaled to a fixed height."""
        label = QLabel()
        logo = QPixmap(str(LOGO_PATH))
        if not logo.isNull():
            logo = logo.scaledToHeight(
                28, Qt.TransformationMode.SmoothTransformation)
            label.setPixmap(logo)
        return label

    def _build_channel_controls(self) -> QHBoxLayout:
        """Minimal channel selection — two friendly-index (0-127) spinboxes +
        Apply, per docs/interfaces/channel-selection-control-plane.md
        (explicit Phase-A UI scope, polished UI is Phase B)."""
        row = QHBoxLayout()
        row.setSpacing(6)

        row.addWidget(QLabel("Ch A:"))
        self._spin_ch_a = QSpinBox()
        self._spin_ch_a.setRange(0, 127)
        self._spin_ch_a.setValue(0)
        self._spin_ch_a.setToolTip(CHIP_RANGE_TEXT)
        row.addWidget(self._spin_ch_a)

        row.addWidget(QLabel("Ch B:"))
        self._spin_ch_b = QSpinBox()
        self._spin_ch_b.setRange(0, 127)
        self._spin_ch_b.setValue(1)
        self._spin_ch_b.setToolTip(CHIP_RANGE_TEXT)
        row.addWidget(self._spin_ch_b)

        self._btn_apply_channels = QPushButton("Apply")
        self._btn_apply_channels.setEnabled(False)
        self._btn_apply_channels.clicked.connect(self._apply_channels)
        row.addWidget(self._btn_apply_channels)

        self._lbl_verify = QLabel("")
        self._lbl_verify.setStyleSheet("font-size: 11px;")
        row.addWidget(self._lbl_verify)

        # Extra fixed spacing on both sides of the divider — the default
        # layout spacing alone (row.setSpacing(6)) looked lopsided next to
        # _lbl_verify's variable-width text, so the gap is padded out
        # explicitly instead of relying on a label's width to provide it.
        row.addSpacing(12)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        row.addWidget(divider)
        row.addSpacing(12)

        # "Get Settings" — docs/interfaces/recording-format.md §2.1/§2.1a.
        # Reads the RHD2164 filter/bandwidth registers for the sidecar.
        # Operator-triggered, not automatic, because it briefly stops
        # streaming and repoints ch_a at the FPGA's command slot before
        # restoring the operator's own channels — same STOP/act/restore/
        # START shape as Apply, just for a read instead of a write.
        self._btn_get_settings = QPushButton("Get Settings")
        self._btn_get_settings.setEnabled(False)
        self._btn_get_settings.clicked.connect(self._get_filter_settings)
        row.addWidget(self._btn_get_settings)

        self._lbl_settings = QLabel("")
        self._lbl_settings.setStyleSheet("font-size: 11px;")
        row.addWidget(self._lbl_settings)

        row.addStretch(1)
        return row

    def _build_diagnostics_panel(self) -> QGroupBox:
        """A.1.1 verification ladder — docs/interfaces/fpga-diagnostic-access.md §4.2.

        Checkable and unchecked by default. The register console underneath has
        no write protection (matching the RTL), so it can corrupt the RHD
        config table and leave the sampling cycle issuing nonsense until the
        FPGA is reset. Gating it behind a deliberate click is the mitigation;
        an FPGA reset is the documented recovery.
        """
        box = QGroupBox("Diagnostics — A.1.1 verification ladder")
        box.setCheckable(True)
        box.setChecked(False)
        box.toggled.connect(self._on_diagnostics_toggled)

        row = QHBoxLayout(box)
        row.addWidget(QLabel("Rung:"))

        self._combo_rung = QComboBox()
        # Insertion order, not sorted() — RUNGS is declared in running order
        # (link, then offset, then a-d), and that dependency is real: (a)-(d)
        # are not interpretable until L and O have passed.
        for key, rung in RUNGS.items():
            self._combo_rung.addItem(rung.title, key)
        row.addWidget(self._combo_rung)

        self._btn_run_rung = QPushButton("Run")
        self._btn_run_rung.clicked.connect(self._run_rung)
        row.addWidget(self._btn_run_rung)

        self._lbl_rung = QLabel("idle")
        self._lbl_rung.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self._lbl_rung, stretch=1)

        self._rung_runner = RungRunner(self._reader, self)
        self._rung_runner.progress.connect(self._on_rung_progress)
        self._rung_runner.finished.connect(self._on_rung_finished)
        self._rung_runner.failed.connect(self._on_rung_failed)

        box.setEnabled(True)
        self._diag_box = box
        return box

    def _on_diagnostics_toggled(self, on: bool) -> None:
        if not on:
            self._rung_runner.abort("diagnostics panel closed")
            self._lbl_rung.setText("idle")

    def _run_rung(self) -> None:
        key = self._combo_rung.currentData()
        rung = RUNGS[key]
        if not self._rung_runner.run(key):
            self._lbl_rung.setText("busy — a rung is already running")
            return
        self._btn_run_rung.setEnabled(False)
        self._btn_apply_channels.setEnabled(False)
        self._btn_get_settings.setEnabled(False)
        print(f"\n=== {rung.title} ===\n{rung.note}\n")

    def _on_rung_progress(self, line: str) -> None:
        self._lbl_rung.setText(line.strip())
        print(line)

    def _on_rung_finished(self, key: str, results: list, all_passed: bool) -> None:
        self._btn_run_rung.setEnabled(True)
        self._btn_apply_channels.setEnabled(True)
        self._btn_get_settings.setEnabled(self._is_connected)
        verdicts = [r for r in results if not getattr(r, "info", False)]
        if not verdicts:
            summary = f"rung {key}: {len(results)} measurements recorded — read the console"
        else:
            n_ok = sum(1 for r in verdicts if r.ok)
            summary = f"rung {key}: {n_ok}/{len(verdicts)} observations passed"
        if all_passed:
            self._lbl_rung.setText(f"✓ {summary}")
            self._lbl_rung.setStyleSheet("color: #2e7d32;")
        else:
            self._lbl_rung.setText(f"✗ {summary} — see console")
            self._lbl_rung.setStyleSheet("color: #c62828;")
            hints = RUNGS[key].diagnosis
            if hints:
                print("\nDiagnosis — match the observed values against:")
                for symptom, meaning in hints.items():
                    print(f"  {symptom:<28} {meaning}")
        print(f"\n{summary}\n")

    def _on_rung_failed(self, key: str, reason: str) -> None:
        self._btn_run_rung.setEnabled(True)
        self._btn_apply_channels.setEnabled(True)
        self._btn_get_settings.setEnabled(self._is_connected)
        self._lbl_rung.setText(f"✗ rung {key} aborted: {reason}")
        self._lbl_rung.setStyleSheet("color: #c62828;")
        print(f"\nrung {key} ABORTED: {reason}")
        print("The rung's restore step may not have run. An FPGA reset "
              "restores every default unconditionally.\n")

    def _build_debug_panel(self) -> QGroupBox:
        box = QGroupBox("Debug Info")
        box.setMaximumHeight(90)
        outer = QHBoxLayout(box)

        def lbl(text, bold=False):
            l = QLabel(text)
            if bold:
                f = l.font(); f.setBold(True); l.setFont(f)
            l.setStyleSheet("font-size: 11px;")
            return l

        # Channel map — which chip each channel range belongs to. Its own
        # column, to the left of the rate/status grid, inside the same
        # Debug Info box.
        chan_col = QVBoxLayout()
        chan_col.setSpacing(2)
        chan_col.addWidget(lbl("Chip 0: channels 0-63"))
        chan_col.addWidget(lbl("Chip 1: channels 64-127"))
        chan_col.addStretch(1)
        outer.addLayout(chan_col)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        outer.addWidget(divider)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(2)
        outer.addLayout(grid, stretch=1)

        # Left column
        grid.addWidget(lbl("Status:"),   0, 0)
        grid.addWidget(lbl("Packets:"),  1, 0)
        grid.addWidget(lbl("Dropped:"),  2, 0)

        self._lbl_status  = lbl("—")
        self._lbl_packets = lbl("—")
        self._lbl_dropped = lbl("—")
        grid.addWidget(self._lbl_status,  0, 1)
        grid.addWidget(self._lbl_packets, 1, 1)
        grid.addWidget(self._lbl_dropped, 2, 1)

        # Right column
        grid.addWidget(lbl("Rate:"),       0, 2)
        grid.addWidget(lbl("Throughput:"), 1, 2)
        grid.addWidget(lbl("Underruns:"),  2, 2)

        self._lbl_rate  = lbl("—")
        self._lbl_thru  = lbl("—")
        self._lbl_underruns = lbl("—")
        grid.addWidget(self._lbl_rate,       0, 3)
        grid.addWidget(self._lbl_thru,       1, 3)
        grid.addWidget(self._lbl_underruns,  2, 3)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return box

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _connect_signals(self):
        self._btn_connect.clicked.connect(self._toggle_connection)
        self._btn_rec.clicked.connect(self._toggle_recording)
        self._reader.batch_received.connect(self._on_batch)
        self._reader.connection_changed.connect(self._on_connection_changed)
        self._reader.error.connect(self._on_error)
        self._reader.channels_readback.connect(self._on_channels_readback)
        self._reader.stop_streaming_ack.connect(self._on_stop_ack)
        self._reader.start_streaming_ack.connect(self._on_start_ack)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _refresh_ports(self):
        current = self._port_combo.currentText()
        self._port_combo.clear()
        ports = SerialReader.list_ports()
        self._port_combo.addItems(ports)
        if current in ports:
            self._port_combo.setCurrentText(current)
        elif DEFAULT_PORT in ports:
            self._port_combo.setCurrentText(DEFAULT_PORT)

    def _toggle_connection(self, checked: bool):
        if checked:
            port = self._port_combo.currentText()
            if not port:
                self._btn_connect.setChecked(False)
                self.statusBar().showMessage("No port selected")
                return
            self._reader.set_port(port)
            self._reader.start()
            self._btn_connect.setText("Disconnect")
        else:
            self._reader.stop()
            self._btn_connect.setText("Connect")

    def _toggle_recording(self, checked: bool):
        if checked:
            RECORDINGS_DIR.mkdir(exist_ok=True)
            path = self._recorder.start(str(RECORDINGS_DIR), metadata=self._build_sidecar_metadata())
            self._btn_rec.setText("■ Stop")
            self._lbl_rec_path.setText(f"Recording → {path}")
        else:
            self._recorder.stop()
            self._btn_rec.setText("● REC")
            info = self._recorder.info
            reason = f"  ({info.auto_stop_reason})" if info.auto_stop_reason else ""
            self._lbl_rec_path.setText(
                f"Saved  {info.elapsed_sec}s  ~{info.estimated_mb} MB{reason}  → {info.file_path}"
            )

    def _build_sidecar_metadata(self) -> dict:
        """Everything known at recording-start() time, per
        docs/interfaces/recording-format.md §2. firmware_version/
        bitstream_version are genuinely not obtainable yet (spec §5) — do
        not infer them from git state, they must read "unknown" literally
        until PLAN.md B.5/B.6 land."""
        return {
            "sample_rate": {
                "config": "2ch_v1",
                "channel_hz": SAMPLE_RATE_CHANNEL_HZ,
                "source": (
                    "docs/interfaces/stream-packet-format.md §1.1 — "
                    "2026-08-27 PLL retune. Will be revised after "
                    "PLAN.md A.7 step 3 sets the rate margin; the actual "
                    "streaming rate is expected to land below this figure "
                    "deliberately."
                ),
            },
            "gain": {
                "amplifier_uv_per_lsb": rhd2164_units.AMPLIFIER_UV_PER_LSB,
                "source": (
                    "Intan_RHD2000_series_datasheet.pdf, page 6, table "
                    "'Electrical Characteristics', symbol V_LSB, row "
                    "'referred to amplifier input'. Confirmed by Manuel "
                    "2026-08-27 (PLAN.md A.6.2, DECISION 1). Applies to "
                    "CH0/CH1 as amplifier channels, which is what "
                    "SET_CHANNELS selects in normal operation -- see "
                    "pc-app/rhd2164_units.py for the auxiliary-input and "
                    "supply-sensor step sizes, not used by this field."
                ),
            },
            "channels": dict(self._channels_state),
            "filter_settings": dict(self._filter_settings_state),
            "firmware_version": "unknown",
            "bitstream_version": "unknown",
        }

    def _on_batch(self, packet):
        self._total_underruns += packet.fifo_underruns
        self._graph.add_batch(packet.timestamps_us, packet.ch0, packet.ch1)

        # CSV
        if self._recorder.info.is_recording:
            ok = self._recorder.write_batch(
                packet.timestamps_us, packet.ch0, packet.ch1, packet.header.seq_num
            )
            if not ok and self._recorder.info.auto_stopped:
                self._btn_rec.setChecked(False)
                self._toggle_recording(False)

    def _on_connection_changed(self, connected: bool, port: str):
        self._is_connected = connected
        if connected:
            self._lbl_status.setText(f"Connected ({port})")
            self._lbl_status.setStyleSheet("font-size: 11px; color: green;")
            self._btn_rec.setEnabled(True)
            self._btn_apply_channels.setEnabled(True)
            self._btn_get_settings.setEnabled(True)
            self._graph.clear()
            self._rate_ts         = time.time()
            self._rate_pkts       = 0
            self._total_underruns = 0
            self.statusBar().showMessage(f"Connected on {port}")
            # Open bench log for this session
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            BENCH_DIR.mkdir(exist_ok=True)
            self._bench_path = str(BENCH_DIR / f"bench_{ts}.csv")
            self._bench_file = open(self._bench_path, "w", newline="")
            self._bench_log  = csv.writer(self._bench_file)
            self._bench_log.writerow(["elapsed_s", "kbps", "pps"])
            self._bench_start = time.time()
        else:
            self._lbl_status.setText("Disconnected")
            self._lbl_status.setStyleSheet("font-size: 11px; color: gray;")
            self._btn_rec.setEnabled(False)
            self._btn_apply_channels.setEnabled(False)
            self._btn_get_settings.setEnabled(False)
            self._verify_timer.stop()
            self._pending_channels = None
            self._stop_ack_timer.stop()
            self._start_ack_timer.stop()
            self._awaiting_stop_ack = False
            self._awaiting_start_ack = False
            self._lbl_verify.setText("")
            self._lbl_settings.setText("")
            self._filter_settings_reader.abort("disconnected")
            self._raw_channel_setter.abort("disconnected")
            # A different device (or the same one power-cycled) may be on
            # the other end of the next connect — last-known state doesn't
            # carry over, same reasoning as _pending_channels above.
            self._channels_state = {"ch_a": None, "ch_b": None, "provenance": "unknown"}
            self._filter_settings_state = {"registers": None, "provenance": "unknown"}
            self._update_graph_titles()
            if self._recorder.info.is_recording:
                self._btn_rec.setChecked(False)
                self._toggle_recording(False)
            if self._bench_file:
                self._bench_file.close()
                self._bench_file = None
                self._bench_log  = None
                self.statusBar().showMessage(f"Disconnected  — bench log: {self._bench_path}")
            else:
                self.statusBar().showMessage("Disconnected")

    def _update_graph_titles(self) -> None:
        """Graph pane titles show which PHYSICAL channel is live, replacing
        the old static 'CH0'/'CH1' — resolves the ChA/ChB-vs-CH0/CH1 naming
        confusion by making the graph state the one live fact instead of
        aliasing two naming schemes. Driven by _channels_state, same
        mutation points as the sidecar provenance (spec §2.1)."""
        prov = self._channels_state["provenance"]
        ch_a, ch_b = self._channels_state["ch_a"], self._channels_state["ch_b"]
        if prov == "unknown":
            self._graph.set_channel_titles("Channel —", "Channel —")
        elif prov == "unverified_requested":
            self._graph.set_channel_titles(
                f"Channel {ch_a}  (pending)", f"Channel {ch_b}  (pending)")
        else:  # verified_readback
            self._graph.set_channel_titles(f"Channel {ch_a}", f"Channel {ch_b}")

    def _apply_channels(self):
        """SET_CHANNELS now requires streaming to already be stopped (see
        docs/interfaces/channel-selection-control-plane.md section 5) —
        Apply orchestrates STOP_STREAMING -> SET_CHANNELS -> (readback or
        timeout) -> START_STREAMING as one operator-facing action.

        Each step now waits for a real MCU-confirmed ack on 0xFFF3 (section
        5.6) before advancing to the next, instead of a fixed settle delay —
        a real ack already proves the previous command was relayed and fully
        processed, so no artificial spacing is needed on the success path.
        STREAMING_ACK_TIMEOUT_MS is the fallback if no ack ever arrives (e.g.
        an old MCU build without this feature) so the sequence still
        completes rather than hanging forever.
        """
        if not self._reader.send_stop_streaming():
            self.statusBar().showMessage("STOP_STREAMING failed — not connected", 3000)
            return
        self._btn_apply_channels.setEnabled(False)
        self._btn_get_settings.setEnabled(False)
        self._btn_run_rung.setEnabled(False)
        self._lbl_verify.setText("… stopping stream")
        self._lbl_verify.setStyleSheet("font-size: 11px; color: gray;")
        self.statusBar().showMessage("STOP_STREAMING sent", 2000)
        self._apply_ch_a = self._spin_ch_a.value()
        self._apply_ch_b = self._spin_ch_b.value()
        # A change is in flight — whatever was verified before is stale as
        # of this click (spec §2.1's "invalidation/refresh" requirement).
        self._channels_state = {
            "ch_a": self._apply_ch_a, "ch_b": self._apply_ch_b,
            "provenance": "unverified_requested",
        }
        self._update_graph_titles()
        self._awaiting_stop_ack = True
        self._stop_ack_timer.start()

    def _on_stop_ack(self, success: bool):
        """STOP_STREAMING ack arrived on 0xFFF3 (section 5.6)."""
        if not self._awaiting_stop_ack:
            return  # stale/unsolicited — already timed out
        self._awaiting_stop_ack = False
        self._stop_ack_timer.stop()
        if not success:
            self._lbl_verify.setText("✗ STOP_STREAMING not confirmed by MCU")
            self._lbl_verify.setStyleSheet("font-size: 11px; color: #B71C1C; font-weight: bold;")
        QTimer.singleShot(COMMAND_GAP_MS, self._apply_channels_send_set)

    def _on_stop_ack_timeout(self):
        """No 0xFFF3 ack within the window — proceed anyway rather than
        hanging forever (e.g. an MCU build predating section 5.6, or a
        command dropped by a bridge UART overrun — see COMMAND_GAP_MS)."""
        if not self._awaiting_stop_ack:
            return
        self._awaiting_stop_ack = False
        self._lbl_verify.setText("✗ STOP_STREAMING unsuccessful — no confirmation received")
        self._lbl_verify.setStyleSheet("font-size: 11px; color: #E65100; font-weight: bold;")
        QTimer.singleShot(COMMAND_GAP_MS, self._apply_channels_send_set)

    def _apply_channels_send_set(self):
        """Sends the operator's PHYSICAL channels (channel_mapping.py),
        compensating for the RHD2164 pipeline offset the firmware doesn't
        (docs/interfaces/channel-selection-control-plane.md §1a-addendum).
        124 of 128 channels go through the normal friendly SET_CHANNELS
        path with an adjusted index; the other 4 (one per 32-channel
        module) need a direct raw REG_WRITE16 on REG_CH_A/REG_CH_B instead,
        since the friendly encoding can't express their raw code."""
        ch_a, ch_b = self._apply_ch_a, self._apply_ch_b
        wire_a, raw_a = channel_mapping.physical_to_wire(ch_a)
        wire_b, raw_b = channel_mapping.physical_to_wire(ch_b)

        if raw_a or raw_b:
            if not self._raw_channel_setter.run(
                    channel_mapping.physical_to_raw(ch_a),
                    channel_mapping.physical_to_raw(ch_b)):
                self.statusBar().showMessage("Channel write busy — try again", 3000)
                self._resume_streaming()
                return
            self.statusBar().showMessage(
                f"Writing raw channel registers  ch_a={ch_a}  ch_b={ch_b}", 3000)
            self._lbl_verify.setText("… writing (raw)")
            self._lbl_verify.setStyleSheet("font-size: 11px; color: gray;")
            return

        if self._reader.send_set_channels(wire_a, wire_b):
            self.statusBar().showMessage(f"SET_CHANNELS  ch_a={ch_a}  ch_b={ch_b}  sent", 3000)
            self._pending_channels = (wire_a, wire_b)   # wire-space, matches the readback below
            self._lbl_verify.setText("… verifying")
            self._lbl_verify.setStyleSheet("font-size: 11px; color: gray;")
            self._verify_timer.start()
        else:
            self.statusBar().showMessage("SET_CHANNELS failed — not connected", 3000)
            self._lbl_verify.setText("")
            self._resume_streaming()  # still try to un-stop the MCU

    def _on_channels_readback(self, ch_a: int, ch_b: int):
        """SET_CHANNELS readback arrived on 0xFFF3 — see
        docs/interfaces/channel-selection-control-plane.md section 4.
        ch_a/ch_b here are wire/friendly-space values, same as everything
        else on this signal (the raw REG_WRITE16 path never fires it —
        see _on_raw_channels_set below).

        Always a real hardware confirmation regardless of what triggered it
        (an Apply click below, or Get Settings restoring the operator's
        channels after reading filter registers) — sidecar provenance
        (spec §2.1) is updated unconditionally, using what the FPGA
        actually reports rather than what was requested, converted back to
        the physical channel number (channel_mapping.py) so the sidecar
        and UI never carry the wire-compensated value.

        wire_to_physical() can raise for a wire value physical_to_wire()
        never produces — this pc-app never sends one, so seeing one back
        means a corrupted/unexpected response, not a real channel; handled
        as its own failure state rather than storing a fabricated >127
        "channel number" into the sidecar (see channel_mapping.py)."""
        try:
            phys_a = channel_mapping.wire_to_physical(ch_a)
            phys_b = channel_mapping.wire_to_physical(ch_b)
        except ValueError as e:
            self._verify_timer.stop()
            self._pending_channels = None
            self._lbl_verify.setText(f"✗ Unexpected readback (ch_a={ch_a}, ch_b={ch_b}): {e}")
            self._lbl_verify.setStyleSheet("font-size: 11px; color: #B71C1C; font-weight: bold;")
            self._resume_streaming()
            return
        self._channels_state = {
            "ch_a": phys_a, "ch_b": phys_b, "provenance": "verified_readback",
        }
        self._update_graph_titles()
        self._verify_timer.stop()
        if self._pending_channels is None:
            return  # stale/unsolicited — already timed out or nothing was applied
        requested = self._pending_channels
        self._pending_channels = None
        if (ch_a, ch_b) == requested:
            self._lbl_verify.setText("✓ Verified")
            self._lbl_verify.setStyleSheet("font-size: 11px; color: green; font-weight: bold;")
        else:
            self._lbl_verify.setText(f"✗ Mismatch (FPGA has channel {phys_a}/{phys_b})")
            self._lbl_verify.setStyleSheet("font-size: 11px; color: #B71C1C; font-weight: bold;")
        self._resume_streaming()

    def _on_raw_channels_set(self) -> None:
        """RawChannelSetter finished — the raw-path equivalent of a
        confirmed channels_readback (channel_mapping.py's 4 special
        channels). The write is already ack-gated/verified by
        RawChannelSetter itself, so finishing at all is the confirmation."""
        self._channels_state = {
            "ch_a": self._apply_ch_a, "ch_b": self._apply_ch_b,
            "provenance": "verified_readback",
        }
        self._update_graph_titles()
        self._lbl_verify.setText("✓ Verified (raw)")
        self._lbl_verify.setStyleSheet("font-size: 11px; color: green; font-weight: bold;")
        self._resume_streaming()

    def _on_raw_channels_failed(self, reason: str) -> None:
        self._lbl_verify.setText(f"✗ Channel write failed: {reason}")
        self._lbl_verify.setStyleSheet("font-size: 11px; color: #B71C1C; font-weight: bold;")
        self._resume_streaming()

    def _on_verify_timeout(self):
        """No 0xFFF3 readback within the window. Originally this only meant
        "RTL readback not implemented yet" (PLAN.md A.1) — now that readback
        is live and working in most cycles, a timeout here usually means the
        SET_CHANNELS command (or its readback) was actually dropped, most
        often by a bridge UART overrun (see COMMAND_GAP_MS) — so this is
        reported as an unsuccessful command, not a neutral "no response"."""
        if self._pending_channels is None:
            return
        self._pending_channels = None
        self._lbl_verify.setText("✗ SET_CHANNELS unsuccessful — no confirmation received")
        self._lbl_verify.setStyleSheet("font-size: 11px; color: #E65100; font-weight: bold;")
        self._resume_streaming()

    def _resume_streaming(self):
        """Final step of the Apply sequence — always runs, whatever happened
        above, so streaming never stays stopped because of a failure partway
        through, and the Apply button is always re-enabled afterward."""
        QTimer.singleShot(COMMAND_GAP_MS, self._apply_channels_send_start)

    def _apply_channels_send_start(self):
        if self._reader.send_start_streaming():
            self.statusBar().showMessage("START_STREAMING sent", 2000)
            self._awaiting_start_ack = True
            self._start_ack_timer.start()
        else:
            self.statusBar().showMessage("START_STREAMING failed — not connected", 3000)
            QTimer.singleShot(APPLY_COOLDOWN_MS, self._apply_channels_reenable)

    def _on_start_ack(self, success: bool):
        """START_STREAMING ack arrived on 0xFFF3 (section 5.6)."""
        if not self._awaiting_start_ack:
            return  # stale/unsolicited — already timed out
        self._awaiting_start_ack = False
        self._start_ack_timer.stop()
        if not success:
            self.statusBar().showMessage("✗ START_STREAMING not confirmed by MCU", 3000)
        QTimer.singleShot(APPLY_COOLDOWN_MS, self._apply_channels_reenable)

    def _on_start_ack_timeout(self):
        """No 0xFFF3 ack within the window — proceed anyway rather than
        hanging forever (e.g. an MCU build predating section 5.6, or a
        command dropped by a bridge UART overrun — see COMMAND_GAP_MS)."""
        if not self._awaiting_start_ack:
            return
        self._awaiting_start_ack = False
        self.statusBar().showMessage("✗ START_STREAMING unsuccessful — no confirmation received", 3000)
        QTimer.singleShot(APPLY_COOLDOWN_MS, self._apply_channels_reenable)

    def _get_filter_settings(self):
        """'Get Settings' — docs/interfaces/recording-format.md §2.1/§2.1a.
        Mutually exclusive with Apply and the diagnostics ladder: all three
        drive the same live FPGA state (channel selection, sampling table,
        streaming), so only one may run at a time."""
        orig_ch_a = self._channels_state["ch_a"] if self._channels_state["ch_a"] is not None \
            else self._spin_ch_a.value()
        orig_ch_b = self._channels_state["ch_b"] if self._channels_state["ch_b"] is not None \
            else self._spin_ch_b.value()
        if not self._filter_settings_reader.run(orig_ch_a, orig_ch_b):
            return
        self._get_settings_orig = (orig_ch_a, orig_ch_b)
        self._btn_get_settings.setEnabled(False)
        self._btn_apply_channels.setEnabled(False)
        self._btn_run_rung.setEnabled(False)
        self._lbl_settings.setText("… reading filter registers")
        self._lbl_settings.setStyleSheet("font-size: 11px; color: gray;")

    def _on_get_settings_progress(self, line: str) -> None:
        self._lbl_settings.setText(line.strip())

    def _on_get_settings_finished(self, result) -> None:
        self._btn_get_settings.setEnabled(self._is_connected)
        self._btn_apply_channels.setEnabled(self._is_connected)
        self._btn_run_rung.setEnabled(True)
        self._filter_settings_state = {
            "registers": result.registers, "provenance": "verified_readback",
        }
        # FilterSettingsReader's restore is ack-gated and verified (either
        # via SET_CHANNELS's own readback or a raw REG_WRITE16 — see
        # diagnostics.py), so a successful finish is itself the confirmation
        # that the channels are back to _get_settings_orig; the raw-restore
        # path never fires channels_readback, so this can't rely on that
        # signal the way the friendly path does.
        if self._get_settings_orig is not None:
            ch_a, ch_b = self._get_settings_orig
            self._channels_state = {
                "ch_a": ch_a, "ch_b": ch_b, "provenance": "verified_readback",
            }
            self._update_graph_titles()
            self._get_settings_orig = None
        self._lbl_settings.setText(f"✓ {len(result.registers)} registers read")
        self._lbl_settings.setStyleSheet("font-size: 11px; color: green; font-weight: bold;")

    def _on_get_settings_failed(self, reason: str) -> None:
        self._btn_get_settings.setEnabled(self._is_connected)
        self._btn_apply_channels.setEnabled(self._is_connected)
        self._btn_run_rung.setEnabled(True)
        self._get_settings_orig = None
        self._lbl_settings.setText(f"✗ Get Settings failed: {reason}")
        self._lbl_settings.setStyleSheet("font-size: 11px; color: #B71C1C; font-weight: bold;")

    def _apply_channels_reenable(self):
        # Guard against a disconnect happening mid-sequence — don't
        # re-enable Apply if we're not actually connected anymore;
        # _on_connection_changed(True, ...) will re-enable it on reconnect.
        if self._is_connected:
            self._btn_apply_channels.setEnabled(True)
            self._btn_get_settings.setEnabled(True)
        self._btn_run_rung.setEnabled(True)

    def _on_error(self, msg: str):
        self._btn_connect.setChecked(False)
        self._btn_connect.setText("Connect")
        self.statusBar().showMessage(f"Error: {msg}")

    def _update_status(self):
        """Called every 2 s — update packet count, rate, drop counter, status bar."""
        pkts  = self._reader.total_packets
        drops = self._reader.dropped_packets
        self._lbl_packets.setText(str(pkts))

        # Colour drop label red as soon as any drop is detected; stays red.
        self._lbl_dropped.setText(str(drops))
        if drops > 0:
            self._lbl_dropped.setStyleSheet("font-size: 11px; color: #B71C1C; font-weight: bold;")

        now = time.time()
        elapsed = now - self._rate_ts
        if elapsed >= 2.0 and self._rate_ts > 0:
            delta        = pkts - self._rate_pkts
            drop_delta   = drops - self._drops_prev
            pps          = delta / elapsed
            kbps         = pps * 244 * 8 / 1000
            sps          = pps * 59
            self._lbl_rate.setText(f"{pps:.1f} pkt/s")
            self._lbl_thru.setText(f"{kbps:.0f} kbit/s")
            ur_pct = 100.0 * self._total_underruns / max(1, pkts * 59)
            self._lbl_underruns.setText(f"{self._total_underruns:,}  ({ur_pct:.1f}%)")
            self._rate_ts    = now
            self._rate_pkts  = pkts
            self._drops_prev = drops
            if self._bench_log:
                self._bench_log.writerow([
                    f"{now - self._bench_start:.1f}",
                    f"{kbps:.1f}",
                    f"{pps:.1f}",
                ])
                self._bench_file.flush()

            # Status bar: compact one-liner with drops prominently shown
            port = self._port_combo.currentText()
            drop_str = f"drops: {drops}" if drop_delta == 0 else f"drops: {drops} (+{drop_delta})"
            self.statusBar().showMessage(
                f"{port}  |  {pps:.0f} pkt/s  {sps:.0f} SPS  {kbps:.0f} kbit/s  |  {drop_str}  |  underruns: {self._total_underruns:,} ({ur_pct:.1f}%)"
            )

        if self._recorder.info.is_recording:
            info = self._recorder.info
            m, s = divmod(info.elapsed_sec, 60)
            self._lbl_rec_path.setText(
                f"Recording  {m}:{s:02d} / {MAX_DURATION_STR}  •  ~{info.estimated_mb} MB"
            )

    def closeEvent(self, event):
        """Without this, closing the window mid-recording/mid-connection
        just kills the process: CsvRecorder's buffered writes (64 KB) can
        lose their last unflushed chunk, and the sidecar never gets its
        stop()-time rewrite (duration, stop reason, etc.) — a clean window
        close shouldn't degrade to the same failure mode as a crash."""
        if self._recorder.info.is_recording:
            self._recorder.stop()
        if self._is_connected:
            self._reader.stop()
        super().closeEvent(event)
