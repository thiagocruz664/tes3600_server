
"""Almacenamiento local de mediciones del TES3600 mediante SQLite."""

import logging
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

FRAME_SIZE = 61
FRAME_START = 0x02
FRAME_END = 0x03

RETENTION_DAYS = 30
RETENTION_MS = RETENTION_DAYS * 24 * 60 * 60 * 1000

CLEANUP_INTERVAL = 1000


class MeasurementDatabase:
    """Almacena las tramas originales y sus marcas temporales."""

    def __init__(self, database_path=None):
        if database_path is None:
            database_path = (
                Path(__file__).resolve().parent / "measurements.db"
            )

        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        self.lock = threading.Lock()
        self.insert_count = 0

        self.connection = sqlite3.connect(
            self.database_path,
            timeout=5.0,
            check_same_thread=False,
        )

        self._initialize()
        self.cleanup()

        logger.info(
            "Base de datos inicializada: %s",
            self.database_path,
        )

    def _initialize(self):
        """Configura SQLite y crea la estructura necesaria."""

        with self.lock:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=NORMAL")
            self.connection.execute("PRAGMA busy_timeout=5000")

            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS measurements (
                    id INTEGER PRIMARY KEY,
                    timestamp_ms INTEGER NOT NULL,
                    frame BLOB NOT NULL
                        CHECK(length(frame) = 61)
                )
                """
            )

            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_measurements_timestamp
                ON measurements(timestamp_ms)
                """
            )

            self.connection.commit()

    @staticmethod
    def is_valid_frame(frame):
        """Comprueba longitud y delimitadores de una medición."""

        return (
            isinstance(frame, bytes)
            and len(frame) == FRAME_SIZE
            and frame[0] == FRAME_START
            and frame[-1] == FRAME_END
        )

    def save_measurement(self, frame):
        """Guarda una medición válida con timestamp Unix en ms."""

        if not self.is_valid_frame(frame):
            logger.warning(
                "Se descartó una trama inválida para almacenamiento "
                "(tamaño: %d bytes).",
                len(frame) if isinstance(frame, bytes) else -1,
            )
            return False

        timestamp_ms = time.time_ns() // 1_000_000

        with self.lock:
            self.connection.execute(
                """
                INSERT INTO measurements(timestamp_ms, frame)
                VALUES (?, ?)
                """,
                (timestamp_ms, sqlite3.Binary(frame)),
            )

            self.connection.commit()
            self.insert_count += 1

            if self.insert_count >= CLEANUP_INTERVAL:
                self._cleanup_locked()
                self.insert_count = 0

        return True

    def _cleanup_locked(self):
        """Elimina registros anteriores al período de retención."""

        cutoff = time.time_ns() // 1_000_000 - RETENTION_MS

        cursor = self.connection.execute(
            """
            DELETE FROM measurements
            WHERE timestamp_ms < ?
            """,
            (cutoff,),
        )

        self.connection.commit()

        if cursor.rowcount:
            logger.info(
                "Retención: se eliminaron %d mediciones antiguas.",
                cursor.rowcount,
            )

    def cleanup(self):
        """Ejecuta la limpieza de registros antiguos."""

        with self.lock:
            self._cleanup_locked()

    def close(self):
        """Cierra la conexión con la base de datos."""

        with self.lock:
            if self.connection is not None:
                self.connection.close()
                self.connection = None

        logger.info("Base de datos cerrada.")
