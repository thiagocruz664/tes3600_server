"""Servidor TCP para consultar mediciones históricas del TES3600."""

import logging
import socket
import struct
import threading
import time

from storage.database import RETENTION_MS

logger = logging.getLogger(__name__)

HISTORY_HOST = "0.0.0.0"
HISTORY_PORT = 9001

MAX_CLIENTS = 2
CLIENT_TIMEOUT = 10.0

HEADER_SIZE = 4
TIMESTAMP_SIZE = 8
FRAME_SIZE = 61
RECORD_SIZE = TIMESTAMP_SIZE + FRAME_SIZE

PERIODS = {
    0x01: 1 * 60 * 60 * 1000,
    0x02: 3 * 60 * 60 * 1000,
    0x03: 6 * 60 * 60 * 1000,
    0x04: 12 * 60 * 60 * 1000,
    0x05: 24 * 60 * 60 * 1000,
    0x06: 3 * 24 * 60 * 60 * 1000,
    0x07: 7 * 24 * 60 * 60 * 1000,
    0x08: 15 * 24 * 60 * 60 * 1000,
    0x09: 30 * 24 * 60 * 60 * 1000,
}


class HistoryTCPServer:
    """Atiende solicitudes de descarga de mediciones históricas."""

    def __init__(
        self,
        database,
        host=HISTORY_HOST,
        port=HISTORY_PORT,
    ):
        self.database = database
        self.host = host
        self.port = port

        self.server_socket = None
        self.accept_thread = None

        self.stop_event = threading.Event()

        self.clients = set()
        self.clients_lock = threading.Lock()

    @staticmethod
    def _recv_exact(client, size):
        """Recibe exactamente la cantidad de bytes solicitada."""

        data = bytearray()

        while len(data) < size:
            chunk = client.recv(size - len(data))

            if not chunk:
                raise ConnectionError(
                    "El cliente cerró la conexión."
                )

            data.extend(chunk)

        return bytes(data)

    def _decode_request(self, client):
        """Interpreta el código de período enviado por el cliente."""

        request = self._recv_exact(client, 1)
        code = request[0]

        now_ms = time.time_ns() // 1_000_000

        if code in PERIODS:
            duration = PERIODS[code]

            start_ms = now_ms - duration
            end_ms = now_ms

        elif code == 0x0F:
            timestamps = self._recv_exact(client, 16)

            start_ms, end_ms = struct.unpack("!QQ", timestamps)

            if start_ms > end_ms:
                raise ValueError(
                    "El timestamp inicial supera al final."
                )

            if end_ms > now_ms:
                raise ValueError(
                    "El timestamp final está en el futuro."
                )

        else:
            raise ValueError(
                f"Código de solicitud desconocido: 0x{code:02X}"
            )

        retention_start = now_ms - RETENTION_MS

        start_ms = max(start_ms, retention_start)

        return start_ms, end_ms

    def _send_measurements(self, client, start_ms, end_ms):
        """Envía las mediciones correspondientes al período solicitado."""

        count = 0

        for timestamp_ms, frame in self.database.iter_measurements(
            start_ms,
            end_ms,
        ):
            if self.stop_event.is_set():
                break

            if len(frame) != FRAME_SIZE:
                logger.warning(
                    "Se omitió una medición con longitud incorrecta."
                )
                continue

            header = struct.pack("!I", RECORD_SIZE)
            timestamp = struct.pack("!Q", timestamp_ms)

            client.sendall(header + timestamp + frame)

            count += 1

        if not self.stop_event.is_set():
            client.sendall(struct.pack("!I", 0))

        logger.info(
            "Historial enviado: %d mediciones.",
            count,
        )

    def _handle_client(self, client, address):
        """Procesa una solicitud histórica."""

        try:
            client.settimeout(CLIENT_TIMEOUT)

            logger.info(
                "Cliente histórico conectado: %s:%s",
                address[0],
                address[1],
            )

            start_ms, end_ms = self._decode_request(client)

            logger.info(
                "Consulta histórica: %d a %d",
                start_ms,
                end_ms,
            )

            self._send_measurements(
                client,
                start_ms,
                end_ms,
            )

        except (OSError, ConnectionError, ValueError, struct.error):
            logger.exception(
                "Error procesando solicitud histórica."
            )

        finally:
            with self.clients_lock:
                self.clients.discard(client)

            try:
                client.close()
            except OSError:
                pass

            logger.info("Cliente histórico desconectado.")

    def _accept_loop(self, server_socket):
        """Acepta conexiones históricas."""

        while not self.stop_event.is_set():

            try:
                client, address = server_socket.accept()

            except socket.timeout:
                continue

            except OSError:
                if not self.stop_event.is_set():
                    logger.exception(
                        "Error durante la escucha histórica."
                    )
                break

            with self.clients_lock:

                if (
                    self.stop_event.is_set()
                    or len(self.clients) >= MAX_CLIENTS
                ):
                    aceptar = False
                else:
                    self.clients.add(client)
                    aceptar = True

            if not aceptar:
                client.close()
                continue

            thread = threading.Thread(
                target=self._handle_client,
                args=(client, address),
                name="history-client",
                daemon=True,
            )

            thread.start()

    def start(self):
        """Inicia el servidor histórico."""

        if self.server_socket is not None:
            raise RuntimeError(
                "El servidor histórico ya está iniciado."
            )

        self.stop_event.clear()

        server_socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
        )

        server_socket.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1,
        )

        try:
            server_socket.bind((self.host, self.port))
            server_socket.listen()
            server_socket.settimeout(0.5)

        except OSError:
            server_socket.close()
            raise

        self.server_socket = server_socket

        self.accept_thread = threading.Thread(
            target=self._accept_loop,
            args=(server_socket,),
            name="history-accept",
            daemon=True,
        )

        self.accept_thread.start()

        logger.info(
            "Servidor histórico escuchando en %s:%s",
            self.host,
            self.port,
        )

    def stop(self):
        """Detiene el servidor y cierra sus conexiones."""

        self.stop_event.set()

        server_socket = self.server_socket
        self.server_socket = None

        if server_socket is not None:
            try:
                server_socket.close()
            except OSError:
                pass

        with self.clients_lock:
            clients = tuple(self.clients)

        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

            try:
                client.close()
            except OSError:
                pass

        if self.accept_thread is not None:
            self.accept_thread.join(timeout=2.0)
            self.accept_thread = None

        logger.info("Servidor histórico detenido.")
