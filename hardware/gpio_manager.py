"""Control de los indicadores GPIO del servidor TES3600."""

import logging
import threading
import time

import gpiod
from gpiod.line import Direction, Value

logger = logging.getLogger(__name__)

GPIO_CHIP = "/dev/gpiochip1"

# Offsets confirmados mediante gpioinfo en el ODROID-C2.
LED_SERIAL = 83
LED_TCP = 98
LED_GREEN = 78

BLINK_PERIOD = 1.0
UPDATE_INTERVAL = 0.05

# Estados seriales
WAITING_DEVICE = "WAITING_DEVICE"
VALIDATING_DEVICE = "VALIDATING_DEVICE"
SERIAL_CONNECTED = "CONNECTED"

# Estados TCP
TCP_ERROR = "TCP_ERROR"
TCP_WAITING_CLIENT = "TCP_WAITING_CLIENT"
TCP_CONNECTED = "TCP_CONNECTED"


class GPIOManager:
    """Administra los indicadores LED del servidor principal."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()

        self.serial_state = WAITING_DEVICE
        self.tcp_state = TCP_ERROR

        self.outputs = {
            LED_SERIAL: False,
            LED_TCP: False,
            LED_GREEN: False,
        }

        config = {
            LED_SERIAL: gpiod.LineSettings(
                direction=Direction.OUTPUT,
                output_value=Value.INACTIVE,
            ),
            LED_TCP: gpiod.LineSettings(
                direction=Direction.OUTPUT,
                output_value=Value.INACTIVE,
            ),
            LED_GREEN: gpiod.LineSettings(
                direction=Direction.OUTPUT,
                output_value=Value.INACTIVE,
            ),
        }

        self.request = gpiod.request_lines(
            GPIO_CHIP,
            consumer="tes3600-server",
            config=config,
        )

        self.thread = threading.Thread(
            target=self._update_loop,
            name="gpio-led-controller",
            daemon=True,
        )

        self.thread.start()

        logger.info("Controlador GPIO inicializado.")

    def set_serial_state(self, state):
        """Actualiza el estado del indicador serial."""

        valid_states = {
            WAITING_DEVICE,
            VALIDATING_DEVICE,
            SERIAL_CONNECTED,
        }

        if state not in valid_states:
            raise ValueError(f"Estado serial desconocido: {state}")

        with self.lock:
            self.serial_state = state

        logger.info("Estado serial actualizado: %s", state)

    def set_tcp_state(self, state):
        """Actualiza el estado del indicador TCP."""

        valid_states = {
            TCP_ERROR,
            TCP_WAITING_CLIENT,
            TCP_CONNECTED,
        }

        if state not in valid_states:
            raise ValueError(f"Estado TCP desconocido: {state}")

        with self.lock:
            self.tcp_state = state

        logger.info("Estado TCP actualizado: %s", state)

    def _calculate_outputs(self):
        """Calcula el estado deseado de los tres indicadores."""

        now = time.monotonic()
        blink_on = (now % BLINK_PERIOD) < (BLINK_PERIOD / 2)

        # LED serial
        if self.serial_state == WAITING_DEVICE:
            serial_led = True

        elif self.serial_state == VALIDATING_DEVICE:
            serial_led = blink_on

        else:
            serial_led = False

        # LED TCP
        if self.tcp_state == TCP_ERROR:
            tcp_led = True

        elif self.tcp_state == TCP_WAITING_CLIENT:
            tcp_led = blink_on

        else:
            tcp_led = False

        # LED verde: todos los subsistemas operativos.
        green_led = (
            self.serial_state == SERIAL_CONNECTED
            and self.tcp_state == TCP_CONNECTED
        )

        return {
            LED_SERIAL: serial_led,
            LED_TCP: tcp_led,
            LED_GREEN: green_led,
        }

    def _apply_outputs(self, desired):
        """Actualiza únicamente las salidas que cambiaron."""

        with self.lock:
            for offset, value in desired.items():

                if self.outputs[offset] == value:
                    continue

                self.request.set_value(
                    offset,
                    Value.ACTIVE if value else Value.INACTIVE,
                )

                self.outputs[offset] = value

    def _update_loop(self):
        """Actualiza periódicamente los indicadores."""

        while not self.stop_event.is_set():

            try:
                desired = self._calculate_outputs()
                self._apply_outputs(desired)

            except Exception:
                logger.exception("Error actualizando los GPIO.")
                self.stop_event.set()
                break

            self.stop_event.wait(UPDATE_INTERVAL)

    def close(self):
        """Apaga los indicadores y libera los GPIO."""

        self.stop_event.set()
        self.thread.join(timeout=1.0)

        with self.lock:
            for offset in self.outputs:
                try:
                    self.request.set_value(
                        offset,
                        Value.INACTIVE,
                    )
                except Exception:
                    logger.exception(
                        "No se pudo apagar el GPIO %s.",
                        offset,
                    )

            self.request.release()

        logger.info("Controlador GPIO liberado.")
