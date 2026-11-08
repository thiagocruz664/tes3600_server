"""Capa de comunicación serie con el TES3600."""

import time

import serial

from config import (
    SERIAL_PORT,
    SERIAL_BAUDRATE,
    SERIAL_BYTESIZE,
    SERIAL_PARITY,
    SERIAL_STOPBITS,
    SERIAL_TIMEOUT,
)


class TES3600Serial:
    """Gestiona el transporte serie del TES3600."""

    def __init__(self, port=SERIAL_PORT):
        self.port = port
        self.connection = None

    def connect(self):
        """Abre el puerto serie con los parámetros configurados."""
        if self.connection and self.connection.is_open:
            return

        self.connection = serial.Serial(
            port=self.port,
            baudrate=SERIAL_BAUDRATE,
            bytesize=SERIAL_BYTESIZE,
            parity=SERIAL_PARITY,
            stopbits=SERIAL_STOPBITS,
            timeout=SERIAL_TIMEOUT,
            write_timeout=1,
            rtscts=False,
            dsrdtr=False,
        )

        # Configuración utilizada durante las pruebas con Power Analyzer.
        self.connection.dtr = True
        self.connection.rts = False

    def disconnect(self):
        """Cierra el puerto serie si está abierto."""
        if self.connection and self.connection.is_open:
            self.connection.close()

    def send(self, data):
        """Envía bytes al equipo."""
        self._require_connection()

        if isinstance(data, int):
            data = bytes([data])

        self.connection.write(data)
        self.connection.flush()

    def receive(self, size=1):
        """Lee hasta size bytes, con el timeout configurado."""
        self._require_connection()
        return self.connection.read(size)

    def receive_available(self):
        """Lee los bytes que ya están disponibles en el búfer."""
        self._require_connection()

        available = self.connection.in_waiting
        if available == 0:
            return b""

        return self.connection.read(available)

    def wait_for_silence(self, silence=0.005, max_wait=1.0):
        """Recibe datos hasta detectar un intervalo de silencio."""
        self._require_connection()

        received = bytearray()
        last_data_time = time.monotonic()
        start_time = last_data_time

        while time.monotonic() - start_time < max_wait:
            chunk = self.connection.read(1)

            if chunk:
                received.extend(chunk)
                last_data_time = time.monotonic()
            elif time.monotonic() - last_data_time >= silence:
                break

        return bytes(received)

    def _require_connection(self):
        """Comprueba que el puerto esté abierto."""
        if self.connection is None or not self.connection.is_open:
            raise RuntimeError("El puerto serie no está conectado.")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.disconnect()
