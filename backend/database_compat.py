"""讓既有 DB-API 寫法可同時使用 SQLite 與 PostgreSQL。"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Iterable

try:
    import psycopg
    from psycopg.rows import dict_row
except ModuleNotFoundError:  # 本機尚未安裝部署套件時提供清楚錯誤。
    psycopg = None
    dict_row = None


POSTGRES_URL_PREFIXES = ("postgresql://", "postgres://")
DATABASE_ERROR_TYPES = (
    (sqlite3.Error, psycopg.Error) if psycopg is not None else (sqlite3.Error,)
)
INTEGRITY_ERROR_TYPES = (
    (sqlite3.IntegrityError, psycopg.IntegrityError)
    if psycopg is not None
    else (sqlite3.IntegrityError,)
)

_INSERT_WITH_ID = re.compile(
    r"^\s*INSERT\s+INTO\s+(group_sessions|store_profiles|orders)\b",
    re.IGNORECASE,
)


def is_postgresql_url(database_url: str) -> bool:
    return database_url.startswith(POSTGRES_URL_PREFIXES)


def normalize_postgresql_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql://" + database_url.removeprefix("postgres://")
    return database_url


def _postgresql_sql(sql: str) -> str:
    normalized = sql.strip()
    if normalized.upper() == "BEGIN IMMEDIATE":
        return "BEGIN"
    return sql.replace("?", "%s")


class PostgreSQLCursor:
    """提供既有程式會使用的 cursor 最小介面。"""

    def __init__(self, cursor: Any, *, lastrowid: int | None = None) -> None:
        self._cursor = cursor
        self.lastrowid = lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        return self._cursor.fetchall()


class PostgreSQLConnection:
    """將 Psycopg 連線包成既有 SQLite 呼叫方式。"""

    backend = "postgresql"

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    @property
    def in_transaction(self) -> bool:
        if psycopg is None:
            return False
        return self._connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE

    def execute(
        self,
        sql: str,
        parameters: Iterable[Any] | None = None,
    ) -> PostgreSQLCursor:
        statement = _postgresql_sql(sql)
        needs_id = bool(_INSERT_WITH_ID.match(statement)) and "RETURNING" not in statement.upper()
        if needs_id:
            statement = statement.rstrip().rstrip(";") + " RETURNING id"
        cursor = self._connection.execute(statement, tuple(parameters or ()))
        lastrowid = None
        if needs_id:
            returned = cursor.fetchone()
            if returned is not None:
                lastrowid = returned["id"]
        return PostgreSQLCursor(cursor, lastrowid=lastrowid)

    def executemany(
        self,
        sql: str,
        parameter_rows: Iterable[Iterable[Any]],
    ) -> PostgreSQLCursor:
        cursor = self._connection.cursor()
        cursor.executemany(
            _postgresql_sql(sql),
            [tuple(parameters) for parameters in parameter_rows],
        )
        return PostgreSQLCursor(cursor)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


def connect_postgresql(database_url: str) -> PostgreSQLConnection:
    if psycopg is None:
        raise RuntimeError(
            "PostgreSQL 需要安裝 requirements.txt 中的 psycopg 套件"
        )
    connection = psycopg.connect(
        normalize_postgresql_url(database_url),
        row_factory=dict_row,
    )
    return PostgreSQLConnection(connection)


def is_postgresql_connection(connection: Any) -> bool:
    return getattr(connection, "backend", None) == "postgresql"
