from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from pydantic import BaseModel
from pypdf import PdfReader
from pypdf.errors import PdfReadError


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_LABEL = "10 MB"

ALLOWED_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
}

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_END_MARKER = b"\x00\x00\x00\x00IEND\xaeB`\x82"
JPEG_SIGNATURE = b"\xff\xd8\xff"
JPEG_END_MARKER = b"\xff\xd9"
PDF_SIGNATURE = b"%PDF-"


class MenuUploadValidationError(ValueError):
    """可安全顯示給使用者的菜單檔案驗證錯誤。"""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedMenuUpload:
    filename: str
    content_type: str
    size: int
    page_count: int | None
    content: bytes


class MenuUploadFileResponse(BaseModel):
    name: str
    content_type: str
    size: int
    page_count: int | None


class MenuUploadResponse(BaseModel):
    success: bool
    message: str
    file: MenuUploadFileResponse


def missing_file_error() -> MenuUploadValidationError:
    return MenuUploadValidationError(
        code="FILE_REQUIRED",
        message="請選擇一個菜單檔案。",
    )


def multiple_files_error() -> MenuUploadValidationError:
    return MenuUploadValidationError(
        code="MULTIPLE_FILES_NOT_ALLOWED",
        message="一次只能上傳一個菜單檔案。",
    )


def _validate_image_content(extension: str, content: bytes) -> None:
    if extension in {".jpg", ".jpeg"}:
        if not content.startswith(JPEG_SIGNATURE):
            raise MenuUploadValidationError(
                code="FILE_TYPE_MISMATCH",
                message="檔案內容與副檔名不一致，請重新匯出後再上傳。",
                status_code=415,
            )
        if not content.endswith(JPEG_END_MARKER):
            raise MenuUploadValidationError(
                code="UNREADABLE_FILE",
                message="無法讀取這個檔案，請確認檔案沒有損壞後再試一次。",
                status_code=422,
            )
        return

    if not content.startswith(PNG_SIGNATURE):
        raise MenuUploadValidationError(
            code="FILE_TYPE_MISMATCH",
            message="檔案內容與副檔名不一致，請重新匯出後再上傳。",
            status_code=415,
        )
    if not content.endswith(PNG_END_MARKER):
        raise MenuUploadValidationError(
            code="UNREADABLE_FILE",
            message="無法讀取這個檔案，請確認檔案沒有損壞後再試一次。",
            status_code=422,
        )


def _get_pdf_page_count(content: bytes) -> int:
    if not content.startswith(PDF_SIGNATURE):
        raise MenuUploadValidationError(
            code="FILE_TYPE_MISMATCH",
            message="檔案內容與副檔名不一致，請重新匯出後再上傳。",
            status_code=415,
        )

    try:
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise PdfReadError("encrypted PDF")
        page_count = len(reader.pages)
    except (PdfReadError, OSError, ValueError) as error:
        raise MenuUploadValidationError(
            code="UNREADABLE_FILE",
            message="無法讀取這個檔案，請確認檔案沒有損壞後再試一次。",
            status_code=422,
        ) from error

    if page_count != 1:
        raise MenuUploadValidationError(
            code="PDF_PAGE_COUNT_INVALID",
            message="目前只支援一頁式 PDF，請只保留一頁後再上傳。",
            status_code=422,
        )
    return page_count


async def validate_menu_upload(upload: UploadFile) -> ValidatedMenuUpload:
    """讀取並驗證一個菜單檔案，但不儲存或送往 AI。"""
    original_filename = upload.filename or ""
    safe_filename = Path(original_filename).name
    extension = Path(safe_filename).suffix.lower()

    if extension not in ALLOWED_CONTENT_TYPES:
        raise MenuUploadValidationError(
            code="UNSUPPORTED_FILE_TYPE",
            message="檔案格式不支援，請上傳 JPG、PNG 或一頁式 PDF。",
            status_code=415,
        )

    expected_content_type = ALLOWED_CONTENT_TYPES[extension]
    if upload.content_type != expected_content_type:
        raise MenuUploadValidationError(
            code="FILE_TYPE_MISMATCH",
            message="檔案內容與副檔名不一致，請重新匯出後再上傳。",
            status_code=415,
        )

    content = await upload.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise MenuUploadValidationError(
            code="EMPTY_FILE",
            message="這個檔案是空的，請重新選擇菜單檔案。",
        )
    if len(content) > MAX_UPLOAD_BYTES:
        raise MenuUploadValidationError(
            code="FILE_TOO_LARGE",
            message=f"檔案超過 {MAX_UPLOAD_LABEL}，請縮小檔案後再試一次。",
            status_code=413,
        )

    page_count = None
    if extension == ".pdf":
        page_count = _get_pdf_page_count(content)
    else:
        _validate_image_content(extension, content)

    return ValidatedMenuUpload(
        filename=safe_filename,
        content_type=expected_content_type,
        size=len(content),
        page_count=page_count,
        content=content,
    )
