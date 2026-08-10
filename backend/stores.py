import hmac
import secrets
import sqlite3
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.database import (
    StoreManagementAccessDeniedError,
    StoreNotFoundError,
    get_store_management_data_for_access_check,
    get_store_menu_for_access_check,
    replace_store_menu,
    save_store_menu,
)
from backend.database_compat import INTEGRITY_ERROR_TYPES
from backend.group_orders import confirmed_menu_to_snapshot, hash_secret_token
from backend.schemas import GroupCreateRequest


MAX_SLUG_GENERATION_ATTEMPTS = 10


@dataclass(frozen=True)
class CreatedStore:
    public_slug: str
    management_token: str
    menu: dict
    version: int


def create_store_from_confirmation(
    confirmation: GroupCreateRequest,
    database_path: Path | None = None,
) -> CreatedStore:
    """建立店家固定菜單，原始管理 Token 只回傳一次。"""
    menu = confirmed_menu_to_snapshot(confirmation)
    for _ in range(MAX_SLUG_GENERATION_ATTEMPTS):
        public_slug = "".join(secrets.choice(string.ascii_lowercase) for _ in range(8))
        management_token = secrets.token_urlsafe(32)
        try:
            save_store_menu(
                public_slug=public_slug,
                management_token_hash=hash_secret_token(management_token),
                menu=menu,
                created_at=datetime.now(timezone.utc),
                database_path=database_path,
            )
        except INTEGRITY_ERROR_TYPES:
            continue
        return CreatedStore(
            public_slug=public_slug,
            management_token=management_token,
            menu=menu,
            version=1,
        )
    raise sqlite3.IntegrityError("無法產生不重複的店家公開識別碼")


def get_public_store_menu(
    public_slug: str,
    database_path: Path | None = None,
) -> dict:
    """取得公開店家菜單，移除所有內部與管理欄位。"""
    store = get_store_menu_for_access_check(
        public_slug=public_slug,
        database_path=database_path,
    )
    if store is None:
        raise StoreNotFoundError
    return {
        "public_slug": store["public_slug"],
        "active": store["active"],
        "version": store["version"],
        "menu": store["menu"],
    }


def update_store_from_confirmation(
    *,
    public_slug: str,
    management_token: str,
    confirmation: GroupCreateRequest,
    database_path: Path | None = None,
) -> dict:
    """驗證店家 Token 後更新目前菜單，不變更固定公開網址。"""
    store = get_store_menu_for_access_check(
        public_slug=public_slug,
        database_path=database_path,
    )
    if store is None or not management_token:
        raise StoreManagementAccessDeniedError
    received_hash = hash_secret_token(management_token)
    if not hmac.compare_digest(store["management_token_hash"], received_hash):
        raise StoreManagementAccessDeniedError

    menu = confirmed_menu_to_snapshot(confirmation)
    version = replace_store_menu(
        store_profile_id=store["store_profile_id"],
        menu=menu,
        updated_at=datetime.now(timezone.utc),
        database_path=database_path,
    )
    return {
        "public_slug": public_slug,
        "active": store["active"],
        "version": version,
        "menu": menu,
    }


def get_store_management_data(
    *,
    public_slug: str,
    management_token: str,
    database_path: Path | None = None,
) -> dict:
    """驗證店家管理 Token 後，回傳該店家的訂單明細與餐點彙整。"""
    store = get_store_management_data_for_access_check(
        public_slug=public_slug,
        database_path=database_path,
    )
    if store is None or not management_token:
        raise StoreManagementAccessDeniedError
    received_hash = hash_secret_token(management_token)
    if not hmac.compare_digest(store["management_token_hash"], received_hash):
        raise StoreManagementAccessDeniedError

    del store["management_token_hash"]
    store["order_count"] = len(store["orders"])
    store["grand_total"] = sum(
        order["total_amount"] for order in store["orders"]
    )
    summary_by_item: dict[str, dict[str, dict]] = {}
    for order in store["orders"]:
        for item in order["items"]:
            item_summaries = summary_by_item.setdefault(item["item_id"], {})
            note = item["note"]
            summary = item_summaries.setdefault(
                note,
                {
                    "item_id": item["item_id"],
                    "item_name": item["item_name"],
                    "unit_price": item["unit_price"],
                    "note": note,
                    "total_quantity": 0,
                    "total_amount": 0,
                },
            )
            summary["total_quantity"] += item["quantity"]
            summary["total_amount"] += item["subtotal"]
    store["summary"] = [
        summary
        for item_summaries in summary_by_item.values()
        for summary in item_summaries.values()
    ]
    return store
