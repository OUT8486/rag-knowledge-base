"""Evaluate an authorized pilot KB. Retrieval-only by default; stdout contains no questions or snippets."""

import argparse
import json
import os
from pathlib import Path
from statistics import mean
from urllib.parse import urlsplit

import httpx
from app.access import KBId
from app.services.llm import NO_EVIDENCE
from pydantic import BaseModel, Field, TypeAdapter, model_validator


class Page(BaseModel):
    filename: str
    page: int = Field(ge=1)


class Case(BaseModel):
    id: str
    question: str = Field(min_length=1, max_length=1000)
    expected_pages: list[Page]
    should_refuse: bool

    @model_validator(mode="after")
    def validate_gold(self):
        if not self.should_refuse and not self.expected_pages:
            raise ValueError("Answerable cases need at least one gold page")
        return self


def evaluate(client, kb, cases, k=5, answers=False, allow_cloud=False):
    kb = TypeAdapter(KBId).validate_python(kb)
    session = client.get("/api/session").raise_for_status().json()
    selected = next((item for item in session["knowledge_bases"] if item["id"] == kb), None)
    if not selected or (answers and selected["policy"] != "local_only" and not allow_cloud):
        raise ValueError("知识库未授权，或云端答案评测未经显式允许。")
    scores, refusal, citations = [], [], []
    for case in cases:
        gold = {(p.filename, p.page) for p in case.expected_pages}
        rows = (
            client.post(f"/api/kbs/{kb}/search", json={"query": case.question, "top_k": k})
            .raise_for_status()
            .json()["results"]
        )
        if not case.should_refuse:
            scores.append(
                next(
                    (1 / i for i, r in enumerate(rows, 1) if (r["filename"], r["page"]) in gold), 0
                )
            )
        if answers:
            body = (
                client.post(
                    f"/api/kbs/{kb}/chat",
                    json={"question": case.question, "top_k": k, "require_local": not allow_cloud},
                )
                .raise_for_status()
                .json()
            )
            if case.should_refuse:
                refusal.append(body["answer"] == NO_EVIDENCE and not body["sources"])
            else:
                citations.append(any((r["filename"], r["page"]) in gold for r in body["sources"]))
    return {
        "cases": len(cases),
        "answerable_cases": len(scores),
        f"hit@{k}": mean(bool(s) for s in scores) if scores else None,
        f"mrr@{k}": mean(scores) if scores else None,
        "refusal_rate_on_unanswerable": mean(refusal) if refusal else None,
        "answer_cites_a_gold_page": mean(citations) if citations else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("--kb", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--k", type=int, choices=range(1, 11), default=5)
    parser.add_argument("--answers", action="store_true")
    parser.add_argument("--allow-cloud", action="store_true")
    args = parser.parse_args()
    dest = urlsplit(args.url)
    if dest.scheme != "https" and not (
        dest.scheme == "http" and dest.hostname in {"127.0.0.1", "::1"}
    ):
        parser.error("远程服务必须使用 HTTPS。")
    token = os.getenv("RAG_EVAL_TOKEN")
    if not token:
        parser.error("请通过 RAG_EVAL_TOKEN 提供只读评测令牌。")
    cases = [
        Case.model_validate_json(line)
        for line in args.cases.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    if not cases:
        parser.error("没有评测问题。")
    with httpx.Client(
        base_url=args.url,
        headers={"Authorization": "Bearer " + token},
        trust_env=False,
        follow_redirects=False,
        timeout=120,
    ) as client:
        print(
            json.dumps(
                evaluate(client, args.kb, cases, args.k, args.answers, args.allow_cloud),
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
