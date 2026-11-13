"""Botón físico de reinicio del ODROID-C2."""
# Solucion al estado de catastrofe y cualquier otro

import logging
import subprocess
import time

import gpiod
from gpiod.line import Direction, Value, Bias

GPIO_CHIP = "/dev/gpiochip1"
BUTTON_RESET = 82

POLL_INTERVAL = 0.020
DEBOUNCE_TIME = 0.050
HOLD_TIME = 2.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


def main():
    settings = {
        BUTTON_RESET: gpiod.LineSettings(
            direction=Direction.INPUT,
            bias=Bias.DISABLED,
            active_low=True,
        )
    }

    request = gpiod.request_lines(
        GPIO_CHIP,
        consumer="tes3600-reset-button",
        config=settings,
    )

    logger.info("Botón de reinicio iniciado.")

    pressed_since = None
    candidate_since = None
    stable_pressed = False
    reboot_requested = False

    try:
        while True:

            now = time.monotonic()

            # active_low=True: ACTIVE significa botón presionado.
            pressed = (
                request.get_value(BUTTON_RESET) == Value.ACTIVE
            )

            if pressed != stable_pressed:

                if candidate_since is None:
                    candidate_since = now

                elif now - candidate_since >= DEBOUNCE_TIME:

                    stable_pressed = pressed
                    candidate_since = None

                    if stable_pressed:
                        pressed_since = now
                        reboot_requested = False
                        logger.info("Botón presionado.")

                    else:
                        pressed_since = None
                        reboot_requested = False
                        logger.info("Botón liberado.")

            else:
                candidate_since = None

            if (
                stable_pressed
                and pressed_since is not None
                and not reboot_requested
                and now - pressed_since >= HOLD_TIME
            ):
                reboot_requested = True

                logger.warning(
                    "Pulsación prolongada detectada. Reiniciando ODROID."
                )

                subprocess.run(
                    ["/usr/bin/systemctl", "reboot"],
                    check=True,
                )

                break

            time.sleep(POLL_INTERVAL)

    finally:
        request.release()


if __name__ == "__main__":
    main()
