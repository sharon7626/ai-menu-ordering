import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.database_compat import (
    connect_postgresql,
    is_postgresql_connection,
    is_postgresql_url,
)
from backend.schemas import AcceptedOrder


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_URL = "sqlite:///./app.db"
SQLITE_URL_PREFIX = "sqlite:///"

POSTGRES_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS group_sessions (
        id BIGSERIAL PRIMARY KEY,
        public_code TEXT NOT NULL UNIQUE CHECK (
            char_length(public_code) = 6
            AND public_code ~ '^[A-HJ-NP-Z2-9]{6}$'
        ),
        management_token_hash TEXT NOT NULL UNIQUE CHECK (
            char_length(management_token_hash) = 64
            AND management_token_hash ~ '^[0-9a-f]{64}$'
        ),
        status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
        next_order_sequence INTEGER NOT NULL DEFAULT 1 CHECK (next_order_sequence >= 1),
        created_at TEXT NOT NULL,
        closed_at TEXT,
        CHECK (
            (status = 'open' AND closed_at IS NULL)
            OR (status = 'closed' AND closed_at IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS group_menus (
        group_session_id BIGINT PRIMARY KEY REFERENCES group_sessions(id),
        menu_json TEXT NOT NULL CHECK (jsonb_typeof(menu_json::jsonb) = 'object'),
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS store_profiles (
        id BIGSERIAL PRIMARY KEY,
        public_slug TEXT NOT NULL UNIQUE CHECK (
            char_length(public_slug) = 8
            AND public_slug ~ '^[a-z]{8}$'
        ),
        management_token_hash TEXT NOT NULL UNIQUE CHECK (
            char_length(management_token_hash) = 64
            AND management_token_hash ~ '^[0-9a-f]{64}$'
        ),
        active SMALLINT NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        next_order_sequence INTEGER NOT NULL DEFAULT 1 CHECK (next_order_sequence >= 1),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS store_menus (
        store_profile_id BIGINT PRIMARY KEY REFERENCES store_profiles(id),
        menu_json TEXT NOT NULL CHECK (jsonb_typeof(menu_json::jsonb) = 'object'),
        version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        id BIGSERIAL PRIMARY KEY,
        group_session_id BIGINT REFERENCES group_sessions(id),
        store_profile_id BIGINT REFERENCES store_profiles(id),
        public_order_number TEXT,
        order_access_token_hash TEXT,
        customer_name TEXT NOT NULL CHECK (char_length(trim(customer_name)) > 0),
        total_amount INTEGER NOT NULL CHECK (total_amount >= 0),
        created_at TEXT NOT NULL,
        CHECK (
            (
                group_session_id IS NULL
                AND store_profile_id IS NULL
                AND public_order_number IS NULL
                AND order_access_token_hash IS NULL
            )
            OR (
                (group_session_id IS NOT NULL OR store_profile_id IS NOT NULL)
                AND public_order_number IS NOT NULL
                AND order_access_token_hash IS NOT NULL
            )
        ),
        CHECK (NOT (group_session_id IS NOT NULL AND store_profile_id IS NOT NULL))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS order_items (
        id BIGSERIAL PRIMARY KEY,
        order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        item_id TEXT NOT NULL CHECK (char_length(trim(item_id)) > 0),
        item_name TEXT NOT NULL CHECK (char_length(trim(item_name)) > 0),
        unit_price INTEGER NOT NULL CHECK (unit_price >= 0),
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        note TEXT NOT NULL DEFAULT '' CHECK (char_length(note) <= 200),
        subtotal INTEGER NOT NULL CHECK (
            subtotal >= 0 AND subtotal = unit_price * quantity
        )
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id)",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_public_order_number
    ON orders(public_order_number) WHERE public_order_number IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_access_token_hash
    ON orders(order_access_token_hash) WHERE order_access_token_hash IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_orders_group_created_at
    ON orders(group_session_id, created_at) WHERE group_session_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_orders_store_created_at
    ON orders(store_profile_id, created_at) WHERE store_profile_id IS NOT NULL
    """,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS group_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_code TEXT NOT NULL UNIQUE CHECK (
        length(public_code) = 6
        AND public_code NOT GLOB '*[^A-HJ-NP-Z2-9]*'
    ),
    management_token_hash TEXT NOT NULL UNIQUE CHECK (
        length(management_token_hash) = 64
        AND management_token_hash NOT GLOB '*[^0-9a-f]*'
    ),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    next_order_sequence INTEGER NOT NULL DEFAULT 1 CHECK (next_order_sequence >= 1),
    created_at TEXT NOT NULL,
    closed_at TEXT,
    CHECK (
        (status = 'open' AND closed_at IS NULL)
        OR (status = 'closed' AND closed_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS group_menus (
    group_session_id INTEGER PRIMARY KEY,
    menu_json TEXT NOT NULL CHECK (json_valid(menu_json)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (group_session_id) REFERENCES group_sessions(id)
);

CREATE TABLE IF NOT EXISTS store_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_slug TEXT NOT NULL UNIQUE CHECK (
        length(public_slug) = 8
        AND public_slug NOT GLOB '*[^a-z]*'
    ),
    management_token_hash TEXT NOT NULL UNIQUE CHECK (
        length(management_token_hash) = 64
        AND management_token_hash NOT GLOB '*[^0-9a-f]*'
    ),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    next_order_sequence INTEGER NOT NULL DEFAULT 1 CHECK (next_order_sequence >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS store_menus (
    store_profile_id INTEGER PRIMARY KEY,
    menu_json TEXT NOT NULL CHECK (json_valid(menu_json)),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (store_profile_id) REFERENCES store_profiles(id)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_session_id INTEGER,
    store_profile_id INTEGER,
    public_order_number TEXT,
    order_access_token_hash TEXT,
    customer_name TEXT NOT NULL CHECK (length(trim(customer_name)) > 0),
    total_amount INTEGER NOT NULL CHECK (total_amount >= 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY (group_session_id) REFERENCES group_sessions(id),
    FOREIGN KEY (store_profile_id) REFERENCES store_profiles(id),
    CHECK (
        (
            group_session_id IS NULL
            AND store_profile_id IS NULL
            AND public_order_number IS NULL
            AND order_access_token_hash IS NULL
        )
        OR (
            (group_session_id IS NOT NULL OR store_profile_id IS NOT NULL)
            AND public_order_number IS NOT NULL
            AND order_access_token_hash IS NOT NULL
        )
    ),
    CHECK (NOT (group_session_id IS NOT NULL AND store_profile_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    item_id TEXT NOT NULL CHECK (length(trim(item_id)) > 0),
    item_name TEXT NOT NULL CHECK (length(trim(item_name)) > 0),
    unit_price INTEGER NOT NULL CHECK (unit_price >= 0),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 200),
    subtotal INTEGER NOT NULL CHECK (
        subtotal >= 0 AND subtotal = unit_price * quantity
    ),
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_orders_created_at
ON orders(created_at);

CREATE INDEX IF NOT EXISTS idx_order_items_order_id
ON order_items(order_id);
"""

ORDER_GROUP_COLUMNS = {
    "group_session_id": (
        "INTEGER REFERENCES group_sessions(id)"
    ),
    "public_order_number": "TEXT",
    "order_access_token_hash": "TEXT",
}

GROUP_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_orders_created_at
ON orders(created_at);

CREATE INDEX IF NOT EXISTS idx_order_items_order_id
ON order_items(order_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_public_order_number
ON orders(public_order_number)
WHERE public_order_number IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_access_token_hash
ON orders(order_access_token_hash)
WHERE order_access_token_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_orders_group_created_at
ON orders(group_session_id, created_at)
WHERE group_session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_orders_store_created_at
ON orders(store_profile_id, created_at)
WHERE store_profile_id IS NOT NULL;
"""


class GroupNotFoundError(ValueError):
    """公開團購代碼不存在。"""


class GroupClosedError(ValueError):
    """團購已關閉，不能再建立訂單。"""


class GroupOrderValidationError(ValueError):
    """訂單選擇與團購菜單快照不一致。"""


class GroupOrderAccessDeniedError(ValueError):
    """個人訂單不存在或查看 Token 不正確。"""


class GroupManagementAccessDeniedError(ValueError):
    """團購不存在或統籌管理 Token 不正確。"""


class StoreNotFoundError(ValueError):
    """固定店家識別碼不存在。"""


class StoreManagementAccessDeniedError(ValueError):
    """店家不存在或店家管理 Token 不正確。"""


class StoreInactiveError(ValueError):
    """店家目前暫停接單。"""


class StoreOrderValidationError(ValueError):
    """訂單選擇與店家目前菜單不一致。"""


class StoreOrderAccessDeniedError(ValueError):
    """店家個人訂單不存在或查看 Token 不正確。"""


def get_database_path(database_url: str | None = None) -> Path:
    """將 SQLite 連線字串轉成專案可使用的檔案路徑。"""
    resolved_url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    if not resolved_url.startswith(SQLITE_URL_PREFIX):
        raise ValueError("目前只支援 sqlite:/// 開頭的 DATABASE_URL")

    database_path = Path(resolved_url.removeprefix(SQLITE_URL_PREFIX))
    if not str(database_path).strip():
        raise ValueError("DATABASE_URL 必須包含 SQLite 檔案路徑")
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path
    return database_path.resolve()


def connect_database(database_path: Path | None = None) -> Any:
    """依 DATABASE_URL 建立 SQLite 或 PostgreSQL 連線。"""
    if database_path is None:
        database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
        if is_postgresql_url(database_url):
            return connect_postgresql(database_url)

    resolved_path = (database_path or get_database_path()).resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(resolved_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: Path | None = None) -> Path | str:
    """依環境初始化 SQLite，或建立空的 PostgreSQL 正式資料表。"""
    if database_path is None:
        database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
        if is_postgresql_url(database_url):
            connection = connect_postgresql(database_url)
            try:
                for statement in POSTGRES_SCHEMA_STATEMENTS:
                    connection.execute(statement)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
            return "PostgreSQL"

    resolved_path = (database_path or get_database_path()).resolve()
    connection = connect_database(resolved_path)
    try:
        connection.executescript(SCHEMA_SQL)
        _add_missing_order_group_columns(connection)
        _migrate_orders_for_store_support(connection)
        _add_missing_order_item_note_column(connection)
        connection.executescript(GROUP_INDEX_SQL)
        connection.commit()
    finally:
        connection.close()
    return resolved_path


def _row_lock_suffix(connection: Any, table_name: str) -> str:
    """PostgreSQL 需鎖定流水號資料列；SQLite 由 BEGIN IMMEDIATE 負責。"""
    if is_postgresql_connection(connection):
        return f" FOR UPDATE OF {table_name}"
    return ""


def _add_missing_order_group_columns(connection: sqlite3.Connection) -> None:
    """替既有第一階段資料庫補上可為空的團購欄位。"""
    existing_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(orders)")
    }
    for column_name, column_definition in ORDER_GROUP_COLUMNS.items():
        if column_name not in existing_columns:
            connection.execute(
                f"ALTER TABLE orders ADD COLUMN {column_name} {column_definition}"
            )


def _add_missing_order_item_note_column(connection: sqlite3.Connection) -> None:
    """替既有訂單明細補上每個餐點的選填備註。"""
    existing_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(order_items)")
    }
    if "note" not in existing_columns:
        connection.execute(
            "ALTER TABLE order_items ADD COLUMN note TEXT NOT NULL DEFAULT ''"
        )


def _migrate_orders_for_store_support(connection: sqlite3.Connection) -> None:
    """重建既有訂單表，加入店家關聯並保留全部舊資料與明細。"""
    existing_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(orders)")
    }
    if "store_profile_id" in existing_columns:
        return

    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.executescript(
            """
            BEGIN IMMEDIATE;

            ALTER TABLE order_items RENAME TO order_items_before_store;
            ALTER TABLE orders RENAME TO orders_before_store;

            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_session_id INTEGER,
                store_profile_id INTEGER,
                public_order_number TEXT,
                order_access_token_hash TEXT,
                customer_name TEXT NOT NULL CHECK (length(trim(customer_name)) > 0),
                total_amount INTEGER NOT NULL CHECK (total_amount >= 0),
                created_at TEXT NOT NULL,
                FOREIGN KEY (group_session_id) REFERENCES group_sessions(id),
                FOREIGN KEY (store_profile_id) REFERENCES store_profiles(id),
                CHECK (
                    (
                        group_session_id IS NULL
                        AND store_profile_id IS NULL
                        AND public_order_number IS NULL
                        AND order_access_token_hash IS NULL
                    )
                    OR (
                        (group_session_id IS NOT NULL OR store_profile_id IS NOT NULL)
                        AND public_order_number IS NOT NULL
                        AND order_access_token_hash IS NOT NULL
                    )
                ),
                CHECK (
                    NOT (
                        group_session_id IS NOT NULL
                        AND store_profile_id IS NOT NULL
                    )
                )
            );

            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                item_id TEXT NOT NULL CHECK (length(trim(item_id)) > 0),
                item_name TEXT NOT NULL CHECK (length(trim(item_name)) > 0),
                unit_price INTEGER NOT NULL CHECK (unit_price >= 0),
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 200),
                subtotal INTEGER NOT NULL CHECK (
                    subtotal >= 0 AND subtotal = unit_price * quantity
                ),
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
            );

            INSERT INTO orders (
                id,
                group_session_id,
                store_profile_id,
                public_order_number,
                order_access_token_hash,
                customer_name,
                total_amount,
                created_at
            )
            SELECT
                id,
                group_session_id,
                NULL,
                public_order_number,
                order_access_token_hash,
                customer_name,
                total_amount,
                created_at
            FROM orders_before_store;

            INSERT INTO order_items (
                id,
                order_id,
                item_id,
                item_name,
                unit_price,
                quantity,
                subtotal
            )
            SELECT
                id,
                order_id,
                item_id,
                item_name,
                unit_price,
                quantity,
                subtotal
            FROM order_items_before_store;

            DROP TABLE order_items_before_store;
            DROP TABLE orders_before_store;
            COMMIT;
            """
        )
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")

    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise sqlite3.IntegrityError("訂單資料表遷移後外鍵檢查失敗")


def save_group_menu(
    *,
    public_code: str,
    management_token_hash: str,
    menu: dict,
    created_at: datetime,
    database_path: Path | None = None,
) -> int:
    """以單一交易建立團購及其不可變的菜單快照。"""
    connection = connect_database(database_path)
    try:
        cursor = connection.execute(
            """
            INSERT INTO group_sessions (
                public_code,
                management_token_hash,
                status,
                next_order_sequence,
                created_at
            )
            VALUES (?, ?, 'open', 1, ?)
            """,
            (public_code, management_token_hash, created_at.isoformat()),
        )
        group_session_id = cursor.lastrowid
        if group_session_id is None:
            raise sqlite3.DatabaseError("無法取得新團購識別碼")

        connection.execute(
            """
            INSERT INTO group_menus (group_session_id, menu_json, created_at)
            VALUES (?, ?, ?)
            """,
            (
                group_session_id,
                json.dumps(menu, ensure_ascii=False, separators=(",", ":")),
                created_at.isoformat(),
            ),
        )
        connection.commit()
        return group_session_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_public_group_menu(
    public_code: str,
    database_path: Path | None = None,
) -> dict | None:
    """以公開代碼取得團購狀態與菜單，不包含任何管理資訊。"""
    connection = connect_database(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                group_sessions.public_code,
                group_sessions.status,
                group_menus.menu_json
            FROM group_sessions
            JOIN group_menus ON group_menus.group_session_id = group_sessions.id
            WHERE group_sessions.public_code = ?
            """,
            (public_code,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None
    return {
        "public_code": row["public_code"],
        "status": row["status"],
        "menu": json.loads(row["menu_json"]),
    }


def save_group_order(
    *,
    public_code: str,
    customer_name: str,
    selections: list[dict],
    order_access_token_hash: str,
    created_at: datetime,
    database_path: Path | None = None,
) -> dict:
    """依團購菜單快照重新核價，並在單一交易中建立個人訂單。"""
    connection = connect_database(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        group_row = connection.execute(
            """
            SELECT
                group_sessions.id,
                group_sessions.status,
                group_sessions.next_order_sequence,
                group_menus.menu_json
            FROM group_sessions
            JOIN group_menus ON group_menus.group_session_id = group_sessions.id
            WHERE group_sessions.public_code = ?
            """ + _row_lock_suffix(connection, "group_sessions"),
            (public_code,),
        ).fetchone()
        if group_row is None:
            raise GroupNotFoundError
        if group_row["status"] != "open":
            raise GroupClosedError

        menu = json.loads(group_row["menu_json"])
        available_items = {
            item["id"]: item
            for category in menu["categories"]
            for item in category["items"]
            if item["available"]
        }

        stored_items = []
        for selection in selections:
            menu_item = available_items.get(selection["item_id"])
            if menu_item is None:
                raise GroupOrderValidationError(
                    "餐點不存在或目前暫停供應，請重新整理菜單"
                )
            subtotal = menu_item["price"] * selection["quantity"]
            stored_items.append(
                {
                    "item_id": menu_item["id"],
                    "item_name": menu_item["name"],
                    "unit_price": menu_item["price"],
                    "quantity": selection["quantity"],
                    "note": selection.get("note", "").strip(),
                    "subtotal": subtotal,
                }
            )

        sequence = group_row["next_order_sequence"]
        public_order_number = f"{public_code}-{sequence:03d}"
        total_amount = sum(item["subtotal"] for item in stored_items)

        connection.execute(
            """
            UPDATE group_sessions
            SET next_order_sequence = next_order_sequence + 1
            WHERE id = ?
            """,
            (group_row["id"],),
        )
        order_cursor = connection.execute(
            """
            INSERT INTO orders (
                group_session_id,
                public_order_number,
                order_access_token_hash,
                customer_name,
                total_amount,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                group_row["id"],
                public_order_number,
                order_access_token_hash,
                customer_name,
                total_amount,
                created_at.isoformat(),
            ),
        )
        order_id = order_cursor.lastrowid
        if order_id is None:
            raise sqlite3.DatabaseError("無法取得新訂單識別碼")

        connection.executemany(
            """
            INSERT INTO order_items (
                order_id,
                item_id,
                item_name,
                unit_price,
                quantity,
                note,
                subtotal
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    order_id,
                    item["item_id"],
                    item["item_name"],
                    item["unit_price"],
                    item["quantity"],
                    item["note"],
                    item["subtotal"],
                )
                for item in stored_items
            ],
        )
        connection.commit()
        return {
            "public_order_number": public_order_number,
            "customer_name": customer_name,
            "total_amount": total_amount,
            "created_at": created_at,
            "items": stored_items,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_group_order_for_access_check(
    *,
    public_code: str,
    public_order_number: str,
    database_path: Path | None = None,
) -> dict | None:
    """取得個人訂單與 Token 雜湊，僅供後端權限驗證。"""
    connection = connect_database(database_path)
    try:
        rows = connection.execute(
            """
            SELECT
                orders.id AS order_id,
                orders.public_order_number,
                orders.order_access_token_hash,
                orders.customer_name,
                orders.total_amount,
                orders.created_at,
                group_menus.menu_json,
                order_items.item_id,
                order_items.item_name,
                order_items.unit_price,
                order_items.quantity,
                order_items.note,
                order_items.subtotal
            FROM orders
            JOIN group_sessions ON group_sessions.id = orders.group_session_id
            JOIN group_menus ON group_menus.group_session_id = group_sessions.id
            LEFT JOIN order_items ON order_items.order_id = orders.id
            WHERE group_sessions.public_code = ?
              AND orders.public_order_number = ?
            ORDER BY order_items.id
            """,
            (public_code, public_order_number),
        ).fetchall()
    finally:
        connection.close()

    if not rows:
        return None
    first = rows[0]
    menu = json.loads(first["menu_json"])
    return {
        "public_code": public_code,
        "restaurant_name": menu["restaurant"]["name"],
        "public_order_number": first["public_order_number"],
        "order_access_token_hash": first["order_access_token_hash"],
        "customer_name": first["customer_name"],
        "total_amount": first["total_amount"],
        "created_at": first["created_at"],
        "items": [
            {
                "item_id": row["item_id"],
                "item_name": row["item_name"],
                "unit_price": row["unit_price"],
                "quantity": row["quantity"],
                "note": row["note"],
                "subtotal": row["subtotal"],
            }
            for row in rows
            if row["item_id"] is not None
        ],
    }


def get_group_management_data_for_access_check(
    *,
    public_code: str,
    database_path: Path | None = None,
) -> dict | None:
    """取得團購管理資料與 Token 雜湊，僅供後端權限驗證。"""
    connection = connect_database(database_path)
    try:
        group_row = connection.execute(
            """
            SELECT
                group_sessions.id,
                group_sessions.public_code,
                group_sessions.management_token_hash,
                group_sessions.status,
                group_sessions.created_at,
                group_sessions.closed_at,
                group_menus.menu_json
            FROM group_sessions
            JOIN group_menus ON group_menus.group_session_id = group_sessions.id
            WHERE group_sessions.public_code = ?
            """,
            (public_code,),
        ).fetchone()
        if group_row is None:
            return None

        rows = connection.execute(
            """
            SELECT
                orders.id AS order_id,
                orders.public_order_number,
                orders.customer_name,
                orders.total_amount,
                orders.created_at,
                order_items.item_id,
                order_items.item_name,
                order_items.unit_price,
                order_items.quantity,
                order_items.note,
                order_items.subtotal
            FROM orders
            LEFT JOIN order_items ON order_items.order_id = orders.id
            WHERE orders.group_session_id = ?
            ORDER BY orders.created_at, orders.id, order_items.id
            """,
            (group_row["id"],),
        ).fetchall()
    finally:
        connection.close()

    orders_by_id: dict[int, dict] = {}
    for row in rows:
        order_id = row["order_id"]
        if order_id not in orders_by_id:
            orders_by_id[order_id] = {
                "public_order_number": row["public_order_number"],
                "customer_name": row["customer_name"],
                "total_amount": row["total_amount"],
                "created_at": row["created_at"],
                "items": [],
            }
        if row["item_id"] is not None:
            orders_by_id[order_id]["items"].append(
                {
                    "item_id": row["item_id"],
                    "item_name": row["item_name"],
                    "unit_price": row["unit_price"],
                    "quantity": row["quantity"],
                    "note": row["note"],
                    "subtotal": row["subtotal"],
                }
            )

    menu = json.loads(group_row["menu_json"])
    return {
        "public_code": group_row["public_code"],
        "management_token_hash": group_row["management_token_hash"],
        "restaurant_name": menu["restaurant"]["name"],
        "status": group_row["status"],
        "created_at": group_row["created_at"],
        "closed_at": group_row["closed_at"],
        "orders": list(orders_by_id.values()),
    }


def mark_group_closed(
    *,
    public_code: str,
    closed_at: datetime,
    database_path: Path | None = None,
) -> None:
    """將已驗證管理權限的團購設為截止；重複執行不改寫原截止時間。"""
    connection = connect_database(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE group_sessions
            SET status = 'closed', closed_at = ?
            WHERE public_code = ? AND status = 'open'
            """,
            (closed_at.isoformat(), public_code),
        )
        if cursor.rowcount == 0:
            existing = connection.execute(
                "SELECT status FROM group_sessions WHERE public_code = ?",
                (public_code,),
            ).fetchone()
            if existing is None:
                raise GroupNotFoundError
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def save_store_menu(
    *,
    public_slug: str,
    management_token_hash: str,
    menu: dict,
    created_at: datetime,
    database_path: Path | None = None,
) -> int:
    """以單一交易建立店家資料與第一版固定菜單。"""
    connection = connect_database(database_path)
    try:
        cursor = connection.execute(
            """
            INSERT INTO store_profiles (
                public_slug,
                management_token_hash,
                active,
                next_order_sequence,
                created_at,
                updated_at
            )
            VALUES (?, ?, 1, 1, ?, ?)
            """,
            (
                public_slug,
                management_token_hash,
                created_at.isoformat(),
                created_at.isoformat(),
            ),
        )
        store_profile_id = cursor.lastrowid
        if store_profile_id is None:
            raise sqlite3.DatabaseError("無法取得新店家識別碼")

        connection.execute(
            """
            INSERT INTO store_menus (
                store_profile_id,
                menu_json,
                version,
                created_at,
                updated_at
            )
            VALUES (?, ?, 1, ?, ?)
            """,
            (
                store_profile_id,
                json.dumps(menu, ensure_ascii=False, separators=(",", ":")),
                created_at.isoformat(),
                created_at.isoformat(),
            ),
        )
        connection.commit()
        return store_profile_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_store_menu_for_access_check(
    *,
    public_slug: str,
    database_path: Path | None = None,
) -> dict | None:
    """取得店家目前菜單與管理 Token 雜湊，供公開讀取或後端驗證。"""
    connection = connect_database(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                store_profiles.id,
                store_profiles.public_slug,
                store_profiles.management_token_hash,
                store_profiles.active,
                store_profiles.created_at,
                store_profiles.updated_at,
                store_menus.menu_json,
                store_menus.version
            FROM store_profiles
            JOIN store_menus ON store_menus.store_profile_id = store_profiles.id
            WHERE store_profiles.public_slug = ?
            """,
            (public_slug,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None
    return {
        "store_profile_id": row["id"],
        "public_slug": row["public_slug"],
        "management_token_hash": row["management_token_hash"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "menu": json.loads(row["menu_json"]),
    }


def replace_store_menu(
    *,
    store_profile_id: int,
    menu: dict,
    updated_at: datetime,
    database_path: Path | None = None,
) -> int:
    """只更新指定店家的目前菜單，固定網址及既有訂單維持不變。"""
    connection = connect_database(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE store_menus
            SET menu_json = ?, version = version + 1, updated_at = ?
            WHERE store_profile_id = ?
            """,
            (
                json.dumps(menu, ensure_ascii=False, separators=(",", ":")),
                updated_at.isoformat(),
                store_profile_id,
            ),
        )
        if cursor.rowcount != 1:
            raise StoreNotFoundError
        connection.execute(
            """
            UPDATE store_profiles
            SET updated_at = ?
            WHERE id = ?
            """,
            (updated_at.isoformat(), store_profile_id),
        )
        version = connection.execute(
            "SELECT version FROM store_menus WHERE store_profile_id = ?",
            (store_profile_id,),
        ).fetchone()["version"]
        connection.commit()
        return version
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def save_store_order(
    *,
    public_slug: str,
    customer_name: str,
    selections: list[dict],
    order_access_token_hash: str,
    created_at: datetime,
    database_path: Path | None = None,
) -> dict:
    """依店家目前菜單重新核價，並在單一交易中建立個人訂單。"""
    connection = connect_database(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        store_row = connection.execute(
            """
            SELECT
                store_profiles.id,
                store_profiles.active,
                store_profiles.next_order_sequence,
                store_menus.menu_json
            FROM store_profiles
            JOIN store_menus ON store_menus.store_profile_id = store_profiles.id
            WHERE store_profiles.public_slug = ?
            """ + _row_lock_suffix(connection, "store_profiles"),
            (public_slug,),
        ).fetchone()
        if store_row is None:
            raise StoreNotFoundError
        if not store_row["active"]:
            raise StoreInactiveError

        menu = json.loads(store_row["menu_json"])
        available_items = {
            item["id"]: item
            for category in menu["categories"]
            for item in category["items"]
            if item["available"]
        }
        stored_items = []
        for selection in selections:
            menu_item = available_items.get(selection["item_id"])
            if menu_item is None:
                raise StoreOrderValidationError(
                    "餐點不存在或目前暫停供應，請重新整理菜單"
                )
            subtotal = menu_item["price"] * selection["quantity"]
            stored_items.append(
                {
                    "item_id": menu_item["id"],
                    "item_name": menu_item["name"],
                    "unit_price": menu_item["price"],
                    "quantity": selection["quantity"],
                    "note": selection.get("note", "").strip(),
                    "subtotal": subtotal,
                }
            )

        sequence = store_row["next_order_sequence"]
        public_order_number = f"S-{public_slug.upper()}-{sequence:03d}"
        total_amount = sum(item["subtotal"] for item in stored_items)
        connection.execute(
            """
            UPDATE store_profiles
            SET next_order_sequence = next_order_sequence + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (created_at.isoformat(), store_row["id"]),
        )
        order_cursor = connection.execute(
            """
            INSERT INTO orders (
                store_profile_id,
                public_order_number,
                order_access_token_hash,
                customer_name,
                total_amount,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                store_row["id"],
                public_order_number,
                order_access_token_hash,
                customer_name,
                total_amount,
                created_at.isoformat(),
            ),
        )
        order_id = order_cursor.lastrowid
        if order_id is None:
            raise sqlite3.DatabaseError("無法取得新訂單識別碼")
        connection.executemany(
            """
            INSERT INTO order_items (
                order_id, item_id, item_name, unit_price, quantity, note, subtotal
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    order_id,
                    item["item_id"],
                    item["item_name"],
                    item["unit_price"],
                    item["quantity"],
                    item["note"],
                    item["subtotal"],
                )
                for item in stored_items
            ],
        )
        connection.commit()
        return {
            "public_order_number": public_order_number,
            "customer_name": customer_name,
            "total_amount": total_amount,
            "created_at": created_at,
            "items": stored_items,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_store_order_for_access_check(
    *,
    public_slug: str,
    public_order_number: str,
    database_path: Path | None = None,
) -> dict | None:
    """取得店家個人訂單與 Token 雜湊，僅供後端權限驗證。"""
    connection = connect_database(database_path)
    try:
        rows = connection.execute(
            """
            SELECT
                orders.public_order_number,
                orders.order_access_token_hash,
                orders.customer_name,
                orders.total_amount,
                orders.created_at,
                store_menus.menu_json,
                order_items.item_id,
                order_items.item_name,
                order_items.unit_price,
                order_items.quantity,
                order_items.note,
                order_items.subtotal
            FROM orders
            JOIN store_profiles ON store_profiles.id = orders.store_profile_id
            JOIN store_menus ON store_menus.store_profile_id = store_profiles.id
            LEFT JOIN order_items ON order_items.order_id = orders.id
            WHERE store_profiles.public_slug = ?
              AND orders.public_order_number = ?
            ORDER BY order_items.id
            """,
            (public_slug, public_order_number),
        ).fetchall()
    finally:
        connection.close()

    if not rows:
        return None
    first = rows[0]
    menu = json.loads(first["menu_json"])
    return {
        "public_slug": public_slug,
        "restaurant_name": menu["restaurant"]["name"],
        "public_order_number": first["public_order_number"],
        "order_access_token_hash": first["order_access_token_hash"],
        "customer_name": first["customer_name"],
        "total_amount": first["total_amount"],
        "created_at": first["created_at"],
        "items": [
            {
                "item_id": row["item_id"],
                "item_name": row["item_name"],
                "unit_price": row["unit_price"],
                "quantity": row["quantity"],
                "note": row["note"],
                "subtotal": row["subtotal"],
            }
            for row in rows
            if row["item_id"] is not None
        ],
    }


def get_store_management_data_for_access_check(
    *,
    public_slug: str,
    database_path: Path | None = None,
) -> dict | None:
    """取得單一店家的管理資料與訂單，僅供後端權限驗證。"""
    connection = connect_database(database_path)
    try:
        store_row = connection.execute(
            """
            SELECT
                store_profiles.id,
                store_profiles.public_slug,
                store_profiles.management_token_hash,
                store_profiles.active,
                store_menus.version,
                store_menus.menu_json
            FROM store_profiles
            JOIN store_menus ON store_menus.store_profile_id = store_profiles.id
            WHERE store_profiles.public_slug = ?
            """,
            (public_slug,),
        ).fetchone()
        if store_row is None:
            return None

        rows = connection.execute(
            """
            SELECT
                orders.id AS order_id,
                orders.public_order_number,
                orders.customer_name,
                orders.total_amount,
                orders.created_at,
                order_items.item_id,
                order_items.item_name,
                order_items.unit_price,
                order_items.quantity,
                order_items.note,
                order_items.subtotal
            FROM orders
            LEFT JOIN order_items ON order_items.order_id = orders.id
            WHERE orders.store_profile_id = ?
            ORDER BY orders.id, order_items.id
            """,
            (store_row["id"],),
        ).fetchall()
    finally:
        connection.close()

    orders_by_id: dict[int, dict] = {}
    for row in rows:
        order = orders_by_id.setdefault(
            row["order_id"],
            {
                "public_order_number": row["public_order_number"],
                "customer_name": row["customer_name"],
                "total_amount": row["total_amount"],
                "created_at": row["created_at"],
                "items": [],
            },
        )
        if row["item_id"] is not None:
            order["items"].append(
                {
                    "item_id": row["item_id"],
                    "item_name": row["item_name"],
                    "unit_price": row["unit_price"],
                    "quantity": row["quantity"],
                    "note": row["note"],
                    "subtotal": row["subtotal"],
                }
            )

    menu = json.loads(store_row["menu_json"])
    return {
        "public_slug": store_row["public_slug"],
        "management_token_hash": store_row["management_token_hash"],
        "restaurant_name": menu["restaurant"]["name"],
        "active": bool(store_row["active"]),
        "version": store_row["version"],
        "orders": list(orders_by_id.values()),
    }


def save_order(order: AcceptedOrder, database_path: Path | None = None) -> int:
    """以單一交易寫入訂單主表與所有餐點明細。"""
    connection = connect_database(database_path)
    try:
        cursor = connection.execute(
            """
            INSERT INTO orders (customer_name, total_amount, created_at)
            VALUES (?, ?, ?)
            """,
            (
                order.customer_name,
                order.total_amount,
                order.created_at.isoformat(),
            ),
        )
        order_id = cursor.lastrowid
        if order_id is None:
            raise sqlite3.DatabaseError("無法取得新訂單識別碼")

        connection.executemany(
            """
            INSERT INTO order_items (
                order_id,
                item_id,
                item_name,
                unit_price,
                quantity,
                note,
                subtotal
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    order_id,
                    item.item_id,
                    item.item_name,
                    item.unit_price,
                    item.quantity,
                    item.note,
                    item.subtotal,
                )
                for item in order.items
            ],
        )
        connection.commit()
        return order_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_orders_with_items(database_path: Path | None = None) -> list[dict]:
    """只取得舊示範模式訂單，不包含團購或店家顧客資料。"""
    connection = connect_database(database_path)
    try:
        rows = connection.execute(
            """
            SELECT
                orders.id AS order_id,
                orders.customer_name,
                orders.total_amount,
                orders.created_at,
                order_items.item_id,
                order_items.item_name,
                order_items.unit_price,
                order_items.quantity,
                order_items.note,
                order_items.subtotal
            FROM orders
            LEFT JOIN order_items ON order_items.order_id = orders.id
            WHERE orders.group_session_id IS NULL
              AND orders.store_profile_id IS NULL
            ORDER BY orders.created_at DESC, orders.id DESC, order_items.id ASC
            """
        ).fetchall()
    finally:
        connection.close()

    orders_by_id: dict[int, dict] = {}
    for row in rows:
        order_id = row["order_id"]
        if order_id not in orders_by_id:
            orders_by_id[order_id] = {
                "order_id": order_id,
                "customer_name": row["customer_name"],
                "total_amount": row["total_amount"],
                "created_at": row["created_at"],
                "items": [],
            }

        if row["item_id"] is not None:
            orders_by_id[order_id]["items"].append(
                {
                    "item_id": row["item_id"],
                    "item_name": row["item_name"],
                    "unit_price": row["unit_price"],
                    "quantity": row["quantity"],
                    "note": row["note"],
                    "subtotal": row["subtotal"],
                }
            )

    return list(orders_by_id.values())


if __name__ == "__main__":
    initialized_database = initialize_database()
    if initialized_database == "PostgreSQL":
        print("PostgreSQL 資料表已初始化")
    else:
        print(f"SQLite 資料庫已初始化：{initialized_database}")
