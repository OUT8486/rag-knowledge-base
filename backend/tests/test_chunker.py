from types import SimpleNamespace

import pytest
from tokenizers import Tokenizer, models, pre_tokenizers

from app.services import embedding
from app.services.chunker import chunk_pages
from app.services.embedding import EmbeddingTokenBudget


def _split(text, test_tokenizer, *, target=350, maximum=510):
    chunks = chunk_pages(
        [{"page": 1, "text": text}],
        "doc",
        target_tokens=target,
        token_budget=EmbeddingTokenBudget(test_tokenizer, maximum),
    )
    pieces = [chunk["text"] for chunk in chunks]
    assert all(
        len(test_tokenizer.encode(piece, add_special_tokens=False)) <= maximum
        for piece in pieces
    )
    return pieces


def test_packs_short_paragraphs_without_breaking_fitting_paragraphs(test_tokenizer):
    short_paragraphs = "甲乙\r\n \r\n丙丁"
    paragraph = "第一句。又一句。"
    assert _split(f"{short_paragraphs}\r\n\r\n{paragraph}", test_tokenizer, target=8) == [
        "甲乙\n\n丙丁", paragraph,
    ]


def test_long_paragraph_packs_sentences_without_losing_punctuation(test_tokenizer):
    first = "第一句。第二句。"
    second = "“第三句！”第四句。"
    assert _split(first + second, test_tokenizer, target=10) == [first, second]


def test_keeps_decimal_and_english_sentence_spacing(test_tokenizer):
    assert _split("Rate is 3.14. Next.", test_tokenizer, target=6) == [
        "Rate is 3.14.", "Next.",
    ]


def test_complete_sentence_may_exceed_soft_target(test_tokenizer):
    sentence = "甲" * 509 + "。"
    assert _split(sentence + "乙。", test_tokenizer) == [sentence, "乙。"]
    assert len(test_tokenizer.encode(sentence)) == 512


def test_splits_a_long_unpunctuated_sentence_without_overlap(test_tokenizer):
    text = "甲" * 350 + "乙" * 350 + "丙" * 101
    assert _split(text, test_tokenizer) == [text[:350], text[350:700], text[700:]]


def test_requested_target_is_capped_at_model_budget(test_tokenizer):
    text = "甲乙丙丁戊己庚辛壬癸"
    assert _split(text, test_tokenizer, target=350, maximum=4) == ["甲乙丙丁", "戊己庚辛", "壬癸"]


def test_rechecks_token_count_when_slicing_changes_wordpiece_encoding():
    vocabulary = ["[UNK]", "x", "##ab", "a", "##b", "b"]
    tokenizer = Tokenizer(models.WordPiece(
        {token: index for index, token in enumerate(vocabulary)}, unk_token="[UNK]"
    ))
    tokenizer.pre_tokenizer = pre_tokenizers.BertPreTokenizer()
    text = "xababab"
    assert tokenizer.encode(text).tokens == ["x", "##ab", "##ab", "##ab"]
    pieces = _split(text, tokenizer, target=2, maximum=3)
    assert "".join(pieces) == text
    assert all(len(tokenizer.encode(piece)) <= 2 for piece in pieces)


def test_blank_pages_are_skipped_and_indices_span_the_document(test_tokenizer):
    chunks = chunk_pages(
        [
            {"page": 1, "text": "甲。"},
            {"page": 2, "text": " \x00\n "},
            {"page": 3, "text": "乙。"},
        ],
        "doc",
        token_budget=EmbeddingTokenBudget(test_tokenizer, 510),
    )
    assert chunks == [
        {"chunk_id": "doc_chunk_0001", "document_id": "doc", "chunk_index": 1, "page": 1, "text": "甲。"},
        {"chunk_id": "doc_chunk_0002", "document_id": "doc", "chunk_index": 2, "page": 3, "text": "乙。"},
    ]


def test_rejects_nonpositive_target():
    with pytest.raises(ValueError, match="target_tokens"):
        chunk_pages([], "doc", target_tokens=0)


def test_embedding_budget_reserves_special_tokens_and_does_not_mutate_model_tokenizer(
    test_tokenizer, monkeypatch,
):
    test_tokenizer.enable_truncation(max_length=6)
    test_tokenizer.enable_padding(length=6)
    model = SimpleNamespace(
        tokenizer=SimpleNamespace(backend_tokenizer=test_tokenizer), max_seq_length=6
    )
    monkeypatch.setattr(embedding, "get_embedding_model", lambda: model)

    budget = embedding.get_embedding_token_budget.__wrapped__()

    assert budget.max_content_tokens == 4
    assert len(budget.tokenizer.encode("甲" * 9)) == 11
    assert len(budget.tokenizer.encode("甲")) == 3
    assert len(test_tokenizer.encode("甲" * 9)) == 6
    assert len(test_tokenizer.encode("甲")) == 6
