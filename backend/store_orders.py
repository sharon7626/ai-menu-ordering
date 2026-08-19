import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.database import (
    AccountClaimDeniedError,
    StoreOrderAccessDeniedError,
    claim_order_for_user,
    get_store_order_for_access_check,
    save_store_order,
)
from backend.group_orders import hash_secret_token
from backend.schemas import StoreOrderCreateRequest


@dataclass(frozen=True)
class CreatedStoreOrder:
    public_order_number: str
    order_access_token: str
    customer_name: str
    total_amount: int
    created_at: datetime
    items: list[dict]


def create_store_order(
    public_slug: str,
    order: StoreOrderCreateRequest,
    database_path: Path | None = None,
    user_id: int | None = None,
) -> CreatedStoreOrder:
    """建立店家顧客訂單，價格由店家目前菜單重新計算。"""
    order_access_token = secrets.token_urlsafe(32)
    created_at = datetime.now(timezone.utc)
    saved_order = save_store_order(
        public_slug=public_slug,
        customer_name=order.customer_name,
        selections=[selection.model_dump() for selection in order.items],
        order_access_token_hash=hash_secret_token(order_access_token),
        created_at=created_at,
        user_id=user_id,
        guest_contact_method=order.contact_method if user_id is None else None,
        guest_contact_value=order.contact_value if user_id is None else None,
        database_path=database_path,
    )
    return CreatedStoreOrder(
        public_order_number=saved_order["public_order_number"],
        order_access_token=order_access_token,
        customer_name=saved_order["customer_name"],
        total_amount=saved_order["total_amount"],
        created_at=saved_order["created_at"],
        items=saved_order["items"],
    )


def get_personal_store_order(
    *,
    public_slug: str,
    public_order_number: str,
    order_access_token: str,
    database_path: Path | None = None,
) -> dict:
    """驗證顧客個人 Token，成功後才回傳自己的店家訂單。"""
    order = get_store_order_for_access_check(
        public_slug=public_slug,
        public_order_number=public_order_number,
        database_path=database_path,
    )
    if order is None or not order_access_token:
        raise StoreOrderAccessDeniedError

    expected_hash = order["order_access_token_hash"]
    received_hash = hash_secret_token(order_access_token)
    if not hmac.compare_digest(expected_hash, received_hash):
        raise StoreOrderAccessDeniedError

    del order["order_access_token_hash"]
    del order["user_id"]
    return order


def get_store_order_for_user(
    *,
    public_slug: str,
    public_order_number: str,
    user_id: int,
    database_path: Path | None = None,
) -> dict:
    """以已驗證帳號身分讀取自己的店家訂單。"""
    order = get_store_order_for_access_check(
        public_slug=public_slug,
        public_order_number=public_order_number,
        database_path=database_path,
    )
    if order is None or order["user_id"] != user_id:
        raise StoreOrderAccessDeniedError
    del order["order_access_token_hash"]
    del order["user_id"]
    return order


def claim_store_order(
    *,
    public_slug: str,
    public_order_number: str,
    order_access_token: str,
    user_id: int,
    database_path: Path | None = None,
) -> None:
    """以個人查看 Token 將訪客店家訂單保存至目前帳號。"""
    if not order_access_token:
        raise AccountClaimDeniedError
    claim_order_for_user(
        mode="store",
        parent_identifier=public_slug,
        public_order_number=public_order_number,
        order_access_token_hash=hash_secret_token(order_access_token),
        user_id=user_id,
        database_path=database_path,
    )
