"""Descubrimiento, validación y reconexión del TES3600."""

import logging
import threading
import time

from serial.tools import list_ports

from config import (
    SERIAL_PORT,
    COMMAND_START,
    STATUS_READY,
    COMMAND_POLL,
    POLL_INTERVAL,
)
from tes3600.serial_link import TES3600Serial
from tes3600.session import TES3600Session

logger = logging.getLogger(__name__)

SCAN_INTERVAL = 1.0
VALIDATION_TIMEOUT = 0.75
INITIAL_POLL_DELAY = 0.095

WAITING_DEVICE = "WAITING_DEVICE"
VALIDATING_DEVICE = "VALIDATING_DEVICE"
CONNECTED = "CONNECTED"


class SerialManager:
    """Administra la búsqueda y conexión del TES3600."""

    def __init__(self, on_block=None, on_state=None):
        self.on_block = on_block
        self.on_state = on_state

        self.detener = threading.Event()
        self.session = None

        self.estado = None

    def _set_state(self, state):
        """Actualiza el estado e informa a quien lo esté supervisando."""
        if self.estado == state:
            return

        self.estado = state
        logger.info("Estado serial: %s", state)

        if self.on_state:
            try:
                self.on_state(state)
            except Exception:
                logger.exception("Error al actualizar el estado serial.")

    def _buscar_puertos(self):
        """Obtiene los puertos serie disponibles."""

        ports = list(list_ports.comports())

        # Priorizar el puerto configurado, sin limitar la búsqueda a él.
        ports.sort(
            key=lambda port: port.device != SERIAL_PORT
        )

        return ports

    def _validar_dispositivo(self, port_name):
        link = TES3600Serial(port=port_name)

        try:
            link.connect()
            link.send(COMMAND_START)

            # Lectura no bloqueante durante la validación.
            original_timeout = link.connection.timeout
            link.connection.timeout = 0

            start_time = time.monotonic()
            deadline = start_time + VALIDATION_TIMEOUT
            next_poll = start_time + INITIAL_POLL_DELAY

            received = bytearray()
            polls_sent = 0

            while time.monotonic() < deadline:
                if self.detener.is_set():
                    break

                now = time.monotonic()

                # Enviar el primer sondeo a los 95 ms
                # y continuar con el intervalo configurado.
                if now >= next_poll:
                    link.send(COMMAND_POLL)
                    polls_sent += 1

                    next_poll += POLL_INTERVAL

                    if next_poll <= now:
                        next_poll = now + POLL_INTERVAL

                response = link.receive(1)

                if response:
                    received.extend(response)

                    if STATUS_READY in response:
                        link.connection.timeout = original_timeout

                        logger.info(
                            "TES3600 validado en %s (%d sondeos).",
                            port_name,
                            polls_sent,
                        )

                        return link

                else:
                    time.sleep(0.001)

            logger.warning(
                "No se validó el dispositivo en %s. "
                "Sondeos enviados: %d. Respuesta: %s",
                port_name,
                polls_sent,
                received.hex(" ").upper() if received else "ninguna",
            )

        except Exception:
            logger.exception(
                "Error durante la validación del puerto %s.",
                port_name,
            )

        link.disconnect()
        return None

    def _gestionar_sesion(self, link):
        """Transfiere el puerto validado a la sesión de comunicación."""

        self.session = TES3600Session(
            on_block=self.on_block,
            link=link,
        )

        try:
            # El handshake ya fue realizado por el manager.
            self.session.iniciar(enviar_inicio=False)

            self._set_state(CONNECTED)

            logger.info("Comunicación con TES3600 iniciada.")

            while not self.detener.is_set():
                if self.session.detener.wait(0.2):
                    break

        finally:
            self.session.detener_sesion()
            self.session = None

            logger.warning(
                "Sesión serial finalizada. Reiniciando búsqueda."
            )

    def run(self):
        """Ejecuta continuamente la búsqueda y gestión del TES3600."""

        logger.info("Iniciando administrador serial.")

        try:
            while not self.detener.is_set():

                ports = self._buscar_puertos()

                if not ports:
                    self._set_state(WAITING_DEVICE)
                    self.detener.wait(SCAN_INTERVAL)
                    continue

                dispositivo_encontrado = False

                for port in ports:

                    if self.detener.is_set():
                        break

                    self._set_state(VALIDATING_DEVICE)

                    logger.debug(
                        "Evaluando puerto serie: %s",
                        port.device,
                    )

                    link = self._validar_dispositivo(port.device)

                    if link is None:
                        continue

                    dispositivo_encontrado = True

                    self._gestionar_sesion(link)

                    break

                if not dispositivo_encontrado:
                    self._set_state(WAITING_DEVICE)
                    self.detener.wait(SCAN_INTERVAL)

        finally:
            self._set_state(WAITING_DEVICE)
            logger.info("Administrador serial detenido.")

    def stop(self):
        """Solicita detener la búsqueda y la sesión activa."""

        self.detener.set()
