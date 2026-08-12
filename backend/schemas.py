from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FirebaseWebConfigResponse(BaseModel):
    """提供前端初始化 Firebase Web SDK 的公開設定。"""

    enabled: bool
    api_key: str | None = None
    auth_domain: str | None = None
    project_id: str | None = None
    app_id: str | None = None


class FirebaseSessionResponse(BaseModel):
    """Firebase ID Token 通過後端驗證後的登入身分。"""

    authenticated: bool = True
    uid: str
    email: str | None = None
    display_name: str | None = None


class AccountClaimResponse(BaseModel):
    success: bool = True
    message: str


class OrderItem(BaseModel):
    """一筆訂單中的單一餐點。"""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(pattern=r"^[a-z]+(?:-[a-z]+)*$")
    item_name: str
    unit_price: int = Field(ge=0, strict=True)
    quantity: int = Field(gt=0, strict=True)
    subtotal: int = Field(ge=0, strict=True)
    note: str = Field(default="", max_length=200)

    @field_validator("item_name")
    @classmethod
    def item_name_must_not_be_blank(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError("餐點名稱不可空白")
        return cleaned_value

    @field_validator("note")
    @classmethod
    def note_must_be_trimmed(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def subtotal_must_match(self) -> Self:
        expected_subtotal = self.unit_price * self.quantity
        if self.subtotal != expected_subtotal:
            raise ValueError("餐點小計必須等於單價乘以數量")
        return self


class OrderCreateRequest(BaseModel):
    """顧客送到後端的訂單資料。"""

    model_config = ConfigDict(extra="forbid")

    customer_name: str
    items: list[OrderItem] = Field(min_length=1)
    total_amount: int = Field(ge=0, strict=True)

    @field_validator("customer_name")
    @classmethod
    def customer_name_must_not_be_blank(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError("顧客姓名不可空白")
        return cleaned_value

    @model_validator(mode="after")
    def total_amount_must_match(self) -> Self:
        expected_total = sum(item.subtotal for item in self.items)
        if self.total_amount != expected_total:
            raise ValueError("總金額必須等於所有餐點小計的加總")
        return self


class AcceptedOrder(OrderCreateRequest):
    """後端驗證完成並補上建立時間的訂單。"""

    created_at: datetime


class OrderCreateResponse(BaseModel):
    """有效訂單的 API 回應。"""

    success: bool
    message: str
    order_id: int = Field(gt=0)
    order: AcceptedOrder


class StoredOrderItem(OrderItem):
    """管理者查詢時看到的訂單餐點明細。"""


class StoredOrder(BaseModel):
    """SQLite 中一張包含完整明細的訂單。"""

    order_id: int = Field(gt=0)
    customer_name: str
    total_amount: int = Field(ge=0)
    created_at: datetime
    items: list[StoredOrderItem]


class AdminOrderListResponse(BaseModel):
    """管理者訂單列表 API 回應。"""

    orders: list[StoredOrder]


class ConfirmedMenuItem(BaseModel):
    """人工確認後、準備建立團購的餐點。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=100)
    description: str = Field(max_length=300)
    price: int = Field(ge=0, strict=True)

    @field_validator("name")
    @classmethod
    def confirmed_item_name_must_not_be_blank(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError("餐點名稱不可空白")
        return cleaned_value


class ConfirmedMenuCategory(BaseModel):
    """人工確認後、準備建立團購的菜單分類。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=100)
    items: list[ConfirmedMenuItem] = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def confirmed_category_name_must_not_be_blank(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError("分類名稱不可空白")
        return cleaned_value


class GroupCreateRequest(BaseModel):
    """建立團購前已由統籌確認的菜單內容。"""

    model_config = ConfigDict(extra="forbid")

    restaurant_name: str = Field(max_length=100)
    categories: list[ConfirmedMenuCategory] = Field(min_length=1)

    @field_validator("restaurant_name")
    @classmethod
    def restaurant_name_must_not_be_blank(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError("餐廳名稱不可空白")
        return cleaned_value


class GroupCreateResponse(BaseModel):
    """建立團購成功後只回傳一次的公開入口與管理連結。"""

    success: bool
    message: str
    public_code: str
    participant_url: str
    management_url: str
    restaurant_name: str
    category_count: int = Field(gt=0)
    item_count: int = Field(gt=0)


class PublicMenuItem(BaseModel):
    """團購公開頁顯示的標準餐點。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z]+(?:-[a-z]+)*$")
    name: str
    description: str
    price: int = Field(ge=0, strict=True)
    available: bool


class PublicMenuCategory(BaseModel):
    """團購公開頁顯示的標準分類。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z]+(?:-[a-z]+)*$")
    name: str
    items: list[PublicMenuItem]


class PublicRestaurant(BaseModel):
    """團購公開頁顯示的餐廳資料。"""

    model_config = ConfigDict(extra="forbid")

    name: str


class PublicMenu(BaseModel):
    """符合統一資料格式的公開團購菜單。"""

    model_config = ConfigDict(extra="forbid")

    restaurant: PublicRestaurant
    categories: list[PublicMenuCategory]


class PublicGroupResponse(BaseModel):
    """參與者使用公開代碼取得的團購內容。"""

    public_code: str
    status: Literal["open", "closed"]
    menu: PublicMenu


class GroupOrderSelection(BaseModel):
    """參與者從團購菜單選擇的一個品項與數量。"""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(pattern=r"^[a-z]+(?:-[a-z]+)*$")
    quantity: int = Field(gt=0, strict=True)
    note: str = Field(default="", max_length=200)

    @field_validator("note")
    @classmethod
    def selection_note_must_be_trimmed(cls, value: str) -> str:
        return value.strip()


class GroupOrderCreateRequest(BaseModel):
    """團購參與者送出的最小訂單資料，價格由後端取得。"""

    model_config = ConfigDict(extra="forbid")

    customer_name: str = Field(max_length=50)
    items: list[GroupOrderSelection] = Field(min_length=1)

    @field_validator("customer_name")
    @classmethod
    def group_customer_name_must_not_be_blank(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError("取餐姓名不可空白")
        return cleaned_value

    @model_validator(mode="after")
    def selected_items_must_not_repeat(self) -> Self:
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("同一餐點不可重複送出")
        return self


class GroupOrderCreateResponse(BaseModel):
    """團購訂單建立成功後回傳的個人訂單資訊。"""

    success: bool
    message: str
    public_order_number: str
    order_url: str
    customer_name: str
    total_amount: int = Field(ge=0)
    created_at: datetime
    items: list[OrderItem]


class PersonalGroupOrderResponse(BaseModel):
    """通過個人 Token 驗證後可查看的單張訂單。"""

    public_code: str
    restaurant_name: str
    public_order_number: str
    customer_name: str
    total_amount: int = Field(ge=0)
    created_at: datetime
    items: list[OrderItem]


class ManagedGroupOrder(BaseModel):
    """統籌管理頁中的一張參與者訂單。"""

    public_order_number: str
    customer_name: str
    total_amount: int = Field(ge=0)
    created_at: datetime
    items: list[OrderItem]


class AggregatedGroupItem(BaseModel):
    """統籌依餐點查看的團購合計。"""

    item_id: str = Field(pattern=r"^[a-z]+(?:-[a-z]+)*$")
    item_name: str
    unit_price: int = Field(ge=0)
    note: str = Field(default="", max_length=200)
    total_quantity: int = Field(gt=0)
    total_amount: int = Field(ge=0)


class GroupManagementResponse(BaseModel):
    """通過統籌 Token 驗證後可查看的團購個人明細。"""

    public_code: str
    restaurant_name: str
    status: Literal["open", "closed"]
    created_at: datetime
    closed_at: datetime | None
    orders: list[ManagedGroupOrder]
    summary: list[AggregatedGroupItem]
    order_count: int = Field(ge=0)
    grand_total: int = Field(ge=0)
    text_summary: str


class MyGroupSummary(BaseModel):
    """登入者的單筆團購摘要，不包含任何私密 Token。"""

    public_code: str
    restaurant_name: str
    status: Literal["open", "closed"]
    created_at: datetime
    closed_at: datetime | None
    order_count: int = Field(ge=0)
    grand_total: int = Field(ge=0)
    public_url: str
    management_url: str
    archive_api_url: str


class MyGroupsResponse(BaseModel):
    groups: list[MyGroupSummary]


class MyOrderSummary(BaseModel):
    """登入者的單筆訂單摘要，不包含任何查看 Token。"""

    mode: Literal["group", "store"]
    restaurant_name: str
    public_order_number: str
    customer_name: str
    total_amount: int = Field(ge=0)
    created_at: datetime
    order_url: str
    archive_api_url: str


class MyOrdersResponse(BaseModel):
    orders: list[MyOrderSummary]


class SavedMenuSummary(BaseModel):
    id: int = Field(gt=0)
    restaurant_name: str
    category_count: int = Field(ge=0)
    item_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class SavedMenusResponse(BaseModel):
    menus: list[SavedMenuSummary]


class StoreCreateResponse(BaseModel):
    """店家固定菜單建立成功後的一次性入口資訊。"""

    success: bool
    message: str
    public_slug: str
    public_url: str
    management_url: str
    menu_update_url: str
    restaurant_name: str
    version: int = Field(gt=0)


class PublicStoreResponse(BaseModel):
    """任何顧客可讀取的店家目前菜單。"""

    public_slug: str
    active: bool
    version: int = Field(gt=0)
    menu: PublicMenu


class StoreMenuUpdateResponse(BaseModel):
    """店家通過管理 Token 驗證後的菜單更新結果。"""

    success: bool
    message: str
    public_slug: str
    public_url: str
    restaurant_name: str
    version: int = Field(gt=0)


class StoreOrderCreateRequest(GroupOrderCreateRequest):
    """店家顧客送出的最小訂單資料，價格由後端取得。"""


class StoreOrderCreateResponse(BaseModel):
    """店家顧客送單成功後回傳的一次性個人入口。"""

    success: bool
    message: str
    public_order_number: str
    order_url: str
    customer_name: str
    total_amount: int = Field(ge=0)
    created_at: datetime
    items: list[OrderItem]


class PersonalStoreOrderResponse(BaseModel):
    """通過個人 Token 驗證後可查看的單張店家訂單。"""

    public_slug: str
    restaurant_name: str
    public_order_number: str
    customer_name: str
    total_amount: int = Field(ge=0)
    created_at: datetime
    items: list[OrderItem]


class StoreManagementResponse(BaseModel):
    """通過店家管理 Token 驗證後可查看的該店訂單。"""

    public_slug: str
    restaurant_name: str
    active: bool
    version: int = Field(gt=0)
    orders: list[ManagedGroupOrder]
    summary: list[AggregatedGroupItem]
    order_count: int = Field(ge=0)
    grand_total: int = Field(ge=0)
