from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, AsyncIterator

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.database import (
    GroupClosedError,
    GroupManagementAccessDeniedError,
    GroupNotFoundError,
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
    save_order,
)
from backend.database_compat import DATABASE_ERROR_TYPES
from backend.group_orders import (
    create_group_from_confirmation,
    create_group_order,
    close_group,
    get_group_management_data,
    get_personal_group_order,
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
from backend.schemas import (
    AcceptedOrder,
    AdminOrderListResponse,
    GroupCreateRequest,
    GroupCreateResponse,
    GroupOrderCreateRequest,
    GroupOrderCreateResponse,
    GroupManagementResponse,
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
    create_store_from_confirmation,
    get_public_store_menu,
    get_store_management_data,
    update_store_from_confirmation,
)
from backend.store_qr import build_store_qr_svg
from backend.store_orders import create_store_order, get_personal_store_order


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIRECTORY = PROJECT_ROOT / "frontend"
DATA_DIRECTORY = PROJECT_ROOT / "data"


class MenuRecognitionResponse(MenuUploadResponse):
    recognition: MenuRecognitionResult


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """服務啟動時確認目前環境的資料表已建立。"""
    initialize_database()
    yield


app = FastAPI(title="AI 菜單點餐系統", lifespan=lifespan)

app.mount(
    "/frontend",
    StaticFiles(directory=FRONTEND_DIRECTORY, html=True),
    name="frontend",
)
app.mount("/data", StaticFiles(directory=DATA_DIRECTORY), name="data")


@app.post("/api/groups", response_model=GroupCreateResponse, status_code=201)
async def create_group(confirmation: GroupCreateRequest) -> GroupCreateResponse:
    """將人工確認菜單保存為獨立團購，回傳一次性管理連結。"""
    try:
        created_group = create_group_from_confirmation(confirmation)
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
async def create_store(confirmation: GroupCreateRequest) -> StoreCreateResponse:
    """將人工確認菜單保存為店家固定菜單，回傳一次性管理連結。"""
    try:
        store = create_store_from_confirmation(confirmation)
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
) -> StoreOrderCreateResponse:
    """依店家目前菜單核價並建立顧客的個人訂單。"""
    slug = public_slug.strip().lower()
    try:
        created_order = create_store_order(slug, order)
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
) -> StoreManagementResponse:
    """只有持有店家管理 Token 的人能取得該店全部顧客訂單。"""
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    try:
        store = get_store_management_data(
            public_slug=public_slug.strip().lower(),
            management_token=token,
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
) -> Response:
    """驗證店家管理 Token 後，下載不含私密 Token 的 Excel 訂單表。"""
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    normalized_slug = public_slug.strip().lower()
    try:
        store = get_store_management_data(
            public_slug=normalized_slug,
            management_token=token,
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
) -> StoreMenuUpdateResponse:
    """驗證店家管理 Token 後更新目前固定菜單。"""
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    slug = public_slug.strip().lower()
    try:
        store = update_store_from_confirmation(
            public_slug=slug,
            management_token=token,
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


@app.post(
    "/api/groups/{public_code}/orders",
    response_model=GroupOrderCreateResponse,
    status_code=201,
)
async def submit_group_order(
    public_code: str,
    order: GroupOrderCreateRequest,
) -> GroupOrderCreateResponse:
    """依團購菜單快照核價並建立參與者的個人訂單。"""
    normalized_code = public_code.strip().upper()
    try:
        created_order = create_group_order(normalized_code, order)
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
    return GroupOrderCreateResponse(
        success=True,
        message="訂單已成功送出，請保存個人訂單連結。",
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
