
"""Descubrimiento, validación y reconexión del TES3600."""

import logging
import threading
import time

from serial.tools import list_ports

from config import (
    SERIAL_PORT,
    COMMAND_START,
    STATUS_READY,
)
from tes3600.serial_link import TES3600Serial
from tes3600.session import TES3600Session

logger = logging.getLogger(__name__)

SCAN_INTERVAL = 1.0
VALIDATION_TIMEOUT = 0.75

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
        """
        Comprueba si el dispositivo conectado responde al handshake
        inicial del TES3600.

        Devuelve el enlace serie abierto si la validación es correcta.
        """

        link = TES3600Serial(port=port_name)

        try:
            link.connect()

            # Solicitar inicio de comunicación.
            link.send(COMMAND_START)

            deadline = time.monotonic() + VALIDATION_TIMEOUT

            while time.monotonic() < deadline:
                if self.detener.is_set():
                    break

                response = link.receive(1)

                if response:
                    if response[0] == STATUS_READY:
                        logger.info(
                            "TES3600 validado en %s.",
                            port_name,
                        )
                        return link

                    # Respuesta inesperada: descartar candidato.
                    logger.debug(
                        "Respuesta inválida en %s: %s",
                        port_name,
                        response.hex(" ").upper(),
                    )
                    break

            logger.debug(
                "El dispositivo %s no superó la validación.",
                port_name,
            )

        except Exception:
            logger.debug(
                "No se pudo validar el puerto %s.",
                port_name,
                exc_info=True,
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
