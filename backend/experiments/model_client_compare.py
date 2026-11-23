"""同步 OpenAI 与 AsyncOpenAI 对事件循环影响的真实请求对照实验。

本文件只定义代码结构。请按各函数中的 TODO 完成实现，不要改动外部行为：
- 使用 backend/.env 中的真实本地服务配置；
- 两种实验使用相同任务与请求参数；
- 同步请求和异步请求分别与心跳一起交给 asyncio.gather；
- 输出必须保留任务标识与回答的对应关系。

注意：学习记录只写入 learning-workspace；本文件属于关联代码实验，不写入秘密值。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI

from app.services.llm_metrics import build_model_metrics

# 固定从 backend/.env 读取配置
BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

# 正式请求与预热请求共用的受限输出长度
MAX_TOKENS = 1024

# 预热使用与正式实验同类的短问题
PREWARM_QUESTION = "你好，请用一句话打个招呼。"


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """从 backend/.env 读取到的最小客户端配置。"""

    base_url: str
    api_key: str = field(repr=False)
    model_name: str


@dataclass(frozen=True, slots=True)
class RequestTask:
    """一次可识别的短问题请求。task_id 用于稳定映射问题和回答。"""

    task_id: str
    question: str


@dataclass(frozen=True, slots=True)
class ExperimentSummary:
    """一次正式实验的耗时与按任务标识保存的回答。"""

    elapsed_seconds: float
    answers: dict[str, str]


def load_client_config(env_path: Path) -> ClientConfig:
    """读取并校验 LLM_BASE_URL、LLM_API_KEY、LLM_MODEL。

    输入：backend/.env 的路径。
    输出：不含任何打印副作用的 ClientConfig。
    要求：缺少任一配置时给出明确错误；任何日志都不得包含 API Key。
    """
    # 确保从指定 .env 重新加载（不打印任何配置值）
    load_dotenv(env_path, override=True)

    base_url = os.getenv("LLM_BASE_URL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model_name = os.getenv("LLM_MODEL", "").strip()

    missing: list[str] = []
    if not base_url:
        missing.append("LLM_BASE_URL")
    if not api_key:
        missing.append("LLM_API_KEY")
    if not model_name:
        missing.append("LLM_MODEL")

    if missing:
        # 只报缺失的配置名，不泄露任何密钥值
        raise RuntimeError(
            f"缺少必要的客户端配置：{', '.join(missing)}；请检查 {env_path}"
        )

    return ClientConfig(base_url,api_key,model_name)


def create_sync_client(config: ClientConfig) -> OpenAI:
    """创建同步 OpenAI 客户端。

    输入：ClientConfig。
    输出：完成配置的 OpenAI 实例。
    """
    return OpenAI(api_key=config.api_key, base_url=config.base_url)


def create_async_client(config: ClientConfig) -> AsyncOpenAI:
    """创建异步 AsyncOpenAI 客户端。

    输入：ClientConfig。
    输出：完成配置的 AsyncOpenAI 实例。
    """
    return AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)


def prewarm_sync_client(client: OpenAI, config: ClientConfig) -> None:
    """用同步客户端发出一次不计入正式耗时的预热请求。"""
    print("[同步] 预热开始")
    client.chat.completions.create(
        model=config.model_name,
        messages=[{"role": "user", "content": PREWARM_QUESTION}],
        max_tokens=MAX_TOKENS,
        temperature=0.2,
    )
    print("[同步] 预热成功")


async def prewarm_async_client(client: AsyncOpenAI, config: ClientConfig) -> None:
    """用异步客户端发出一次不计入正式耗时的预热请求。"""
    print("[异步] 预热开始")
    await client.chat.completions.create(
        model=config.model_name,
        messages=[{"role": "user", "content": PREWARM_QUESTION}],
        max_tokens=MAX_TOKENS,
        temperature=0.2,
    )
    print("[异步] 预热成功")


async def heartbeat(experiment_name: str, started_at: float) -> None:
    """每约 0.2 秒打印一次当前实验的累计耗时，最多打印 3 次。

    输入：实验名和 perf_counter() 起点。
    输出：无。
    """
    for _ in range(3):
        await asyncio.sleep(0.2)
        elapsed = time.perf_counter() - started_at
        print(f"[{experiment_name}] 心跳：实验累计耗时 {elapsed:.3f}s")


async def run_sync_request(
    client: OpenAI,
    config: ClientConfig,
    task: RequestTask,
    started_at: float,
) -> tuple[str, str]:
    """使用同步 SDK 处理一个请求，并返回 (task_id, answer)。

    关键约束：这是 async def，但请直接在事件循环线程中调用同步
    client.chat.completions.create(...)。不要使用 to_thread、run_in_executor
    或自行创建线程，否则实验观察不到同步调用对事件循环的阻塞。
    """
    print(f"[同步][{task.task_id}] 请求开始")
    
    started_time = time.perf_counter()

    # 直接在当前事件循环线程内执行阻塞调用，用于观察阻塞效果
    response = client.chat.completions.create(
        model=config.model_name,
        messages=[{"role": "user", "content": task.question}],
        max_tokens=MAX_TOKENS,
        temperature=0,
    )

    metrics = build_model_metrics(response, (time.perf_counter()-started_time)*1000)
    metrics["task_id"] = task.task_id
    metrics["client_type"] = "sync"
    print(json.dumps(metrics))

    answer = (response.choices[0].message.content or "").strip()
    print(
        f"[同步][{task.task_id}] 请求结束"
        f"（实验累计 {time.perf_counter() - started_at:.3f}s）"
    )
    return task.task_id, answer


async def run_async_request(
    client: AsyncOpenAI,
    config: ClientConfig,
    task: RequestTask,
    started_at: float,
) -> tuple[str, str]:
    """使用 AsyncOpenAI 处理一个请求，并返回 (task_id, answer)。"""
    print(f"[异步][{task.task_id}] 请求开始")

    started_time = time.perf_counter()

    response = await client.chat.completions.create(
        model=config.model_name,
        messages=[{"role": "user", "content": task.question}],
        max_tokens=MAX_TOKENS,
        temperature=0,
    )

    metrics = build_model_metrics(response, (time.perf_counter()-started_time)*1000)
    metrics["task_id"] = task.task_id
    metrics["client_type"] = "async"
    print(json.dumps(metrics))
    
    answer = (response.choices[0].message.content or "").strip()
    print(
        f"[异步][{task.task_id}] 请求结束"
        f"（实验累计 {time.perf_counter() - started_at:.3f}s）"
    )
    return task.task_id, answer


async def run_sync_experiment(
    config: ClientConfig,
    tasks: list[RequestTask],
) -> ExperimentSummary:
    """编排同步客户端正式实验。"""
    print("=== 同步实验开始 ===")
    client = create_sync_client(config)
    try:
        # 预热不计入正式耗时
        prewarm_sync_client(client, config)

        started_at = time.perf_counter()
        results = await asyncio.gather(
            heartbeat("同步", started_at),
            *(run_sync_request(client, config, task, started_at) for task in tasks),
        )
        elapsed_seconds = time.perf_counter() - started_at

        # results[0] 是心跳返回值 None；其余为 (task_id, answer)
        answers: dict[str, str] = {}
        for task_id, answer in results[1:]:
            answers[task_id] = answer

        summary = ExperimentSummary(
            elapsed_seconds=elapsed_seconds,
            answers=answers,
        )
        print(f"=== 同步实验结束：总耗时 {elapsed_seconds:.3f}s ===")
        return summary
    finally:
        # 覆盖正常结束与异常结束的关闭流程
        client.close()


async def run_async_experiment(
    config: ClientConfig,
    tasks: list[RequestTask],
) -> ExperimentSummary:
    """编排 AsyncOpenAI 正式实验。"""
    print("=== 异步实验开始 ===")
    client = create_async_client(config)
    try:
        # 预热不计入正式耗时
        await prewarm_async_client(client, config)

        started_at = time.perf_counter()
        results = await asyncio.gather(
            heartbeat("异步", started_at),
            *(run_async_request(client, config, task, started_at) for task in tasks),
            return_exceptions=True
        )
        elapsed_seconds = time.perf_counter() - started_at

        # results[0] 是心跳返回值 None；其余为 (task_id, answer)
        answers: dict[str, str] = {}
        for item in results[1:]:
            if isinstance(item, Exception):
                raise item
            answers[item[0]] = item[1]
        
        summary = ExperimentSummary(
            elapsed_seconds=elapsed_seconds,
            answers=answers,
        )
        print(f"=== 异步实验结束：总耗时 {elapsed_seconds:.3f}s ===")
        return summary
    finally:
        # 覆盖正常结束与异常结束的关闭流程
        await client.close()


async def main() -> None:
    """运行同步实验和异步实验。"""
    env_path = BACKEND_DIR / ".env"
    config = load_client_config(env_path)

    # 两个实验复用同一组任务，保证对照公平
    tasks = [
        RequestTask(
            task_id="q1",
            question="请用一句话解释什么是 asyncio 事件循环。",
        ),
        RequestTask(
            task_id="q2",
            question="请用一句话解释什么是协程。",
        ),
    ]

    # 先运行同步实验，观察同步调用阻塞事件循环时心跳被推迟的情况
    sync_summary = await run_sync_experiment(config, tasks)
    print(f"同步实验总耗时：{sync_summary.elapsed_seconds:.3f}s")
    print("同步实验回答映射：")
    for task_id, answer in sync_summary.answers.items():
        print(f"  {task_id} -> {answer}")

    print()

    # 再运行异步实验，观察心跳与请求在事件循环中交替推进
    async_summary = await run_async_experiment(config, tasks)
    print(f"异步实验总耗时：{async_summary.elapsed_seconds:.3f}s")
    print("异步实验回答映射：")
    for task_id, answer in async_summary.answers.items():
        print(f"  {task_id} -> {answer}")
        if isinstance(answer, Exception):
            raise Exception


if __name__ == "__main__":
    asyncio.run(main())