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

# Command-frame framing (pc-app -> bridge), distinct from the 0xAA 0x55
# data-direction magic so a framing bug can't cross-interpret the two.
# See docs/interfaces/channel-selection-control-plane.md section 3.
CMD_MAGIC          = bytes([0xCC, 0x33])
CMD_SET_CHANNELS   = 0x01
CMD_STOP_STREAMING = 0x02
CMD_START_STREAMING = 0x03
# Register console — docs/interfaces/fpga-diagnostic-access.md section 2.
# The diagnostic path behind the A.1.1 verification ladder: raw access to any
# of the 256 FPGA regbank words, reaching what SET_CHANNELS deliberately
# cannot (sampling slot 32, RHD command injection, arbitrary readback).
CMD_REG_WRITE16    = 0x04
CMD_REG_READ16     = 0x05

# Command-response framing (bridge -> pc-app). See
# docs/interfaces/channel-selection-control-plane.md sections 4.4 and 5.6.
# Payload's first byte is always a type/cmd tag matching the CMD_* values
# above, so a response always echoes which command it's answering:
#   CMD_SET_CHANNELS   (0x01): [0x01, ch_a, ch_b]   (3 bytes) — readback
#   CMD_STOP_STREAMING (0x02): [0x02, success]      (2 bytes) — ack
#   CMD_START_STREAMING(0x03): [0x03, success]      (2 bytes) — ack
#   CMD_REG_WRITE16    (0x04): [0x04, addr, lo, hi] (4 bytes) — value READ BACK
#   CMD_REG_READ16     (0x05): [0x05, addr, lo, hi] (4 bytes)
RESPONSE_MAGIC = bytes([0xEE, 0x11])


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
    channels_readback  = pyqtSignal(int, int)   # ch_a, ch_b — SET_CHANNELS readback (section 4.4)
    stop_streaming_ack  = pyqtSignal(bool)       # success — real MCU confirmation (section 5.6)
    start_streaming_ack = pyqtSignal(bool)       # success — real MCU confirmation (section 5.6)
    # type (CMD_REG_WRITE16 / CMD_REG_READ16), addr, value — register console.
    # For a write, value is what the FPGA regbank read back, not what was sent.
    reg_access_response = pyqtSignal(int, int, int)

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

    def send_command(self, payload: bytes) -> bool:
        """Send a command frame to the bridge: 0xCC 0x33 <len> <payload>.
        Called from the UI thread while run() reads on this QThread — same
        cross-thread self._port access pattern stop() already relies on."""
        if self._port is None or not self._port.is_open:
            return False
        frame = CMD_MAGIC + bytes([len(payload)]) + payload
        try:
            self._port.write(frame)
        except (serial.SerialException, OSError):
            return False
        return True

    def send_set_channels(self, ch_a: int, ch_b: int) -> bool:
        """SET_CHANNELS command — see
        docs/interfaces/channel-selection-control-plane.md section 2.
        As of section 5, the MCU rejects this unless streaming is already
        stopped (send_stop_streaming() first) — this method doesn't enforce
        that itself, callers must sequence it (see MainWindow._apply_channels)."""
        if not (0 <= ch_a <= 127 and 0 <= ch_b <= 127):
            raise ValueError("channel index must be 0-127")
        return self.send_command(bytes([CMD_SET_CHANNELS, ch_a, ch_b]))

    def send_stop_streaming(self) -> bool:
        """STOP_STREAMING command — see
        docs/interfaces/channel-selection-control-plane.md section 5.1."""
        return self.send_command(bytes([CMD_STOP_STREAMING]))

    def send_reg_write16(self, addr: int, value: int) -> bool:
        """Write one FPGA regbank word — docs/interfaces/fpga-diagnostic-access.md §2.

        The MCU reads the word back and returns what it actually holds, so the
        reg_access_response for this call is a verification, not an echo.
        Rejected by the MCU unless streaming is stopped.
        """
        return self.send_command(
            bytes([CMD_REG_WRITE16, addr & 0xFF, value & 0xFF, (value >> 8) & 0xFF]))

    def send_reg_read16(self, addr: int) -> bool:
        """Read one FPGA regbank word. Rejected by the MCU unless streaming is stopped."""
        return self.send_command(bytes([CMD_REG_READ16, addr & 0xFF]))

    def send_start_streaming(self) -> bool:
        """START_STREAMING command — see
        docs/interfaces/channel-selection-control-plane.md section 5.1."""
        return self.send_command(bytes([CMD_START_STREAMING]))

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
            except (serial.SerialException, OSError, TypeError):
                # OSError/TypeError: port fd closed by stop() while read() was blocked
                break

            if not chunk:
                continue

            buf.extend(chunk)

            # Re-sync: find whichever magic (data or command-response) comes
            # first and extract complete frames of that type.
            while True:
                idx_data = buf.find(MAGIC)
                idx_resp = buf.find(RESPONSE_MAGIC)

                if idx_data == -1 and idx_resp == -1:
                    # Neither magic found — keep last 1 byte (could be partial magic)
                    buf = buf[-1:]
                    break

                if idx_resp == -1 or (idx_data != -1 and idx_data <= idx_resp):
                    idx, is_response = idx_data, False
                else:
                    idx, is_response = idx_resp, True

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

                if is_response:
                    if len(payload) >= 1:
                        rtype = payload[0]
                        if rtype == CMD_SET_CHANNELS and len(payload) >= 3:
                            self.channels_readback.emit(payload[1], payload[2])
                        elif rtype == CMD_STOP_STREAMING and len(payload) >= 2:
                            self.stop_streaming_ack.emit(bool(payload[1]))
                        elif rtype == CMD_START_STREAMING and len(payload) >= 2:
                            self.start_streaming_ack.emit(bool(payload[1]))
                        elif rtype in (CMD_REG_WRITE16, CMD_REG_READ16) and len(payload) >= 4:
                            self.reg_access_response.emit(
                                rtype, payload[1], payload[2] | (payload[3] << 8))
                        # else: unknown type or short payload — ignore
                    continue

                packet = parse(payload)
                if packet is None:
                    continue

                # Monotonicity clamp: if this packet's first timestamp doesn't
                # strictly follow the previous one, rebase it forward.  This
                # fixes backwards jumps from BLE burst delivery where multiple
                # packets share the same RTC base timestamp.  Genuine forward
                # gaps (missed CIs) are left untouched.
                # A header-only/malformed packet (num_pairs == 0) carries no
                # samples to clamp or rebase on — skip this block rather than
                # index an empty array (found 2026-08-06 as a reader-thread
                # crash; never triggered by real firmware, which always sends
                # 59 pairs, but the parser must not crash on a malformed frame
                # it can't control). _last_ts_us is deliberately left
                # unchanged: there is no timestamp here to advance it to.
                if len(packet.timestamps_us) > 0:
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

        try:
            if self._port and self._port.is_open:
                self._port.close()
        except OSError:
            pass  # already closed by stop()
        self._last_ts_us = 0
        self.connection_changed.emit(False, self._port_name)

    @staticmethod
    def list_ports() -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]
