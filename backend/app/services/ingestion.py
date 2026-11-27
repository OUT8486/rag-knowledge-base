"""Single-process pilot: SQLite queue/outbox + one embedded Chroma writer."""

import json
import logging
from contextlib import asynccontextmanager
from threading import Event, Thread
from time import perf_counter

from app import telemetry
from app.config import data_dir
from app.services.catalog import open_catalog
from app.services.chunker import chunk_pages
from app.services.customer_budget import PublicBudget
from app.services.customer_store import CustomerStore
from app.services.document_parser import extract_pdf_pages
from app.services.vector_store import VectorStore
from fastapi import Request
from filelock import FileLock
from starlette.concurrency import run_in_threadpool

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, catalog, vectors):
        self.catalog = catalog
        self.vectors = vectors
        self.stop = Event()
        self.wake = Event()
        self.thread = Thread(target=self.run, name="rag-ingestion", daemon=True)

    def index_one(self):
        job = self.catalog.claim()
        if not job:
            return False
        started = perf_counter()
        try:
            pages = extract_pdf_pages(job["pdf"])
            chunks = chunk_pages(pages, document_id=job["id"])
            if not chunks:
                self.catalog.finish(job["id"], error="PDF 中没有可提取的文字。")
                return True
            self.vectors.index(job["kb"], job["id"], job["doc"], job["filename"], chunks)
            self.catalog.finish(job["id"], len(chunks), len(pages))
        except Exception as exc:
            # Parser/model exception details can contain source text; never persist or log them.
            self.catalog.finish(job["id"], error="入库失败，请检查 PDF 或模型配置后重试。")
            log.warning(
                json.dumps(
                    {"event": "index_failed", "job_id": job["id"], "type": type(exc).__name__}
                )
            )
        finally:
            log.info(
                json.dumps(
                    {
                        "event": "index_finished",
                        "job_id": job["id"],
                        "kb_id": job["kb"],
                        "elapsed_ms": round((perf_counter() - started) * 1000),
                    }
                )
            )
        return True

    def clean_one(self):
        entry = self.catalog.next_cleanup()
        if entry:
            self.vectors.discard(*entry)
            self.catalog.cleaned(entry[1])
        return bool(entry)

    def run(self):
        while not self.stop.is_set():
            try:
                work = self.index_one()
                if self.clean_one() or work:
                    continue
            except Exception as exc:
                log.error(json.dumps({"event": "worker_error", "type": type(exc).__name__}))
            self.wake.wait(1)
            self.wake.clear()

    def search(self, kb, versions, query, top_k):
        started = perf_counter()
        results = self.vectors.search(kb, versions, query, top_k)
        if results:
            # A document may have been replaced/deleted while the query was being encoded.
            current = self.catalog.still_active(kb, {row["version_id"] for row in results})
            results = [row for row in results if row["version_id"] in current]
        log.info(
            json.dumps(
                {
                    "event": "retrieval",
                    "request_id": telemetry.request_id.get(),
                    "kb_id": kb,
                    "result_count": len(results),
                    "elapsed_ms": round((perf_counter() - started) * 1000),
                }
            )
        )
        return results


def runtime(request: Request) -> Worker:
    return request.app.state.runtime


@asynccontextmanager
async def lifespan(app):
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    # Fail startup instead of attaching two independent writers to the same Chroma files.
    with FileLock(str(root / "writer.lock"), timeout=0):
        worker = Worker(open_catalog(), VectorStore(root / "chroma"))
        worker.catalog.recover()
        app.state.customer_store = CustomerStore(worker.catalog)
        app.state.customer_budget = PublicBudget()
        app.state.runtime = worker
        worker.thread.start()
        try:
            yield
        finally:
            worker.stop.set()
            worker.wake.set()
            await run_in_threadpool(worker.thread.join)
            await run_in_threadpool(worker.vectors.close)
