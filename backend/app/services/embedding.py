from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer
    from tokenizers import Tokenizer


MODEL_NAME = "BAAI/bge-small-zh-v1.5"

# BGE 推荐用于短查询检索的指令
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


@dataclass(frozen=True)
class EmbeddingTokenBudget:
    tokenizer: Tokenizer
    max_content_tokens: int


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """只加载一次模型，后续调用复用。"""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        MODEL_NAME,
        device="cpu",
        local_files_only=True,
    )


@lru_cache(maxsize=1)
def get_embedding_token_budget() -> EmbeddingTokenBudget:
    """复用实际 BGE tokenizer 的配置，独立计数以免影响模型的截断、填充设置。"""
    from tokenizers import Tokenizer

    model = get_embedding_model()
    tokenizer = Tokenizer.from_str(model.tokenizer.backend_tokenizer.to_str())
    tokenizer.no_truncation()
    tokenizer.no_padding()

    max_length = model.max_seq_length
    special_tokens = tokenizer.num_special_tokens_to_add(False)
    if max_length is None or max_length <= special_tokens:
        raise ValueError("向量模型没有可用的文本 token 预算。")

    return EmbeddingTokenBudget(tokenizer, max_length - special_tokens)


def embed_documents(texts: list[str]) -> list[list[float]]:
    """把多个文档文本块转换为向量。"""
    if not texts:
        return []

    model = get_embedding_model()

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    return embeddings.tolist()


def embed_query(query: str) -> list[float]:
    """把用户的问题转换为查询向量。"""
    model = get_embedding_model()

    embeddings = model.encode(
        [QUERY_INSTRUCTION + query],
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    return embeddings[0].tolist()
