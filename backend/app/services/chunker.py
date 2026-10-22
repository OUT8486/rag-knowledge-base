
import re


def clean_text(text: str) -> str:
    """清理多余空格和连续空行。"""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_pages(
    pages: list[dict],
    document_id: str,
    chunk_size: int = 600,
    overlap: int = 100,
) -> list[dict]:
    """
    将 PDF 各页的文本切分成多个片段。

    每个片段保留文档 ID、页码、片段编号和文本。
    """

    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")

    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap 必须大于等于 0 且小于 chunk_size")

    chunks = []

    for page in pages:
        page_number = page["page"]
        text = clean_text(page["text"])

        if not text:
            continue

        start = 0

        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk_text = text[start:end].strip()

            if chunk_text:
                chunk_index = len(chunks) + 1

                chunks.append({
                    "chunk_id": (
                        f"{document_id}_chunk_{chunk_index:04d}"
                    ),
                    "document_id": document_id,
                    "chunk_index": chunk_index,
                    "page": page_number,
                    "text": chunk_text,
                })

            if end >= len(text):
                break

            # 保留上一块末尾的一部分文本
            start = end - overlap

    return chunks
