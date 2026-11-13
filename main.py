"""Punto de entrada del servidor TES3600."""

import logging
import threading

from server.tcp_server import TCPServer
from tes3600.serial_manager import SerialManager

from hardware.gpio_manager import GPIOManager

logger = logging.getLogger(__name__)

TCP_RETRY_INTERVAL = 5.0


def main():
    gpio = GPIOManager()

    tcp_server = TCPServer(
        host="0.0.0.0",
        port=9000,
        on_state=gpio.set_tcp_state,
    )

    def procesar_bloque(bloque):
        """Retransmite las tramas recibidas a los clientes TCP."""
        tcp_server.broadcast(bloque)

    manager = SerialManager(
        on_block=procesar_bloque,
        on_state=gpio.set_serial_state,
    )

    tcp_retry_stop = threading.Event()

    def recuperar_tcp():
        """Reintenta iniciar el servidor TCP cuando no está disponible."""

        while not tcp_retry_stop.is_set():

            if tcp_server.server_socket is None:

                try:
                    tcp_server.start()

                except OSError:
                    logger.exception(
                        "No se pudo iniciar el servidor TCP. "
                        "Nuevo intento en %.1f segundos.",
                        TCP_RETRY_INTERVAL,
                    )

            tcp_retry_stop.wait(TCP_RETRY_INTERVAL)

    tcp_retry_thread = None

    try:
        try:
            tcp_server.start()

        except OSError:
            logger.exception(
                "Error inicializando TCP. "
                "Se continuará intentando."
            )

        tcp_retry_thread = threading.Thread(
            target=recuperar_tcp,
            name="tcp-recovery",
            daemon=True,
        )
        tcp_retry_thread.start()

        logger.info("Servidor TES3600 iniciado.")
        logger.info("Buscando dispositivo serial.")

        manager.run()

    except KeyboardInterrupt:
        logger.info("Interrupción solicitada.")

    except Exception:
        logger.exception("Error irrecuperable en el servidor.")
        raise

    finally:
        logger.info("Iniciando cierre del servidor.")

        manager.stop()

        tcp_retry_stop.set()

        if tcp_retry_thread is not None:
            tcp_retry_thread.join(timeout=2.0)

        tcp_server.stop()
        gpio.close()

        logger.info("Servidor finalizado.")


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "[%(levelname)s] "
            "%(name)s: %(message)s"
        ),
    )

    main()
