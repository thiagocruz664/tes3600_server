
"""Servidor TCP para retransmitir tramas del TES3600."""

import socket
import threading

from protocol.messages import encode_frame


MAX_CLIENTS = 4
CLIENT_TIMEOUT = 0.5


class TCPServer:
    """Acepta clientes TCP y distribuye las tramas recibidas."""

    def __init__(self, host="0.0.0.0", port=9000):
        self.host = host
        self.port = port

        self.server_socket = None
        self.accept_thread = None

        self.detener = threading.Event()
        self.clients = set()
        self.clients_lock = threading.Lock()

    def start(self):
        """Inicia el servidor TCP."""
        if self.server_socket is not None:
            raise RuntimeError("El servidor TCP ya fue iniciado.")

        self.detener.clear()

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
            name="tcp-accept",
            daemon=True,
        )
        self.accept_thread.start()

        print(f"Servidor TCP escuchando en {self.host}:{self.port}")

    def _accept_loop(self, server_socket):
        """Acepta conexiones y limita los clientes simultáneos."""
        while not self.detener.is_set():
            try:
                client, address = server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                if not self.detener.is_set():
                    print("Error: se interrumpió la escucha TCP.")
                break

            client.settimeout(CLIENT_TIMEOUT)

            with self.clients_lock:
                if self.detener.is_set():
                    aceptar = False
                elif len(self.clients) >= MAX_CLIENTS:
                    aceptar = False
                else:
                    self.clients.add(client)
                    aceptar = True

            if not aceptar:
                client.close()
                continue

            print(
                f"Cliente TCP conectado: "
                f"{address[0]}:{address[1]}"
            )

    def _remove_client(self, client):
        """Elimina y cierra un cliente de forma segura."""
        with self.clients_lock:
            registrado = client in self.clients
            self.clients.discard(client)

        try:
            client.close()
        except OSError:
            pass

        if registrado:
            print("Cliente TCP desconectado.")

    def broadcast(self, frame: bytes):
        """Envía una trama a los clientes sin bloquear el registro."""
        if self.detener.is_set():
            return

        message = encode_frame(frame)

        with self.clients_lock:
            clients = tuple(self.clients)

        for client in clients:
            if self.detener.is_set():
                break

            try:
                client.sendall(message)
            except (OSError, socket.timeout):
                self._remove_client(client)

    def stop(self):
        """Cierra el servidor y todas las conexiones activas."""
        self.detener.set()

        server_socket = self.server_socket
        self.server_socket = None

        if server_socket is not None:
            try:
                server_socket.close()
            except OSError:
                pass

        if self.accept_thread is not None:
            self.accept_thread.join(timeout=1.0)
            self.accept_thread = None

        with self.clients_lock:
            clients = tuple(self.clients)
            self.clients.clear()

        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

            try:
                client.close()
            except OSError:
                pass

        print("Servidor TCP detenido.")
