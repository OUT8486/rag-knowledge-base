from __future__ import annotations

import re
from collections.abc import Iterator
from typing import TYPE_CHECKING

from app.services.embedding import EmbeddingTokenBudget, get_embedding_token_budget

if TYPE_CHECKING:
    from tokenizers import Tokenizer


TARGET_CHUNK_TOKENS = 350

# 保留句末标点和右引号；英文句点只在空白或行尾断句，避开 3.14 之类的数字。
_CLOSING_PUNCTUATION = r'''[”’」』）》】)\]"']*'''
_SENTENCE_END = re.compile(
    rf"[。！？!?]+{_CLOSING_PUNCTUATION}|\.+{_CLOSING_PUNCTUATION}(?=\s|$)"
)


def clean_text(text: str) -> str:
    """清理多余空格和连续空行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(?m)^ +$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _count_tokens(text: str, tokenizer: Tokenizer) -> int:
    return len(tokenizer.encode(text.strip(), add_special_tokens=False))


def _sentence_spans(text: str) -> Iterator[tuple[int, int]]:
    start = 0
    for match in _SENTENCE_END.finditer(text):
        yield start, match.end()
        start = match.end()
    if start < len(text):
        yield start, len(text)


def _sentence_units(
    sentence: str, tokenizer: Tokenizer, target: int, maximum: int
) -> Iterator[tuple[int, int]]:
    """仅拆超过模型预算的句子，用 offset 切原文而不是解码 token。"""
    pending = [(0, len(sentence), maximum)]
    while pending:
        start, end, limit = pending.pop()
        text = sentence[start:end]
        encoding = tokenizer.encode(text.strip(), add_special_tokens=False)
        if len(encoding) <= limit:
            yield start, end
            continue

        leading = len(text) - len(text.lstrip())
        cuts = sorted({
            offset + leading + start
            for offset, _ in encoding.offsets[target::target]
            if start < offset + leading + start < end
        })
        if not cuts:
            # 极端情况下多个 token 可指向同一字符；用字符边界维持进度。
            if end - start == 1:
                raise ValueError("无法在向量模型的 token 预算内切分该字符。")
            cuts = [(start + end) // 2]

        # 切开的 WordPiece 可能重新编码成不同数量的 token，所以逐段复查。
        bounds = [start, *cuts, end]
        for index in range(len(bounds) - 2, -1, -1):
            pending.append((bounds[index], bounds[index + 1], target))


def _page_units(
    text: str, tokenizer: Tokenizer, target: int, maximum: int
) -> Iterator[tuple[int, int]]:
    offset = 0
    for paragraph in text.split("\n\n"):
        end = offset + len(paragraph)
        if _count_tokens(paragraph, tokenizer) <= target:
            yield offset, end
        else:
            for left, right in _sentence_spans(paragraph):
                for start, stop in _sentence_units(
                    paragraph[left:right], tokenizer, target, maximum
                ):
                    yield offset + left + start, offset + left + stop
        offset = end + 2


def _chunk_page(
    text: str, tokenizer: Tokenizer, target: int, maximum: int
) -> Iterator[str]:
    start = None
    end = 0
    for unit_start, unit_end in _page_units(text, tokenizer, target, maximum):
        if not text[unit_start:unit_end].strip():
            continue
        if start is not None and _count_tokens(text[start:unit_end], tokenizer) > target:
            yield text[start:end]
            start = None
        if start is None:
            start = unit_start
        end = unit_end

    if start is not None:
        yield text[start:end]


def chunk_pages(
    pages: list[dict],
    document_id: str,
    *,
    target_tokens: int = TARGET_CHUNK_TOKENS,
    token_budget: EmbeddingTokenBudget | None = None,
) -> list[dict]:
    """按页、段落、句子逐级切分，不跨页，也不重复相邻块的正文。"""
    if target_tokens <= 0:
        raise ValueError("target_tokens 必须大于 0")

    chunks = []

    for page in pages:
        page_number = page["page"]
        text = clean_text(page["text"])

        if not text:
            continue

        if token_budget is None:
            token_budget = get_embedding_token_budget()
        maximum = token_budget.max_content_tokens
        target = min(target_tokens, maximum)
        if target <= 0:
            raise ValueError("向量模型没有可用的文本 token 预算。")

        for piece in _chunk_page(text, token_budget.tokenizer, target, maximum):
            chunk_text = piece.strip()
            if not chunk_text:
                continue
            chunk_index = len(chunks) + 1
            chunks.append({
                "chunk_id": f"{document_id}_chunk_{chunk_index:04d}",
                "document_id": document_id,
                "chunk_index": chunk_index,
                "page": page_number,
                "text": chunk_text,
            })

    return chunks
