"""Public customer support, independent of private department data and production credentials."""

import hashlib
import json
import os
import time
from unittest.mock import Mock

import pytest
from app.access import SUPPORT_KB
from app.api import customer
from app.manage import initialize_support
from app.services import chunker, embedding
from app.services.customer_store import RETENTION
from app.services.embedding import EmbeddingTokenBudget
from app.services.llm import NO_EVIDENCE
from test_enterprise import text_pdf

PUBLIC = "/api/customer"
DESK = "/api/kbs/customer-help/desk"


@pytest.fixture
def support(pilot):
    initialize_support()
    config = json.loads(pilot.path.read_text(encoding="utf-8"))
    key = "test-agent-only"
    config["users"]["customer-agent"]["sha256"] = hashlib.sha256(key.encode()).hexdigest()
    pilot.path.write_text(json.dumps(config), encoding="utf-8")
    pilot.agent = {"Authorization": "Bearer " + key}
    return pilot


def stage(s, kb=SUPPORT_KB, name="internal-name.pdf", payload=b"v1"):
    c = s.rt.catalog
    j = c.enqueue(kb, "staff", name, payload)
    assert c.claim()["id"] == j["job_id"]
    c.finish(j["job_id"], 1, 1)
    return j


def release(s, j, title="公开售后指南"):
    return s.client.put(
        DESK + "/materials/" + j["document_id"],
        headers=s.agent,
        json={"version_id": j["job_id"], "public_title": title},
    )


def ask(s, question="我该如何申请售后？", **fields):
    return s.client.post(PUBLIC + "/ask", json={"question": question, **fields})


def test_off_without_admin_opt_in(pilot):
    assert pilot.client.get(PUBLIC + "/info").status_code == 404
    assert ask(pilot).status_code == 404
    assert (
        pilot.client.post(
            PUBLIC + "/tickets", json={"issue": "问题", "share_with_agent": True}
        ).status_code
        == 404
    )


def test_bootstrap_is_idempotent_and_preserves_existing_roles(pilot, capsys):
    orig = pilot.path.read_bytes()
    before = json.loads(orig)
    initialize_support()
    config = json.loads(pilot.path.read_bytes())
    creds = capsys.readouterr().out.splitlines()[-1].split(": ")[-1]
    assert creds not in pilot.path.read_text(encoding="utf-8")
    assert config["users"]["customer-agent"]["sha256"] == hashlib.sha256(creds.encode()).hexdigest()
    assert all(config["users"][k] == v for k, v in before["users"].items())
    assert all(config["knowledge_bases"][k] == v for k, v in before["knowledge_bases"].items())
    assert config["knowledge_bases"][SUPPORT_KB]["policy"] == "local_only"
    snapshot = pilot.path.read_bytes()
    initialize_support()
    assert pilot.path.read_bytes() == snapshot
    assert creds not in capsys.readouterr().out
    before["knowledge_bases"][SUPPORT_KB] = {"name": "内部部门", "writers": ["internal"]}
    pilot.path.write_text(json.dumps(before))
    snapshot = pilot.path.read_bytes()
    with pytest.raises(ValueError):
        initialize_support()
    assert pilot.path.read_bytes() == snapshot


def test_empty_unpublished_replaced_withdrawn_and_foreign_material(support, monkeypatch):
    s = support
    gen = Mock(return_value="公开回答 [S1]")
    monkeypatch.setattr(customer, "generate_customer_answer", gen)
    j = stage(s)
    private = stage(s, "finance", "finance.pdf")
    assert ask(s).json()["kind"] == "no_evidence"
    assert release(s, private).status_code == 404
    assert release(s, j).status_code == 200
    j2 = stage(s, payload=b"v2")
    assert ask(s).json()["kind"] == "no_evidence"
    assert release(s, j).status_code == 409
    items = s.client.get(DESK + "/materials", headers=s.agent).json()
    assert len(items) == 1 and items[0]["version"] == 2 and items[0]["public_title"] is None
    assert release(s, j2).is_success
    assert release(s, j2, None).is_success
    assert ask(s).json()["sources"] == []
    gen.assert_not_called()


@pytest.mark.parametrize("cred,status", [("anonymous", 401), ("finance", 404), ("reader", 404)])
def test_staff_data_only_for_dedicated_agent(support, cred, status):
    h = {} if cred == "anonymous" else support.auth(cred)
    for path in ("/tickets", "/materials"):
        assert support.client.get(DESK + path, headers=h).status_code == status
    assert (
        support.client.get(
            "/api/kbs/finance/desk/tickets", headers=support.auth("finance")
        ).status_code
        == 404
    )


def test_support_reader_cannot_read_tickets_or_publish(support):
    s = support
    cfg = json.loads(s.path.read_bytes())
    cfg["knowledge_bases"][SUPPORT_KB]["readers"] = ["fin-r"]
    s.path.write_text(json.dumps(cfg))
    for path in ("/tickets", "/materials"):
        assert s.client.get(DESK + path, headers=s.auth("reader")).status_code == 403
    assert "customer-help" in [
        k["id"]
        for k in s.client.get("/api/session", headers=s.agent).json()["knowledge_bases"]
        if k["customer_desk"]
    ]


@pytest.fixture
def published(support, monkeypatch):
    s = support
    j = stage(s)
    release(s, j).raise_for_status()
    hit = {
        "document_id": j["document_id"],
        "version_id": j["job_id"],
        "filename": "internal-name.pdf",
        "page": 2,
        "text": "公开的退换流程",
        "distance": 0.1,
        "chunk_index": 1,
        "chunk_id": "chunk",
    }
    not_released = dict(hit, version_id="not-released", text="非公开资料", filename="secret.pdf")
    query = Mock(return_value=[hit, not_released])
    monkeypatch.setattr(s.rt, "search", query)
    model = Mock(return_value="根据指南申请售后 [S1]。")
    monkeypatch.setattr(customer, "generate_customer_answer", model)
    return s, j, query, model


def test_grounded_only_public_citations_and_follow_up(published):
    s, j, query, model = published
    out = ask(s, "那具体怎么申请？", previous_questions=["如何退换？"]).json()
    args = model.call_args.args
    assert out["kind"] == "answered" and out["sources"] == [
        {"source_id": "S1", "title": "公开售后指南", "page": 2, "excerpt": "公开的退换流程"}
    ]
    assert (
        query.call_args.args[:2] == (SUPPORT_KB, [j["job_id"]])
        and "如何退换" in query.call_args.args[2]
    )
    assert args[1] == ["如何退换？"] and args[3].model == "local-test"
    assert set(args[2][0]) == {"source_id", "filename", "page", "text"} and len(args[2]) == 1
    assert "internal-name" not in str(args) and "非公开资料" not in str(args)


@pytest.mark.parametrize(
    "fields",
    [
        {"kb_id": "finance"},
        {"model": "other"},
        {"document_id": "other"},
        {"previous_questions": ["x"] * 3},
    ],
)
def test_customer_cannot_select_internal_targets(published, fields):
    s, _, _, model = published
    assert ask(s, **fields).status_code == 422
    model.assert_not_called()


@pytest.mark.parametrize("text", [NO_EVIDENCE, "未引用结论", "无效引用 [S19]"])
def test_invalid_evidence_offers_handoff_and_does_not_create_ticket(published, text):
    s, _, _, model = published
    model.return_value = text
    assert ask(s).json()["kind"] == "no_evidence"
    assert s.client.get(DESK + "/tickets", headers=s.agent).json() == []


def test_withdrawal_in_flight_suppresses_answer(published):
    s, j, _, model = published

    def withdraw(*args):
        release(s, j, None).raise_for_status()
        return "过期答复 [S1]"

    model.side_effect = withdraw
    out = ask(s).json()
    assert out["kind"] == "no_evidence" and "过期答复" not in str(out)


def test_cloud_needs_consent_and_model_failure_never_falls_back(published):
    s, _, _, model = published
    cfg = json.loads(s.path.read_bytes())
    cfg["knowledge_bases"][SUPPORT_KB]["policy"] = "approved_cloud"
    s.path.write_text(json.dumps(cfg))
    assert ask(s).status_code == 409
    model.assert_not_called()
    assert ask(s, "转人工").json()["kind"] == "handoff"
    model.assert_not_called()
    assert (
        ask(s, allow_cloud=True).json()["kind"] == "answered"
        and model.call_args.args[3].model == "cloud-test"
    )
    model.side_effect = RuntimeError("private provider error")
    out = ask(s, allow_cloud=True).json()
    assert (
        out["kind"] == "unavailable"
        and "private provider" not in str(out)
        and model.call_count == 2
    )


def test_real_ticket_lifecycle_lookup_requires_secret_reply_is_final(support):
    s = support
    private = {"issue": "合成问题，请核实", "share_with_agent": True}
    assert (
        s.client.post(PUBLIC + "/tickets", json={**private, "share_with_agent": False}).status_code
        == 400
    )
    res = s.client.post(PUBLIC + "/tickets", json=private)
    assert res.status_code == 201
    ticket = res.json()
    key = ticket["receipt"]
    tid = ticket["id"]

    def track(key):
        return s.client.get(PUBLIC + "/ticket", headers={"X-Ticket-Receipt": key})

    assert track(tid).status_code == 404 and s.client.get(PUBLIC + "/ticket").status_code == 404
    assert track(key).json()["status"] == "open"
    rows = s.client.get(DESK + "/tickets", headers=s.agent).json()
    assert [r["id"] for r in rows] == [tid] and "receipt" not in rows[0]

    def reply():
        return s.client.post(
            DESK + f"/tickets/{tid}/reply", headers=s.agent, json={"reply": "问题已核实。"}
        )

    assert reply().is_success and reply().status_code == 409
    result = track(key).json()
    assert (
        result["status"] == "resolved"
        and result["reply"] == "问题已核实。"
        and "replied_by" not in result
    )
    assert s.client.get(DESK + "/tickets", headers=s.agent).json() == []
    with s.rt.catalog.connection(write=True) as db:
        row = db.execute(
            "SELECT receipt_hash,replied_by FROM customer_tickets WHERE id=?", (tid,)
        ).fetchone()
        assert (
            row["receipt_hash"] == hashlib.sha256(key.encode()).hexdigest()
            and row["replied_by"] == "customer-agent"
        )
        db.execute(
            "UPDATE customer_tickets SET created=? WHERE id=?",
            (int(time.time()) - RETENTION - 2, tid),
        )
    assert (
        track(key).status_code == 404
        and s.client.get(DESK + "/tickets?state=resolved", headers=s.agent).json() == []
    )


def test_public_quotas_and_busy_ai_keep_manual_service_available(published, monkeypatch):
    from app.services import customer_budget

    monkeypatch.setattr(customer_budget, "monotonic", lambda: 1)
    s, *_ = published
    slots = s.client.app.state.customer_budget.inference
    with slots, slots:
        assert ask(s).status_code == 429
        assert s.client.post(
            PUBLIC + "/tickets", json={"issue": "需要帮助", "share_with_agent": True}
        ).is_success
    for _ in range(11):
        assert ask(s, "转人工").is_success
    assert ask(s).status_code == 429


@pytest.mark.live_worker
def test_pdf_to_public_answer_and_withdrawal(support, monkeypatch, test_tokenizer):
    s = support
    if os.getenv("RAG_TEST_REAL_BGE") != "1":
        monkeypatch.setattr(
            chunker, "get_embedding_token_budget", lambda: EmbeddingTokenBudget(test_tokenizer, 510)
        )
        monkeypatch.setattr(embedding, "embed_documents", lambda texts: [[1.0, 0.0] for _ in texts])
        monkeypatch.setattr(embedding, "embed_query", lambda _: [1.0, 0.0])
    model = Mock(return_value="申请入口在帮助页面 [S1]。")
    monkeypatch.setattr(customer, "generate_customer_answer", model)
    res = s.client.post(
        "/api/kbs/customer-help/documents/upload",
        headers=s.agent,
        files={
            "file": (
                "internal-review.pdf",
                text_pdf(["Open the Help page to request product support."]),
                "application/pdf",
            )
        },
    )
    assert res.status_code == 202
    j = res.json()
    deadline = time.monotonic() + 180
    while j["status"] in ("running", "queued") and time.monotonic() < deadline:
        time.sleep(0.15)
        j = s.client.get("/api/kbs/customer-help/jobs/" + j["job_id"], headers=s.agent).json()
    assert j["status"] == "ready"
    assert ask(s).json()["kind"] == "no_evidence"
    model.assert_not_called()
    release(s, j).raise_for_status()
    out = ask(s, "How do I request product support?").json()
    assert (
        out["kind"] == "answered"
        and out["sources"][0]["page"] == 1
        and out["sources"][0]["title"] == "公开售后指南"
    )
    assert "internal-review" not in str(out) and "internal-review" not in str(model.call_args)
    release(s, j, None)
    assert ask(s).json()["kind"] == "no_evidence"


@pytest.mark.parametrize(
    ("question", "kind"), [("如何查看人工回复？", "guidance"), ("帮我退款", "handoff")]
)
def test_builtin_guidance_and_personal_actions_do_not_call_model(published, question, kind):
    s, _, search, model = published
    assert ask(s, question).json()["kind"] == kind
    search.assert_not_called()
    model.assert_not_called()


def test_policy_change_during_retrieval_blocks_dispatch(published):
    s, _, search, model = published

    def change(*args):
        cfg = json.loads(s.path.read_bytes())
        cfg["knowledge_bases"][SUPPORT_KB]["policy"] = "approved_cloud"
        s.path.write_text(json.dumps(cfg))
        return search.return_value

    search.side_effect = change
    assert ask(s).status_code == 409
    model.assert_not_called()
