import pytest
from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors


@pytest.fixture
def test_tokenizer():
    # 小型 WordPiece 与 BGE 一样逐字预处理中文；测试不依赖本地模型缓存。
    vocabulary = ["[UNK]", "[CLS]", "[SEP]", "RAG", "Rate", "is", "3", "14", ".", "Next"]
    tokenizer = Tokenizer(
        models.WordPiece(
            {token: index for index, token in enumerate(vocabulary)}, unk_token="[UNK]"
        )
    )
    tokenizer.normalizer = normalizers.BertNormalizer(lowercase=False)
    tokenizer.pre_tokenizer = pre_tokenizers.BertPreTokenizer()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 1), ("[SEP]", 2)]
    )
    return tokenizer


# All API tests use isolated files and fake identities, never a developer's data or model credentials.
@pytest.fixture
def pilot(tmp_path, monkeypatch, request):
    import hashlib
    import json
    import secrets
    from types import SimpleNamespace

    from app.main import app
    from app.services.ingestion import Worker
    from fastapi.testclient import TestClient

    tokens = {name: secrets.token_urlsafe(32) for name in ("finance", "hr", "reader", "both")}
    roles = {"finance": ["fin-w"], "hr": ["hr-w"], "reader": ["fin-r"], "both": ["fin-r", "hr-r"]}
    config = {
        "knowledge_bases": {
            "finance": {"name": "财务", "writers": ["fin-w"], "readers": ["fin-r"]},
            "hr": {
                "name": "人事",
                "writers": ["hr-w"],
                "readers": ["hr-r"],
                "policy": "approved_cloud",
            },
        },
        "users": {
            name: {"sha256": hashlib.sha256(key.encode()).hexdigest(), "groups": roles[name]}
            for name, key in tokens.items()
        },
    }
    path = tmp_path / "access.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    for key, val in {
        "RAG_DATA_DIR": str(tmp_path / "storage"),
        "RAG_ACCESS_FILE": str(path),
        "RAG_AUTH_MODE": "token",
        "LOCAL_LLM_BASE_URL": "http://127.0.0.1:1/v1",
        "LOCAL_LLM_MODEL": "local-test",
        "LOCAL_LLM_API_KEY": "",
        "LLM_BASE_URL": "https://llm.example.test/v1",
        "LLM_MODEL": "cloud-test",
        "LLM_API_KEY": "fake",
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }.items():
        monkeypatch.setenv(key, val)
    # Keep lifecycle and recovery real; each test drives worker steps deterministically.
    if not request.node.get_closest_marker("live_worker"):
        monkeypatch.setattr(Worker, "run", lambda self: self.stop.wait())
    with TestClient(app) as client:
        rt = app.state.runtime
        yield SimpleNamespace(
            client=client,
            rt=rt,
            config=config,
            path=path,
            auth=lambda who: {"Authorization": "Bearer " + tokens[who]},
            vectors=rt.vectors,
        )
