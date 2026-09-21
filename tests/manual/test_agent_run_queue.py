"""AgentRunRegistry 队列机制验证（无 LLM 依赖，纯 asyncio 驱动）

运行：uv run python tests/manual/test_agent_run_queue.py
覆盖：
1. 提交 8 个 run，前 5 个被领取执行、其余排队，并发峰值恰好 MAX_CONCURRENT_RUNS=5
2. FIFO：完成顺序与入队顺序一致
3. 排队中 cancel **立即落终态**（同步返回即 done，不等 worker 领取），factory 不执行
4. 取消后新入队 run 的 queue_position 排除已取消的排队 run
5. 事件流含 queued（带 queue_position）/ started；观流 stream() 先 queued 后 started
"""
import asyncio
import sys

sys.path.insert(0, ".")

from backend.core.agent_sdk.registry import MAX_CONCURRENT_RUNS, AgentRunRegistry


async def main() -> None:
    reg = AgentRunRegistry()
    running = 0
    peak = 0
    order: list[int] = []

    def make_factory(idx: int):
        async def factory(on_event, interrupt) -> dict:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.2)
            running -= 1
            order.append(idx)
            return {"idx": idx}
        return factory

    ids = [reg.start(f"task-{i}", make_factory(i)) for i in range(8)]

    # 让 worker 领取前 5 个（factory 各 0.2s，仍在执行中）
    await asyncio.sleep(0.05)
    handles = [reg.get(rid) for rid in ids]
    assert [h.status for h in handles] == ["running"] * 5 + ["queued"] * 3, \
        f"前 5 应执行、后 3 应排队: {[h.status for h in handles]}"

    # 排队中取消第 8 个：cancel 同步返回即落终态（不等 worker 领取）
    assert reg.cancel(ids[7]) is True
    h7 = handles[7]
    assert h7.done and h7.success is False and "取消" in (h7.error or ""), \
        f"排队取消应立即落终态: {h7.to_dict()}"
    assert "error" in [ev.type for _, ev in h7.events], "排队取消应立即发 error 事件"

    # 取消后再入队：queue_position 排除已取消的（前面只剩 task-5/task-6 两个有效排队者）
    ids.append(reg.start("task-8", make_factory(8)))
    queued8 = next(ev for _, ev in reg.get(ids[8]).events if ev.type == "queued")
    assert queued8.queue_position == 2, f"取消后 position 应排除已取消 run（期望 2）: {queued8.queue_position}"

    # 观流：对排队中的 task-5 订阅，应先收到 queued 再收到 started
    stream_events: list[str] = []
    async def watch():
        async for ev in reg.stream(ids[5]):
            stream_events.append(ev["type"])
    watcher = asyncio.create_task(watch())

    handles = [reg.get(rid) for rid in ids]
    while not all(h.done for h in handles):
        await asyncio.sleep(0.05)
    await watcher

    # 并发上限 + FIFO + 取消的未执行
    assert peak == MAX_CONCURRENT_RUNS, f"并发峰值 {peak} ≠ {MAX_CONCURRENT_RUNS}"
    assert order == [0, 1, 2, 3, 4, 5, 6, 8], f"FIFO 顺序异常: {order}"
    # 观流顺序与生命周期
    assert stream_events[:2] == ["queued", "started"], f"观流首批事件异常: {stream_events[:3]}"
    assert reg.get(ids[0]).to_dict()["status"] == "done"

    print(f"✅ 全部断言通过：并发峰值={peak} 完成顺序={order} 排队取消即时生效 position 排除已取消")


if __name__ == "__main__":
    asyncio.run(main())
