
"""Codificación de mensajes para el transporte TCP."""

import struct
from datetime import datetime

HEADER_SIZE = 4
TIMESTAMP_SIZE = 4
MAX_FRAME_SIZE = 1024 * 1024


def encode_frame(frame: bytes) -> bytes:
    """Codificar longitud, marca temporal y trama original."""
    if not isinstance(frame, bytes):
        raise TypeError("La trama debe ser de tipo bytes.")

    if not frame:
        raise ValueError("No se pueden transmitir tramas vacías.")

    if len(frame) > MAX_FRAME_SIZE:
        raise ValueError("La trama supera el tamaño máximo permitido.")

    ahora = datetime.now()

    milisegundos_desde_medianoche = (
        (ahora.hour * 3600 + ahora.minute * 60 + ahora.second) * 1000
        + ahora.microsecond // 1000
    )

    longitud = struct.pack("!I", len(frame) + TIMESTAMP_SIZE)
    timestamp = struct.pack("!I", milisegundos_desde_medianoche)

    return longitud + timestamp + frame
