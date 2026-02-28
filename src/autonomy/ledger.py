from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class CommandLedger:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    idempotency_key TEXT PRIMARY KEY,
                    expires_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS vehicle_nonce (
                    vehicle_id TEXT PRIMARY KEY,
                    last_ack_nonce INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS command_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    vehicle_id TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT
                )
                """
            )

    def is_duplicate_idempotency_key(self, idempotency_key: str) -> bool:
        now = time.time()
        with self._connect() as connection:
            connection.execute("DELETE FROM idempotency_keys WHERE expires_at < ?", (now,))
            row = connection.execute(
                "SELECT 1 FROM idempotency_keys WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            return row is not None

    def mark_idempotency_key(self, idempotency_key: str, ttl_s: float) -> None:
        expires_at = time.time() + ttl_s
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO idempotency_keys(idempotency_key, expires_at) VALUES(?, ?)",
                (idempotency_key, expires_at),
            )

    def get_last_ack_nonce(self, vehicle_id: str) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT last_ack_nonce FROM vehicle_nonce WHERE vehicle_id = ?",
                (vehicle_id,),
            ).fetchone()
            return int(row[0]) if row else None

    def update_last_ack_nonce(self, vehicle_id: str, ack_nonce: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO vehicle_nonce(vehicle_id, last_ack_nonce)
                VALUES(?, ?)
                ON CONFLICT(vehicle_id)
                DO UPDATE SET last_ack_nonce = excluded.last_ack_nonce
                """,
                (vehicle_id, ack_nonce),
            )

    def append_command_event(
        self,
        vehicle_id: str,
        command_id: str,
        idempotency_key: str,
        status: str,
        detail: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO command_events(ts, vehicle_id, command_id, idempotency_key, status, detail)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (time.time(), vehicle_id, command_id, idempotency_key, status, detail),
            )
