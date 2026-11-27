import hashlib
import json

import httpx
import pytest
from app.access import AccessConfig
from app.evaluate import Case, evaluate
from app.manage import initialize
from app.services.llm import NO_EVIDENCE


def test_bootstrap_does_not_overwrite_or_store_cleartext(tmp_path, monkeypatch, capsys):
    path = tmp_path / "new" / "access.json"
    monkeypatch.setenv("RAG_ACCESS_FILE", str(path))
    initialize()
    data = path.read_text(encoding="utf-8")
    conf = AccessConfig.model_validate_json(data)
    lines = capsys.readouterr().out.splitlines()[1:]
    assert set(conf.knowledge_bases) == {"finance", "hr"} and all(
        k.policy == "local_only" for k in conf.knowledge_bases.values()
    )
    assert len(lines) == len(conf.users) == 3
    for line in lines:
        name, key = line.split(": ")
        assert (
            key not in data and hashlib.sha256(key.encode()).hexdigest() == conf.users[name].sha256
        )
    with pytest.raises(FileExistsError):
        initialize()
    assert path.read_text(encoding="utf-8") == data and not capsys.readouterr().out


def test_eval_ranking_and_refusals_are_counted_separately():
    cases = [
        Case(
            id="a",
            question="evidence",
            expected_pages=[{"filename": "policy.pdf", "page": 2}],
            should_refuse=False,
        ),
        Case(id="b", question="absent", expected_pages=[], should_refuse=True),
    ]
    documents = [{"filename": "policy.pdf", "page": p} for p in (1, 2)]

    def answer(req):
        if req.url.path == "/api/session":
            body = {"knowledge_bases": [{"id": "finance", "policy": "local_only"}]}
        elif req.url.path.endswith("/search"):
            body = {"results": documents}
        elif json.loads(req.content)["question"] == "absent":
            body = {"answer": NO_EVIDENCE, "sources": []}
        else:
            body = {"answer": "evidence [S1]", "sources": documents[1:]}
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(answer), base_url="http://test") as client:
        metrics = evaluate(client, "finance", cases, 2, answers=True)
    assert metrics == {
        "cases": 2,
        "answerable_cases": 1,
        "hit@2": 1,
        "mrr@2": 0.5,
        "refusal_rate_on_unanswerable": 1,
        "answer_cites_a_gold_page": 1,
    }


def test_eval_never_generates_cloud_answers_by_default():
    paths = []

    def session(req):
        paths.append(req.url.path)
        return httpx.Response(
            200, json={"knowledge_bases": [{"id": "hr", "policy": "approved_cloud"}]}
        )

    with httpx.Client(transport=httpx.MockTransport(session), base_url="http://test") as client:
        with pytest.raises(ValueError):
            evaluate(client, "hr", [], answers=True)
    assert paths == ["/api/session"]
