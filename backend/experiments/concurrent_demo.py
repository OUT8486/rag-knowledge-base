import asyncio
import time


async def request(version: str, name: str) -> None:
    print(f"[{version}] {name} 开始")
    if version == "blocking":
        time.sleep(1)
    else:
        await asyncio.sleep(1)
    print(f"[{version}] {name} 结束")


async def run_blocking() -> float:
    start = time.perf_counter()
    await asyncio.gather(
        request("blocking", "A"),
        request("blocking", "B"),
        request("blocking", "C"),
    )
    elapsed = time.perf_counter() - start
    print(f"[blocking] 总耗时: {elapsed:.3f} 秒")
    return elapsed


async def run_nonblocking() -> float:
    start = time.perf_counter()
    await asyncio.gather(
        request("nonblocking", "A"),
        request("nonblocking", "B"),
        request("nonblocking", "C"),
    )
    elapsed = time.perf_counter() - start
    print(f"[nonblocking] 总耗时: {elapsed:.3f} 秒")
    return elapsed


async def main() -> None:
    await run_blocking()
    print("-" * 40)
    await run_nonblocking()


if __name__ == "__main__":
    asyncio.run(main())