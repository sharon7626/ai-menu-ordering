import os
import unittest
from unittest.mock import patch

from backend.database import (
    POSTGRES_SCHEMA_STATEMENTS,
    _row_lock_suffix,
    connect_database,
    initialize_database,
)
from backend.database_compat import (
    PostgreSQLConnection,
    is_postgresql_url,
    normalize_postgresql_url,
)


class FakeCursor:
    def __init__(self, row=None, rowcount=1):
        self.row = row
        self.rowcount = rowcount
        self.executemany_call = None

    def fetchone(self):
        return self.row

    def fetchall(self):
        return []

    def executemany(self, sql, rows):
        self.executemany_call = (sql, rows)


class FakePsycopgConnection:
    def __init__(self):
        self.calls = []
        self.cursor_instance = FakeCursor()

    def execute(self, sql, parameters):
        self.calls.append((sql, parameters))
        row = {"id": 37} if "RETURNING id" in sql else None
        return FakeCursor(row=row)

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class FakeSchemaConnection:
    backend = "postgresql"

    def __init__(self):
        self.statements = []
        self.committed = False
        self.closed = False

    def execute(self, statement):
        self.statements.append(statement)

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("schema initialization should not roll back")

    def close(self):
        self.closed = True


class PostgreSQLCompatibilityTests(unittest.TestCase):
    def test_render_postgres_urls_are_supported_and_normalized(self):
        self.assertTrue(is_postgresql_url("postgresql://user:secret@host/database"))
        self.assertTrue(is_postgresql_url("postgres://user:secret@host/database"))
        self.assertEqual(
            normalize_postgresql_url("postgres://user:secret@host/database"),
            "postgresql://user:secret@host/database",
        )

    def test_adapter_converts_parameters_and_returns_insert_id(self):
        raw_connection = FakePsycopgConnection()
        connection = PostgreSQLConnection(raw_connection)

        cursor = connection.execute(
            "INSERT INTO orders (customer_name, total_amount) VALUES (?, ?)",
            ("測試", 100),
        )

        sql, parameters = raw_connection.calls[0]
        self.assertIn("VALUES (%s, %s) RETURNING id", sql)
        self.assertEqual(parameters, ("測試", 100))
        self.assertEqual(cursor.lastrowid, 37)

    def test_adapter_maps_sqlite_immediate_transaction_to_postgres(self):
        raw_connection = FakePsycopgConnection()
        connection = PostgreSQLConnection(raw_connection)

        connection.execute("BEGIN IMMEDIATE")

        self.assertEqual(raw_connection.calls[0], ("BEGIN", ()))
        self.assertEqual(_row_lock_suffix(connection, "group_sessions"), " FOR UPDATE OF group_sessions")

    def test_postgres_schema_initialization_is_repeatable_and_secret_safe(self):
        fake_connection = FakeSchemaConnection()
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://user:secret@host/database"},
        ):
            with patch(
                "backend.database.connect_postgresql",
                return_value=fake_connection,
            ) as connect:
                initialized = initialize_database()

        self.assertEqual(initialized, "PostgreSQL")
        connect.assert_called_once_with("postgresql://user:secret@host/database")
        self.assertEqual(fake_connection.statements, list(POSTGRES_SCHEMA_STATEMENTS))
        self.assertTrue(fake_connection.committed)
        self.assertTrue(fake_connection.closed)
        combined_schema = "\n".join(fake_connection.statements)
        self.assertIn("CREATE TABLE IF NOT EXISTS group_sessions", combined_schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS store_profiles", combined_schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS orders", combined_schema)
        self.assertNotIn("user:secret", combined_schema)

    def test_connect_database_routes_postgres_url_without_treating_it_as_path(self):
        sentinel = object()
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://user:secret@host/database"},
        ):
            with patch(
                "backend.database.connect_postgresql",
                return_value=sentinel,
            ) as connect:
                connection = connect_database()

        self.assertIs(connection, sentinel)
        connect.assert_called_once_with("postgresql://user:secret@host/database")


if __name__ == "__main__":
    unittest.main()
