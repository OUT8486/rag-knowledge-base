"""Scoped chat contract: validate first; rewrite cannot change retrieval scope or destination."""

from unittest.mock import Mock

import pytest
from app.api import chat
from app.services.extract import SearchIntent
from app.services.llm import NO_EVIDENCE

URL = "/api/kbs/finance/chat"


@pytest.fixture
def indexed(pilot, monkeypatch):
    cat = pilot.rt.catalog
    job = cat.enqueue("finance", "finance", "手册.pdf", b"synthetic")
    cat.claim()
    cat.finish(job["job_id"], 2, 2)
    chunks = [
        {
            "chunk_id": f"chunk-{i}",
            "document_id": job["document_id"],
            "version_id": job["job_id"],
            "filename": "手册.pdf",
            "page": i,
            "chunk_index": i,
            "distance": 0.1,
            "text": f"第{i}条制度",
        }
        for i in (1, 2)
    ]
    search = Mock(return_value=chunks)
    intent = Mock(
        return_value=SearchIntent(query="改写词", document_id="ignored-model-scope", top_k=9)
    )
    answer = Mock(return_value="结论一 [S1]，结论二 [S2]。")
    monkeypatch.setattr(pilot.rt, "search", search)
    monkeypatch.setattr(chat, "generate_search_intent", intent)
    monkeypatch.setattr(chat, "generate_answer", answer)
    return job, chunks, intent, search, answer


@pytest.mark.parametrize(
    "body,status",
    [
        ({}, 422),
        ({"question": ""}, 422),
        ({"question": " "}, 400),
        ({"question": "x", "policy": "approved_cloud"}, 422),
    ],
)
def test_validation(pilot, indexed, body, status):
    assert pilot.client.post(URL, json=body, headers=pilot.auth("finance")).status_code == status
    indexed[2].assert_not_called()


def test_no_results_and_missing_document_do_not_answer(pilot, indexed):
    _, _, intent, search, answer = indexed
    for doc in ("not-visible", None):
        search.return_value = []
        res = pilot.client.post(
            URL, json={"question": "假期？", "document_id": doc}, headers=pilot.auth("finance")
        )
        assert res.json() == {"answer": NO_EVIDENCE, "sources": []}
    assert (
        intent.call_count == 1
    )  # Missing/foreign document short-circuits before any model invocation.
    answer.assert_not_called()


def test_retrieval_failure(pilot, indexed):
    *_, search, answer = indexed
    search.side_effect = RuntimeError("private diagnostic")
    res = pilot.client.post(URL, json={"question": "制度？"}, headers=pilot.auth("finance"))
    assert res.status_code == 500 and "private" not in res.text
    answer.assert_not_called()


def test_rewrite_fallback_uses_original_and_never_changes_route(pilot, indexed):
    job, _, intent, search, answer = indexed
    intent.side_effect = ValueError("invalid model JSON")
    res = pilot.client.post(URL, json={"question": " 原问题 "}, headers=pilot.auth("finance"))
    assert res.status_code == 200
    search.assert_called_once_with("finance", [job["job_id"]], "原问题", 5)
    assert intent.call_args.args[1] == answer.call_args.args[2] == chat.model_route("local_only")


def test_rewrite_uses_user_scope_not_model_fields(pilot, indexed):
    job, chunks, intent, search, answer = indexed
    res = pilot.client.post(
        URL,
        json={"question": "制度？", "top_k": 2, "document_id": job["document_id"]},
        headers=pilot.auth("finance"),
    )
    assert res.status_code == 200
    assert res.json()["sources"] == [dict(c, source_id=f"S{i}") for i, c in enumerate(chunks, 1)]
    intent.assert_called_once_with("制度？", chat.model_route("local_only"))
    search.assert_called_once_with("finance", [job["job_id"]], "改写词", 2)
    assert answer.call_args.args == (
        "制度？",
        res.json()["sources"],
        chat.model_route("local_only"),
    )


@pytest.mark.parametrize("length", [2999, 3000, 3001, 5000])
def test_text_budget_keeps_only_excerpts_sent(pilot, indexed, length):
    _, chunks, _, _, answer = indexed
    chunks[0]["text"] = "甲" * 1000
    chunks[1]["text"] = "乙" * (length - 1000)
    res = pilot.client.post(URL, json={"question": "制度？"}, headers=pilot.auth("finance"))
    assert res.status_code == 200
    assert sum(len(s["text"]) for s in res.json()["sources"]) == min(length, 3000)
    assert answer.call_args.args[1] == res.json()["sources"]


@pytest.mark.parametrize(
    "model_answer", ["没有引用", "不存在的来源 [S99]", "混合引用 [S1][S0]", NO_EVIDENCE]
)
def test_missing_invalid_or_refused_citations(pilot, indexed, model_answer):
    indexed[-1].return_value = model_answer
    assert pilot.client.post(
        URL, json={"question": "问题"}, headers=pilot.auth("finance")
    ).json() == {"answer": NO_EVIDENCE, "sources": []}


def test_answer_failure_not_rerouted(pilot, indexed):
    indexed[-1].side_effect = RuntimeError("failure")
    res = pilot.client.post(URL, json={"question": "问题"}, headers=pilot.auth("finance"))
    assert res.status_code == 502 and indexed[-1].call_count == 1


def test_local_consent_survives_kb_reclassification(pilot, indexed):
    import json

    pilot.config["knowledge_bases"]["finance"]["policy"] = "approved_cloud"
    pilot.path.write_text(json.dumps(pilot.config), encoding="utf-8")
    response = pilot.client.post(
        URL, headers=pilot.auth("finance"), json={"question": "旧页面的问题", "require_local": True}
    )
    assert response.status_code == 409
    for stage in indexed[2:]:
        stage.assert_not_called()
