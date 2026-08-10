import asyncio
import json
import logging
import os
import re
import ssl
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.menu_upload import ValidatedMenuUpload


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "doc" / "menu-recognition.schema.json"
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
MAX_RETRY_ATTEMPTS = 2
RETRY_DELAYS_SECONDS = (1, 2)
LOGGER = logging.getLogger("uvicorn.error")

MENU_RECOGNITION_PROMPT = """你是台灣餐廳菜單資料擷取助手。請只依本次檔案中實際可見的內容輸出資料。

規則：
1. 擷取餐廳名稱、分類、餐點名稱、實際印出的簡短說明與新臺幣價格。
2. 保留原菜單的分類及餐點順序，不得固定成飯類、麵類或其他預設分類。
3. 不得增加檔案中不存在的分類、餐點、說明或價格。
4. 菜單沒有分類時，將可辨識餐點放在「未分類」。
5. 價格只輸出大於或等於 0 的整數，不包含 NT$、元、逗號或貨幣文字。
6. 沒有餐點說明時，description 輸出空字串。
7. 必須仔細比對每一列餐點與同列、點線後方或價格欄中的數字；若上方欄名標示 M、L、大、小、冷、熱等規格，要依欄位位置配對原菜單價格。
8. 同一餐點有兩個以上且規格標示清楚的價格時，不要留空，也不要任選一個。請拆成多個可獨立點選的餐點，名稱加上原菜單規格，例如「古早味紅茶（M）」與「古早味紅茶（L）」，各自填入對應價格。
9. 套餐與單點價格同時存在且標示清楚時，也拆成名稱清楚的獨立餐點；加料價格只有在原菜單將它列為可單獨點選的品項時才建立餐點。
10. 只有文字或數字真的無法從圖片確認時才輸出 null；不得因版面有價格欄、共用欄名或多種規格就把所有價格設為 null。
11. 名稱或價格看不清楚時輸出 null，needs_review 設為 true，並用繁體中文在 warnings 說明。
12. 不得依常識、其他餐廳或先前菜單猜測缺漏內容。
"""


class MenuRecognitionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None
    description: str
    price: Annotated[int, Field(ge=0, strict=True)] | None


class MenuRecognitionCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None
    items: list[MenuRecognitionItem]


class MenuRecognitionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    restaurant_name: str | None
    categories: list[MenuRecognitionCategory]
    needs_review: bool
    warnings: list[str]


class MenuRecognitionError(RuntimeError):
    """可安全回傳給店家的 AI 辨識錯誤。"""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _recognition_error(code: str) -> MenuRecognitionError:
    error_messages = {
        "AI_NOT_CONFIGURED": (
            "AI 菜單辨識尚未完成設定，請聯絡系統管理者。",
            503,
        ),
        "AI_RATE_LIMITED": ("AI 服務目前忙碌，請稍後再試。", 429),
        "AI_QUOTA_EXHAUSTED": (
            "今日免費 AI 額度可能已用完，請稍後或隔天再試。",
            429,
        ),
        "AI_SERVICE_UNAVAILABLE": ("AI 服務暫時無法使用，請稍後再試。", 503),
        "AI_REFUSED": (
            "這份菜單目前無法由 AI 處理，請改用其他清楚的菜單檔案。",
            422,
        ),
        "AI_RESPONSE_INCOMPLETE": ("AI 回應不完整，請重新辨識。", 502),
        "AI_OUTPUT_INVALID": ("AI 辨識結果格式不正確，請重新辨識。", 502),
        "AI_NO_MENU_FOUND": (
            "沒有辨識到菜單內容，請確認圖片清楚且包含完整菜單。",
            422,
        ),
    }
    message, status_code = error_messages[code]
    return MenuRecognitionError(code, message, status_code)


def _load_recognition_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


def _make_file_part(upload: ValidatedMenuUpload) -> types.Part:
    return types.Part.from_bytes(
        data=upload.content,
        mime_type=upload.content_type,
    )


def _get_gemini_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise _recognition_error("AI_NOT_CONFIGURED")

    http_options = types.HttpOptions(timeout=60_000)
    if os.name == "nt":
        try:
            import truststore
        except ImportError:
            pass
        else:
            ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            http_options.async_client_args = {
                "transport": httpx.AsyncHTTPTransport(verify=ssl_context),
            }

    return genai.Client(api_key=api_key, http_options=http_options)


def _enum_name(value: Any) -> str:
    return str(getattr(value, "name", value or "")).upper()


def _extract_result(response: Any) -> MenuRecognitionResult:
    prompt_feedback = getattr(response, "prompt_feedback", None)
    block_reason = _enum_name(getattr(prompt_feedback, "block_reason", None))
    if block_reason and block_reason not in {"BLOCK_REASON_UNSPECIFIED", "NONE"}:
        raise _recognition_error("AI_REFUSED")

    candidates = getattr(response, "candidates", None) or []
    finish_reason = _enum_name(
        getattr(candidates[0], "finish_reason", None) if candidates else None
    )
    if finish_reason in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
        raise _recognition_error("AI_REFUSED")
    if finish_reason in {"MAX_TOKENS", "MALFORMED_FUNCTION_CALL"}:
        raise _recognition_error("AI_RESPONSE_INCOMPLETE")

    raw_result = getattr(response, "parsed", None)
    if raw_result is None:
        try:
            response_text = response.text
            raw_result = json.loads(response_text)
        except (AttributeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise _recognition_error("AI_OUTPUT_INVALID") from error

    try:
        result = MenuRecognitionResult.model_validate(raw_result)
    except (TypeError, ValidationError) as error:
        raise _recognition_error("AI_OUTPUT_INVALID") from error

    if not result.categories or not any(category.items for category in result.categories):
        raise _recognition_error("AI_NO_MENU_FOUND")
    return result


def _is_daily_quota_error(error: genai_errors.APIError) -> bool:
    quota_ids = _quota_ids(error)
    if quota_ids:
        return any(
            "perday" in quota_id.lower() or "daily" in quota_id.lower()
            for quota_id in quota_ids
        )
    message = str(getattr(error, "message", "")).lower()
    markers = ("per day", "per_day", "daily")
    return any(marker in message for marker in markers)


def _api_error_details(error: genai_errors.APIError) -> list[dict[str, Any]]:
    root = getattr(error, "details", None)
    if not isinstance(root, dict):
        return []
    nested_error = root.get("error")
    if isinstance(nested_error, dict):
        root = nested_error
    details = root.get("details", [])
    return [detail for detail in details if isinstance(detail, dict)]


def _quota_ids(error: genai_errors.APIError) -> list[str]:
    quota_ids = []
    for detail in _api_error_details(error):
        if not str(detail.get("@type", "")).endswith("QuotaFailure"):
            continue
        for violation in detail.get("violations", []):
            if not isinstance(violation, dict):
                continue
            quota_id = violation.get("quotaId")
            if quota_id:
                quota_ids.append(str(quota_id))
    return quota_ids


def _quota_kind(error: genai_errors.APIError) -> str:
    joined_ids = " ".join(_quota_ids(error)).lower()
    if "perday" in joined_ids or "daily" in joined_ids:
        return "DAILY"
    if "token" in joined_ids and "perminute" in joined_ids:
        return "TPM"
    if "request" in joined_ids and "perminute" in joined_ids:
        return "RPM"
    if "perminute" in joined_ids:
        return "PER_MINUTE"
    return "UNKNOWN"


def _parse_retry_delay(value: Any) -> float | None:
    if isinstance(value, dict):
        try:
            seconds = float(value.get("seconds", 0))
            nanos = float(value.get("nanos", 0))
        except (TypeError, ValueError):
            return None
        delay = seconds + nanos / 1_000_000_000
        return delay if delay >= 0 else None
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", value)
        if match:
            return float(match.group(1))
    return None


def _retry_delay_seconds(error: Exception) -> float | None:
    if not isinstance(error, genai_errors.APIError):
        return None
    for detail in _api_error_details(error):
        if str(detail.get("@type", "")).endswith("RetryInfo"):
            delay = _parse_retry_delay(detail.get("retryDelay"))
            if delay is not None:
                return delay
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        try:
            delay = float(headers.get("retry-after", ""))
        except (TypeError, ValueError):
            return None
        return delay if delay >= 0 else None
    return None


def _is_retryable_error(error: Exception) -> bool:
    if isinstance(error, genai_errors.APIError):
        if error.code == 429:
            return not _is_daily_quota_error(error)
        return isinstance(error.code, int) and 500 <= error.code < 600
    return isinstance(
        error,
        (httpx.TimeoutException, httpx.TransportError, OSError),
    )


def _safe_error_log_fields(error: Exception) -> str:
    if isinstance(error, genai_errors.APIError):
        fields = f"error=APIError http_code={error.code}"
        if error.code == 429:
            fields += f" quota_kind={_quota_kind(error)}"
        retry_delay = _retry_delay_seconds(error)
        if retry_delay is not None:
            fields += f" retry_after_seconds={retry_delay:.3f}"
        return fields
    if isinstance(error, httpx.TimeoutException):
        return "error=TimeoutException"
    if isinstance(error, httpx.TransportError):
        return "error=TransportError"
    return "error=OSError"


async def _generate_content_with_retry(
    gemini_client: Any,
    request: dict[str, Any],
) -> Any:
    for attempt in range(MAX_RETRY_ATTEMPTS + 1):
        attempt_number = attempt + 1
        total_attempts = MAX_RETRY_ATTEMPTS + 1
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        started_timer = time.perf_counter()
        LOGGER.info(
            "Gemini call attempt=%d/%d start=%s",
            attempt_number,
            total_attempts,
            started_at,
        )
        try:
            response = await gemini_client.aio.models.generate_content(**request)
        except (
            genai_errors.APIError,
            httpx.TimeoutException,
            httpx.TransportError,
            OSError,
        ) as error:
            duration = time.perf_counter() - started_timer
            can_retry = _is_retryable_error(error)
            has_retry_remaining = attempt < MAX_RETRY_ATTEMPTS
            will_retry = can_retry and has_retry_remaining
            retry_delay = _retry_delay_seconds(error)
            wait_seconds = (
                retry_delay
                if will_retry and retry_delay is not None
                else RETRY_DELAYS_SECONDS[attempt]
                if will_retry
                else None
            )
            LOGGER.info(
                "Gemini call attempt=%d/%d result=failed %s "
                "duration_seconds=%.3f retry=%s wait_seconds=%s final=%s",
                attempt_number,
                total_attempts,
                _safe_error_log_fields(error),
                duration,
                str(will_retry).lower(),
                f"{wait_seconds:.3f}" if wait_seconds is not None else "none",
                str(not will_retry).lower(),
            )
            if not will_retry:
                raise
            await asyncio.sleep(wait_seconds)
        else:
            duration = time.perf_counter() - started_timer
            LOGGER.info(
                "Gemini call attempt=%d/%d result=success "
                "duration_seconds=%.3f retry=false final=true",
                attempt_number,
                total_attempts,
                duration,
            )
            return response

    raise RuntimeError("Gemini retry loop ended unexpectedly.")


async def recognize_menu(
    upload: ValidatedMenuUpload,
    client: Any | None = None,
) -> MenuRecognitionResult:
    """將已驗證菜單送至 Gemini，回傳尚未確認的結構化結果。"""
    owns_client = client is None
    gemini_client = client or _get_gemini_client()
    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    generation_config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
        response_json_schema=_load_recognition_schema(),
        thinking_config=(
            types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
            if model == DEFAULT_GEMINI_MODEL
            else None
        ),
    )
    try:
        response = await _generate_content_with_retry(
            gemini_client,
            {
                "model": model,
                "contents": [_make_file_part(upload), MENU_RECOGNITION_PROMPT],
                "config": generation_config,
            },
        )
    except genai_errors.APIError as error:
        if error.code in {401, 403}:
            raise _recognition_error("AI_NOT_CONFIGURED") from error
        if error.code == 429:
            code = "AI_QUOTA_EXHAUSTED" if _is_daily_quota_error(error) else "AI_RATE_LIMITED"
            raise _recognition_error(code) from error
        if error.code >= 500:
            raise _recognition_error("AI_SERVICE_UNAVAILABLE") from error
        raise _recognition_error("AI_OUTPUT_INVALID") from error
    except (httpx.TimeoutException, httpx.TransportError, OSError) as error:
        raise _recognition_error("AI_SERVICE_UNAVAILABLE") from error
    finally:
        if owns_client:
            await gemini_client.aio.aclose()

    return _extract_result(response)
