"""Explicit, version-specific releases and private customer tickets in the existing catalog."""

import hashlib
import secrets
import time
from uuid import uuid4

from app.access import SUPPORT_KB

RETENTION = 30 * 24 * 60 * 60
_SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_releases (
    doc TEXT PRIMARY KEY REFERENCES docs(id) ON DELETE CASCADE,
    version TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    title TEXT NOT NULL, published_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS customer_tickets (
    id TEXT PRIMARY KEY, receipt_hash TEXT NOT NULL UNIQUE,
    issue TEXT NOT NULL, created INTEGER NOT NULL,
    reply TEXT, replied_at INTEGER, replied_by TEXT);
CREATE INDEX IF NOT EXISTS customer_ticket_created ON customer_tickets(created);
"""
_TICKET = "id, issue, created, reply, replied_at, CASE WHEN reply IS NULL THEN 'open' ELSE 'resolved' END AS status"


class CustomerStore:
    def __init__(self, catalog):
        self.catalog = catalog
        with catalog.connection() as db:
            db.executescript(_SCHEMA)
            db.execute(
                "DELETE FROM customer_tickets WHERE created<=?", (int(time.time()) - RETENTION,)
            )

    def materials(self, limit, offset):
        with self.catalog.connection() as db:
            rows = db.execute(
                """SELECT d.id AS document_id,d.active AS version_id,d.filename,j.version,
                r.title AS public_title FROM docs d JOIN jobs j ON j.id=d.active
                LEFT JOIN customer_releases r ON r.doc=d.id AND r.version=d.active
                WHERE d.kb=? ORDER BY d.filename,d.id LIMIT ? OFFSET ?""",
                (SUPPORT_KB, limit, offset),
            )
            return [dict(r) for r in rows]

    def release(self, doc, expected_version, title, actor):
        with self.catalog.connection(write=True) as db:
            current = db.execute(
                "SELECT active FROM docs WHERE id=? AND kb=?", (doc, SUPPORT_KB)
            ).fetchone()
            if not current:
                return "missing"
            if current["active"] != expected_version:
                return "stale"
            if title is None:
                db.execute("DELETE FROM customer_releases WHERE doc=?", (doc,))
            else:
                db.execute(
                    """INSERT INTO customer_releases(doc,version,title,published_by) VALUES(?,?,?,?)
                ON CONFLICT(doc) DO UPDATE SET version=excluded.version,title=excluded.title,published_by=excluded.published_by""",
                    (doc, expected_version, title, actor),
                )
            return "ok"

    def releases(self):
        with self.catalog.connection() as db:
            return dict(
                db.execute(
                    """SELECT r.version,r.title FROM customer_releases r JOIN docs d
                ON d.id=r.doc AND d.active=r.version WHERE d.kb=?""",
                    (SUPPORT_KB,),
                )
            )

    @staticmethod
    def digest(receipt):
        return hashlib.sha256(receipt.encode("ascii")).hexdigest()

    def new_ticket(self, issue):
        receipt, ticket, now = (
            secrets.token_urlsafe(32),
            "KF-" + uuid4().hex[:16].upper(),
            int(time.time()),
        )
        with self.catalog.connection(write=True) as db:
            db.execute("DELETE FROM customer_tickets WHERE created<=?", (now - RETENTION,))
            db.execute(
                "INSERT INTO customer_tickets(id,receipt_hash,issue,created) VALUES(?,?,?,?)",
                (ticket, self.digest(receipt), issue, now),
            )
        return {
            "id": ticket,
            "issue": issue,
            "created": now,
            "reply": None,
            "replied_at": None,
            "status": "open",
            "receipt": receipt,
        }

    def lookup(self, receipt):
        with self.catalog.connection() as db:
            row = db.execute(
                f"SELECT {_TICKET} FROM customer_tickets WHERE receipt_hash=? AND created>?",
                (self.digest(receipt), int(time.time()) - RETENTION),
            ).fetchone()
            return dict(row) if row else None

    def tickets(self, state, limit, offset):
        condition = "reply IS NULL" if state == "open" else "reply IS NOT NULL"
        with self.catalog.connection() as db:
            rows = db.execute(
                f"SELECT {_TICKET} FROM customer_tickets WHERE {condition} AND created>? ORDER BY created DESC,id LIMIT ? OFFSET ?",
                (int(time.time()) - RETENTION, limit, offset),
            )
            return [dict(r) for r in rows]

    def resolve(self, ticket, reply, actor):
        now = int(time.time())
        with self.catalog.connection(write=True) as db:
            updated = db.execute(
                """UPDATE customer_tickets SET reply=?,replied_at=?,replied_by=? WHERE id=?
                AND reply IS NULL AND created>?""",
                (reply, now, actor, ticket, now - RETENTION),
            )
            if updated.rowcount:
                return "ok"
            exists = db.execute(
                "SELECT 1 FROM customer_tickets WHERE id=? AND created>?", (ticket, now - RETENTION)
            ).fetchone()
            return "resolved" if exists else "missing"
