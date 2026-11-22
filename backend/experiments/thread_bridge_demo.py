
import asyncio
from http import client
import time


def request(question: str):
    print("开始")
    time.sleep(1)
    print("结束")
    return question+"的回答"

async def heartbeat(question_name: str, started_at: float) -> None:
    """
    每约 0.2 秒打印一次当前实验的累计耗时，最多打印 3 次。
    """
    for _ in range(3):
        await asyncio.sleep(0.2)
        elapsed = time.perf_counter() - started_at
        print(f"[{question_name}] 心跳：实验累计耗时 {elapsed:.3f}s")


async def main():
    question = input()
    started_at = time.perf_counter()
    result = await asyncio.gather(
        asyncio.to_thread(request, question=question),
        heartbeat(question_name=question, started_at=started_at),
    )
    print(f"总耗时：{time.perf_counter()-started_at}")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())   
