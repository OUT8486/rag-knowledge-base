from unittest.mock import Mock

import pytest
from app.services import ingestion
from app.services.embedding import EmbeddingTokenBudget

BASE = "/api/kbs/finance"


def upload(pilot, content, name="policy.pdf", kb="finance", who="finance"):
    return pilot.client.post(
        f"/api/kbs/{kb}/documents/upload",
        headers=pilot.auth(who),
        files={"file": (name, content, "application/pdf")},
    )


@pytest.mark.parametrize(
    "name,data,status",
    [
        ("notes.txt", b"a", 400),
        ("x.pdf", b"", 400),
        ("x.pdf", b"no header", 400),
        ("large.pdf", b"%PDF-" + b"x" * (10 * 1024 * 1024), 413),
    ],
)
def test_input_rejected_before_queue(pilot, name, data, status):
    assert upload(pilot, data, name).status_code == status
    assert pilot.rt.catalog.claim() is None


@pytest.mark.parametrize("pages", [[], [{"page": 1, "text": " "}]])
def test_no_text_is_failed_job(pilot, monkeypatch, pages):
    monkeypatch.setattr(ingestion, "extract_pdf_pages", lambda _: pages)
    res = upload(pilot, b"%PDF-synthetic")
    job = res.json()
    assert res.status_code == 202 and job["status"] == "queued"
    assert pilot.rt.index_one()
    assert pilot.rt.catalog.job("finance", job["job_id"])["status"] == "failed"
    assert pilot.rt.catalog.active_versions("finance") == []


def test_retry_parse_error_keeps_original_and_never_publishes_partial(
    pilot, monkeypatch, test_tokenizer
):
    from app.services import chunker

    raw = b"%PDF-original"
    parse = Mock(side_effect=ValueError("private parser details"))
    monkeypatch.setattr(ingestion, "extract_pdf_pages", parse)
    monkeypatch.setattr(
        chunker, "get_embedding_token_budget", lambda: EmbeddingTokenBudget(test_tokenizer, 510)
    )
    write = Mock()
    monkeypatch.setattr(pilot.vectors, "index", write)
    job = upload(pilot, raw).json()
    pilot.rt.index_one()
    failed = pilot.client.get(BASE + "/jobs/" + job["job_id"], headers=pilot.auth("reader")).json()
    assert failed["status"] == "failed" and "private" not in failed["error"]
    write.assert_not_called()
    parse.side_effect = None
    parse.return_value = [{"page": 1, "text": " "}, {"page": 2, "text": "RAG"}]
    retried = pilot.client.post(
        BASE + "/jobs/" + job["job_id"] + "/retry", headers=pilot.auth("finance")
    )
    assert retried.status_code == 202 and retried.json()["job_id"] == job["job_id"]
    pilot.rt.index_one()
    ready = pilot.rt.catalog.job("finance", job["job_id"])
    assert ready["page_count"] == 2 and ready["indexed_count"] == 1 and ready["status"] == "ready"
    assert write.call_args.args[-1][0]["page"] == 2 and parse.call_args.args == (raw,)


def test_long_page_chunking_on_worker(pilot, monkeypatch, test_tokenizer):
    from app.services import chunker

    one, two = "甲" * 299 + "。", "乙" * 299 + "。"
    monkeypatch.setattr(ingestion, "extract_pdf_pages", lambda _: [{"page": 1, "text": one + two}])
    monkeypatch.setattr(
        chunker, "get_embedding_token_budget", lambda: EmbeddingTokenBudget(test_tokenizer, 510)
    )
    write = Mock()
    monkeypatch.setattr(pilot.vectors, "index", write)
    job = upload(pilot, b"%PDF-long").json()
    pilot.rt.index_one()
    assert [c["text"] for c in write.call_args.args[-1]] == [one, two]
    assert pilot.rt.catalog.job("finance", job["job_id"])["indexed_count"] == 2


def test_dedup_publish_restart_and_old_version_safety(pilot):
    cat = pilot.rt.catalog
    first = upload(pilot, b"%PDF-1").json()
    again = upload(pilot, b"%PDF-1", "renamed.pdf").json()
    other = upload(pilot, b"%PDF-1", kb="hr", who="hr").json()
    assert first == again and other["document_id"] != first["document_id"]
    assert cat.claim()["pdf"] == b"%PDF-1"
    cat.recover()
    assert cat.claim()["id"] == first["job_id"]
    cat.finish(first["job_id"], 2, 1)
    cat.claim()
    cat.finish(other["job_id"], 1, 1)
    second = upload(pilot, b"%PDF-2").json()
    assert second["document_id"] == first["document_id"] and second["version"] == 2
    cat.claim()
    cat.finish(second["job_id"], error="failed")
    assert cat.active_versions("finance") == [first["job_id"]]
    third = upload(pilot, b"%PDF-3").json()
    cat.claim()
    cat.finish(third["job_id"], 3, 1)
    cat.job("finance", second["job_id"], retry=True)
    cat.claim()
    cat.finish(second["job_id"], 1, 1)
    assert cat.active_versions("finance") == [third["job_id"]]
    docs = pilot.client.get(BASE + "/documents", headers=pilot.auth("reader")).json()
    assert docs["document_count"] == 1 and docs["documents"][0]["version"] == 3
    assert (
        pilot.client.delete(
            BASE + "/documents/" + first["document_id"], headers=pilot.auth("finance")
        ).status_code
        == 200
    )
    assert cat.active_versions("finance") == [] and cat.job("finance", second["job_id"]) is None
    assert cat.active_versions("hr") == [other["job_id"]]


def test_deleting_inflight_job_can_never_publish_it(pilot):
    cat = pilot.rt.catalog
    j = upload(pilot, b"%PDF-inflight").json()
    cat.claim()
    cat.remove("finance", j["document_id"])
    cat.finish(j["job_id"], 1, 1)
    assert cat.active_versions("finance") == [] and cat.next_cleanup() == ("finance", j["job_id"])
