"""Run once on the server: python -m app.manage init"""

import argparse
import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path

from app.access import SUPPORT_KB, AccessConfig
from app.config import access_path
from filelock import FileLock


def initialize() -> None:
    path = access_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".edit.lock", timeout=5):
        _initialize_departments(path)


def _initialize_departments(path: Path) -> None:
    kbs = {
        k: {
            "name": label,
            "policy": "local_only",
            "readers": [f"{k}-read"],
            "writers": [f"{k}-write"],
        }
        for k, label in [("finance", "财务制度"), ("hr", "人事制度")]
    }
    keys = {
        user: secrets.token_urlsafe(32) for user in ("finance-write", "hr-write", "finance-read")
    }
    users = {
        user: {"groups": [user], "sha256": hashlib.sha256(key.encode()).hexdigest()}
        for user, key in keys.items()
    }
    # Exclusive create: never reset a live deployment or print existing credentials.
    with path.open("x", encoding="utf-8") as out:
        json.dump({"knowledge_bases": kbs, "users": users}, out, indent=2, ensure_ascii=False)
    print(f"已创建 {path}；以下随机访问令牌仅显示本次，请分别安全分发：")
    for user, key in keys.items():
        print(f"{user}: {key}")


def initialize_support() -> None:
    """Explicit opt-in. Add a dedicated agent; never repurpose an existing internal KB/group."""
    path = access_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    role = "customer-agent"
    with FileLock(str(path) + ".edit.lock", timeout=5):
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            AccessConfig.model_validate(raw)
        else:
            raw = {"knowledge_bases": {}, "users": {}}
        if raw.get("customer_service_enabled") is True:
            print("客服已启用，未更改已有配置或令牌。")
            return
        kbs = raw["knowledge_bases"]
        users = raw.setdefault("users", {})
        if (
            SUPPORT_KB in kbs
            or role in users
            or any(role in u["groups"] for u in users.values())
            or any(role in (k.get("readers", []) + k.get("writers", [])) for k in kbs.values())
        ):
            raise ValueError("客服库或坐席标识已经占用。未覆盖配置，请由管理员核对归属。")
        key = secrets.token_urlsafe(32)
        kbs[SUPPORT_KB] = {"name": "客户帮助中心", "policy": "local_only", "writers": [role]}
        users[role] = {"groups": [role], "sha256": hashlib.sha256(key.encode()).hexdigest()}
        raw["customer_service_enabled"] = True
        AccessConfig.model_validate(raw)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as f:
            tmp = Path(f.name)
            json.dump(raw, f, ensure_ascii=False, indent=2)
        try:
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
    print("客服已启用，尚未发布任何资料。以下坐席令牌仅显示一次，请妥善保存：")
    print(f"{role}: {key}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "init-support"])
    args = parser.parse_args()
    try:
        if args.command == "init":
            initialize()
        else:
            initialize_support()
    except FileExistsError:
        parser.exit(1, "配置已存在，未改动账号或令牌。\n")
    except (ValueError, KeyError):
        parser.exit(1, "配置无效或客服标识已占用，未覆盖原配置，请联系管理员。\n")
