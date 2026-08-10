import unittest
from io import BytesIO

from fastapi import UploadFile
from pypdf import PdfWriter
from starlette.datastructures import Headers

from backend.menu_upload import (
    MAX_UPLOAD_BYTES,
    MenuUploadValidationError,
    validate_menu_upload,
)


VALID_JPEG = b"\xff\xd8\xff\xe0test-image\xff\xd9"
VALID_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"test-image"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def make_upload(filename: str, content_type: str, content: bytes) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def make_pdf(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=200, height=200)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class MenuUploadValidationTests(unittest.IsolatedAsyncioTestCase):
    async def assert_upload_error(
        self,
        expected_code: str,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> None:
        upload = make_upload(filename, content_type, content)
        with self.assertRaises(MenuUploadValidationError) as context:
            await validate_menu_upload(upload)
        self.assertEqual(context.exception.code, expected_code)

    async def test_jpg_png_and_one_page_pdf_are_accepted(self) -> None:
        cases = [
            ("menu.jpg", "image/jpeg", VALID_JPEG, None),
            ("menu.jpeg", "image/jpeg", VALID_JPEG, None),
            ("menu.png", "image/png", VALID_PNG, None),
            ("menu.pdf", "application/pdf", make_pdf(1), 1),
        ]

        for filename, content_type, content, page_count in cases:
            with self.subTest(filename=filename):
                result = await validate_menu_upload(
                    make_upload(filename, content_type, content),
                )
                self.assertEqual(result.filename, filename)
                self.assertEqual(result.size, len(content))
                self.assertEqual(result.page_count, page_count)

    async def test_empty_file_is_rejected(self) -> None:
        await self.assert_upload_error("EMPTY_FILE", "menu.png", "image/png", b"")

    async def test_unsupported_extension_is_rejected(self) -> None:
        await self.assert_upload_error(
            "UNSUPPORTED_FILE_TYPE",
            "menu.gif",
            "image/gif",
            b"GIF89a",
        )

    async def test_mismatched_content_type_is_rejected(self) -> None:
        await self.assert_upload_error(
            "FILE_TYPE_MISMATCH",
            "menu.jpg",
            "image/png",
            VALID_JPEG,
        )

    async def test_damaged_image_is_rejected(self) -> None:
        await self.assert_upload_error(
            "UNREADABLE_FILE",
            "menu.jpg",
            "image/jpeg",
            b"\xff\xd8\xffdamaged",
        )

    async def test_file_over_10_mb_is_rejected(self) -> None:
        await self.assert_upload_error(
            "FILE_TOO_LARGE",
            "menu.jpg",
            "image/jpeg",
            VALID_JPEG[:3] + (b"a" * MAX_UPLOAD_BYTES) + VALID_JPEG[-2:],
        )

    async def test_multiple_page_pdf_is_rejected(self) -> None:
        await self.assert_upload_error(
            "PDF_PAGE_COUNT_INVALID",
            "menu.pdf",
            "application/pdf",
            make_pdf(2),
        )


if __name__ == "__main__":
    unittest.main()
