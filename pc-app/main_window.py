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
    QFileDialog, QStatusBar, QSpinBox,
)
from PyQt6.QtGui import QFont

from serial_reader import SerialReader
from graph_widget  import GraphWidget
from csv_recorder  import CsvRecorder

RECORDINGS_DIR = Path(__file__).parent / "recordings"
BENCH_DIR      = Path(__file__).parent / "bench"

# Measured at ~4 500 SPS with current CI (~13 ms). Update when CI is tightened to 7.5 ms.
DELIVERED_SPS = 5_000

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

        # GPIO bench logging — opened on BLE connect, closed on disconnect
        self._bench_log: "csv.writer | None" = None
        self._bench_file = None
        self._bench_start = 0.0
        self._bench_path = ""

        self._build_ui()
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

        return row

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
        row.addWidget(self._spin_ch_a)

        row.addWidget(QLabel("Ch B:"))
        self._spin_ch_b = QSpinBox()
        self._spin_ch_b.setRange(0, 127)
        self._spin_ch_b.setValue(1)
        row.addWidget(self._spin_ch_b)

        self._btn_apply_channels = QPushButton("Apply")
        self._btn_apply_channels.setEnabled(False)
        self._btn_apply_channels.clicked.connect(self._apply_channels)
        row.addWidget(self._btn_apply_channels)

        self._lbl_verify = QLabel("")
        self._lbl_verify.setStyleSheet("font-size: 11px;")
        row.addWidget(self._lbl_verify)

        row.addStretch(1)
        return row

    def _build_debug_panel(self) -> QGroupBox:
        box = QGroupBox("Debug Info")
        box.setMaximumHeight(90)
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(2)

        def lbl(text, bold=False):
            l = QLabel(text)
            if bold:
                f = l.font(); f.setBold(True); l.setFont(f)
            l.setStyleSheet("font-size: 11px;")
            return l

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
            path = self._recorder.start(str(RECORDINGS_DIR))
            self._btn_rec.setText("■ Stop")
            self._lbl_rec_path.setText(f"Recording → {path}")
        else:
            self._recorder.stop()
            self._btn_rec.setText("● REC")
            info = self._recorder.info
            self._lbl_rec_path.setText(
                f"Saved  {info.elapsed_sec}s  ~{info.estimated_mb} MB  → {info.file_path}"
            )

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
            self._verify_timer.stop()
            self._pending_channels = None
            self._stop_ack_timer.stop()
            self._start_ack_timer.stop()
            self._awaiting_stop_ack = False
            self._awaiting_start_ack = False
            self._lbl_verify.setText("")
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
        self._lbl_verify.setText("… stopping stream")
        self._lbl_verify.setStyleSheet("font-size: 11px; color: gray;")
        self.statusBar().showMessage("STOP_STREAMING sent", 2000)
        self._apply_ch_a = self._spin_ch_a.value()
        self._apply_ch_b = self._spin_ch_b.value()
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
        ch_a, ch_b = self._apply_ch_a, self._apply_ch_b
        if self._reader.send_set_channels(ch_a, ch_b):
            self.statusBar().showMessage(f"SET_CHANNELS  ch_a={ch_a}  ch_b={ch_b}  sent", 3000)
            self._pending_channels = (ch_a, ch_b)
            self._lbl_verify.setText("… verifying")
            self._lbl_verify.setStyleSheet("font-size: 11px; color: gray;")
            self._verify_timer.start()
        else:
            self.statusBar().showMessage("SET_CHANNELS failed — not connected", 3000)
            self._lbl_verify.setText("")
            self._resume_streaming()  # still try to un-stop the MCU

    def _on_channels_readback(self, ch_a: int, ch_b: int):
        """SET_CHANNELS readback arrived on 0xFFF3 — see
        docs/interfaces/channel-selection-control-plane.md section 4."""
        self._verify_timer.stop()
        if self._pending_channels is None:
            return  # stale/unsolicited — already timed out or nothing was applied
        requested = self._pending_channels
        self._pending_channels = None
        if (ch_a, ch_b) == requested:
            self._lbl_verify.setText("✓ Verified")
            self._lbl_verify.setStyleSheet("font-size: 11px; color: green; font-weight: bold;")
        else:
            self._lbl_verify.setText(f"✗ Mismatch (FPGA has {ch_a}/{ch_b})")
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

    def _apply_channels_reenable(self):
        # Guard against a disconnect happening mid-sequence — don't
        # re-enable Apply if we're not actually connected anymore;
        # _on_connection_changed(True, ...) will re-enable it on reconnect.
        if self._is_connected:
            self._btn_apply_channels.setEnabled(True)

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
                f"Recording  {m}:{s:02d} / 10:00  •  ~{info.estimated_mb} MB"
            )
