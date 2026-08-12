"""Firebase Authentication 的安全設定與 ID Token 驗證。"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from threading import Lock
from typing import Any


FIREBASE_APP_NAME = "ai-menu-ordering-auth"
GOOGLE_SIGN_IN_PROVIDER = "google.com"
LOGGER = logging.getLogger(__name__)


class FirebaseConfigurationError(RuntimeError):
    """Firebase 後端設定缺漏或格式錯誤。"""


class FirebaseAuthenticationError(RuntimeError):
    """Firebase ID Token 無法通過驗證。"""


@dataclass(frozen=True)
class AuthenticatedFirebaseUser:
    """只保留後端驗證後可信任的使用者資料。"""

    uid: str
    email: str | None
    display_name: str | None


_firebase_app: Any | None = None
_firebase_app_lock = Lock()
_windows_truststore_configured = False


def _configure_windows_truststore() -> None:
    """讓 Windows 本機開發使用系統憑證庫；其他平台維持原本行為。"""
    global _windows_truststore_configured

    if os.name != "nt" or _windows_truststore_configured:
        return

    try:
        import truststore
    except ImportError:
        LOGGER.warning("Windows system certificate store is unavailable")
        return

    truststore.inject_into_ssl()
    _windows_truststore_configured = True


def get_firebase_web_config() -> dict[str, str] | None:
    """讀取可公開給 Firebase Web SDK 的設定；缺漏時停用登入。"""
    config = {
        "api_key": os.getenv("FIREBASE_WEB_API_KEY", "").strip(),
        "auth_domain": os.getenv("FIREBASE_AUTH_DOMAIN", "").strip(),
        "project_id": os.getenv("FIREBASE_PROJECT_ID", "").strip(),
        "app_id": os.getenv("FIREBASE_APP_ID", "").strip(),
    }
    if not all(config.values()):
        return None
    return config


def _load_firebase_modules() -> tuple[Any, Any, Any]:
    _configure_windows_truststore()
    try:
        import firebase_admin
        from firebase_admin import auth, credentials
    except ImportError as error:
        raise FirebaseConfigurationError("Firebase 後端套件尚未安裝。") from error
    return firebase_admin, credentials, auth


def _get_firebase_app() -> Any:
    global _firebase_app

    if _firebase_app is not None:
        return _firebase_app

    project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not project_id or not service_account_json:
        raise FirebaseConfigurationError("Firebase 後端驗證尚未完成設定。")

    try:
        service_account = json.loads(service_account_json)
    except (TypeError, json.JSONDecodeError) as error:
        raise FirebaseConfigurationError("Firebase 服務帳戶設定格式錯誤。") from error
    if not isinstance(service_account, dict):
        raise FirebaseConfigurationError("Firebase 服務帳戶設定格式錯誤。")

    firebase_admin, credentials, _ = _load_firebase_modules()
    with _firebase_app_lock:
        if _firebase_app is not None:
            return _firebase_app
        try:
            _firebase_app = firebase_admin.get_app(FIREBASE_APP_NAME)
        except ValueError:
            try:
                credential = credentials.Certificate(service_account)
                _firebase_app = firebase_admin.initialize_app(
                    credential,
                    {"projectId": project_id},
                    name=FIREBASE_APP_NAME,
                )
            except (TypeError, ValueError) as error:
                raise FirebaseConfigurationError(
                    "Firebase 服務帳戶設定無法使用。"
                ) from error
    return _firebase_app


def verify_firebase_id_token(token: str) -> AuthenticatedFirebaseUser:
    """驗證 Firebase ID Token，並只回傳可信任的 Google 登入身分。"""
    cleaned_token = token.strip()
    if not cleaned_token:
        raise FirebaseAuthenticationError("缺少登入憑證。")

    _, _, firebase_auth = _load_firebase_modules()
    firebase_app = _get_firebase_app()
    try:
        claims = firebase_auth.verify_id_token(cleaned_token, app=firebase_app)
    except Exception as error:
        # 只記錄例外類型，避免把 SDK 詳細訊息、Token 或帳號資料寫入 log。
        LOGGER.warning(
            "Firebase ID Token verification failed error_type=%s",
            type(error).__name__,
        )
        raise FirebaseAuthenticationError("登入憑證無效或已過期。") from error

    uid = claims.get("uid") or claims.get("sub")
    provider = claims.get("firebase", {}).get("sign_in_provider")
    if not isinstance(uid, str) or not uid.strip():
        raise FirebaseAuthenticationError("登入憑證缺少使用者識別資料。")
    if provider != GOOGLE_SIGN_IN_PROVIDER:
        raise FirebaseAuthenticationError("目前只接受 Google 登入。")

    email = claims.get("email")
    display_name = claims.get("name")
    return AuthenticatedFirebaseUser(
        uid=uid.strip(),
        email=email.strip() if isinstance(email, str) and email.strip() else None,
        display_name=(
            display_name.strip()
            if isinstance(display_name, str) and display_name.strip()
            else None
        ),
    )
