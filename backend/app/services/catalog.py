"""The original PDF, durable job and publish pointer commit in SQLite transactions.

A job id is also an immutable index version. Only a document's active job is searchable.
"""

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from app.config import data_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
 id TEXT PRIMARY KEY, kb TEXT NOT NULL, filename TEXT NOT NULL, active TEXT,
 UNIQUE(kb, filename), UNIQUE(id, kb));
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, doc TEXT NOT NULL, kb TEXT NOT NULL, version INTEGER NOT NULL,
 digest TEXT NOT NULL, pdf BLOB NOT NULL, actor TEXT NOT NULL, status TEXT NOT NULL,
 chunks INTEGER NOT NULL DEFAULT 0, pages INTEGER NOT NULL DEFAULT 0, error TEXT,
 FOREIGN KEY(doc,kb) REFERENCES docs(id,kb) ON DELETE CASCADE,
 UNIQUE(kb,digest), UNIQUE(doc,version));
CREATE INDEX IF NOT EXISTS active_by_kb ON docs(kb,active);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status);
CREATE TABLE IF NOT EXISTS cleanup (kb TEXT NOT NULL, version_id TEXT PRIMARY KEY);
"""
_PUBLIC = """SELECT j.id AS job_id, d.id AS document_id, d.filename, j.version,
             j.status, (d.active IS j.id) AS is_active, j.chunks AS indexed_count, j.pages AS page_count, j.error
             FROM jobs j JOIN docs d ON j.doc=d.id"""


class Catalog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)

    @contextmanager
    def connection(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def enqueue(self, kb, actor, filename, pdf):
        digest = hashlib.sha256(pdf).hexdigest()
        with self.connection(write=True) as db:
            existing = db.execute(_PUBLIC + " WHERE j.kb=? AND digest=?", (kb, digest)).fetchone()
            if existing:
                return dict(existing)
            doc = db.execute(
                "SELECT id FROM docs WHERE kb=? AND filename=?", (kb, filename)
            ).fetchone()
            doc_id = doc["id"] if doc else uuid4().hex
            if not doc:
                db.execute("INSERT INTO docs(id,kb,filename) VALUES(?,?,?)", (doc_id, kb, filename))
            version = db.execute(
                "SELECT coalesce(max(version),0)+1 FROM jobs WHERE doc=?", (doc_id,)
            ).fetchone()[0]
            job = uuid4().hex
            db.execute(
                "INSERT INTO jobs(id,doc,kb,version,digest,pdf,actor,status) VALUES(?,?,?,?,?,?,?,'queued')",
                (job, doc_id, kb, version, digest, pdf, actor),
            )
            return dict(db.execute(_PUBLIC + " WHERE j.id=?", (job,)).fetchone())

    def job(self, kb, job, *, retry=False):
        with self.connection(write=retry) as db:
            if retry:
                changed = db.execute(
                    "UPDATE jobs SET status='queued',error=NULL WHERE kb=? AND id=? AND status='failed'",
                    (kb, job),
                )
                if changed.rowcount:
                    db.execute("DELETE FROM cleanup WHERE kb=? AND version_id=?", (kb, job))
            row = db.execute(_PUBLIC + " WHERE j.kb=? AND j.id=?", (kb, job)).fetchone()
            return dict(row) if row else None

    def listing(self, kb, limit, offset):
        with self.connection() as db:
            db.execute("BEGIN")
            total = db.execute(
                "SELECT count(*) FROM docs WHERE kb=? AND active IS NOT NULL", (kb,)
            ).fetchone()[0]
            rows = db.execute(
                """SELECT d.id AS document_id,d.filename,j.chunks AS chunk_count,j.version
                FROM docs d JOIN jobs j ON j.id=d.active WHERE d.kb=? ORDER BY d.filename,d.id LIMIT ? OFFSET ?""",
                (kb, limit, offset),
            )
            return {"document_count": total, "documents": [dict(row) for row in rows]}

    def active_versions(self, kb, doc=None):
        with self.connection() as db:
            sql = "SELECT active FROM docs WHERE kb=? AND active IS NOT NULL"
            rows = db.execute(
                sql if doc is None else sql + " AND id=?", (kb,) if doc is None else (kb, doc)
            )
            return [row[0] for row in rows]

    def still_active(self, kb, candidates):
        if not candidates:
            return set()
        # Only recheck Top-K returned versions; do not scan the entire KB a second time.
        marks = ",".join("?" for _ in candidates)
        with self.connection() as db:
            rows = db.execute(
                f"SELECT active FROM docs WHERE kb=? AND active IN ({marks})", (kb, *candidates)
            )
            return {row[0] for row in rows}

    def remove(self, kb, doc):
        with self.connection(write=True) as db:
            if not db.execute("SELECT 1 FROM docs WHERE kb=? AND id=?", (kb, doc)).fetchone():
                return False
            db.execute(
                "INSERT OR IGNORE INTO cleanup SELECT kb,id FROM jobs WHERE doc=? AND kb=?",
                (doc, kb),
            )
            db.execute("DELETE FROM docs WHERE kb=? AND id=?", (kb, doc))
            return True

    def recover(self):
        # Called only after acquiring the single-worker process lock.
        with self.connection(write=True) as db:
            db.execute("UPDATE jobs SET status='queued' WHERE status='running'")

    def claim(self):
        with self.connection(write=True) as db:
            row = db.execute("""SELECT j.id,j.doc,j.kb,j.pdf,d.filename FROM jobs j JOIN docs d
                ON j.doc=d.id WHERE j.status='queued' ORDER BY j.rowid LIMIT 1""").fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running' WHERE id=?", (row["id"],))
                return dict(row)

    def finish(self, job, chunks=0, pages=0, error=None):
        with self.connection(write=True) as db:
            row = db.execute(
                "SELECT doc,kb,version FROM jobs WHERE id=? AND status='running'", (job,)
            ).fetchone()
            if not row:  # Deleted while being indexed; deletion has already queued cleanup.
                return
            if error:
                db.execute("UPDATE jobs SET status='failed',error=? WHERE id=?", (error, job))
                db.execute("INSERT OR IGNORE INTO cleanup VALUES(?,?)", (row["kb"], job))
                return
            db.execute(
                "UPDATE jobs SET status='ready',pages=?,chunks=?,error=NULL WHERE id=?",
                (pages, chunks, job),
            )
            old = db.execute(
                "SELECT j.id,j.version FROM docs d JOIN jobs j ON j.id=d.active WHERE d.id=?",
                (row["doc"],),
            ).fetchone()
            if not old or old["version"] < row["version"]:
                db.execute("UPDATE docs SET active=? WHERE id=?", (job, row["doc"]))
                retired = old["id"] if old else None
            else:
                retired = job  # A late retry must never roll back a newer published version.
            if retired:
                db.execute("INSERT OR IGNORE INTO cleanup VALUES(?,?)", (row["kb"], retired))

    def next_cleanup(self):
        with self.connection() as db:
            row = db.execute("SELECT kb,version_id FROM cleanup ORDER BY rowid LIMIT 1").fetchone()
            return tuple(row) if row else None

    def cleaned(self, version):
        with self.connection(write=True) as db:
            db.execute("DELETE FROM cleanup WHERE version_id=?", (version,))


def open_catalog():
    return Catalog(data_dir() / "catalog.sqlite3")
