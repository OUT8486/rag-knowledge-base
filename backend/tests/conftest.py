import pytest
from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors


@pytest.fixture
def test_tokenizer():
    # 小型 WordPiece 与 BGE 一样逐字预处理中文；测试不依赖本地模型缓存。
    vocabulary = ["[UNK]", "[CLS]", "[SEP]", "RAG", "Rate", "is", "3", "14", ".", "Next"]
    tokenizer = Tokenizer(models.WordPiece(
        {token: index for index, token in enumerate(vocabulary)}, unk_token="[UNK]"
    ))
    tokenizer.normalizer = normalizers.BertNormalizer(lowercase=False)
    tokenizer.pre_tokenizer = pre_tokenizers.BertPreTokenizer()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 1), ("[SEP]", 2)]
    )
    return tokenizer
