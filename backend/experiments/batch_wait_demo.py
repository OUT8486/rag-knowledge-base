import asyncio
import time


async def request(name: str, wait_time) -> str:
    print(f"{name} 开始")
    await asyncio.sleep(wait_time)
    print(f"{name} 结束")
    done_message = f"{name}任务已完成"
    return done_message
    
async def run_nonblocking(table: list) -> list[str]:
    if table == []:
        return []
    start = time.perf_counter()
    items = (request(req["name"],req["wait_time"]) for req in table)
    done_list = await asyncio.gather(*items)
    elapsed = time.perf_counter() - start
    print(f"[nonblocking] 总耗时: {elapsed:.3f} 秒")
    return done_list

async def main() -> None:
    table1 = [{"name": "合同摘要","wait_time": 2},{"name": "意图分类", "wait_time": 1},{"name": "关键词抽取", "wait_time": 3}]
    print(await run_nonblocking(table1))
    print("-"*40)
    table2 = []
    print(await run_nonblocking(table2))


if __name__ == "__main__":
    asyncio.run(main())