"""Indicador independiente del estado del servidor TES3600."""
# Indica un estado de catastrofe en el que todo fallo


import logging
import subprocess
import time

import gpiod
from gpiod.line import Direction, Value

GPIO_CHIP = "/dev/gpiochip1"
LED_RED = 92

SERVICE_NAME = "tes3600-server.service"
CHECK_INTERVAL = 0.5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


def main():
    settings = {
        LED_RED: gpiod.LineSettings(
            direction=Direction.OUTPUT,
            output_value=Value.ACTIVE,
        )
    }

    request = gpiod.request_lines(
        GPIO_CHIP,
        consumer="tes3600-status-led",
        config=settings,
    )

    logger.info("Indicador rojo iniciado.")

    try:
        while True:

            result = subprocess.run(
                [
                    "/usr/bin/systemctl",
                    "is-active",
                    "--quiet",
                    SERVICE_NAME,
                ],
                check=False,
                timeout=2,
            )

            # Rojo encendido cuando el servidor no está activo.
            value = (
                Value.INACTIVE
                if result.returncode == 0
                else Value.ACTIVE
            )

            request.set_value(LED_RED, value)

            time.sleep(CHECK_INTERVAL)

    finally:
        request.set_value(LED_RED, Value.INACTIVE)
        request.release()


if __name__ == "__main__":
    main()
