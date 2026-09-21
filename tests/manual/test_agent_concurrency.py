"""Agent 并发上限动态调整验证（无 LLM 依赖，纯 asyncio 驱动 + SettingsManager 持久化）

运行：uv run python tests/manual/test_agent_concurrency.py
覆盖：
1. PUT 缩容（5→2）：正在执行的 run 不被中断照常完成，多余 worker 完成当前 run 后自愿退出，
   后续任务按新上限（2）并发
2. PUT 扩容（2→4）：排队中的任务立即被补足的 worker 领取
3. 配置持久化：SettingsManager 写入后重新读取一致；registry 重启恢复（lifespan 注入逻辑等价）
"""
import asyncio
import sys
import tempfile

sys.path.insert(0, ".")

from backend.core.agent_sdk.registry import AgentRunRegistry
from backend.core.persistence.settings_manager import AGENT_CONCURRENCY_KEY, SettingsManager


async def _drive(reg: AgentRunRegistry, factories_running: list[bool]) -> None:
    """让事件循环推进：等所有 factory 结束（running 标记全部 False）"""
    while any(factories_running):
        await asyncio.sleep(0.02)


def make_factory(idx: int, running: list[bool], order: list[int], duration: float = 0.3):
    async def factory(on_event, interrupt) -> dict:
        running[idx] = True
        await asyncio.sleep(duration)
        running[idx] = False
        order.append(idx)
        return {"idx": idx}
    return factory


async def main() -> None:
    # ---------- 1. 缩容：5 → 2，执行中的不中断 ----------
    reg = AgentRunRegistry()
    assert reg.max_concurrent == 5
    running: list[bool] = []
    order: list[int] = []

    ids = []
    for i in range(5):
        running.append(False)
        ids.append(reg.start(f"task-{i}", make_factory(i, running, order)))
    await asyncio.sleep(0.05)  # 5 个全部被领取执行中
    assert all(running), "前 5 个应全部执行中"
    assert reg.active_workers == 5

    # 排 3 个，随后缩容到 2：执行中的 5 个不受影响，后续并发上限变 2
    for i in range(5, 8):
        running.append(False)
        ids.append(reg.start(f"task-{i}", make_factory(i, running, order)))
    reg.set_max_concurrent(2)
    await _drive(reg, running)

    assert all(reg.get(rid).done for rid in ids), "全部 run 应完成"
    assert order[:5] == [0, 1, 2, 3, 4], f"缩容前执行中的 5 个应照常完成: {order}"
    assert reg.active_workers == 2, f"缩容后存活 worker 应为 2: {reg.active_workers}"
    print(f"✅ 缩容 5→2：执行中任务未中断，worker 收敛到 {reg.active_workers}，完成顺序 {order}")

    # ---------- 2. 扩容：2 → 4，排队任务立即被领取 ----------
    running2: list[bool] = []
    order2: list[int] = []
    ids2 = []
    for i in range(6):
        running2.append(False)
        ids2.append(reg.start(f"task2-{i}", make_factory(i, running2, order2, duration=0.5)))
    await asyncio.sleep(0.05)
    assert sum(running2) == 2, f"并发上限 2，只应执行 2 个: {sum(running2)}"

    reg.set_max_concurrent(4)  # 扩容：补 2 个 worker，排队 2 个立即被领取
    await asyncio.sleep(0.1)
    assert sum(running2) == 4, f"扩容后应立即有 4 个执行中: {sum(running2)}"
    await _drive(reg, running2)
    assert reg.active_workers == 4
    print(f"✅ 扩容 2→4：排队任务立即被领取，worker 数 {reg.active_workers}")

    # ---------- 3. 持久化 round-trip（独立临时 db，不动 data/sessions.db） ----------
    with tempfile.TemporaryDirectory() as td:
        sm = SettingsManager(db_path=f"{td}/test.db")
        assert sm.get(AGENT_CONCURRENCY_KEY) is None
        sm.set(AGENT_CONCURRENCY_KEY, "3")
        sm.set(AGENT_CONCURRENCY_KEY, "7")  # UPSERT 覆盖
        assert sm.get(AGENT_CONCURRENCY_KEY) == "7"
        sm2 = SettingsManager(db_path=f"{td}/test.db")  # 新实例模拟重启
        assert sm2.get(AGENT_CONCURRENCY_KEY) == "7"
        reg2 = AgentRunRegistry()
        reg2.set_max_concurrent(int(sm2.get(AGENT_CONCURRENCY_KEY)))  # lifespan 等价逻辑
        assert reg2.max_concurrent == 7
    print("✅ 持久化：UPSERT 覆盖、重启重读、注入新 registry 均正确")

    print("\n🎉 全部通过")


if __name__ == "__main__":
    asyncio.run(main())
