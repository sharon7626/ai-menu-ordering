import hashlib
import hmac
import secrets
import sqlite3
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.database import (
    GroupManagementAccessDeniedError,
    AccountClaimDeniedError,
    SavedMenuAccessDeniedError,
    GroupOrderAccessDeniedError,
    GroupOrderEditCodeDeniedError,
    get_guest_group_order_for_recovery,
    get_group_order_for_access_check,
    get_group_management_data_for_access_check,
    list_groups_for_owner,
    list_orders_for_user,
    list_saved_menus_for_owner,
    get_saved_menu_for_owner,
    save_group_menu,
    save_group_order,
    mark_group_closed,
    claim_group_for_user,
    claim_order_for_user,
    set_group_archive_for_owner,
    set_order_archive_for_user,
)
from backend.database_compat import INTEGRITY_ERROR_TYPES
from backend.schemas import GroupCreateRequest, GroupOrderCreateRequest, GroupOrderRecoveryRequest


PUBLIC_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MAX_CODE_GENERATION_ATTEMPTS = 10


@dataclass(frozen=True)
class CreatedGroup:
    public_code: str
    management_token: str
    menu: dict


@dataclass(frozen=True)
class CreatedGroupOrder:
    public_order_number: str
    order_access_token: str
    customer_name: str
    total_amount: int
    created_at: datetime
    items: list[dict]
    was_updated: bool


def hash_secret_token(token: str) -> str:
    """將高強度隨機 Token 轉成不可直接使用的固定長度雜湊。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _alphabetic_suffix(index: int) -> str:
    """將從零開始的順序轉為 a、b、...、z、aa。"""
    result = ""
    current = index
    while True:
        current, remainder = divmod(current, len(string.ascii_lowercase))
        result = string.ascii_lowercase[remainder] + result
        if current == 0:
            return result
        current -= 1


def confirmed_menu_to_snapshot(confirmation: GroupCreateRequest) -> dict:
    """把人工確認資料轉成點餐頁共用的標準菜單格式。"""
    categories = []
    for category_index, category in enumerate(confirmation.categories):
        category_suffix = _alphabetic_suffix(category_index)
        items = []
        for item_index, item in enumerate(category.items):
            item_suffix = _alphabetic_suffix(item_index)
            items.append(
                {
                    "id": f"item-{category_suffix}-{item_suffix}",
                    "name": item.name,
                    "description": item.description,
                    "price": item.price,
                    "available": True,
                }
            )
        categories.append(
            {
                "id": f"category-{category_suffix}",
                "name": category.name,
                "items": items,
            }
        )

    return {
        "restaurant": {"name": confirmation.restaurant_name},
        "categories": categories,
    }


def create_group_from_confirmation(
    confirmation: GroupCreateRequest,
    database_path: Path | None = None,
    owner_user_id: int | None = None,
) -> CreatedGroup:
    """產生公開代碼與私密 Token，並保存獨立團購菜單快照。"""
    menu = confirmed_menu_to_snapshot(confirmation)
    for _ in range(MAX_CODE_GENERATION_ATTEMPTS):
        public_code = "".join(
            secrets.choice(PUBLIC_CODE_ALPHABET) for _ in range(6)
        )
        management_token = secrets.token_urlsafe(32)
        try:
            save_group_menu(
                public_code=public_code,
                management_token_hash=hash_secret_token(management_token),
                menu=menu,
                created_at=datetime.now(timezone.utc),
                owner_user_id=owner_user_id,
                database_path=database_path,
            )
        except INTEGRITY_ERROR_TYPES:
            continue
        return CreatedGroup(
            public_code=public_code,
            management_token=management_token,
            menu=menu,
        )
    raise sqlite3.IntegrityError("無法產生不重複的團購代碼")


def create_group_from_saved_menu(
    *,
    menu_id: int,
    owner_user_id: int,
    database_path: Path | None = None,
) -> CreatedGroup:
    """從本人常用菜單建立新的獨立團購快照，不呼叫 Gemini。"""
    menu = get_saved_menu_for_owner(
        menu_id=menu_id,
        owner_user_id=owner_user_id,
        database_path=database_path,
    )
    if menu is None:
        raise SavedMenuAccessDeniedError
    for _ in range(MAX_CODE_GENERATION_ATTEMPTS):
        public_code = "".join(secrets.choice(PUBLIC_CODE_ALPHABET) for _ in range(6))
        management_token = secrets.token_urlsafe(32)
        try:
            save_group_menu(
                public_code=public_code,
                management_token_hash=hash_secret_token(management_token),
                menu=menu,
                created_at=datetime.now(timezone.utc),
                owner_user_id=owner_user_id,
                database_path=database_path,
            )
        except INTEGRITY_ERROR_TYPES:
            continue
        return CreatedGroup(public_code, management_token, menu)
    raise sqlite3.IntegrityError("無法產生不重複的團購代碼")


def get_saved_menus(
    *, owner_user_id: int, database_path: Path | None = None
) -> list[dict]:
    return list_saved_menus_for_owner(
        owner_user_id=owner_user_id,
        database_path=database_path,
    )


def create_group_order(
    public_code: str,
    order: GroupOrderCreateRequest,
    database_path: Path | None = None,
    user_id: int | None = None,
    existing_order_number: str | None = None,
    existing_order_access_token: str | None = None,
) -> CreatedGroupOrder:
    """建立團購個人訂單，原始查看 Token 只回傳給本次參與者。"""
    order_access_token = secrets.token_urlsafe(32)
    created_at = datetime.now(timezone.utc)
    saved_order = save_group_order(
        public_code=public_code,
        customer_name=order.customer_name,
        selections=[selection.model_dump() for selection in order.items],
        order_access_token_hash=hash_secret_token(order_access_token),
        created_at=created_at,
        user_id=user_id,
        guest_contact_method=order.contact_method if user_id is None else None,
        guest_contact_value=order.contact_value if user_id is None else None,
        guest_edit_code_hash=(
            hash_secret_token(order.edit_code)
            if user_id is None and order.edit_code
            else None
        ),
        repeat_action=order.repeat_action,
        existing_order_number=existing_order_number,
        existing_order_access_token_hash=(
            hash_secret_token(existing_order_access_token)
            if existing_order_access_token
            else None
        ),
        database_path=database_path,
    )
    return CreatedGroupOrder(
        public_order_number=saved_order["public_order_number"],
        order_access_token=order_access_token,
        customer_name=saved_order["customer_name"],
        total_amount=saved_order["total_amount"],
        created_at=saved_order["created_at"],
        items=saved_order["items"],
        was_updated=saved_order["was_updated"],
    )


def recover_guest_group_order(
    public_code: str,
    recovery: GroupOrderRecoveryRequest,
    database_path: Path | None = None,
) -> dict:
    """以聯絡方式與修改碼驗證訪客身分，成功才回傳原訂單內容。"""
    order = get_guest_group_order_for_recovery(
        public_code=public_code,
        guest_contact_method=recovery.contact_method,
        guest_contact_value=recovery.contact_value,
        database_path=database_path,
    )
    if order is None or not order["guest_edit_code_hash"]:
        raise GroupOrderEditCodeDeniedError
    received_hash = hash_secret_token(recovery.edit_code)
    if not hmac.compare_digest(order["guest_edit_code_hash"], received_hash):
        raise GroupOrderEditCodeDeniedError
    del order["guest_edit_code_hash"]
    return order


def get_personal_group_order(
    *,
    public_code: str,
    public_order_number: str,
    order_access_token: str,
    database_path: Path | None = None,
) -> dict:
    """驗證個人查看 Token，成功後才移除雜湊並回傳訂單。"""
    order = get_group_order_for_access_check(
        public_code=public_code,
        public_order_number=public_order_number,
        database_path=database_path,
    )
    if order is None or not order_access_token:
        raise GroupOrderAccessDeniedError

    expected_hash = order["order_access_token_hash"]
    received_hash = hash_secret_token(order_access_token)
    if not hmac.compare_digest(expected_hash, received_hash):
        raise GroupOrderAccessDeniedError

    del order["order_access_token_hash"]
    del order["user_id"]
    return order


def get_group_order_for_user(
    *,
    public_code: str,
    public_order_number: str,
    user_id: int,
    database_path: Path | None = None,
) -> dict:
    order = get_group_order_for_access_check(
        public_code=public_code,
        public_order_number=public_order_number,
        database_path=database_path,
    )
    if order is None or order["user_id"] != user_id:
        raise GroupOrderAccessDeniedError
    del order["order_access_token_hash"]
    del order["user_id"]
    return order


def claim_group(
    *,
    public_code: str,
    management_token: str,
    user_id: int,
    database_path: Path | None = None,
) -> None:
    if not management_token:
        raise AccountClaimDeniedError
    claim_group_for_user(
        public_code=public_code,
        management_token_hash=hash_secret_token(management_token),
        user_id=user_id,
        database_path=database_path,
    )


def claim_group_order(
    *,
    public_code: str,
    public_order_number: str,
    order_access_token: str,
    user_id: int,
    database_path: Path | None = None,
) -> None:
    if not order_access_token:
        raise AccountClaimDeniedError
    claim_order_for_user(
        mode="group",
        parent_identifier=public_code,
        public_order_number=public_order_number,
        order_access_token_hash=hash_secret_token(order_access_token),
        user_id=user_id,
        database_path=database_path,
    )


def get_group_management_data(
    *,
    public_code: str,
    management_token: str,
    database_path: Path | None = None,
) -> dict:
    """驗證統籌 Token，成功後才回傳該團購全部個人訂單。"""
    group = get_group_management_data_for_access_check(
        public_code=public_code,
        database_path=database_path,
    )
    if group is None or not management_token:
        raise GroupManagementAccessDeniedError

    expected_hash = group["management_token_hash"]
    received_hash = hash_secret_token(management_token)
    if not hmac.compare_digest(expected_hash, received_hash):
        raise GroupManagementAccessDeniedError

    del group["management_token_hash"]
    del group["owner_user_id"]
    return _populate_group_management(group)


def get_group_management_data_for_owner(
    *,
    public_code: str,
    owner_user_id: int,
    database_path: Path | None = None,
) -> dict:
    """以已驗證帳號擁有權取得團購管理資料。"""
    group = get_group_management_data_for_access_check(
        public_code=public_code,
        database_path=database_path,
    )
    if group is None or group["owner_user_id"] != owner_user_id:
        raise GroupManagementAccessDeniedError
    del group["management_token_hash"]
    del group["owner_user_id"]
    return _populate_group_management(group)


def get_owned_groups(
    *,
    owner_user_id: int,
    archived: bool = False,
    database_path: Path | None = None,
) -> list[dict]:
    return list_groups_for_owner(
        owner_user_id=owner_user_id,
        archived=archived,
        database_path=database_path,
    )


def get_user_orders(
    *,
    user_id: int,
    archived: bool = False,
    database_path: Path | None = None,
) -> list[dict]:
    return list_orders_for_user(
        user_id=user_id,
        archived=archived,
        database_path=database_path,
    )


def set_owned_group_archived(
    *,
    public_code: str,
    owner_user_id: int,
    archived: bool,
    database_path: Path | None = None,
) -> None:
    set_group_archive_for_owner(
        public_code=public_code,
        owner_user_id=owner_user_id,
        archived=archived,
        database_path=database_path,
    )


def set_user_order_archived(
    *,
    mode: str,
    parent_identifier: str,
    public_order_number: str,
    user_id: int,
    archived: bool,
    database_path: Path | None = None,
) -> None:
    set_order_archive_for_user(
        mode=mode,
        parent_identifier=parent_identifier,
        public_order_number=public_order_number,
        user_id=user_id,
        archived=archived,
        database_path=database_path,
    )


def _populate_group_management(group: dict) -> dict:
    """共用 Token 與帳號授權後的團購彙整邏輯。"""
    summary_by_item: dict[str, dict[str, dict]] = {}
    for order in group["orders"]:
        for item in order["items"]:
            note = item["note"].strip()
            item_summaries = summary_by_item.setdefault(item["item_id"], {})
            if note not in item_summaries:
                item_summaries[note] = {
                    "item_id": item["item_id"],
                    "item_name": item["item_name"],
                    "unit_price": item["unit_price"],
                    "note": note,
                    "total_quantity": 0,
                    "total_amount": 0,
                }
            item_summaries[note]["total_quantity"] += item["quantity"]
            item_summaries[note]["total_amount"] += item["subtotal"]

    group["summary"] = [
        summary
        for item_summaries in summary_by_item.values()
        for summary in item_summaries.values()
    ]
    group["order_count"] = len(group["orders"])
    group["grand_total"] = sum(order["total_amount"] for order in group["orders"])
    group["text_summary"] = _build_text_summary(group)
    return group


def _format_amount(amount: int) -> str:
    return f"NT$ {amount:,}"


def _build_text_summary(group: dict) -> str:
    status_text = "進行中" if group["status"] == "open" else "已截止"
    lines = [
        f"【{group['restaurant_name']} 團購訂單】",
        f"團購代碼：{group['public_code']}",
        f"狀態：{status_text}",
        f"訂單數：{group['order_count']}",
        "",
        "餐點彙整",
    ]
    if group["summary"]:
        lines.extend(
            (
                f"- {item['item_name']}"
                + (f"｜{item['note']}" if item["note"] else "")
                + f" × {item['total_quantity']}（{_format_amount(item['total_amount'])}）"
            )
            for item in group["summary"]
        )
    else:
        lines.append("- 目前沒有餐點")

    lines.extend(["", "個人明細"])
    if group["orders"]:
        for order in group["orders"]:
            item_text = "、".join(
                (
                    f"{item['item_name']} × {item['quantity']}"
                    + (f"（備註：{item['note']}）" if item["note"] else "")
                )
                for item in order["items"]
            )
            lines.append(
                f"- {order['customer_name']}："
                f"{item_text}｜{_format_amount(order['total_amount'])}"
            )
    else:
        lines.append("- 目前沒有個人訂單")

    lines.extend(["", f"總金額：{_format_amount(group['grand_total'])}"])
    return "\n".join(lines)


def close_group(
    *,
    public_code: str,
    management_token: str,
    database_path: Path | None = None,
) -> dict:
    """先驗證統籌 Token，再關閉團購並回傳更新後的管理資料。"""
    get_group_management_data(
        public_code=public_code,
        management_token=management_token,
        database_path=database_path,
    )
    mark_group_closed(
        public_code=public_code,
        closed_at=datetime.now(timezone.utc),
        database_path=database_path,
    )
    return get_group_management_data(
        public_code=public_code,
        management_token=management_token,
        database_path=database_path,
    )


def close_group_for_owner(
    *,
    public_code: str,
    owner_user_id: int,
    database_path: Path | None = None,
) -> dict:
    """以已驗證帳號擁有權關閉團購。"""
    get_group_management_data_for_owner(
        public_code=public_code,
        owner_user_id=owner_user_id,
        database_path=database_path,
    )
    mark_group_closed(
        public_code=public_code,
        closed_at=datetime.now(timezone.utc),
        database_path=database_path,
    )
    return get_group_management_data_for_owner(
        public_code=public_code,
        owner_user_id=owner_user_id,
        database_path=database_path,
    )
