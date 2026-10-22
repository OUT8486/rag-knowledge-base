
from io import BytesIO

from pypdf import PdfReader


def extract_pdf_pages(pdf_bytes: bytes) -> list[dict]:
    """读取 PDF，并按页提取文本。"""
    try:
        reader = PdfReader(BytesIO(pdf_bytes))

        if reader.is_encrypted:
            raise ValueError("该 PDF 已加密，暂不支持读取。")

        pages = []

        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""

            pages.append({
                "page": page_number,
                "text": text,
            })

        return pages

    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            "PDF 解析失败，请检查文件是否损坏或格式是否正确。"
        ) from exc
