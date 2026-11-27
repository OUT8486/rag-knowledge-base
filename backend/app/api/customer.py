"""Anonymous customer surface. This router never accepts a KB, document, model or prompt override."""

import logging
import re
from typing import Annotated, Literal

from app.access import SUPPORT_KB, AccessConfig, Policy, configuration
from app.services.evidence import checked_answer, pack_sources
from app.services.ingestion import Worker, runtime
from app.services.llm import generate_customer_answer, model_route
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/customer", tags=["网站客服"])
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Issue = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]
Previous = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Ask(Input):
    question: Question
    previous_questions: list[Previous] = Field(default_factory=list, max_length=2)
    allow_cloud: StrictBool = False


class Citation(BaseModel):
    source_id: str
    title: str
    page: int
    excerpt: str


class Answer(BaseModel):
    kind: Literal["answered", "guidance", "no_evidence", "handoff", "unavailable"]
    answer: str
    sources: list[Citation]


class TicketInput(Input):
    issue: Issue
    share_with_agent: StrictBool


class Ticket(BaseModel):
    id: str
    created: int
    issue: str
    status: Literal["open", "resolved"]
    reply: str | None
    replied_at: int | None


class NewTicket(Ticket):
    receipt: str


def enabled(config: Annotated[AccessConfig, Depends(configuration)]) -> Policy:
    if not config.customer_service_enabled:
        raise HTTPException(404, "在线客服尚未开放。")
    return config.knowledge_bases[SUPPORT_KB].policy


Site = Annotated[Policy, Depends(enabled)]
NO_MATCH = "已公开的帮助资料不足以确认答案。你可以补充产品名称或具体场景，也可以转人工。"


def meter(request, action):
    peer = request.client.host if request.client else "unknown"
    if not request.app.state.customer_budget.admit(action, peer):
        raise HTTPException(429, "请求较多，请稍后再试。", headers={"Retry-After": "60"})


def result(kind, text, sources=()):
    return {"kind": kind, "answer": text, "sources": list(sources)}


@router.get("/info")
def info(policy: Site):
    return {"policy": policy, "ticket_retention_days": 30}


@router.post("/ask", response_model=Answer)
def ask(payload: Ask, policy: Site, request: Request, rt: Annotated[Worker, Depends(runtime)]):
    meter(request, "ask")
    wording = payload.question.rstrip("！!。.？?")
    if wording in {"如何查看人工回复", "怎么查工单进度", "如何查看工单进度"}:
        return result(
            "guidance",
            "打开「工单进度」，输入提交后收到的私密查询凭证，点击「查询进度」即可看到回复。使用原标签页时会自动带入凭证。工单号不能代替凭证。",
        )
    direct_action = re.match(
        r"^(?:请|麻烦)?(?:帮我|替我|给我)(?:查(?:一下|下)?(?:订单|物流)|办理退款|退款|取消订单|修改收货地址)",
        wording,
    )
    if direct_action:
        return result(
            "handoff",
            "我不能查看个人订单或执行这项操作。可以把问题描述交给人工坐席核实，请勿填写支付信息、密码或验证码。",
        )
    if wording in {"转人工", "人工", "人工客服", "我要转人工", "找人工客服"}:
        return result(
            "handoff", "可以。请确认要交给人工客服的问题描述，提交后可以凭查询凭证查看回复。"
        )
    store = request.app.state.customer_store
    published = store.releases()
    if not published:
        return result("no_evidence", NO_MATCH)
    if policy == "approved_cloud" and not payload.allow_cloud:
        raise HTTPException(
            409, "客服使用指定云模型，须先同意发送本次问题和最近提问；也可直接转人工。"
        )
    slots = request.app.state.customer_budget.inference
    if not slots.acquire(blocking=False):
        raise HTTPException(
            429, "AI 正在处理其他咨询，请稍后再试或转人工。", headers={"Retry-After": "5"}
        )
    try:
        query = payload.question
        if payload.previous_questions:
            query += "\n此前咨询：" + payload.previous_questions[-1]
        rows = rt.search(SUPPORT_KB, list(published), query, 4)
        # Only use the reviewed version and title, even if updated/deleted during retrieval.
        current = store.releases()
        material = [
            {**r, "filename": published[r["version_id"]]}
            for r in rows
            if r["version_id"] in published
            and current.get(r["version_id"]) == published[r["version_id"]]
        ]
        sources = pack_sources(material)
        if not sources:
            return result("no_evidence", NO_MATCH)
        if enabled(configuration()) != policy:
            raise HTTPException(409, "模型策略已变化，请刷新页面后再咨询。")
        route = model_route(policy)
        # The generator only sees these four public fields, not internal names, IDs or staff data.
        evidence = [{k: s[k] for k in ("source_id", "filename", "page", "text")} for s in sources]
        text = generate_customer_answer(
            payload.question, payload.previous_questions, evidence, route
        )
        checked = checked_answer(text, sources)
        current = store.releases()
        if not checked["sources"] or any(
            current.get(s["version_id"]) != s["filename"] for s in sources
        ):
            return result("no_evidence", NO_MATCH)
        citations = [
            {
                "source_id": s["source_id"],
                "title": s["filename"],
                "page": s["page"],
                "excerpt": s["text"][:160],
            }
            for s in checked["sources"]
        ]
        return result("answered", checked["answer"], citations)
    except HTTPException:
        raise
    except Exception as exc:
        # Log neither visitor questions nor raw provider errors; never fall back to a different route.
        log.warning(
            "customer_ai_unavailable request_id=%s type=%s",
            request.state.request_id,
            type(exc).__name__,
        )
        return result("unavailable", "AI 暂时无法回答。你可以稍后重试，或把这个问题交给人工客服。")
    finally:
        slots.release()


@router.post("/tickets", response_model=NewTicket, status_code=201)
def create_ticket(payload: TicketInput, policy: Site, request: Request):
    meter(request, "create")
    if not payload.share_with_agent:
        raise HTTPException(400, "请确认允许坐席查看这段问题描述。")
    return request.app.state.customer_store.new_ticket(payload.issue)


@router.get("/ticket", response_model=Ticket)
def lookup_ticket(
    policy: Site, request: Request, x_ticket_receipt: Annotated[str | None, Header()] = None
):
    meter(request, "lookup")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", x_ticket_receipt or ""):
        raise HTTPException(404, "未找到工单，请核对凭证或有效期。")
    ticket = request.app.state.customer_store.lookup(x_ticket_receipt)
    if ticket is None:
        raise HTTPException(404, "未找到工单，请核对凭证或有效期。")
    return ticket
