"""Decodificación de tramas del analizador TES3600."""


FRAME_START = 0x02
FRAME_END = 0x03

# Índices de los campos conocidos dentro de la trama.
# Cada campo ocupa dos bytes big-endian.
FIELD_OFFSETS = {
    "voltage": 1,
    "current": 3,
    "apparent_power": 5,
    "active_power": 7,
}

FIELD_SCALE = 10.0


class TES3600Decoder:
    """Decodifica los campos conocidos de una trama TES3600."""

    @staticmethod
    def decode_field(frame, offset):
        """Decodifica un campo de dos bytes big-endian."""
        raw_value = int.from_bytes(
            frame[offset:offset + 2],
            byteorder="big",
            signed=False,
        )
        return raw_value / FIELD_SCALE

    @classmethod
    def decode_frame(cls, frame):
        """Valida una trama y devuelve sus mediciones conocidas."""
        if len(frame) < 10:
            raise ValueError("La trama es demasiado corta.")

        if frame[0] != FRAME_START:
            raise ValueError("Byte de inicio incorrecto.")

        if frame[-1] != FRAME_END:
            raise ValueError("Byte de fin incorrecto.")

        measurements = {}

        for name, offset in FIELD_OFFSETS.items():
            measurements[name] = cls.decode_field(frame, offset)

        return measurements
