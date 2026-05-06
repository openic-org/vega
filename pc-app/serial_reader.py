"""
SerialReader — QThread that reads the nRF52840 USB CDC serial port, re-syncs on
the 0xAA 0x55 magic prefix, and emits decoded packets to the UI thread.
"""

import serial
import serial.tools.list_ports
from PyQt6.QtCore import QThread, pyqtSignal
import numpy as np
from packet_parser import parse, ParsedPacket, MAGIC, PACKET_SIZE, SAMPLE_RATE_HZ

BAUD_RATE   = 2000000  # must match WB09KE bridge USART1; ST-LINK VCP is baud-sensitive
READ_TIMEOUT = 1.0     # seconds


class SerialReader(QThread):
    """
    Signals:
      batch_received(packet)  — emitted for every successfully parsed packet
      connection_changed(connected, port_name)
      error(message)
    """
    batch_received     = pyqtSignal(object)   # ParsedPacket
    connection_changed = pyqtSignal(bool, str)
    error              = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._port_name  = ""
        self._running    = False
        self._port: serial.Serial | None = None

        # Statistics
        self.total_packets  = 0
        self.dropped_packets = 0
        self._expected_seq: int | None = None

        # Monotonicity clamp: tracks the last timestamp emitted so that
        # backwards jumps caused by BLE burst delivery / 1 ms RTC resolution
        # are replaced with a forward-continuing sequence.
        self._last_ts_us: int = 0
        self._step_us: int = 1_000_000 // SAMPLE_RATE_HZ  # 33 µs at 30 kSPS

    def set_port(self, port_name: str):
        self._port_name = port_name

    def stop(self):
        self._running = False
        if self._port and self._port.is_open:
            self._port.close()

    def run(self):
        self._running = True
        try:
            self._port = serial.Serial(
                self._port_name,
                baudrate=BAUD_RATE,
                timeout=READ_TIMEOUT,
            )
            self.connection_changed.emit(True, self._port_name)
        except serial.SerialException as e:
            self.error.emit(f"Cannot open {self._port_name}: {e}")
            return

        buf = bytearray()

        while self._running:
            try:
                chunk = self._port.read(512)
            except serial.SerialException as e:
                self.error.emit(f"Serial read error: {e}")
                break

            if not chunk:
                continue

            buf.extend(chunk)

            # Re-sync: find magic prefix and extract complete packets
            while True:
                idx = buf.find(MAGIC)
                if idx == -1:
                    # No magic found — keep last 1 byte (could be partial magic)
                    buf = buf[-1:]
                    break

                if idx > 0:
                    # Discard garbage before magic
                    buf = buf[idx:]

                # Need magic(2) + length(2) + payload
                if len(buf) < 4:
                    break

                frame_len = int.from_bytes(buf[2:4], "little")
                total_frame = 4 + frame_len

                if len(buf) < total_frame:
                    break   # wait for more data

                payload = bytes(buf[4:total_frame])
                buf = buf[total_frame:]

                packet = parse(payload)
                if packet is None:
                    continue

                # Monotonicity clamp: if this packet's first timestamp doesn't
                # strictly follow the previous one, rebase it forward.  This
                # fixes backwards jumps from BLE burst delivery where multiple
                # packets share the same RTC base timestamp.  Genuine forward
                # gaps (missed CIs) are left untouched.
                if self._last_ts_us > 0 and packet.timestamps_us[0] <= self._last_ts_us:
                    new_base = self._last_ts_us + self._step_us
                    packet.timestamps_us = (
                        new_base
                        + np.arange(len(packet.timestamps_us), dtype=np.int64)
                        * self._step_us
                    )
                self._last_ts_us = int(packet.timestamps_us[-1])

                # Drop detection
                seq = packet.header.seq_num
                if self._expected_seq is not None:
                    gap = (seq - self._expected_seq) % 256
                    if gap != 0:
                        self.dropped_packets += gap
                self._expected_seq = (seq + 1) % 256

                self.total_packets += 1
                self.batch_received.emit(packet)

        if self._port and self._port.is_open:
            self._port.close()
        self._last_ts_us = 0
        self.connection_changed.emit(False, self._port_name)

    @staticmethod
    def list_ports() -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]
