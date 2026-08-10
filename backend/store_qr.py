import qrcode
import qrcode.image.svg


def build_store_qr_svg(public_url: str) -> bytes:
    """將店家完整公開網址製成 SVG QR Code，不接受任何管理資訊。"""
    if "#" in public_url or "?" in public_url:
        raise ValueError("QR Code 公開網址不可包含片段或查詢參數")

    qr_code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr_code.add_data(public_url)
    qr_code.make(fit=True)
    image = qr_code.make_image(image_factory=qrcode.image.svg.SvgPathFillImage)
    return image.to_string(encoding="unicode").encode("utf-8")
