"""
MainWindow — top-level PyQt6 window for the Vega PC app.
"""

import csv
import datetime
import time
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QGroupBox, QGridLayout,
    QFileDialog, QStatusBar,
)
from PyQt6.QtGui import QFont

from serial_reader import SerialReader
from graph_widget  import GraphWidget
from csv_recorder  import CsvRecorder

# Measured at ~4 500 SPS with current CI (~13 ms). Update when CI is tightened to 7.5 ms.
DELIVERED_SPS = 5_000


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
            path = self._recorder.start(".")
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
            ok = self._recorder.write_batch(packet.timestamps_us, packet.ch0, packet.ch1)
            if not ok and self._recorder.info.auto_stopped:
                self._btn_rec.setChecked(False)
                self._toggle_recording(False)

    def _on_connection_changed(self, connected: bool, port: str):
        if connected:
            self._lbl_status.setText(f"Connected ({port})")
            self._lbl_status.setStyleSheet("font-size: 11px; color: green;")
            self._btn_rec.setEnabled(True)
            self._graph.clear()
            self._rate_ts         = time.time()
            self._rate_pkts       = 0
            self._total_underruns = 0
            self.statusBar().showMessage(f"Connected on {port}")
            # Open bench log for this session
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self._bench_path = f"bench_{ts}.csv"
            self._bench_file = open(self._bench_path, "w", newline="")
            self._bench_log  = csv.writer(self._bench_file)
            self._bench_log.writerow(["elapsed_s", "kbps", "pps"])
            self._bench_start = time.time()
        else:
            self._lbl_status.setText("Disconnected")
            self._lbl_status.setStyleSheet("font-size: 11px; color: gray;")
            self._btn_rec.setEnabled(False)
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
