import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.firebase_auth import (
    AuthenticatedFirebaseUser,
    FirebaseAuthenticationError,
    FirebaseConfigurationError,
    verify_firebase_id_token,
)
from backend.main import app


class FirebaseAuthApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "firebase-auth.db"
        self.database_url = f"sqlite:///{database_path.as_posix()}"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_public_config_is_disabled_when_environment_is_missing(self) -> None:
        environment = {"DATABASE_URL": self.database_url}
        with patch.dict(os.environ, environment, clear=True):
            with TestClient(app) as client:
                response = client.get("/api/auth/config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "enabled": False,
            "api_key": None,
            "auth_domain": None,
            "project_id": None,
            "app_id": None,
        })

    def test_public_config_never_returns_service_account(self) -> None:
        environment = {
            "DATABASE_URL": self.database_url,
            "FIREBASE_PROJECT_ID": "safe-project-id",
            "FIREBASE_WEB_API_KEY": "public-web-setting",
            "FIREBASE_AUTH_DOMAIN": "safe-project-id.firebaseapp.com",
            "FIREBASE_APP_ID": "safe-app-id",
            "FIREBASE_SERVICE_ACCOUNT_JSON": json.dumps({"private_key": "secret"}),
        }
        with patch.dict(os.environ, environment, clear=True):
            with TestClient(app) as client:
                response = client.get("/api/auth/config")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["enabled"])
        self.assertNotIn("service", response.text.lower())
        self.assertNotIn("private_key", response.text)
        self.assertNotIn("secret", response.text)

    def test_me_rejects_missing_and_invalid_tokens(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                missing = client.get("/api/auth/me")
                with patch(
                    "backend.main.verify_firebase_id_token",
                    side_effect=FirebaseAuthenticationError("invalid"),
                ):
                    invalid = client.get(
                        "/api/auth/me",
                        headers={"Authorization": "Bearer forged-token"},
                    )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)
        self.assertNotIn("forged-token", invalid.text)

    def test_me_returns_only_backend_verified_identity(self) -> None:
        trusted_user = AuthenticatedFirebaseUser(
            uid="firebase-uid-123",
            email="user@example.com",
            display_name="測試使用者",
        )
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                with patch(
                    "backend.main.verify_firebase_id_token",
                    return_value=trusted_user,
                ) as verifier:
                    response = client.get(
                        "/api/auth/me",
                        headers={"Authorization": "Bearer firebase-id-token"},
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["uid"], "firebase-uid-123")
        self.assertEqual(response.json()["display_name"], "測試使用者")
        verifier.assert_called_once_with("firebase-id-token")

    def test_me_reports_unconfigured_backend_without_exposing_details(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                with patch(
                    "backend.main.verify_firebase_id_token",
                    side_effect=FirebaseConfigurationError("private detail"),
                ):
                    response = client.get(
                        "/api/auth/me",
                        headers={"Authorization": "Bearer any-token"},
                    )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private detail", response.text)


class FirebaseTokenVerificationTests(unittest.TestCase):
    def test_google_provider_claims_become_trusted_user(self) -> None:
        fake_auth = Mock()
        fake_auth.verify_id_token.return_value = {
            "uid": "verified-uid",
            "email": " verified@example.com ",
            "name": " 已驗證使用者 ",
            "firebase": {"sign_in_provider": "google.com"},
        }
        with patch("backend.firebase_auth._load_firebase_modules", return_value=(Mock(), Mock(), fake_auth)):
            with patch("backend.firebase_auth._get_firebase_app", return_value=Mock()):
                user = verify_firebase_id_token("verified-token")

        self.assertEqual(user.uid, "verified-uid")
        self.assertEqual(user.email, "verified@example.com")
        self.assertEqual(user.display_name, "已驗證使用者")

    def test_non_google_provider_is_rejected(self) -> None:
        fake_auth = Mock()
        fake_auth.verify_id_token.return_value = {
            "uid": "verified-uid",
            "firebase": {"sign_in_provider": "password"},
        }
        with patch("backend.firebase_auth._load_firebase_modules", return_value=(Mock(), Mock(), fake_auth)):
            with patch("backend.firebase_auth._get_firebase_app", return_value=Mock()):
                with self.assertRaises(FirebaseAuthenticationError):
                    verify_firebase_id_token("verified-token")

    def test_sdk_rejects_forged_expired_or_wrong_project_tokens(self) -> None:
        for sdk_error in (ValueError("forged"), RuntimeError("expired"), OSError("wrong project")):
            fake_auth = Mock()
            fake_auth.verify_id_token.side_effect = sdk_error
            with self.subTest(error=type(sdk_error).__name__):
                with patch("backend.firebase_auth._load_firebase_modules", return_value=(Mock(), Mock(), fake_auth)):
                    with patch("backend.firebase_auth._get_firebase_app", return_value=Mock()):
                        with self.assertRaises(FirebaseAuthenticationError):
                            verify_firebase_id_token("unsafe-token")

    def test_sdk_failure_log_only_contains_safe_error_type(self) -> None:
        fake_auth = Mock()
        fake_auth.verify_id_token.side_effect = ValueError("private-sdk-detail")

        with patch("backend.firebase_auth._load_firebase_modules", return_value=(Mock(), Mock(), fake_auth)):
            with patch("backend.firebase_auth._get_firebase_app", return_value=Mock()):
                with self.assertLogs("backend.firebase_auth", level="WARNING") as captured:
                    with self.assertRaises(FirebaseAuthenticationError):
                        verify_firebase_id_token("unsafe-token")

        logged_text = "\n".join(captured.output)
        self.assertIn("ValueError", logged_text)
        self.assertNotIn("private-sdk-detail", logged_text)
        self.assertNotIn("unsafe-token", logged_text)


if __name__ == "__main__":
    unittest.main()
