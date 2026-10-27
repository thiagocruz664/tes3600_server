
"""Control de la sesión de comunicación con el TES3600."""

import logging
import threading
import time

from config import (
    COMMAND_START,
    COMMAND_POLL,
    COMMAND_MEASURE,
    STATUS_READY,
    POLL_INTERVAL,
    REQUEST_INTERVAL,
    FRAME_END_TIMEOUT,
    FRAME_START,
    FRAME_END,
)
from tes3600.serial_link import TES3600Serial

logger = logging.getLogger(__name__)

# El TES3600 transmite tramas conocidas de aproximadamente 61 bytes.
# El límite deja margen para bloques mayores sin permitir crecimiento infinito.
MAX_BUFFER_SIZE = 4096


class TES3600Session:
    """Gestiona la inicialización, el sondeo y la recepción del TES3600."""

    def __init__(self, on_block=None):
        self.link = TES3600Serial()
        self.detener = threading.Event()
        self.tes_listo = threading.Event()
        self.write_lock = threading.Lock()
        self.on_block = on_block or self._mostrar_bloque
        self.threads = []

    def enviar(self, data, mostrar=True):
        """Envía datos al TES de forma sincronizada."""
        with self.write_lock:
            self.link.send(data)

        if mostrar:
            timestamp = time.perf_counter()
            # Se conserva desactivado el registro de cada comando enviado.

    def _procesar_bloque(self, bloque):
        """Filtra READY y entrega los bloques recibidos."""
        if bloque == bytes([STATUS_READY]):
            self.tes_listo.set()
            return

        if (
            len(bloque) > 1
            and bloque[0] == STATUS_READY
            and bloque[1] == FRAME_START
            and bloque[-1] == FRAME_END
        ):
            bloque = bloque[1:]
        elif bloque.startswith(bytes([STATUS_READY])):
            self.tes_listo.set()

        try:
            self.on_block(bloque)
        except Exception:
            logger.exception("Error al procesar un bloque del TES3600.")

    @staticmethod
    def _mostrar_bloque(bloque):
        """Muestra un bloque recibido en hexadecimal."""
        timestamp = time.perf_counter()
#        print()
#        print(
#            f"[{timestamp:.6f}] "
#            f"TES -> PC BLOQUE ({len(bloque)} bytes):"
#        )
#        print(bloque.hex(" ").upper())

    def _recepcion_loop(self):
        """Agrupa los bytes usando el intervalo de silencio."""
        buffer = bytearray()
        ultimo_byte = None
        conexion = self.link.connection

        timeout_original = conexion.timeout
        conexion.timeout = FRAME_END_TIMEOUT

        try:
            while not self.detener.is_set():
                data = conexion.read(conexion.in_waiting or 1)

                if data:
                    ahora = time.perf_counter()

                    if (
                        ultimo_byte is not None
                        and ahora - ultimo_byte > FRAME_END_TIMEOUT
                        and buffer
                    ):
                        self._procesar_bloque(bytes(buffer))
                        buffer.clear()

                    # Protección frente a una recepción anormalmente grande.
                    if len(buffer) + len(data) > MAX_BUFFER_SIZE:
                        logger.warning(
                            "Buffer serie excedió %d bytes; "
                            "se descarta el bloque incompleto.",
                            MAX_BUFFER_SIZE,
                        )
                        buffer.clear()
                        ultimo_byte = None

                        # No acumular un único bloque que ya excede el límite.
                        if len(data) > MAX_BUFFER_SIZE:
                            data = data[-MAX_BUFFER_SIZE:]

                    buffer.extend(data)
                    ultimo_byte = time.perf_counter()

                elif buffer:
                    self._procesar_bloque(bytes(buffer))
                    buffer.clear()
                    ultimo_byte = None

            if buffer:
                self._procesar_bloque(bytes(buffer))

        except Exception:
            if not self.detener.is_set():
                logger.exception("Error en la recepción serie del TES3600.")
                self.detener.set()

        finally:
            conexion.timeout = timeout_original

    def _polling_loop(self):
        """Envía periódicamente el comando 77 00."""
        while not self.detener.is_set():
            try:
                self.enviar(COMMAND_POLL, mostrar=False)
            except Exception:
                logger.exception("Error al enviar el polling al TES3600.")
                self.detener.set()
                break

            self.detener.wait(POLL_INTERVAL)

    def _solicitudes_loop(self):
        """Solicita mediciones después de recibir el estado READY."""
        while not self.detener.is_set():
            if self.tes_listo.wait(timeout=0.1):
                break

        if self.detener.is_set():
            return

        if self.detener.wait(0.05):
            return

        while not self.detener.is_set():
            try:
                self.enviar(bytes([COMMAND_MEASURE]))
            except Exception:
                logger.exception("Error al solicitar una medición.")
                self.detener.set()
                break

            self.detener.wait(REQUEST_INTERVAL)

    def iniciar(self):
        """Abre el puerto e inicia los hilos de comunicación."""
        self.link.connect()

        hilo_rx = threading.Thread(
            target=self._recepcion_loop,
            name="tes-recepcion",
            daemon=True,
        )
        hilo_rx.start()
        self.threads.append(hilo_rx)

        self.enviar(bytes([COMMAND_START]))

        for target, name in (
            (self._polling_loop, "tes-polling"),
            (self._solicitudes_loop, "tes-solicitudes"),
        ):
            hilo = threading.Thread(
                target=target,
                name=name,
                daemon=True,
            )
            hilo.start()
            self.threads.append(hilo)

    def detener_sesion(self):
        """Detiene los hilos y cierra el puerto serie."""
        self.detener.set()

        for hilo in self.threads:
            hilo.join(timeout=1.0)

        self.link.disconnect()
