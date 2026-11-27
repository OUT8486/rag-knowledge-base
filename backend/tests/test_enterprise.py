import io
import json
import os
from time import monotonic, sleep
from unittest.mock import Mock

import httpx2
import pytest
from app.api import chat
from app.services import chunker, embedding, llm
from app.services.embedding import EmbeddingTokenBudget
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def text_pdf(texts):
    out = io.BytesIO()
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 14 Tf 55 720 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(out)
    return out.getvalue()


def mock_model_transport(monkeypatch, *, redirect=False):
    seen = []
    client = httpx2.Client

    def respond(request):
        data = json.loads(request.content)
        seen.append((str(request.url), data))
        if redirect:
            return httpx2.Response(307, headers={"Location": "https://unused.example.test/v1"})
        reply = '{"query":"travel expenses"}' if len(seen) % 2 == 1 else "见制度 [S1]。"
        return httpx2.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": data["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    class LocalTestClient(client):
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
            super().__init__(**kwargs, transport=httpx2.MockTransport(respond))

    monkeypatch.setattr(httpx2, "Client", LocalTestClient)
    return seen


@pytest.mark.live_worker
def test_two_department_workflow(pilot, monkeypatch, test_tokenizer):
    """Real PDF, background worker, persistent Chroma, API and SDK; never call a live LLM.

    Set RAG_TEST_REAL_BGE=1 to use the actual offline model instead of deterministic vectors.
    """
    if os.getenv("RAG_TEST_REAL_BGE") != "1":
        monkeypatch.setattr(
            chunker, "get_embedding_token_budget", lambda: EmbeddingTokenBudget(test_tokenizer, 510)
        )

        def vec(text):
            return [1.0, 0.0] if "expense" in text else [0.0, 1.0]

        monkeypatch.setattr(embedding, "embed_documents", lambda texts: [vec(t) for t in texts])
        monkeypatch.setattr(embedding, "embed_query", vec)
    seen = mock_model_transport(monkeypatch)
    client = pilot.client
    docs = {}
    for who, lines in [
        (
            "finance",
            [
                "TR-21: submit travel expense receipts within thirty days.",
                "IT-72: return laptops to IT.",
            ],
        ),
        ("hr", ["HR-12: parental leave is managed by human resources."]),
    ]:
        base = f"/api/kbs/{who}"
        j = client.post(
            base + "/documents/upload",
            headers=pilot.auth(who),
            files={"file": (who + ".pdf", text_pdf(lines), "application/pdf")},
        )
        assert j.status_code == 202
        job = j.json()
        deadline = monotonic() + 180
        while job["status"] in ("queued", "running") and monotonic() < deadline:
            sleep(0.15)
            job = client.get(base + "/jobs/" + job["job_id"], headers=pilot.auth(who)).json()
        assert job["status"] == "ready" and job["page_count"] == len(lines), job
        docs[who] = job
    for who, other in [("finance", "hr"), ("hr", "finance")]:
        base = f"/api/kbs/{who}"
        h = pilot.auth(who)
        assert [
            kb["id"] for kb in client.get("/api/session", headers=h).json()["knowledge_bases"]
        ] == [who]
        assert [
            d["filename"] for d in client.get(base + "/documents", headers=h).json()["documents"]
        ] == [who + ".pdf"]
        results = client.post(
            base + "/search", headers=h, json={"query": "travel expenses"}
        ).json()["results"]
        assert results and {row["document_id"] for row in results} == {docs[who]["document_id"]}
        if who == "finance":
            assert results[0]["page"] == 1
        assert not client.post(
            base + "/search",
            headers=h,
            json={"query": "query", "document_id": docs[other]["document_id"]},
        ).json()["results"]
        assert (
            client.delete(base + "/documents/" + docs[other]["document_id"], headers=h).status_code
            == 404
        )
        assert client.get(base + "/jobs/" + docs[other]["job_id"], headers=h).status_code == 404
        count = len(seen)
        res = client.post(
            base + "/chat",
            headers=h,
            json={"question": "制度？", "document_id": docs[other]["document_id"]},
        )
        assert res.json()["sources"] == [] and len(seen) == count
        res = client.post(base + "/chat", headers=h, json={"question": "travel expense policy?"})
        assert res.status_code == 200, res.text
        assert [s["filename"] for s in res.json()["sources"]] == [who + ".pdf"]
        calls = seen[count:]
        assert len(calls) == 2
        route = llm.model_route("local_only" if who == "finance" else "approved_cloud")
        assert all(
            url == route.url + "/chat/completions" and body["model"] == route.model
            for url, body in calls
        )
        assert all(other + ".pdf" not in str(body) for _, body in calls)
    assert client.delete(
        "/api/kbs/finance/documents/" + docs["finance"]["document_id"],
        headers=pilot.auth("finance"),
    ).is_success
    assert (
        client.post(
            "/api/kbs/finance/search", json={"query": "travel"}, headers=pilot.auth("finance")
        ).json()["results"]
        == []
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "documents"),
        ("post", "documents/upload"),
        ("get", "jobs/example"),
        ("post", "jobs/example/retry"),
        ("delete", "documents/example"),
        ("post", "search"),
        ("post", "chat"),
    ],
)
def test_all_routes_deny_anonymous_and_other_group(pilot, method, path):
    for headers, status in [({}, 401), (pilot.auth("hr"), 404)]:
        res = pilot.client.request(method, "/api/kbs/finance/" + path, headers=headers)
        assert res.status_code == status, (path, res.text)


@pytest.mark.parametrize(
    "method,path",
    [("post", "documents/upload"), ("post", "jobs/example/retry"), ("delete", "documents/example")],
)
def test_reader_cannot_write(pilot, method, path):
    assert (
        pilot.client.request(
            method, "/api/kbs/finance/" + path, headers=pilot.auth("reader")
        ).status_code
        == 403
    )


def test_no_legacy_data_paths_and_no_implicit_grants(pilot):
    for method, path in [
        ("get", "documents"),
        ("post", "documents/upload"),
        ("post", "chat"),
        ("post", "search"),
    ]:
        assert (
            pilot.client.request(method, "/api/" + path, headers=pilot.auth("finance")).status_code
            == 404
        )
    assert (
        pilot.client.get(
            "/api/session", headers={"X-RAG-User": "finance", "X-RAG-Groups": "fin-w"}
        ).status_code
        == 401
    )
    # Group removal takes effect on the next API call without restarting.
    pilot.config["users"]["finance"]["groups"] = []
    pilot.path.write_text(json.dumps(pilot.config))
    assert (
        pilot.client.get("/api/kbs/finance/documents", headers=pilot.auth("finance")).status_code
        == 404
    )
    pilot.path.write_text("{}")
    assert pilot.client.get("/api/session", headers=pilot.auth("finance")).status_code == 503


def test_sso_gateway_and_group_mapping(pilot, monkeypatch):
    monkeypatch.setenv("RAG_AUTH_MODE", "proxy")
    monkeypatch.setenv("RAG_GATEWAY_KEY", "x" * 40)
    identity = {"X-RAG-User": "employee", "X-RAG-Groups": "hr-r,fin-w"}
    assert pilot.client.get("/api/session", headers=identity).status_code == 401
    assert pilot.client.get("/api/session", headers=pilot.auth("finance")).status_code == 401
    trusted = {**identity, "X-RAG-Gateway-Key": "x" * 40}
    session = pilot.client.get("/api/session", headers=trusted).json()
    assert session["subject"] == "employee" and {
        kb["id"]: kb["can_write"] for kb in session["knowledge_bases"]
    } == {"finance": True, "hr": False}
    assert (
        pilot.client.post(
            "/api/kbs/finance/search", headers=trusted, json={"query": "x"}
        ).status_code
        == 403
    )
    assert (
        pilot.client.post(
            "/api/kbs/finance/search",
            headers={**trusted, "X-RAG-Request": "1"},
            json={"query": "x"},
        ).status_code
        == 200
    )
    monkeypatch.setenv("RAG_GATEWAY_KEY", "")
    assert pilot.client.get("/api/session", headers=trusted).status_code == 503


@pytest.mark.parametrize(
    "bad", ["https://cloud.example.test/v1", "", "ftp://127.0.0.1/v1", "http://127.0.0.1:bad/v1"]
)
def test_restricted_kb_rejects_bad_endpoint_before_rewrite(pilot, monkeypatch, bad):
    cat = pilot.rt.catalog
    job = cat.enqueue("finance", "x", "policy.pdf", b"test")
    cat.claim()
    cat.finish(job["job_id"], 1, 1)
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", bad)
    model = Mock()
    monkeypatch.setattr(chat, "generate_search_intent", model)
    monkeypatch.setattr(chat, "generate_answer", model)
    assert (
        pilot.client.post(
            "/api/kbs/finance/chat", headers=pilot.auth("finance"), json={"question": "私有"}
        ).status_code
        == 503
    )
    model.assert_not_called()


def test_local_transport_does_not_follow_redirects(pilot, monkeypatch):
    seen = mock_model_transport(monkeypatch, redirect=True)
    from openai import APIStatusError

    with pytest.raises(APIStatusError):
        llm.generate_search_intent("本地问题", llm.model_route("local_only"))
    assert [url for url, _ in seen] == ["http://127.0.0.1:1/v1/chat/completions"]


def test_readiness_checks_dependencies_without_model_inference(pilot, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "get_embedding_model", lambda: object())
    db = Mock()
    monkeypatch.setattr(pilot.vectors, "client", lambda: db)
    assert pilot.client.get("/api/ready").status_code == 200
    db.heartbeat.assert_called_once()
    db.heartbeat.side_effect = RuntimeError("unavailable")
    assert (
        pilot.client.get("/api/ready").status_code == 503
        and pilot.client.get("/api/health").status_code == 200
    )
