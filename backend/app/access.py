"""Server-owned group grants. Missing or invalid configuration always denies access."""

import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Annotated, Literal

from app.config import access_path
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SUPPORT_KB = "customer-help"
Policy = Literal["local_only", "approved_cloud"]
KBId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]([a-z0-9-]{0,46}[a-z0-9])?$")]


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeBase(ConfigModel):
    name: str = Field(min_length=1)
    policy: Policy = "local_only"
    readers: set[str] = Field(default_factory=set)
    writers: set[str] = Field(default_factory=set)


class TokenUser(ConfigModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    groups: set[str]


class AccessConfig(ConfigModel):
    knowledge_bases: dict[KBId, KnowledgeBase] = Field(min_length=1)
    users: dict[str, TokenUser] = Field(default_factory=dict)
    customer_service_enabled: bool = False

    @model_validator(mode="after")
    def unique_credentials(self):
        if len({user.sha256 for user in self.users.values()}) != len(self.users):
            raise ValueError("Duplicate credentials")
        if self.customer_service_enabled and (
            SUPPORT_KB not in self.knowledge_bases or not self.knowledge_bases[SUPPORT_KB].writers
        ):
            raise ValueError("启用客服需配置专用客服库及坐席写入组")
        return self


def configuration() -> AccessConfig:
    # Re-read on each request: a revoked user/grant must not survive in a process cache.
    try:
        return AccessConfig.model_validate_json(access_path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise HTTPException(503, "访问控制配置不可用，请联系管理员。") from None


def auth_mode() -> str:
    mode = os.getenv("RAG_AUTH_MODE", "token")
    key = os.getenv("RAG_GATEWAY_KEY", "")
    if mode not in {"token", "proxy"} or (mode == "proxy" and (len(key) < 32 or not key.isascii())):
        raise HTTPException(503, "身份认证配置不可用。")
    return mode


@dataclass(frozen=True)
class Principal:
    subject: str
    groups: frozenset[str]


def authenticate(
    request: Request, config: Annotated[AccessConfig, Depends(configuration)]
) -> Principal:
    principal = None
    mode = auth_mode()
    if mode == "token":
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer" and token and len(token) <= 256:
            digest = hashlib.sha256(token.encode()).hexdigest()
            for subject, user in config.users.items():
                if secrets.compare_digest(user.sha256, digest):
                    principal = Principal(subject, frozenset(user.groups))
                    break
    else:
        # Only the trusted TLS gateway supplies these three headers, overwriting client values.
        supplied = request.headers.get("x-rag-gateway-key", "")
        if supplied.isascii() and secrets.compare_digest(supplied, os.environ["RAG_GATEWAY_KEY"]):
            subject = request.headers.get("x-rag-user", "").strip()
            groups = request.headers.get("x-rag-groups", "").split(",")
            if subject:
                principal = Principal(subject, frozenset(g.strip() for g in groups if g.strip()))
    if not principal:
        raise HTTPException(401, "请先登录。", headers={"WWW-Authenticate": "Bearer"})
    if (
        mode == "proxy"
        and request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.headers.get("x-rag-request") != "1"
    ):
        raise HTTPException(403, "缺少同源请求标记。")
    request.state.subject = principal.subject
    return principal


@dataclass(frozen=True)
class Scope:
    kb_id: str
    policy: Policy
    can_write: bool
    subject: str


def read_scope(
    kb_id: str,
    request: Request,
    who: Annotated[Principal, Depends(authenticate)],
    config: Annotated[AccessConfig, Depends(configuration)],
) -> Scope:
    kb = config.knowledge_bases.get(kb_id)
    if kb is None or not who.groups.intersection(kb.readers | kb.writers):
        raise HTTPException(404, "知识库不存在或不可访问。")
    request.state.kb_id = kb_id
    return Scope(kb_id, kb.policy, bool(who.groups & kb.writers), who.subject)


ReadScope = Annotated[Scope, Depends(read_scope)]


def write_scope(scope: ReadScope) -> Scope:
    if not scope.can_write:
        raise HTTPException(403, "当前账号只有读取权限。")
    return scope


WriteScope = Annotated[Scope, Depends(write_scope)]
router = APIRouter(prefix="/api", tags=["访问控制"])


@router.get("/session")
def session(
    who: Annotated[Principal, Depends(authenticate)],
    config: Annotated[AccessConfig, Depends(configuration)],
):
    return {
        "subject": who.subject,
        "auth_mode": auth_mode(),
        "knowledge_bases": [
            {
                "id": key,
                "name": kb.name,
                "policy": kb.policy,
                "can_write": bool(who.groups & kb.writers),
                "customer_desk": config.customer_service_enabled
                and key == SUPPORT_KB
                and bool(who.groups & kb.writers),
            }
            for key, kb in config.knowledge_bases.items()
            if who.groups & (kb.readers | kb.writers)
        ],
    }
