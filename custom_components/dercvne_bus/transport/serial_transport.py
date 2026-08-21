"""Serial transport for DALI communication."""

import asyncio
import logging
import time
from typing import Optional

from .base import DALITransport

_LOGGER = logging.getLogger(__name__)


class SerialTransport(DALITransport):
    """Serial transport for RS485 communication.

    Uses termios to force raw mode and explicitly clear RTS/DTR after open,
    preventing CH340 auto-direction adapters from sticking in TX mode.
    """

    def __init__(
        self,
        port: str,
        baud_rate: int = 9600,
        parity: str = "N",
        byteize: int = 8,
        stopbits: int = 1,
        timeout: int = 2,
    ):
        super().__init__(timeout)
        self._port = port
        self._baud_rate = baud_rate
        self._parity = parity
        self._byteize = byteize
        self._stop_bits = stopbits
        self._serial = None
        self._write_lock = asyncio.Lock()
        self._last_read_log = 0.0

    async def connect(self) -> bool:
        """Connect to serial port (pySerial required)."""
        try:
            import serial

            kwargs = dict(
                port=self._port,
                baudrate=self._baud_rate,
                parity=self._parity,
                bytesize=self._byteize,
                stopbits=self._stop_bits,
                timeout=self._timeout,
                write_timeout=self._timeout,
                rtscts=False,
                dsrdtr=False,
                xonxoff=False,
            )
            if hasattr(serial.Serial, "exclusive"):
                kwargs["exclusive"] = True

            # Opening a serial port is a blocking syscall (DTR/RTS handshake,
            # termios setup, etc.).  Run it in an executor so the asyncio
            # event loop is never blocked while the port initializes.
            loop = asyncio.get_running_loop()

            def _open_port() -> "serial.Serial":
                return serial.Serial(**kwargs)

            self._serial = await loop.run_in_executor(None, _open_port)
            # Flush stale buffers
            try:
                self._serial.flushInput()
                self._serial.flushOutput()
            except Exception:
                try:
                    self._serial.reset_input_buffer()
                    self._serial.reset_output_buffer()
                except Exception:
                    pass

            # ------------------------------------------------------------------
            #  CRITICAL: Force termios raw mode + clear RTS/DTR immediately.
            #  Linux tty drivers default to hupcl + rts=True on open(), which
            #  keeps some CH340 RS485 adapters stuck in TX mode (floods bus).
            # ------------------------------------------------------------------
            try:
                import termios
                import tty

                fd = self._serial.fileno()
                # Set raw mode (disables all line discipline processing)
                tty.setraw(fd, termios.TCSANOW)

                # Explicitly clear RTS and DTR
                self._serial.rts = False
                self._serial.dtr = False

                # Double-check via termios control flags
                attrs = termios.tcgetattr(fd)
                attrs[2] = attrs[2] & ~termios.CRTSCTS  # Clear CRTSCTS
                termios.tcsetattr(fd, termios.TCSANOW, attrs)
            except Exception as e:
                _LOGGER.debug("termios raw-mode setup failed (non-fatal): %s", e)
                # Fallback: at least clear the pins via pyserial
                self._serial.rts = False
                self._serial.dtr = False

            _LOGGER.info(
                "Connected to serial %s (baud=%d, bytesize=%d, stopbits=%d, parity=%s, rts=%s, dtr=%s)",
                self._port, self._baud_rate,
                self._byteize, self._stop_bits, self._parity,
                self._serial.rts, self._serial.dtr,
            )

            self._connected = True
            return True
        except Exception as e:
            _LOGGER.error("Failed to connect to serial %s: %s", self._port, e)
            return False

    async def disconnect(self) -> None:
        """Disconnect from serial port."""
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self._connected = False
        _LOGGER.info("Disconnected from serial %s", self._port)

    async def send_bytes(self, data: bytes) -> bool:
        """Send raw bytes via serial (RS485).

        Do NOT touch RTS/DTR here – let the adapter handle direction.
        """
        if not self._connected or self._serial is None:
            _LOGGER.warning("Serial not connected, cannot send bytes")
            return False
        async with self._write_lock:
            try:
                loop = asyncio.get_running_loop()

                def _write():
                    self._serial.write(data)
                    self._serial.flush()

                    # Wait until the last byte has actually left the UART
                    parity_bits = 1 if self._parity != "N" else 0
                    bits_per_byte = 1 + self._byteize + parity_bits + self._stop_bits
                    tx_time = len(data) * bits_per_byte / self._baud_rate
                    time.sleep(tx_time + 0.005)

                await loop.run_in_executor(None, _write)
                _LOGGER.info(
                    "[SERIAL-SEND] %s: %s",
                    self._port, data.hex(" "),
                )
                return True
            except Exception as e:
                _LOGGER.error("Failed to send bytes via serial: %s", e)
                self._connected = False
                return False

    async def read(self, n: int = 256) -> Optional[bytes]:
        """Read raw bytes from the serial port (for background listener).

        pySerial's read() is blocking; run it in a thread
        to avoid blocking the asyncio event loop.
        """
        if not self._connected or self._serial is None:
            return None
        try:
            loop = asyncio.get_running_loop()

            def _read():
                return self._serial.read(n)

            data = await loop.run_in_executor(None, _read)
            if data:
                # Throttle read logging to avoid flooding logs
                now = time.time()
                if now - self._last_read_log >= 2.0:
                    self._last_read_log = now
                    _LOGGER.info(
                        "[SERIAL-READ] %s: %d bytes: %s",
                        self._port, len(data), data[:32].hex(" "),
                    )
                return data  # bytes
            return None
        except Exception as e:
            _LOGGER.debug("Serial read error: %s", e)
            return None

    async def send_command(self, command: str) -> bool:
        """Send command via serial (encode to ASCII bytes)."""
        data = command.encode("ascii")
        return await self.send_bytes(data)

    async def receive_feedback(self) -> Optional[str]:
        """Receive feedback via serial (decode to string)."""
        data = await self.read(256)
        if data is not None:
            return data.decode("latin-1").strip(" \t\r\n")
        return None
