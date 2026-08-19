from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Annotated, AsyncIterator

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.database import (
    AccountClaimDeniedError,
    AccountArchiveDeniedError,
    SavedMenuAccessDeniedError,
    GroupClosedError,
    GroupManagementAccessDeniedError,
    GroupNotFoundError,
    GroupOrderAlreadyExistsError,
    GroupOrderAccessDeniedError,
    GroupOrderValidationError,
    StoreManagementAccessDeniedError,
    StoreInactiveError,
    StoreNotFoundError,
    StoreOrderAccessDeniedError,
    StoreOrderValidationError,
    get_orders_with_items,
    get_public_group_menu,
    initialize_database,
    list_store_menus_for_owner,
    save_order,
    upsert_app_user,
)
from backend.database_compat import DATABASE_ERROR_TYPES
from backend.firebase_auth import (
    FirebaseAuthenticationError,
    FirebaseConfigurationError,
    get_firebase_web_config,
    verify_firebase_id_token,
)
from backend.group_orders import (
    claim_group,
    claim_group_order,
    create_group_from_saved_menu,
    create_group_from_confirmation,
    create_group_order,
    close_group,
    close_group_for_owner,
    get_group_management_data,
    get_group_management_data_for_owner,
    get_owned_groups,
    get_group_order_for_user,
    get_user_orders,
    get_saved_menus,
    get_personal_group_order,
    set_owned_group_archived,
    set_user_order_archived,
)
from backend.group_order_excel import build_group_order_workbook, build_store_order_workbook
from backend.menu_upload import (
    MenuUploadFileResponse,
    MenuUploadResponse,
    MenuUploadValidationError,
    missing_file_error,
    multiple_files_error,
    validate_menu_upload,
)
from backend.menu_recognition import (
    MenuRecognitionError,
    MenuRecognitionResult,
    recognize_menu,
)
from backend.order_abuse_guard import (
    DuplicateOrderSubmissionError,
    OrderRateLimitExceededError,
    protect_order_submission,
    reset_order_abuse_guard,
)
from backend.schemas import (
    AcceptedOrder,
    AccountClaimResponse,
    AdminOrderListResponse,
    FirebaseSessionResponse,
    FirebaseWebConfigResponse,
    GroupCreateRequest,
    GroupCreateResponse,
    GroupOrderCreateRequest,
    GroupOrderCreateResponse,
    GroupManagementResponse,
    MyGroupSummary,
    MyGroupsResponse,
    MyOrderSummary,
    MyOrdersResponse,
    SavedMenuSummary,
    SavedMenusResponse,
    OrderCreateRequest,
    OrderCreateResponse,
    PersonalGroupOrderResponse,
    PersonalStoreOrderResponse,
    PublicGroupResponse,
    PublicStoreResponse,
    StoreCreateResponse,
    StoreMenuUpdateResponse,
    StoreManagementResponse,
    StoreOrderCreateRequest,
    StoreOrderCreateResponse,
)
from backend.stores import (
    claim_store,
    create_store_from_confirmation,
    get_public_store_menu,
    get_store_management_data,
    update_store_from_confirmation,
)
from backend.store_qr import build_store_qr_svg
from backend.store_orders import (
    claim_store_order,
    create_store_order,
    get_personal_store_order,
    get_store_order_for_user,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIRECTORY = PROJECT_ROOT / "frontend"
DATA_DIRECTORY = PROJECT_ROOT / "data"
ORDER_COOKIE_MAX_AGE = 60 * 60 * 24 * 30


class MenuRecognitionResponse(MenuUploadResponse):
    recognition: MenuRecognitionResult


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """服務啟動時確認目前環境的資料表已建立。"""
    initialize_database()
    reset_order_abuse_guard()
    yield


app = FastAPI(title="AI 菜單點餐系統", lifespan=lifespan)

app.mount(
    "/frontend",
    StaticFiles(directory=FRONTEND_DIRECTORY, html=True),
    name="frontend",
)
app.mount("/data", StaticFiles(directory=DATA_DIRECTORY), name="data")


def _group_order_cookie_name(public_code: str, identity: str) -> str:
    """以不可逆身分指紋區隔同一瀏覽器中的不同團購訂單。"""
    identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"seat_group_{public_code.lower()}_{identity_hash}"


def _group_order_cookie(
    request: Request, public_code: str, identity: str
) -> tuple[str | None, str | None]:
    raw_value = request.cookies.get(_group_order_cookie_name(public_code, identity), "")
    if "." not in raw_value:
        return None, None
    public_order_number, order_access_token = raw_value.split(".", 1)
    if not public_order_number or not order_access_token:
        return None, None
    return public_order_number, order_access_token


def _remember_group_order(
    response: Response,
    request: Request,
    public_code: str,
    identity: str,
    public_order_number: str,
    order_access_token: str,
) -> None:
    forwarded_scheme = request.headers.get("x-forwarded-proto", "")
    is_https = (
        request.url.scheme == "https"
        or forwarded_scheme.split(",")[0].strip().lower() == "https"
    )
    response.set_cookie(
        key=_group_order_cookie_name(public_code, identity),
        value=f"{public_order_number}.{order_access_token}",
        max_age=ORDER_COOKIE_MAX_AGE,
        httponly=True,
        secure=is_https,
        samesite="lax",
        path="/",
    )


def _verify_firebase_authorization(
    authorization: str | None,
    *,
    required: bool,
):
    """驗證選填 Firebase Bearer Token；訪客沒有 Header 時維持原流程。"""
    if not authorization:
        if required:
            raise HTTPException(status_code=401, detail="缺少登入憑證。")
        return None
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="登入憑證格式錯誤。")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_firebase_id_token(token)
    except FirebaseAuthenticationError as error:
        raise HTTPException(status_code=401, detail="登入憑證無效或已過期。") from error
    except FirebaseConfigurationError as error:
        raise HTTPException(status_code=503, detail="登入服務尚未完成設定。") from error


def _save_verified_user(user) -> int:
    try:
        return upsert_app_user(
            firebase_uid=user.uid,
            email=user.email,
            display_name=user.display_name,
        )
    except DATABASE_ERROR_TYPES as error:
        raise HTTPException(status_code=500, detail="登入資料暫時無法儲存。") from error


def _resolve_optional_app_user_id(authorization: str | None) -> int | None:
    user = _verify_firebase_authorization(authorization, required=False)
    return _save_verified_user(user) if user is not None else None


def _resolve_required_app_user_id(authorization: str | None) -> int:
    user = _verify_firebase_authorization(authorization, required=True)
    return _save_verified_user(user)


def _resolve_store_access(
    authorization: str | None,
    management_token: str | None,
) -> tuple[int | None, str]:
    """Resolve account ownership while preserving legacy management links."""
    if management_token:
        try:
            return _resolve_optional_app_user_id(authorization), management_token
        except HTTPException as error:
            if error.status_code != 401:
                raise
            return None, management_token
    if not authorization:
        return None, ""
    try:
        return _resolve_optional_app_user_id(authorization), ""
    except HTTPException as error:
        if error.status_code != 401 or not authorization.startswith("Bearer "):
            raise
        return None, authorization.removeprefix("Bearer ").strip()


@app.get("/api/auth/config", response_model=FirebaseWebConfigResponse)
async def get_auth_config() -> FirebaseWebConfigResponse:
    """只回傳 Firebase Web SDK 可公開使用的設定。"""
    config = get_firebase_web_config()
    if config is None:
        return FirebaseWebConfigResponse(enabled=False)
    return FirebaseWebConfigResponse(enabled=True, **config)


@app.get("/api/auth/me", response_model=FirebaseSessionResponse)
async def get_authenticated_user(
    authorization: Annotated[str | None, Header()] = None,
) -> FirebaseSessionResponse:
    """驗證 Firebase ID Token，讓後端取得可信任的 Firebase UID。"""
    user = _verify_firebase_authorization(authorization, required=True)
    _save_verified_user(user)
    return FirebaseSessionResponse(
        uid=user.uid,
        email=user.email,
        display_name=user.display_name,
    )


@app.get("/api/me/groups", response_model=MyGroupsResponse)
async def get_my_groups(
    archived: bool = False,
    authorization: Annotated[str | None, Header()] = None,
) -> MyGroupsResponse:
    user_id = _resolve_required_app_user_id(authorization)
    groups = get_owned_groups(owner_user_id=user_id, archived=archived)
    return MyGroupsResponse(
        groups=[
            MyGroupSummary(
                **group,
                public_url=f"/groups/{group['public_code']}",
                management_url=f"/groups/{group['public_code']}/manage?account=1",
                archive_api_url=f"/api/me/groups/{group['public_code']}",
            )
            for group in groups
        ]
    )


@app.post("/api/me/groups/{public_code}/archive", response_model=AccountClaimResponse)
async def archive_my_group(
    public_code: str,
    authorization: Annotated[str | None, Header()] = None,
) -> AccountClaimResponse:
    user_id = _resolve_required_app_user_id(authorization)
    try:
        set_owned_group_archived(
            public_code=public_code.strip().upper(),
            owner_user_id=user_id,
            archived=True,
        )
    except AccountArchiveDeniedError as error:
        raise HTTPException(status_code=403, detail="無法封存這個團購。") from error
    return AccountClaimResponse(message="團購已封存。")


@app.post("/api/me/groups/{public_code}/restore", response_model=AccountClaimResponse)
async def restore_my_group(
    public_code: str,
    authorization: Annotated[str | None, Header()] = None,
) -> AccountClaimResponse:
    user_id = _resolve_required_app_user_id(authorization)
    try:
        set_owned_group_archived(
            public_code=public_code.strip().upper(),
            owner_user_id=user_id,
            archived=False,
        )
    except AccountArchiveDeniedError as error:
        raise HTTPException(status_code=403, detail="無法恢復這個團購。") from error
    return AccountClaimResponse(message="團購已恢復。")


@app.get(
    "/api/me/groups/{public_code}/management",
    response_model=GroupManagementResponse,
)
async def get_my_group_management(
    public_code: str,
    authorization: Annotated[str | None, Header()] = None,
) -> GroupManagementResponse:
    user_id = _resolve_required_app_user_id(authorization)
    try:
        group = get_group_management_data_for_owner(
            public_code=public_code.strip().upper(),
            owner_user_id=user_id,
        )
    except GroupManagementAccessDeniedError as error:
        raise HTTPException(status_code=403, detail="無法開啟這個團購的管理資料。") from error
    return GroupManagementResponse.model_validate(group)


@app.get("/api/me/groups/{public_code}/management.xlsx")
async def download_my_group_management_excel(
    public_code: str,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    user_id = _resolve_required_app_user_id(authorization)
    normalized_code = public_code.strip().upper()
    try:
        group = get_group_management_data_for_owner(
            public_code=normalized_code,
            owner_user_id=user_id,
        )
    except GroupManagementAccessDeniedError as error:
        raise HTTPException(status_code=403, detail="無法下載這個團購的表格。") from error
    workbook = build_group_order_workbook(group)
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="group-{normalized_code}-orders.xlsx"',
            "Cache-Control": "no-store",
            "Content-Length": str(len(workbook)),
            "X-Order-Count": str(group["order_count"]),
            "X-Grand-Total": str(group["grand_total"]),
        },
    )


@app.post(
    "/api/me/groups/{public_code}/close",
    response_model=GroupManagementResponse,
)
async def close_my_group(
    public_code: str,
    authorization: Annotated[str | None, Header()] = None,
) -> GroupManagementResponse:
    user_id = _resolve_required_app_user_id(authorization)
    try:
        group = close_group_for_owner(
            public_code=public_code.strip().upper(),
            owner_user_id=user_id,
        )
    except GroupManagementAccessDeniedError as error:
        raise HTTPException(status_code=403, detail="無法關閉這個團購。") from error
    return GroupManagementResponse.model_validate(group)


@app.get("/api/me/orders", response_model=MyOrdersResponse)
async def get_my_orders(
    archived: bool = False,
    authorization: Annotated[str | None, Header()] = None,
) -> MyOrdersResponse:
    user_id = _resolve_required_app_user_id(authorization)
    orders = get_user_orders(user_id=user_id, archived=archived)
    summaries = []
    for order in orders:
        if order["mode"] == "group":
            url = (
                f"/groups/{order['public_code']}/orders/"
                f"{order['public_order_number']}?account=1"
            )
            archive_api_url = (
                f"/api/me/orders/group/{order['public_code']}/"
                f"{order['public_order_number']}"
            )
        else:
            url = (
                f"/stores/{order['public_slug']}/orders/"
                f"{order['public_order_number']}?account=1"
            )
            archive_api_url = (
                f"/api/me/orders/store/{order['public_slug']}/"
                f"{order['public_order_number']}"
            )
        summary_data = {
            key: value
            for key, value in order.items()
            if key not in {"public_code", "public_slug"}
        }
        summaries.append(
            MyOrderSummary(
                **summary_data,
                order_url=url,
                archive_api_url=archive_api_url,
            )
        )
    return MyOrdersResponse(orders=summaries)


@app.post(
    "/api/me/orders/{mode}/{parent_identifier}/{public_order_number}/archive",
    response_model=AccountClaimResponse,
)
async def archive_my_order(
    mode: str,
    parent_identifier: str,
    public_order_number: str,
    authorization: Annotated[str | None, Header()] = None,
) -> AccountClaimResponse:
    user_id = _resolve_required_app_user_id(authorization)
    normalized_parent = (
        parent_identifier.strip().upper()
        if mode == "group"
        else parent_identifier.strip().lower()
    )
    try:
        set_user_order_archived(
            mode=mode,
            parent_identifier=normalized_parent,
            public_order_number=public_order_number.strip().upper(),
            user_id=user_id,
            archived=True,
        )
    except (AccountArchiveDeniedError, ValueError) as error:
        raise HTTPException(status_code=403, detail="無法封存這張訂單。") from error
    return AccountClaimResponse(message="訂單已封存。")


@app.post(
    "/api/me/orders/{mode}/{parent_identifier}/{public_order_number}/restore",
    response_model=AccountClaimResponse,
)
async def restore_my_order(
    mode: str,
    parent_identifier: str,
    public_order_number: str,
    authorization: Annotated[str | None, Header()] = None,
) -> AccountClaimResponse:
    user_id = _resolve_required_app_user_id(authorization)
    normalized_parent = (
        parent_identifier.strip().upper()
        if mode == "group"
        else parent_identifier.strip().lower()
    )
    try:
        set_user_order_archived(
            mode=mode,
            parent_identifier=normalized_parent,
            public_order_number=public_order_number.strip().upper(),
            user_id=user_id,
            archived=False,
        )
    except (AccountArchiveDeniedError, ValueError) as error:
        raise HTTPException(status_code=403, detail="無法恢復這張訂單。") from error
    return AccountClaimResponse(message="訂單已恢復。")


@app.get(
    "/api/me/group-orders/{public_code}/{public_order_number}",
    response_model=PersonalGroupOrderResponse,
)
async def get_my_group_order(
    public_code: str,
    public_order_number: str,
    authorization: Annotated[str | None, Header()] = None,
) -> PersonalGroupOrderResponse:
    user_id = _resolve_required_app_user_id(authorization)
    try:
        order = get_group_order_for_user(
            public_code=public_code.strip().upper(),
            public_order_number=public_order_number.strip().upper(),
            user_id=user_id,
        )
    except GroupOrderAccessDeniedError as error:
        raise HTTPException(status_code=403, detail="無法查看這張訂單。") from error
    return PersonalGroupOrderResponse.model_validate(order)


@app.get(
    "/api/me/store-orders/{public_slug}/{public_order_number}",
    response_model=PersonalStoreOrderResponse,
)
async def get_my_store_order(
    public_slug: str,
    public_order_number: str,
    authorization: Annotated[str | None, Header()] = None,
) -> PersonalStoreOrderResponse:
    user_id = _resolve_required_app_user_id(authorization)
    try:
        order = get_store_order_for_user(
            public_slug=public_slug.strip().lower(),
            public_order_number=public_order_number.strip().upper(),
            user_id=user_id,
        )
    except StoreOrderAccessDeniedError as error:
        raise HTTPException(status_code=403, detail="無法查看這張訂單。") from error
    return PersonalStoreOrderResponse.model_validate(order)


@app.post(
    "/api/me/groups/{public_code}/claim",
    response_model=AccountClaimResponse,
)
async def claim_my_group(
    public_code: str,
    authorization: Annotated[str | None, Header()] = None,
    management_token: Annotated[
        str | None, Header(alias="X-Management-Token")
    ] = None,
) -> AccountClaimResponse:
    user_id = _resolve_required_app_user_id(authorization)
    try:
        claim_group(
            public_code=public_code.strip().upper(),
            management_token=management_token or "",
            user_id=user_id,
        )
    except AccountClaimDeniedError as error:
        raise HTTPException(status_code=403, detail="無法將這個團購保存到帳號。") from error
    return AccountClaimResponse(message="團購已保存到我的團購。")


@app.post(
    "/api/me/group-orders/{public_code}/{public_order_number}/claim",
    response_model=AccountClaimResponse,
)
async def claim_my_group_order(
    public_code: str,
    public_order_number: str,
    authorization: Annotated[str | None, Header()] = None,
    order_token: Annotated[str | None, Header(alias="X-Order-Token")] = None,
) -> AccountClaimResponse:
    user_id = _resolve_required_app_user_id(authorization)
    try:
        claim_group_order(
            public_code=public_code.strip().upper(),
            public_order_number=public_order_number.strip().upper(),
            order_access_token=order_token or "",
            user_id=user_id,
        )
    except AccountClaimDeniedError as error:
        raise HTTPException(status_code=403, detail="無法將這張訂單保存到帳號。") from error
    return AccountClaimResponse(message="訂單已保存到我的訂單。")


@app.post(
    "/api/me/store-orders/{public_slug}/{public_order_number}/claim",
    response_model=AccountClaimResponse,
)
async def claim_my_store_order(
    public_slug: str,
    public_order_number: str,
    authorization: Annotated[str | None, Header()] = None,
    order_token: Annotated[str | None, Header(alias="X-Order-Token")] = None,
) -> AccountClaimResponse:
    user_id = _resolve_required_app_user_id(authorization)
    try:
        claim_store_order(
            public_slug=public_slug.strip().lower(),
            public_order_number=public_order_number.strip().upper(),
            order_access_token=order_token or "",
            user_id=user_id,
        )
    except AccountClaimDeniedError as error:
        raise HTTPException(status_code=403, detail="無法將這張訂單保存到帳號。") from error
    return AccountClaimResponse(message="訂單已保存到我的訂單。")


@app.get("/api/me/menus", response_model=SavedMenusResponse)
async def get_my_menus(
    authorization: Annotated[str | None, Header()] = None,
) -> SavedMenusResponse:
    user_id = _resolve_required_app_user_id(authorization)
    menus = get_saved_menus(owner_user_id=user_id)
    menus.extend(list_store_menus_for_owner(owner_user_id=user_id))
    menus.sort(key=lambda menu: (str(menu["updated_at"]), menu["id"]), reverse=True)
    return SavedMenusResponse(menus=[SavedMenuSummary(**menu) for menu in menus])


@app.post(
    "/api/me/stores/{public_slug}/claim",
    response_model=AccountClaimResponse,
)
async def claim_my_store(
    public_slug: str,
    authorization: Annotated[str | None, Header()] = None,
    management_token: Annotated[str | None, Header(alias="X-Management-Token")] = None,
) -> AccountClaimResponse:
    user_id = _resolve_required_app_user_id(authorization)
    try:
        claim_store(
            public_slug=public_slug.strip().lower(),
            management_token=management_token or "",
            owner_user_id=user_id,
        )
    except AccountClaimDeniedError as error:
        raise HTTPException(
            status_code=403,
            detail="無法認領這份店家固定菜單，請使用原本的完整管理連結。",
        ) from error
    return AccountClaimResponse(message="店家固定菜單已儲存到我的菜單。")


@app.post(
    "/api/me/menus/{menu_id}/groups",
    response_model=GroupCreateResponse,
    status_code=201,
)
async def create_group_from_my_menu(
    menu_id: int,
    authorization: Annotated[str | None, Header()] = None,
) -> GroupCreateResponse:
    user_id = _resolve_required_app_user_id(authorization)
    try:
        created_group = create_group_from_saved_menu(
            menu_id=menu_id,
            owner_user_id=user_id,
        )
    except SavedMenuAccessDeniedError as error:
        raise HTTPException(status_code=403, detail="無法使用這份菜單。") from error
    public_code = created_group.public_code
    return GroupCreateResponse(
        success=True,
        message="已從我的菜單建立新團購，請保存統籌管理連結。",
        public_code=public_code,
        participant_url=f"/groups/{public_code}",
        management_url=f"/groups/{public_code}/manage#token={created_group.management_token}",
        restaurant_name=created_group.menu["restaurant"]["name"],
        category_count=len(created_group.menu["categories"]),
        item_count=sum(len(category["items"]) for category in created_group.menu["categories"]),
    )


@app.post("/api/groups", response_model=GroupCreateResponse, status_code=201)
async def create_group(
    confirmation: GroupCreateRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> GroupCreateResponse:
    """將人工確認菜單保存為獨立團購，回傳一次性管理連結。"""
    try:
        owner_user_id = _resolve_optional_app_user_id(authorization)
        created_group = create_group_from_confirmation(
            confirmation,
            owner_user_id=owner_user_id,
        )
    except DATABASE_ERROR_TYPES as error:
        raise HTTPException(
            status_code=500,
            detail="團購建立失敗，請稍後再試",
        ) from error

    public_code = created_group.public_code
    category_count = len(created_group.menu["categories"])
    item_count = sum(
        len(category["items"]) for category in created_group.menu["categories"]
    )
    return GroupCreateResponse(
        success=True,
        message="團購已成功建立，請保存統籌管理連結。",
        public_code=public_code,
        participant_url=f"/groups/{public_code}",
        management_url=(
            f"/groups/{public_code}/manage#token={created_group.management_token}"
        ),
        restaurant_name=created_group.menu["restaurant"]["name"],
        category_count=category_count,
        item_count=item_count,
    )


@app.post("/api/stores", response_model=StoreCreateResponse, status_code=201)
async def create_store(
    confirmation: GroupCreateRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> StoreCreateResponse:
    """將人工確認菜單保存為店家固定菜單，回傳一次性管理連結。"""
    try:
        owner_user_id = _resolve_optional_app_user_id(authorization)
        store = create_store_from_confirmation(
            confirmation,
            owner_user_id=owner_user_id,
        )
    except DATABASE_ERROR_TYPES as error:
        raise HTTPException(
            status_code=500,
            detail="店家固定菜單建立失敗，請稍後再試",
        ) from error

    slug = store.public_slug
    token_fragment = f"#token={store.management_token}"
    return StoreCreateResponse(
        success=True,
        message="店家固定菜單已建立，請保存管理連結。",
        public_slug=slug,
        public_url=f"/stores/{slug}",
        management_url=f"/stores/{slug}/manage{token_fragment}",
        menu_update_url=f"/stores/{slug}/menu-update{token_fragment}",
        restaurant_name=store.menu["restaurant"]["name"],
        version=store.version,
    )


@app.get("/api/stores/{public_slug}", response_model=PublicStoreResponse)
async def get_store(public_slug: str) -> PublicStoreResponse:
    """讓顧客取得店家目前生效的固定菜單。"""
    try:
        store = get_public_store_menu(public_slug.strip().lower())
    except StoreNotFoundError as error:
        raise HTTPException(status_code=404, detail="找不到這家店，請確認網址是否正確") from error
    return PublicStoreResponse.model_validate(store)


@app.get("/api/stores/{public_slug}/qr.svg", include_in_schema=False)
async def get_store_qr(public_slug: str, request: Request) -> Response:
    """產生只包含店家完整公開網址的 SVG QR Code。"""
    slug = public_slug.strip().lower()
    try:
        get_public_store_menu(slug)
    except StoreNotFoundError as error:
        raise HTTPException(status_code=404, detail="找不到這家店，無法產生 QR Code") from error

    origin = str(request.base_url).rstrip("/")
    public_url = f"{origin}/stores/{slug}"
    try:
        svg = build_store_qr_svg(public_url)
    except ValueError as error:
        raise HTTPException(status_code=500, detail="QR Code 產生失敗") from error
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )


@app.post(
    "/api/stores/{public_slug}/orders",
    response_model=StoreOrderCreateResponse,
    status_code=201,
)
async def submit_store_order(
    public_slug: str,
    order: StoreOrderCreateRequest,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> StoreOrderCreateResponse:
    """依店家目前菜單核價並建立顧客的個人訂單。"""
    slug = public_slug.strip().lower()
    try:
        user_id = _resolve_optional_app_user_id(authorization)
        identity = (
            f"user:{user_id}"
            if user_id is not None
            else f"guest:{order.contact_method}:{order.contact_value}"
        )
        source_ip = request.client.host if request.client else "unknown"
        with protect_order_submission(
            scope=f"store:{slug}",
            source_ip=source_ip,
            identity=identity,
            customer_name=order.customer_name,
            items=[item.model_dump() for item in order.items],
        ):
            created_order = create_store_order(slug, order, user_id=user_id)
    except DuplicateOrderSubmissionError as error:
        raise HTTPException(
            status_code=409,
            detail="這筆訂單剛剛已送出，請勿重複送單。",
        ) from error
    except OrderRateLimitExceededError as error:
        raise HTTPException(
            status_code=429,
            detail="短時間內送單次數過多，請稍後再試。",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except StoreNotFoundError as error:
        raise HTTPException(status_code=404, detail="找不到這家店，請確認網址是否正確") from error
    except StoreInactiveError as error:
        raise HTTPException(status_code=409, detail="店家目前暫停接單，不能新增訂單") from error
    except StoreOrderValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except DATABASE_ERROR_TYPES as error:
        raise HTTPException(status_code=500, detail="訂單儲存失敗，請稍後再試") from error

    order_number = created_order.public_order_number
    return StoreOrderCreateResponse(
        success=True,
        message="訂單已成功送出，請保存個人訂單連結。",
        public_order_number=order_number,
        order_url=(
            f"/stores/{slug}/orders/{order_number}"
            f"#token={created_order.order_access_token}"
        ),
        customer_name=created_order.customer_name,
        total_amount=created_order.total_amount,
        created_at=created_order.created_at,
        items=created_order.items,
    )


@app.get(
    "/api/stores/{public_slug}/orders/{public_order_number}",
    response_model=PersonalStoreOrderResponse,
)
async def get_personal_store_order_api(
    public_slug: str,
    public_order_number: str,
    authorization: Annotated[str | None, Header()] = None,
) -> PersonalStoreOrderResponse:
    """只有持有個人查看 Token 的顧客能讀取該張店家訂單。"""
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    try:
        order = get_personal_store_order(
            public_slug=public_slug.strip().lower(),
            public_order_number=public_order_number.strip().upper(),
            order_access_token=token,
        )
    except StoreOrderAccessDeniedError as error:
        raise HTTPException(
            status_code=403,
            detail="無法查看這張訂單，請使用送單成功時取得的完整個人連結",
        ) from error
    return PersonalStoreOrderResponse.model_validate(order)


@app.get(
    "/api/stores/{public_slug}/management",
    response_model=StoreManagementResponse,
)
async def get_store_management_api(
    public_slug: str,
    authorization: Annotated[str | None, Header()] = None,
    management_token: Annotated[str | None, Header(alias="X-Management-Token")] = None,
) -> StoreManagementResponse:
    """只有持有店家管理 Token 的人能取得該店全部顧客訂單。"""
    owner_user_id, token = _resolve_store_access(authorization, management_token)
    try:
        store = get_store_management_data(
            public_slug=public_slug.strip().lower(),
            management_token=token,
            owner_user_id=owner_user_id,
        )
    except StoreManagementAccessDeniedError as error:
        raise HTTPException(
            status_code=403,
            detail="無法開啟店家訂單，請使用建立店家時取得的完整管理連結",
        ) from error
    return StoreManagementResponse.model_validate(store)


@app.get("/api/stores/{public_slug}/management.xlsx")
async def download_store_management_excel(
    public_slug: str,
    authorization: Annotated[str | None, Header()] = None,
    management_token: Annotated[str | None, Header(alias="X-Management-Token")] = None,
) -> Response:
    """驗證店家管理 Token 後，下載不含私密 Token 的 Excel 訂單表。"""
    owner_user_id, token = _resolve_store_access(authorization, management_token)
    normalized_slug = public_slug.strip().lower()
    try:
        store = get_store_management_data(
            public_slug=normalized_slug,
            management_token=token,
            owner_user_id=owner_user_id,
        )
    except StoreManagementAccessDeniedError as error:
        raise HTTPException(
            status_code=403,
            detail="無法下載店家訂單表格，請使用建立店家時取得的完整管理連結",
        ) from error

    workbook = build_store_order_workbook(store)
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="store-{normalized_slug}-orders.xlsx"',
            "Cache-Control": "no-store",
            "Content-Length": str(len(workbook)),
            "X-Order-Count": str(store["order_count"]),
            "X-Grand-Total": str(store["grand_total"]),
        },
    )


@app.put(
    "/api/stores/{public_slug}/menu",
    response_model=StoreMenuUpdateResponse,
)
async def update_store_menu(
    public_slug: str,
    confirmation: GroupCreateRequest,
    authorization: Annotated[str | None, Header()] = None,
    management_token: Annotated[str | None, Header(alias="X-Management-Token")] = None,
) -> StoreMenuUpdateResponse:
    """驗證店家管理 Token 後更新目前固定菜單。"""
    owner_user_id, token = _resolve_store_access(authorization, management_token)
    slug = public_slug.strip().lower()
    try:
        store = update_store_from_confirmation(
            public_slug=slug,
            management_token=token,
            owner_user_id=owner_user_id,
            confirmation=confirmation,
        )
    except StoreManagementAccessDeniedError as error:
        raise HTTPException(
            status_code=403,
            detail="無法更新固定菜單，請使用建立店家時取得的完整管理連結",
        ) from error
    except DATABASE_ERROR_TYPES as error:
        raise HTTPException(
            status_code=500,
            detail="固定菜單更新失敗，請稍後再試",
        ) from error
    return StoreMenuUpdateResponse(
        success=True,
        message="固定菜單已更新，公開網址維持不變。",
        public_slug=slug,
        public_url=f"/stores/{slug}",
        restaurant_name=store["menu"]["restaurant"]["name"],
        version=store["version"],
    )


@app.get("/api/groups/{public_code}", response_model=PublicGroupResponse)
async def get_group(public_code: str) -> PublicGroupResponse:
    """讓參與者以公開團購代碼讀取該次菜單。"""
    normalized_code = public_code.strip().upper()
    group = get_public_group_menu(normalized_code)
    if group is None:
        raise HTTPException(status_code=404, detail="找不到這個團購，請確認代碼是否正確")
    return PublicGroupResponse.model_validate(group)


@app.get("/api/groups/{public_code}/qr.svg", include_in_schema=False)
async def get_group_qr(public_code: str, request: Request) -> Response:
    """產生只包含參與者公開網址、不含管理權限的團購 QR Code。"""
    normalized_code = public_code.strip().upper()
    if get_public_group_menu(normalized_code) is None:
        raise HTTPException(status_code=404, detail="找不到這個團購，請確認代碼是否正確")
    origin = str(request.base_url).rstrip("/")
    public_url = f"{origin}/groups/{normalized_code}"
    try:
        svg = build_store_qr_svg(public_url)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="無法建立團購 QR Code") from error
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.post(
    "/api/groups/{public_code}/orders",
    response_model=GroupOrderCreateResponse,
    status_code=201,
)
async def submit_group_order(
    public_code: str,
    order: GroupOrderCreateRequest,
    request: Request,
    response: Response,
    authorization: Annotated[str | None, Header()] = None,
) -> GroupOrderCreateResponse:
    """依團購菜單快照核價並建立參與者的個人訂單。"""
    normalized_code = public_code.strip().upper()
    try:
        user_id = _resolve_optional_app_user_id(authorization)
        identity = (
            f"user:{user_id}"
            if user_id is not None
            else f"guest:{order.contact_method}:{order.contact_value}"
        )
        existing_order_number, existing_order_token = _group_order_cookie(
            request, normalized_code, identity
        )
        source_ip = request.client.host if request.client else "unknown"
        with protect_order_submission(
            scope=f"group:{normalized_code}",
            source_ip=source_ip,
            identity=identity,
            customer_name=order.customer_name,
            items=[item.model_dump() for item in order.items],
            check_duplicate=user_id is None and not existing_order_token,
        ):
            created_order = create_group_order(
                normalized_code,
                order,
                user_id=user_id,
                existing_order_number=existing_order_number,
                existing_order_access_token=existing_order_token,
            )
    except DuplicateOrderSubmissionError as error:
        raise HTTPException(
            status_code=409,
            detail="這筆訂單剛剛已送出，請勿重複送單。",
        ) from error
    except OrderRateLimitExceededError as error:
        raise HTTPException(
            status_code=429,
            detail="短時間內送單次數過多，請稍後再試。",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except GroupOrderAlreadyExistsError as error:
        if error.can_update:
            detail = {
                "code": "ORDER_ACTION_REQUIRED",
                "message": "這個身分在本團購已有訂單，請選擇加購或修改原訂單。",
                "public_order_number": error.public_order_number,
            }
        else:
            detail = {
                "code": "ORDER_ALREADY_EXISTS",
                "message": (
                    "這個聯絡方式在本團購已有訂單。為保護訂購者，"
                    "請使用第一次送單的裝置或原個人訂單連結處理。"
                ),
            }
        raise HTTPException(status_code=409, detail=detail) from error
    except GroupOrderAccessDeniedError as error:
        raise HTTPException(
            status_code=403,
            detail="無法修改原訂單，請使用第一次送單的裝置或登入原帳號。",
        ) from error
    except GroupNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="找不到這個團購，請確認代碼是否正確",
        ) from error
    except GroupClosedError as error:
        raise HTTPException(
            status_code=409,
            detail="這個團購已截止，不能再新增訂單",
        ) from error
    except GroupOrderValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except DATABASE_ERROR_TYPES as error:
        raise HTTPException(
            status_code=500,
            detail="訂單儲存失敗，請稍後再試",
        ) from error

    order_number = created_order.public_order_number
    response.status_code = 200 if created_order.was_updated else 201
    _remember_group_order(
        response,
        request,
        normalized_code,
        identity,
        order_number,
        created_order.order_access_token,
    )
    return GroupOrderCreateResponse(
        success=True,
        message=(
            "原訂單已更新，訂單編號保持不變。"
            if created_order.was_updated
            else "訂單已成功送出，請保存個人訂單連結。"
        ),
        public_order_number=order_number,
        order_url=(
            f"/groups/{normalized_code}/orders/{order_number}"
            f"#token={created_order.order_access_token}"
        ),
        customer_name=created_order.customer_name,
        total_amount=created_order.total_amount,
        created_at=created_order.created_at,
        items=created_order.items,
    )


@app.get(
    "/api/groups/{public_code}/orders/{public_order_number}",
    response_model=PersonalGroupOrderResponse,
)
async def get_personal_order(
    public_code: str,
    public_order_number: str,
    authorization: Annotated[str | None, Header()] = None,
) -> PersonalGroupOrderResponse:
    """只有持有個人查看 Token 的參與者能讀取該張訂單。"""
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    try:
        order = get_personal_group_order(
            public_code=public_code.strip().upper(),
            public_order_number=public_order_number.strip().upper(),
            order_access_token=token,
        )
    except GroupOrderAccessDeniedError as error:
        raise HTTPException(
            status_code=403,
            detail="無法查看這張訂單，請使用送單成功時取得的完整個人連結",
        ) from error
    return PersonalGroupOrderResponse.model_validate(order)


@app.get(
    "/api/groups/{public_code}/management",
    response_model=GroupManagementResponse,
)
async def get_group_management(
    public_code: str,
    authorization: Annotated[str | None, Header()] = None,
) -> GroupManagementResponse:
    """只有持有統籌管理 Token 的人能取得團購全部個人明細。"""
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    try:
        group = get_group_management_data(
            public_code=public_code.strip().upper(),
            management_token=token,
        )
    except GroupManagementAccessDeniedError as error:
        raise HTTPException(
            status_code=403,
            detail="無法開啟統籌管理資料，請使用建立團購時取得的完整管理連結",
        ) from error
    return GroupManagementResponse.model_validate(group)


@app.get("/api/groups/{public_code}/management.xlsx")
async def download_group_management_excel(
    public_code: str,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """驗證統籌管理 Token 後，下載不含私密 Token 的 Excel 訂單表。"""
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    normalized_code = public_code.strip().upper()
    try:
        group = get_group_management_data(
            public_code=normalized_code,
            management_token=token,
        )
    except GroupManagementAccessDeniedError as error:
        raise HTTPException(
            status_code=403,
            detail="無法下載團購表格，請使用建立團購時取得的完整管理連結",
        ) from error

    workbook = build_group_order_workbook(group)
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="group-{normalized_code}-orders.xlsx"',
            "Cache-Control": "no-store",
            "Content-Length": str(len(workbook)),
            "X-Order-Count": str(group["order_count"]),
            "X-Grand-Total": str(group["grand_total"]),
        },
    )


@app.post(
    "/api/groups/{public_code}/close",
    response_model=GroupManagementResponse,
)
async def close_group_session(
    public_code: str,
    authorization: Annotated[str | None, Header()] = None,
) -> GroupManagementResponse:
    """驗證統籌管理 Token 後關閉團購，之後拒絕新訂單。"""
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    try:
        group = close_group(
            public_code=public_code.strip().upper(),
            management_token=token,
        )
    except GroupManagementAccessDeniedError as error:
        raise HTTPException(
            status_code=403,
            detail="無法關閉團購，請使用建立團購時取得的完整管理連結",
        ) from error
    except DATABASE_ERROR_TYPES as error:
        raise HTTPException(
            status_code=500,
            detail="團購暫時無法關閉，請稍後再試",
        ) from error
    return GroupManagementResponse.model_validate(group)


@app.post("/api/menu-uploads", response_model=MenuRecognitionResponse)
async def upload_menu_file(
    files: Annotated[list[UploadFile] | None, File(alias="file")] = None,
) -> MenuRecognitionResponse:
    """驗證菜單檔案並回傳尚未確認的 AI 辨識結果。"""
    upload_files = files or []
    if not upload_files:
        error = missing_file_error()
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        )
    if len(upload_files) != 1:
        for upload in upload_files:
            await upload.close()
        error = multiple_files_error()
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        )

    upload = upload_files[0]
    try:
        validated = await validate_menu_upload(upload)
        recognition = await recognize_menu(validated)
    except MenuUploadValidationError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    except MenuRecognitionError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    finally:
        await upload.close()

    return MenuRecognitionResponse(
        success=True,
        message="菜單辨識完成，請確認辨識結果。",
        file=MenuUploadFileResponse(
            name=validated.filename,
            content_type=validated.content_type,
            size=validated.size,
            page_count=validated.page_count,
        ),
        recognition=recognition,
    )


@app.get("/api/admin/orders", response_model=AdminOrderListResponse)
async def get_admin_orders() -> AdminOrderListResponse:
    """取得所有訂單及完整餐點明細。"""
    try:
        orders = get_orders_with_items()
    except DATABASE_ERROR_TYPES as error:
        raise HTTPException(
            status_code=500,
            detail="訂單資料暫時無法讀取，請稍後再試",
        ) from error
    return AdminOrderListResponse(orders=orders)


@app.post("/api/orders", response_model=OrderCreateResponse, status_code=201)
async def create_order(order: OrderCreateRequest) -> OrderCreateResponse:
    """驗證訂單格式，完整寫入 SQLite 後回傳結果。"""
    accepted_order = AcceptedOrder(
        **order.model_dump(),
        created_at=datetime.now(timezone.utc),
    )
    try:
        order_id = save_order(accepted_order)
    except DATABASE_ERROR_TYPES as error:
        raise HTTPException(
            status_code=500,
            detail="訂單儲存失敗，請稍後再試",
        ) from error

    return OrderCreateResponse(
        success=True,
        message="訂單已成功儲存",
        order_id=order_id,
        order=accepted_order,
    )


@app.get("/", include_in_schema=False)
async def show_ordering_page() -> RedirectResponse:
    """將首頁導向雙模式選擇頁。"""
    return RedirectResponse(url="/frontend/")


@app.get("/demo", include_in_schema=False)
async def show_demo_ordering_page() -> FileResponse:
    """顯示不依賴 AI 的固定示範菜單。"""
    return FileResponse(FRONTEND_DIRECTORY / "demo.html")


@app.get("/admin", include_in_schema=False)
async def show_admin_page() -> RedirectResponse:
    """將簡短網址導向管理者訂單頁面。"""
    return RedirectResponse(url="/frontend/admin.html")


@app.get("/upload", include_in_schema=False)
async def show_upload_page(mode: str | None = None) -> RedirectResponse:
    """將簡短網址導向菜單上傳頁，並保留首頁選擇的模式。"""
    target = "/frontend/upload.html"
    if mode in {"group", "store"}:
        target = f"{target}?mode={mode}"
    return RedirectResponse(url=target)


@app.get("/join", include_in_schema=False)
async def show_group_join_page() -> FileResponse:
    """顯示可輸入團購代碼的公開入口。"""
    return FileResponse(FRONTEND_DIRECTORY / "group.html")


@app.get("/me/groups", include_in_schema=False)
async def show_my_groups_page() -> FileResponse:
    return FileResponse(FRONTEND_DIRECTORY / "my-groups.html")


@app.get("/me/orders", include_in_schema=False)
async def show_my_orders_page() -> FileResponse:
    return FileResponse(FRONTEND_DIRECTORY / "my-orders.html")


@app.get("/me/menus", include_in_schema=False)
async def show_my_menus_page() -> FileResponse:
    return FileResponse(FRONTEND_DIRECTORY / "my-menus.html")


@app.get("/groups/{public_code}", include_in_schema=False)
async def show_group_page(public_code: str) -> FileResponse:
    """保留分享網址中的團購代碼並顯示公開菜單頁。"""
    return FileResponse(FRONTEND_DIRECTORY / "group.html")


@app.get("/groups/{public_code}/manage", include_in_schema=False)
async def show_group_management_page(public_code: str) -> FileResponse:
    """顯示統籌管理頁，權限由瀏覽器中的私密 Token 另行驗證。"""
    return FileResponse(FRONTEND_DIRECTORY / "group-management.html")


@app.get("/stores/{public_slug}/menu-update", include_in_schema=False)
async def show_store_menu_update_page(public_slug: str) -> FileResponse:
    """使用既有上傳與人工確認頁更新店家固定菜單。"""
    return FileResponse(FRONTEND_DIRECTORY / "upload.html")


@app.get("/stores/{public_slug}/manage", include_in_schema=False)
async def show_store_management_page(public_slug: str) -> FileResponse:
    """顯示店家訂單後台，資料需另以私密管理 Token 取得。"""
    return FileResponse(FRONTEND_DIRECTORY / "store-management.html")


@app.get("/stores/{public_slug}", include_in_schema=False)
async def show_store_page(public_slug: str) -> FileResponse:
    """顯示店家固定公開菜單頁。"""
    return FileResponse(FRONTEND_DIRECTORY / "store.html")


@app.get(
    "/stores/{public_slug}/orders/{public_order_number}",
    include_in_schema=False,
)
async def show_store_personal_order_page(
    public_slug: str,
    public_order_number: str,
) -> FileResponse:
    """顯示店家顧客個人訂單頁，資料需另以私密 Token 取得。"""
    return FileResponse(FRONTEND_DIRECTORY / "personal-order.html")


@app.get(
    "/groups/{public_code}/orders/{public_order_number}",
    include_in_schema=False,
)
async def show_personal_order_page(
    public_code: str,
    public_order_number: str,
) -> FileResponse:
    """顯示個人訂單頁，權限由瀏覽器中的私密 Token 另行驗證。"""
    return FileResponse(FRONTEND_DIRECTORY / "personal-order.html")
