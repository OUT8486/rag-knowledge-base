from contextvars import ContextVar

# FastAPI propagates this value into sync endpoints/thread-pool tasks; the ingestion worker uses job IDs instead.
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
