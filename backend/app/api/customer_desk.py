from typing import Annotated, Literal

from app.access import SUPPORT_KB, Scope, WriteScope
from app.api.customer import Input, Issue, Site, Ticket
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import StringConstraints

router = APIRouter(prefix="/api/kbs/{kb_id}/desk", tags=["客服坐席"])


def agent(scope: WriteScope, policy: Site) -> Scope:
    if scope.kb_id != SUPPORT_KB:
        raise HTTPException(404, "坐席台不存在。")
    return scope


Agent = Annotated[Scope, Depends(agent)]
Version = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class Release(Input):
    version_id: Version
    public_title: Title | None  # null explicitly withdraws this reviewed version


class Reply(Input):
    reply: Issue


@router.get("/materials")
def materials(
    agent: Agent,
    request: Request,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return request.app.state.customer_store.materials(limit, offset)


@router.put("/materials/{doc}")
def publish(doc: str, payload: Release, agent: Agent, request: Request):
    outcome = request.app.state.customer_store.release(
        doc, payload.version_id, payload.public_title, agent.subject
    )
    if outcome == "missing":
        raise HTTPException(404, "客服文档不存在。")
    if outcome == "stale":
        raise HTTPException(409, "文档版本已变化，请刷新并重新审核。")
    return {"public_title": payload.public_title}


@router.get("/tickets", response_model=list[Ticket])
def tickets(
    agent: Agent,
    request: Request,
    state: Literal["open", "resolved"] = "open",
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return request.app.state.customer_store.tickets(state, limit, offset)


@router.post("/tickets/{ticket}/reply")
def respond(ticket: str, payload: Reply, agent: Agent, request: Request):
    outcome = request.app.state.customer_store.resolve(ticket, payload.reply, agent.subject)
    if outcome == "missing":
        raise HTTPException(404, "工单不存在或已过期。")
    if outcome == "resolved":
        raise HTTPException(409, "已有坐席回复，请刷新列表。")
    return {"status": "resolved"}
