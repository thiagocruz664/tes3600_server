
"""Punto de entrada del servidor TES3600."""

import time

from server.tcp_server import TCPServer
from tes3600.session import TES3600Session


def main():
    tcp_server = TCPServer(host="0.0.0.0", port=9000)
    session = None

    def procesar_bloque(bloque):
        """Mostrar y retransmitir una trama sin modificarla."""
        timestamp = time.perf_counter()

#        print()
#        print(
#            f"[{timestamp:.6f}] "
#            f"TES -> TCP ({len(bloque)} bytes):"
#        )
#        print(bloque.hex(" ").upper())

        tcp_server.broadcast(bloque)

    try:
        tcp_server.start()

        session = TES3600Session(on_block=procesar_bloque)
        session.iniciar()

        print("TES3600 conectado.")
        print("Esperando mediciones y clientes TCP.")
        print("Ctrl+C para detener.")
        print()

        while not session.detener.wait(1.0):
            pass

    except KeyboardInterrupt:
        print("\nDeteniendo el servidor...")

    finally:
        if session is not None:
            session.detener_sesion()

        tcp_server.stop()
        print("Servidor finalizado.")


if __name__ == "__main__":
    main()

