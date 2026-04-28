"""
GraphWidget — two-channel real-time pyqtgraph plot with a circular numpy buffer.
Mirrors the Android CircularMultiChannelBuffer + TimeSeriesGraph logic.
"""

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout

BUFFER_SECONDS   = 10
UI_REFRESH_HZ    = 30
WINDOW_SECONDS   = 5.0   # default display window


class GraphWidget(QWidget):
    def __init__(self, delivered_sps: int = 30_000, parent=None):
        super().__init__(parent)
        self._sps        = delivered_sps
        self._buf_size   = delivered_sps * BUFFER_SECONDS
        self._window_pts = int(WINDOW_SECONDS * delivered_sps)

        # Circular buffers
        self._ts  = np.zeros(self._buf_size, dtype=np.int64)
        self._ch0 = np.zeros(self._buf_size, dtype=np.int16)
        self._ch1 = np.zeros(self._buf_size, dtype=np.int16)
        self._head = 0
        self._size = 0

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(1000 // UI_REFRESH_HZ)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _build_ui(self):
        pg.setConfigOption("background", "k")
        pg.setConfigOption("foreground", "w")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._plots = []
        self._curves = []
        colors = ["r", "g"]
        labels = ["CH0", "CH1"]

        for i, (color, label) in enumerate(zip(colors, labels)):
            plot = pg.PlotWidget(title=label)
            plot.showGrid(x=False, y=True, alpha=0.3)
            plot.setLabel("left", "ADC", units="LSB")
            plot.enableAutoRange(axis="y", enable=True)
            plot.setMouseEnabled(x=False, y=False)
            curve = plot.plot(pen=pg.mkPen(color, width=1))
            self._plots.append(plot)
            self._curves.append(curve)
            layout.addWidget(plot)

    def add_batch(self, timestamps_us: np.ndarray, ch0: np.ndarray, ch1: np.ndarray):
        n = len(timestamps_us)
        if n == 0:
            return
        # Write into circular buffer (wrapping)
        for arr_src, arr_dst in [(timestamps_us, self._ts),
                                  (ch0, self._ch0),
                                  (ch1, self._ch1)]:
            end = self._head + n
            if end <= self._buf_size:
                arr_dst[self._head:end] = arr_src
            else:
                split = self._buf_size - self._head
                arr_dst[self._head:] = arr_src[:split]
                arr_dst[:n - split] = arr_src[split:]

        self._head = (self._head + n) % self._buf_size
        self._size = min(self._size + n, self._buf_size)

    def _get_window(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return the last _window_pts samples in time order."""
        n = min(self._size, self._window_pts)
        if n == 0:
            return np.array([]), np.array([]), np.array([])
        start = (self._head - n) % self._buf_size
        if start + n <= self._buf_size:
            ts  = self._ts [start:start + n]
            ch0 = self._ch0[start:start + n]
            ch1 = self._ch1[start:start + n]
        else:
            s1 = self._buf_size - start
            ts  = np.concatenate([self._ts [start:], self._ts [:n - s1]])
            ch0 = np.concatenate([self._ch0[start:], self._ch0[:n - s1]])
            ch1 = np.concatenate([self._ch1[start:], self._ch1[:n - s1]])
        return ts, ch0, ch1

    def _refresh(self):
        ts, ch0, ch1 = self._get_window()
        if len(ts) == 0:
            return
        x = (ts - ts[0]) / 1e6   # seconds from window start
        self._curves[0].setData(x, ch0.astype(np.float32))
        self._curves[1].setData(x, ch1.astype(np.float32))

    def clear(self):
        self._head = 0
        self._size = 0
        for curve in self._curves:
            curve.setData([], [])

    def set_window_seconds(self, seconds: float):
        self._window_pts = int(seconds * self._sps)
