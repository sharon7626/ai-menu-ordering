import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

from google.genai import errors as genai_errors

from backend.menu_recognition import (
    MENU_RECOGNITION_PROMPT,
    MenuRecognitionError,
    _get_gemini_client,
    _is_daily_quota_error,
    _parse_retry_delay,
    _quota_kind,
    recognize_menu,
)
from backend.menu_upload import ValidatedMenuUpload


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FORMAL_MENU_PATH = PROJECT_ROOT / "data" / "menu.json"


def make_upload(content_type: str = "image/png") -> ValidatedMenuUpload:
    filename = "menu.pdf" if content_type == "application/pdf" else "menu.png"
    return ValidatedMenuUpload(
        filename=filename,
        content_type=content_type,
        size=10,
        page_count=1 if content_type == "application/pdf" else None,
        content=b"test-menu",
    )


def make_response(
    result: dict | None,
    finish_reason: str = "STOP",
) -> SimpleNamespace:
    text = json.dumps(result, ensure_ascii=False) if result is not None else None
    return SimpleNamespace(
        text=text,
        parsed=None,
        candidates=[SimpleNamespace(finish_reason=finish_reason)],
        prompt_feedback=None,
    )


def make_quota_error(
    quota_id: str,
    retry_delay: str = "12.5s",
) -> genai_errors.APIError:
    return genai_errors.APIError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "FreeTier quota exceeded",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaId": quota_id,
                                "quotaMetric": "generate_content_free_tier_requests",
                            }
                        ],
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": retry_delay,
                    },
                ],
            }
        },
    )


class FakeModels:
    def __init__(
        self,
        response: SimpleNamespace | None = None,
        error=None,
        outcomes: list | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.outcomes = list(outcomes) if outcomes is not None else None
        self.request = None
        self.call_count = 0

    async def generate_content(self, **kwargs):
        self.request = kwargs
        self.call_count += 1
        if self.outcomes is not None:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(
        self,
        response: SimpleNamespace | None = None,
        error=None,
        outcomes: list | None = None,
    ) -> None:
        self.models = FakeModels(response, error, outcomes)
        self.aio = SimpleNamespace(models=self.models)


class MenuRecognitionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.valid_result = {
            "restaurant_name": "測試小館",
            "categories": [
                {
                    "name": "飲品",
                    "items": [
                        {"name": "紅茶", "description": "", "price": 30},
                        {"name": "冬瓜茶", "description": "甜香", "price": 35},
                    ],
                }
            ],
            "needs_review": False,
            "warnings": [],
        }

    async def test_image_uses_structured_output_without_changing_formal_menu(self) -> None:
        menu_before = FORMAL_MENU_PATH.read_bytes()
        client = FakeClient(make_response(self.valid_result))

        result = await recognize_menu(make_upload(), client=client)

        self.assertEqual(result.categories[0].items[0].price, 30)
        request = client.models.request
        self.assertEqual(request["model"], "gemini-3.6-flash")
        config = request["config"]
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertEqual(config.temperature, 0)
        self.assertEqual(config.thinking_config.thinking_level.value, "LOW")
        self.assertEqual(config.response_json_schema["type"], "object")
        image_part = request["contents"][0]
        self.assertEqual(image_part.inline_data.mime_type, "image/png")
        self.assertEqual(image_part.inline_data.data, b"test-menu")
        self.assertEqual(FORMAL_MENU_PATH.read_bytes(), menu_before)

    async def test_pdf_uses_inline_pdf_bytes(self) -> None:
        client = FakeClient(make_response(self.valid_result))

        await recognize_menu(make_upload("application/pdf"), client=client)

        file_part = client.models.request["contents"][0]
        self.assertEqual(file_part.inline_data.mime_type, "application/pdf")
        self.assertEqual(file_part.inline_data.data, b"test-menu")

    def test_prompt_preserves_clear_multiple_prices_as_separate_items(self) -> None:
        self.assertIn("比對每一列餐點", MENU_RECOGNITION_PROMPT)
        self.assertIn("拆成多個可獨立點選的餐點", MENU_RECOGNITION_PROMPT)
        self.assertIn("古早味紅茶（M）", MENU_RECOGNITION_PROMPT)
        self.assertIn("不得因版面有價格欄", MENU_RECOGNITION_PROMPT)

    async def test_incomplete_and_invalid_results_have_safe_errors(self) -> None:
        cases = [
            (make_response(None, finish_reason="MAX_TOKENS"), "AI_RESPONSE_INCOMPLETE"),
            (make_response({"categories": []}), "AI_OUTPUT_INVALID"),
            (
                make_response({**self.valid_result, "categories": []}),
                "AI_NO_MENU_FOUND",
            ),
        ]

        for response, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(MenuRecognitionError) as context:
                    await recognize_menu(make_upload(), client=FakeClient(response))
                self.assertEqual(context.exception.code, expected_code)

    async def test_safety_block_has_safe_error(self) -> None:
        response = make_response(None, finish_reason="SAFETY")
        with self.assertRaises(MenuRecognitionError) as context:
            await recognize_menu(make_upload(), client=FakeClient(response))
        self.assertEqual(context.exception.code, "AI_REFUSED")

    def test_missing_api_key_is_rejected_without_exposing_a_secret(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MenuRecognitionError) as context:
                _get_gemini_client()
        self.assertEqual(context.exception.code, "AI_NOT_CONFIGURED")
        self.assertNotIn("key", context.exception.message.lower())

    async def test_invalid_api_key_uses_safe_configuration_error(self) -> None:
        api_error = genai_errors.APIError(
            401,
            {"error": {"message": "invalid key"}},
        )
        with self.assertRaises(MenuRecognitionError) as context:
            await recognize_menu(make_upload(), client=FakeClient(error=api_error))
        self.assertEqual(context.exception.code, "AI_NOT_CONFIGURED")
        self.assertNotIn("invalid key", context.exception.message.lower())

    async def test_free_daily_quota_has_clear_safe_error(self) -> None:
        api_error = make_quota_error(
            "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
        )
        client = FakeClient(error=api_error)
        with patch(
            "backend.menu_recognition.asyncio.sleep", new_callable=AsyncMock
        ) as sleep:
            with self.assertRaises(MenuRecognitionError) as context:
                await recognize_menu(make_upload(), client=client)
        self.assertEqual(context.exception.code, "AI_QUOTA_EXHAUSTED")
        self.assertIn("免費", context.exception.message)
        self.assertNotIn("quota exceeded", context.exception.message.lower())
        self.assertEqual(client.models.call_count, 1)
        sleep.assert_not_awaited()

    async def test_free_tier_per_minute_quota_uses_server_retry_delay(self) -> None:
        api_error = make_quota_error(
            "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
        )
        client = FakeClient(outcomes=[api_error, make_response(self.valid_result)])

        with self.assertLogs("uvicorn.error", level="INFO") as captured_logs:
            with patch(
                "backend.menu_recognition.asyncio.sleep", new_callable=AsyncMock
            ) as sleep:
                result = await recognize_menu(make_upload(), client=client)

        self.assertEqual(result.restaurant_name, "測試小館")
        self.assertFalse(_is_daily_quota_error(api_error))
        self.assertEqual(_quota_kind(api_error), "RPM")
        sleep.assert_awaited_once_with(12.5)
        logs = "\n".join(captured_logs.output)
        self.assertIn("quota_kind=RPM", logs)
        self.assertIn("retry_after_seconds=12.500", logs)
        self.assertIn("retry=true wait_seconds=12.500 final=false", logs)

    def test_tpm_quota_and_structured_retry_delay_are_recognized(self) -> None:
        api_error = make_quota_error(
            "GenerateContentInputTokensPerModelPerMinute-FreeTier",
        )

        self.assertFalse(_is_daily_quota_error(api_error))
        self.assertEqual(_quota_kind(api_error), "TPM")
        self.assertEqual(_parse_retry_delay({"seconds": "2", "nanos": 500_000_000}), 2.5)

    async def test_rate_limit_retries_once_then_succeeds(self) -> None:
        api_error = genai_errors.APIError(
            429,
            {"error": {"message": "Too many requests"}},
        )
        client = FakeClient(outcomes=[api_error, make_response(self.valid_result)])

        with self.assertLogs("uvicorn.error", level="INFO") as captured_logs:
            with patch(
                "backend.menu_recognition.asyncio.sleep", new_callable=AsyncMock
            ) as sleep:
                result = await recognize_menu(make_upload(), client=client)

        self.assertEqual(result.restaurant_name, "測試小館")
        self.assertEqual(client.models.call_count, 2)
        sleep.assert_awaited_once_with(1)
        logs = "\n".join(captured_logs.output)
        self.assertIn("attempt=1/3", logs)
        self.assertIn("result=failed error=APIError http_code=429", logs)
        self.assertIn("attempt=2/3", logs)
        self.assertIn("result=success", logs)
        self.assertIn("duration_seconds=", logs)
        self.assertNotIn("Too many requests", logs)

    async def test_service_unavailable_retries_once_then_succeeds(self) -> None:
        api_error = genai_errors.APIError(
            503,
            {"error": {"message": "Service unavailable"}},
        )
        client = FakeClient(outcomes=[api_error, make_response(self.valid_result)])

        with patch(
            "backend.menu_recognition.asyncio.sleep", new_callable=AsyncMock
        ) as sleep:
            result = await recognize_menu(make_upload(), client=client)

        self.assertEqual(result.restaurant_name, "測試小館")
        self.assertEqual(client.models.call_count, 2)
        sleep.assert_awaited_once_with(1)

    async def test_retry_exhaustion_uses_existing_safe_error(self) -> None:
        errors = [
            genai_errors.APIError(
                503,
                {"error": {"message": "Service unavailable"}},
            )
            for _ in range(3)
        ]
        client = FakeClient(outcomes=errors)

        with patch(
            "backend.menu_recognition.asyncio.sleep", new_callable=AsyncMock
        ) as sleep:
            with self.assertRaises(MenuRecognitionError) as context:
                await recognize_menu(make_upload(), client=client)

        self.assertEqual(context.exception.code, "AI_SERVICE_UNAVAILABLE")
        self.assertNotIn("Service unavailable", context.exception.message)
        self.assertEqual(client.models.call_count, 3)
        self.assertEqual(sleep.await_args_list, [call(1), call(2)])

    async def test_os_error_retries_without_logging_error_details(self) -> None:
        network_error = OSError("private request detail must not be logged")
        client = FakeClient(
            outcomes=[network_error, make_response(self.valid_result)],
        )

        with self.assertLogs("uvicorn.error", level="INFO") as captured_logs:
            with patch(
                "backend.menu_recognition.asyncio.sleep", new_callable=AsyncMock
            ) as sleep:
                result = await recognize_menu(make_upload(), client=client)

        self.assertEqual(result.restaurant_name, "測試小館")
        self.assertEqual(client.models.call_count, 2)
        sleep.assert_awaited_once_with(1)
        logs = "\n".join(captured_logs.output)
        self.assertIn("attempt=1/3", logs)
        self.assertIn("result=failed error=OSError", logs)
        self.assertIn("attempt=2/3", logs)
        self.assertIn("result=success", logs)
        self.assertNotIn("private request detail", logs)


if __name__ == "__main__":
    unittest.main()
