"""Turns uploaded files into images the vision models can read.

PDFs are rendered page by page (pdfium, via pypdfium2 — permissively
licensed, unlike MuPDF's AGPL). Every image, rendered or uploaded, is
downscaled and re-encoded in memory if it would exceed what the vision
APIs accept. The original file on disk is never modified: it stays the
evidence of record.
"""
import io
from dataclasses import dataclass

import pypdfium2 as pdfium
from PIL import Image

# Claude rejects images over 5 MB and downsamples anything past ~1568 px on
# the long edge anyway; staying under both keeps every provider happy.
MAX_IMAGE_BYTES = 4_500_000
MAX_LONG_EDGE = 2000
JPEG_QUALITY = 90


class PdfReadError(Exception):
    pass


@dataclass
class RenderedPages:
    images: list[bytes]  # JPEG bytes, one per rendered page
    total_pages: int


def _encode_jpeg(image: Image.Image) -> bytes:
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    if max(image.size) > MAX_LONG_EDGE:
        image = image.copy()
        image.thumbnail((MAX_LONG_EDGE, MAX_LONG_EDGE), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


def prepare_image_for_vision(image_bytes: bytes, media_type: str) -> tuple[bytes, str]:
    """Pass small images through untouched; shrink oversized ones (e.g.
    12-megapixel phone photos) so the provider doesn't reject them."""
    if len(image_bytes) <= MAX_IMAGE_BYTES:
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                if max(img.size) <= MAX_LONG_EDGE:
                    return image_bytes, media_type
        except OSError:
            return image_bytes, media_type  # let the provider report the bad image
    with Image.open(io.BytesIO(image_bytes)) as img:
        return _encode_jpeg(img), "image/jpeg"


def render_pdf_pages(pdf_bytes: bytes, max_pages: int, dpi: int) -> RenderedPages:
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
    except pdfium.PdfiumError as exc:
        message = str(exc).lower()
        if "password" in message:
            raise PdfReadError("PDF is password-protected. Remove the password and re-upload it.") from exc
        raise PdfReadError(f"Could not open PDF (damaged or not a real PDF): {exc}") from exc

    try:
        total = len(pdf)
        if total == 0:
            raise PdfReadError("PDF has no pages.")
        scale = dpi / 72
        images = []
        for index in range(min(total, max_pages)):
            page = pdf[index]
            try:
                bitmap = page.render(scale=scale)
                images.append(_encode_jpeg(bitmap.to_pil()))
            finally:
                page.close()
        return RenderedPages(images=images, total_pages=total)
    finally:
        pdf.close()
