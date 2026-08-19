import os
import json
import sqlite3
import hashlib
import hmac
from datetime import datetime, timezone
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
    CREATE TABLE IF NOT EXISTS app_users (
        id BIGSERIAL PRIMARY KEY,
        firebase_uid TEXT NOT NULL UNIQUE CHECK (char_length(trim(firebase_uid)) > 0),
        email TEXT,
        display_name TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
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
        owner_user_id BIGINT REFERENCES app_users(id),
        created_at TEXT NOT NULL,
        closed_at TEXT,
        archived_at TEXT,
        CHECK (
            (status = 'open' AND closed_at IS NULL)
            OR (status = 'closed' AND closed_at IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_saved_menus (
        id BIGSERIAL PRIMARY KEY,
        owner_user_id BIGINT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
        restaurant_name TEXT NOT NULL,
        menu_json TEXT NOT NULL CHECK (jsonb_typeof(menu_json::jsonb) = 'object'),
        menu_fingerprint TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (owner_user_id, menu_fingerprint)
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
        owner_user_id BIGINT REFERENCES app_users(id),
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
        user_id BIGINT REFERENCES app_users(id),
        customer_name TEXT NOT NULL CHECK (char_length(trim(customer_name)) > 0),
        guest_contact_method TEXT CHECK (guest_contact_method IN ('phone', 'email')),
        guest_contact_value TEXT,
        total_amount INTEGER NOT NULL CHECK (total_amount >= 0),
        created_at TEXT NOT NULL,
        archived_at TEXT,
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
    "ALTER TABLE group_sessions ADD COLUMN IF NOT EXISTS owner_user_id BIGINT REFERENCES app_users(id)",
    "ALTER TABLE store_profiles ADD COLUMN IF NOT EXISTS owner_user_id BIGINT REFERENCES app_users(id)",
    "ALTER TABLE group_sessions ADD COLUMN IF NOT EXISTS archived_at TEXT",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES app_users(id)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS archived_at TEXT",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS guest_contact_method TEXT",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS guest_contact_value TEXT",
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
    "CREATE INDEX IF NOT EXISTS idx_group_sessions_owner_created_at ON group_sessions(owner_user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_orders_user_created_at ON orders(user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_saved_menus_owner_updated ON user_saved_menus(owner_user_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_store_profiles_owner_updated ON store_profiles(owner_user_id, updated_at)",
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
CREATE TABLE IF NOT EXISTS app_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firebase_uid TEXT NOT NULL UNIQUE CHECK (length(trim(firebase_uid)) > 0),
    email TEXT,
    display_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

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
    owner_user_id INTEGER,
    created_at TEXT NOT NULL,
    closed_at TEXT,
    archived_at TEXT,
    FOREIGN KEY (owner_user_id) REFERENCES app_users(id),
    CHECK (
        (status = 'open' AND closed_at IS NULL)
        OR (status = 'closed' AND closed_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS user_saved_menus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER NOT NULL,
    restaurant_name TEXT NOT NULL,
    menu_json TEXT NOT NULL CHECK (json_valid(menu_json)),
    menu_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (owner_user_id) REFERENCES app_users(id) ON DELETE CASCADE,
    UNIQUE (owner_user_id, menu_fingerprint)
);

CREATE TABLE IF NOT EXISTS group_menus (
    group_session_id INTEGER PRIMARY KEY,
    menu_json TEXT NOT NULL CHECK (json_valid(menu_json)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (group_session_id) REFERENCES group_sessions(id)
);

CREATE TABLE IF NOT EXISTS store_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER,
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
    updated_at TEXT NOT NULL,
    FOREIGN KEY (owner_user_id) REFERENCES app_users(id)
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
    user_id INTEGER,
    customer_name TEXT NOT NULL CHECK (length(trim(customer_name)) > 0),
    guest_contact_method TEXT CHECK (guest_contact_method IN ('phone', 'email')),
    guest_contact_value TEXT,
    total_amount INTEGER NOT NULL CHECK (total_amount >= 0),
    created_at TEXT NOT NULL,
    archived_at TEXT,
    FOREIGN KEY (group_session_id) REFERENCES group_sessions(id),
    FOREIGN KEY (store_profile_id) REFERENCES store_profiles(id),
    FOREIGN KEY (user_id) REFERENCES app_users(id),
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

CREATE INDEX IF NOT EXISTS idx_group_sessions_owner_created_at
ON group_sessions(owner_user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_orders_user_created_at
ON orders(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_saved_menus_owner_updated
ON user_saved_menus(owner_user_id, updated_at);

CREATE INDEX IF NOT EXISTS idx_store_profiles_owner_updated
ON store_profiles(owner_user_id, updated_at);
"""


class GroupNotFoundError(ValueError):
    """公開團購代碼不存在。"""


class GroupClosedError(ValueError):
    """團購已關閉，不能再建立訂單。"""


class GroupOrderValidationError(ValueError):
    """訂單選擇與團購菜單快照不一致。"""


class GroupOrderAlreadyExistsError(ValueError):
    """同一身分在同一團購已有訂單。"""

    def __init__(self, public_order_number: str, can_update: bool) -> None:
        super().__init__("group order already exists")
        self.public_order_number = public_order_number
        self.can_update = can_update


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


class AccountClaimDeniedError(ValueError):
    """訪客資料無法以目前 Token 安全綁定至帳號。"""


class SavedMenuAccessDeniedError(ValueError):
    """常用菜單不存在或不屬於目前帳號。"""


class AccountArchiveDeniedError(ValueError):
    """帳號無權封存或恢復指定資料。"""


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
        _add_missing_account_columns(connection)
        _add_missing_store_owner_column(connection)
        _add_missing_archive_columns(connection)
        _add_missing_guest_contact_columns(connection)
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


def _add_missing_account_columns(connection: sqlite3.Connection) -> None:
    """只新增可為空的帳號關聯，不替任何既有資料猜測擁有者。"""
    group_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(group_sessions)")
    }
    if "owner_user_id" not in group_columns:
        connection.execute(
            "ALTER TABLE group_sessions "
            "ADD COLUMN owner_user_id INTEGER REFERENCES app_users(id)"
        )

    order_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(orders)")
    }
    if "user_id" not in order_columns:
        connection.execute(
            "ALTER TABLE orders ADD COLUMN user_id INTEGER REFERENCES app_users(id)"
        )


def _add_missing_store_owner_column(connection: sqlite3.Connection) -> None:
    """Add the optional account owner used by fixed store menus."""
    store_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(store_profiles)")
    }
    if "owner_user_id" not in store_columns:
        connection.execute(
            "ALTER TABLE store_profiles "
            "ADD COLUMN owner_user_id INTEGER REFERENCES app_users(id)"
        )


def _add_missing_archive_columns(connection: sqlite3.Connection) -> None:
    """新增可恢復的帳號清單封存時間，不刪除任何既有資料。"""
    group_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(group_sessions)")
    }
    if "archived_at" not in group_columns:
        connection.execute("ALTER TABLE group_sessions ADD COLUMN archived_at TEXT")

    order_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(orders)")
    }
    if "archived_at" not in order_columns:
        connection.execute("ALTER TABLE orders ADD COLUMN archived_at TEXT")


def _add_missing_guest_contact_columns(connection: sqlite3.Connection) -> None:
    """新增訪客聯絡身分欄位；既有訂單維持空值且不猜測資料。"""
    order_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(orders)")
    }
    if "guest_contact_method" not in order_columns:
        connection.execute("ALTER TABLE orders ADD COLUMN guest_contact_method TEXT")
    if "guest_contact_value" not in order_columns:
        connection.execute("ALTER TABLE orders ADD COLUMN guest_contact_value TEXT")


def upsert_app_user(
    *,
    firebase_uid: str,
    email: str | None,
    display_name: str | None,
    database_path: Path | None = None,
) -> int:
    """以已驗證 Firebase UID 建立或更新最小使用者顯示資料。"""
    now = datetime.now(timezone.utc).isoformat()
    connection = connect_database(database_path)
    try:
        row = connection.execute(
            """
            INSERT INTO app_users (
                firebase_uid, email, display_name, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(firebase_uid) DO UPDATE SET
                email = excluded.email,
                display_name = excluded.display_name,
                updated_at = excluded.updated_at
            RETURNING id
            """,
            (firebase_uid, email, display_name, now, now),
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("無法取得使用者識別碼")
        connection.commit()
        return int(row["id"])
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


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
    owner_user_id: int | None = None,
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
                owner_user_id,
                created_at
            )
            VALUES (?, ?, 'open', 1, ?, ?)
            """,
            (
                public_code,
                management_token_hash,
                owner_user_id,
                created_at.isoformat(),
            ),
        )
        group_session_id = cursor.lastrowid
        if group_session_id is None:
            raise sqlite3.DatabaseError("無法取得新團購識別碼")

        menu_json = json.dumps(menu, ensure_ascii=False, separators=(",", ":"))
        connection.execute(
            """
            INSERT INTO group_menus (group_session_id, menu_json, created_at)
            VALUES (?, ?, ?)
            """,
            (
                group_session_id,
                menu_json,
                created_at.isoformat(),
            ),
        )
        if owner_user_id is not None:
            fingerprint = hashlib.sha256(menu_json.encode("utf-8")).hexdigest()
            connection.execute(
                """
                INSERT INTO user_saved_menus (
                    owner_user_id, restaurant_name, menu_json, menu_fingerprint,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_user_id, menu_fingerprint) DO UPDATE SET
                    restaurant_name = excluded.restaurant_name,
                    updated_at = excluded.updated_at
                """,
                (
                    owner_user_id,
                    menu["restaurant"]["name"],
                    menu_json,
                    fingerprint,
                    created_at.isoformat(),
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


def list_groups_for_owner(
    *,
    owner_user_id: int,
    archived: bool = False,
    database_path: Path | None = None,
) -> list[dict]:
    """列出指定帳號擁有的團購，不回傳任何管理 Token。"""
    connection = connect_database(database_path)
    try:
        rows = connection.execute(
            """
            SELECT
                group_sessions.public_code,
                group_sessions.status,
                group_sessions.created_at,
                group_sessions.closed_at,
                group_menus.menu_json,
                COUNT(orders.id) AS order_count,
                COALESCE(SUM(orders.total_amount), 0) AS grand_total
            FROM group_sessions
            JOIN group_menus ON group_menus.group_session_id = group_sessions.id
            LEFT JOIN orders ON orders.group_session_id = group_sessions.id
            WHERE group_sessions.owner_user_id = ?
              AND group_sessions.archived_at IS {archive_null_test}
            GROUP BY
                group_sessions.id,
                group_sessions.public_code,
                group_sessions.status,
                group_sessions.created_at,
                group_sessions.closed_at,
                group_menus.menu_json
            ORDER BY group_sessions.created_at DESC, group_sessions.id DESC
            """.format(archive_null_test="NOT NULL" if archived else "NULL"),
            (owner_user_id,),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "public_code": row["public_code"],
            "restaurant_name": json.loads(row["menu_json"])["restaurant"]["name"],
            "status": row["status"],
            "created_at": row["created_at"],
            "closed_at": row["closed_at"],
            "order_count": row["order_count"],
            "grand_total": row["grand_total"],
        }
        for row in rows
    ]


def list_saved_menus_for_owner(
    *, owner_user_id: int, database_path: Path | None = None
) -> list[dict]:
    connection = connect_database(database_path)
    try:
        rows = connection.execute(
            """
            SELECT id, restaurant_name, menu_json, created_at, updated_at
            FROM user_saved_menus
            WHERE owner_user_id = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (owner_user_id,),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "id": row["id"],
            "menu_type": "group_template",
            "restaurant_name": row["restaurant_name"],
            "category_count": len(json.loads(row["menu_json"])["categories"]),
            "item_count": sum(
                len(category["items"])
                for category in json.loads(row["menu_json"])["categories"]
            ),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def get_saved_menu_for_owner(
    *, menu_id: int, owner_user_id: int, database_path: Path | None = None
) -> dict | None:
    connection = connect_database(database_path)
    try:
        row = connection.execute(
            "SELECT menu_json FROM user_saved_menus WHERE id = ? AND owner_user_id = ?",
            (menu_id, owner_user_id),
        ).fetchone()
    finally:
        connection.close()
    return json.loads(row["menu_json"]) if row is not None else None


def list_orders_for_user(
    *,
    user_id: int,
    archived: bool = False,
    database_path: Path | None = None,
) -> list[dict]:
    """列出指定帳號的團購與店家訂單，不回傳查看 Token。"""
    connection = connect_database(database_path)
    try:
        rows = connection.execute(
            """
            SELECT
                orders.public_order_number,
                orders.customer_name,
                orders.total_amount,
                orders.created_at,
                group_sessions.public_code,
                group_menus.menu_json AS group_menu_json,
                store_profiles.public_slug,
                store_menus.menu_json AS store_menu_json
            FROM orders
            LEFT JOIN group_sessions ON group_sessions.id = orders.group_session_id
            LEFT JOIN group_menus ON group_menus.group_session_id = group_sessions.id
            LEFT JOIN store_profiles ON store_profiles.id = orders.store_profile_id
            LEFT JOIN store_menus ON store_menus.store_profile_id = store_profiles.id
            WHERE orders.user_id = ?
              AND orders.public_order_number IS NOT NULL
              AND orders.archived_at IS {archive_null_test}
            ORDER BY orders.created_at DESC, orders.id DESC
            """.format(archive_null_test="NOT NULL" if archived else "NULL"),
            (user_id,),
        ).fetchall()
    finally:
        connection.close()

    results = []
    for row in rows:
        is_group = row["public_code"] is not None
        menu_json = row["group_menu_json"] if is_group else row["store_menu_json"]
        results.append(
            {
                "mode": "group" if is_group else "store",
                "restaurant_name": json.loads(menu_json)["restaurant"]["name"],
                "public_code": row["public_code"],
                "public_slug": row["public_slug"],
                "public_order_number": row["public_order_number"],
                "customer_name": row["customer_name"],
                "total_amount": row["total_amount"],
                "created_at": row["created_at"],
            }
        )
    return results


def set_group_archive_for_owner(
    *,
    public_code: str,
    owner_user_id: int,
    archived: bool,
    database_path: Path | None = None,
) -> None:
    """只允許帳號擁有者封存或恢復團購；不更動團購與訂單內容。"""
    archived_at = datetime.now(timezone.utc).isoformat() if archived else None
    connection = connect_database(database_path)
    try:
        cursor = connection.execute(
            """
            UPDATE group_sessions
            SET archived_at = ?
            WHERE public_code = ? AND owner_user_id = ?
            """,
            (archived_at, public_code, owner_user_id),
        )
        if cursor.rowcount != 1:
            raise AccountArchiveDeniedError
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def set_order_archive_for_user(
    *,
    mode: str,
    parent_identifier: str,
    public_order_number: str,
    user_id: int,
    archived: bool,
    database_path: Path | None = None,
) -> None:
    """只允許訂單擁有者封存或恢復自己的團購／店家訂單。"""
    if mode == "group":
        parent_join = "JOIN group_sessions parent ON parent.id = orders.group_session_id"
        parent_column = "parent.public_code"
    elif mode == "store":
        parent_join = "JOIN store_profiles parent ON parent.id = orders.store_profile_id"
        parent_column = "parent.public_slug"
    else:
        raise ValueError("不支援的訂單模式")

    connection = connect_database(database_path)
    try:
        row = connection.execute(
            f"""
            SELECT orders.id
            FROM orders
            {parent_join}
            WHERE {parent_column} = ?
              AND orders.public_order_number = ?
              AND orders.user_id = ?
            """,
            (parent_identifier, public_order_number, user_id),
        ).fetchone()
        if row is None:
            raise AccountArchiveDeniedError
        archived_at = datetime.now(timezone.utc).isoformat() if archived else None
        cursor = connection.execute(
            "UPDATE orders SET archived_at = ? WHERE id = ? AND user_id = ?",
            (archived_at, row["id"], user_id),
        )
        if cursor.rowcount != 1:
            raise AccountArchiveDeniedError
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def claim_group_for_user(
    *,
    public_code: str,
    management_token_hash: str,
    user_id: int,
    database_path: Path | None = None,
) -> None:
    """以管理 Token 原子化認領訪客團購；不覆蓋其他擁有者。"""
    connection = connect_database(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE group_sessions
            SET owner_user_id = ?
            WHERE public_code = ?
              AND management_token_hash = ?
              AND owner_user_id IS NULL
            """,
            (user_id, public_code, management_token_hash),
        )
        if cursor.rowcount != 1:
            existing = connection.execute(
                """
                SELECT owner_user_id
                FROM group_sessions
                WHERE public_code = ? AND management_token_hash = ?
                """,
                (public_code, management_token_hash),
            ).fetchone()
            if existing is None or existing["owner_user_id"] != user_id:
                raise AccountClaimDeniedError
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def claim_order_for_user(
    *,
    mode: str,
    parent_identifier: str,
    public_order_number: str,
    order_access_token_hash: str,
    user_id: int,
    database_path: Path | None = None,
) -> None:
    """以查看 Token 原子化認領訪客訂單；團購與店家共用同一安全規則。"""
    if mode == "group":
        parent_join = "JOIN group_sessions parent ON parent.id = orders.group_session_id"
        parent_column = "parent.public_code"
    elif mode == "store":
        parent_join = "JOIN store_profiles parent ON parent.id = orders.store_profile_id"
        parent_column = "parent.public_slug"
    else:
        raise ValueError("不支援的訂單模式")

    connection = connect_database(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            f"""
            SELECT orders.id, orders.user_id
            FROM orders
            {parent_join}
            WHERE {parent_column} = ?
              AND orders.public_order_number = ?
              AND orders.order_access_token_hash = ?
            """,
            (parent_identifier, public_order_number, order_access_token_hash),
        ).fetchone()
        if row is None or row["user_id"] not in (None, user_id):
            raise AccountClaimDeniedError
        if row["user_id"] is None:
            cursor = connection.execute(
                "UPDATE orders SET user_id = ? WHERE id = ? AND user_id IS NULL",
                (user_id, row["id"]),
            )
            if cursor.rowcount != 1:
                raise AccountClaimDeniedError
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def save_group_order(
    *,
    public_code: str,
    customer_name: str,
    selections: list[dict],
    order_access_token_hash: str,
    created_at: datetime,
    user_id: int | None = None,
    guest_contact_method: str | None = None,
    guest_contact_value: str | None = None,
    repeat_action: str | None = None,
    existing_order_number: str | None = None,
    existing_order_access_token_hash: str | None = None,
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

        if user_id is None and (
            guest_contact_method is None or guest_contact_value is None
        ):
            raise GroupOrderValidationError(
                "未登入時，請提供手機號碼或 Email 以辨識訂購者"
            )

        if user_id is not None:
            existing_order = connection.execute(
                """
                SELECT id, public_order_number, order_access_token_hash,
                       customer_name, total_amount, created_at
                FROM orders
                WHERE group_session_id = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (group_row["id"], user_id),
            ).fetchone()
        else:
            existing_order = connection.execute(
                """
                SELECT id, public_order_number, order_access_token_hash,
                       customer_name, total_amount, created_at
                FROM orders
                WHERE group_session_id = ?
                  AND user_id IS NULL
                  AND guest_contact_method = ?
                  AND guest_contact_value = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (group_row["id"], guest_contact_method, guest_contact_value),
            ).fetchone()

        if existing_order is not None:
            token_matches = bool(
                existing_order_access_token_hash
                and hmac.compare_digest(
                    existing_order["order_access_token_hash"],
                    existing_order_access_token_hash,
                )
            )
            can_update = user_id is not None or token_matches
            if repeat_action is None:
                raise GroupOrderAlreadyExistsError(
                    existing_order["public_order_number"], can_update
                )
            if (
                not can_update
                or (
                    existing_order_number
                    and existing_order_number
                    != existing_order["public_order_number"]
                )
            ):
                raise GroupOrderAccessDeniedError

            if repeat_action == "add":
                existing_items = connection.execute(
                    """
                    SELECT item_id, item_name, unit_price, quantity, note, subtotal
                    FROM order_items
                    WHERE order_id = ?
                    ORDER BY id
                    """,
                    (existing_order["id"],),
                ).fetchall()
                merged_items = {
                    (row["item_id"], row["note"]): {
                        "item_id": row["item_id"],
                        "item_name": row["item_name"],
                        "unit_price": row["unit_price"],
                        "quantity": row["quantity"],
                        "note": row["note"],
                        "subtotal": row["subtotal"],
                    }
                    for row in existing_items
                }
                for item in stored_items:
                    item_key = (item["item_id"], item["note"])
                    current = merged_items.get(item_key)
                    if current is None:
                        merged_items[item_key] = item
                        continue
                    current["quantity"] += item["quantity"]
                    if item["note"]:
                        current["note"] = item["note"]
                    current["subtotal"] = (
                        current["unit_price"] * current["quantity"]
                    )
                stored_items = list(merged_items.values())

            total_amount = sum(item["subtotal"] for item in stored_items)
            connection.execute(
                """
                UPDATE orders
                SET order_access_token_hash = ?, customer_name = ?, total_amount = ?
                WHERE id = ?
                """,
                (
                    order_access_token_hash,
                    customer_name,
                    total_amount,
                    existing_order["id"],
                ),
            )
            connection.execute(
                "DELETE FROM order_items WHERE order_id = ?",
                (existing_order["id"],),
            )
            connection.executemany(
                """
                INSERT INTO order_items (
                    order_id, item_id, item_name, unit_price, quantity, note, subtotal
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        existing_order["id"],
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
                "public_order_number": existing_order["public_order_number"],
                "customer_name": customer_name,
                "total_amount": total_amount,
                "created_at": (
                    existing_order["created_at"]
                    if isinstance(existing_order["created_at"], datetime)
                    else datetime.fromisoformat(existing_order["created_at"])
                ),
                "items": stored_items,
                "was_updated": True,
            }

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
                user_id,
                customer_name,
                guest_contact_method,
                guest_contact_value,
                total_amount,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                group_row["id"],
                public_order_number,
                order_access_token_hash,
                user_id,
                customer_name,
                guest_contact_method,
                guest_contact_value,
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
            "was_updated": False,
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
                orders.user_id,
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
        "user_id": first["user_id"],
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
                group_sessions.owner_user_id,
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
                orders.user_id,
                orders.guest_contact_method,
                orders.guest_contact_value,
                app_users.email AS account_email,
                app_users.display_name AS account_display_name,
                orders.total_amount,
                orders.created_at,
                order_items.item_id,
                order_items.item_name,
                order_items.unit_price,
                order_items.quantity,
                order_items.note,
                order_items.subtotal
            FROM orders
            LEFT JOIN app_users ON app_users.id = orders.user_id
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
                "identity_method": (
                    "google" if row["user_id"] is not None
                    else row["guest_contact_method"] or "legacy"
                ),
                "identity_value": (
                    (row["account_email"] or row["account_display_name"])
                    if row["user_id"] is not None
                    else row["guest_contact_value"]
                ),
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
        "owner_user_id": group_row["owner_user_id"],
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
    owner_user_id: int | None = None,
    database_path: Path | None = None,
) -> int:
    """以單一交易建立店家資料與第一版固定菜單。"""
    connection = connect_database(database_path)
    try:
        cursor = connection.execute(
            """
            INSERT INTO store_profiles (
                owner_user_id,
                public_slug,
                management_token_hash,
                active,
                next_order_sequence,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 1, 1, ?, ?)
            """,
            (
                owner_user_id,
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
                store_profiles.owner_user_id,
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
        "owner_user_id": row["owner_user_id"],
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


def list_store_menus_for_owner(
    *, owner_user_id: int, database_path: Path | None = None
) -> list[dict]:
    """List fixed store menus owned by one signed-in account."""
    connection = connect_database(database_path)
    try:
        rows = connection.execute(
            """
            SELECT
                store_profiles.id,
                store_profiles.owner_user_id,
                store_profiles.public_slug,
                store_profiles.active,
                store_profiles.created_at,
                store_profiles.updated_at,
                store_menus.menu_json,
                store_menus.version
            FROM store_profiles
            JOIN store_menus ON store_menus.store_profile_id = store_profiles.id
            WHERE store_profiles.owner_user_id = ?
            ORDER BY store_profiles.updated_at DESC, store_profiles.id DESC
            """,
            (owner_user_id,),
        ).fetchall()
    finally:
        connection.close()

    menus = []
    for row in rows:
        menu = json.loads(row["menu_json"])
        menus.append(
            {
                "id": row["id"],
                "menu_type": "store_fixed",
                "restaurant_name": menu["restaurant"]["name"],
                "category_count": len(menu["categories"]),
                "item_count": sum(len(category["items"]) for category in menu["categories"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "public_slug": row["public_slug"],
                "version": row["version"],
                "active": bool(row["active"]),
            }
        )
    return menus


def claim_store_for_owner(
    *,
    public_slug: str,
    management_token_hash: str,
    owner_user_id: int,
    database_path: Path | None = None,
) -> None:
    """Bind a legacy fixed store menu to an account after token verification."""
    connection = connect_database(database_path)
    try:
        cursor = connection.execute(
            """
            UPDATE store_profiles
            SET owner_user_id = ?, updated_at = ?
            WHERE public_slug = ?
              AND management_token_hash = ?
              AND (owner_user_id IS NULL OR owner_user_id = ?)
            """,
            (
                owner_user_id,
                datetime.now(timezone.utc).isoformat(),
                public_slug,
                management_token_hash,
                owner_user_id,
            ),
        )
        if cursor.rowcount != 1:
            raise AccountClaimDeniedError
        connection.commit()
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
    user_id: int | None = None,
    guest_contact_method: str | None = None,
    guest_contact_value: str | None = None,
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

        if user_id is None and (
            guest_contact_method is None or guest_contact_value is None
        ):
            raise StoreOrderValidationError(
                "未登入時，請提供手機號碼或 Email 以辨識訂購者"
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
                user_id,
                customer_name,
                guest_contact_method,
                guest_contact_value,
                total_amount,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                store_row["id"],
                public_order_number,
                order_access_token_hash,
                user_id,
                customer_name,
                guest_contact_method,
                guest_contact_value,
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
                orders.user_id,
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
        "user_id": first["user_id"],
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
                store_profiles.owner_user_id,
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
                orders.user_id,
                orders.guest_contact_method,
                orders.guest_contact_value,
                app_users.email AS account_email,
                app_users.display_name AS account_display_name,
                orders.total_amount,
                orders.created_at,
                order_items.item_id,
                order_items.item_name,
                order_items.unit_price,
                order_items.quantity,
                order_items.note,
                order_items.subtotal
            FROM orders
            LEFT JOIN app_users ON app_users.id = orders.user_id
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
                "identity_method": (
                    "google" if row["user_id"] is not None
                    else row["guest_contact_method"] or "legacy"
                ),
                "identity_value": (
                    (row["account_email"] or row["account_display_name"])
                    if row["user_id"] is not None
                    else row["guest_contact_value"]
                ),
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
        "owner_user_id": store_row["owner_user_id"],
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
