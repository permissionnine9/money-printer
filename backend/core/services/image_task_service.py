"""生图任务状态机：insert(pending)→submit→processing→poll→completed/failed

统一核心素材批量 / 核心素材单张重生成 / 分集素材图三处状态机：
- run_batch：批量提交（间隔限流）+ 并发轮询；单张失败不中断（标 failed 继续跑其余）
- run_single：单张同步生成；失败标 failed 并抛业务异常
- 可选归档钩子（on_completed 支持同步/异步；返回 dict 时并入完成态回写，如归档后的 image_path/meta）
- 可选完成后回调（set_entity_lookbook / segment 关联等，在完成态回写后调用）
"""
import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from backend.core.config import IMAGE_REQUEST_TIME_GAP
from backend.core.errors import WorkflowError
from backend.core.models import VideoParams

logger = logging.getLogger(__name__)


@dataclass
class ImageTaskSpec:
    """单张生图任务（image_id 对应 DB 行；prompt 为生图提示词）"""
    image_id: str
    prompt: str
    reference_paths: list[str] | None = field(default=None)


async def _run_completed_hook(
    on_completed: Callable[[str, dict], Optional[dict]], image_id: str, poll: dict,
) -> Optional[dict]:
    """执行完成钩子（兼容同步/异步钩子；返回 dict 时供调用方并入完成态回写）"""
    extra = on_completed(image_id, poll)
    if inspect.isawaitable(extra):
        extra = await extra
    return extra if isinstance(extra, dict) else None


class ImageTaskService:
    """生图任务状态机（行状态回写经 update_row 回调，适配 lookbook/mat_* 两类表）"""

    def __init__(self, error_cls: type[WorkflowError] = WorkflowError):
        self.error = error_cls

    async def run_batch(
        self,
        image_service,
        tasks: list[ImageTaskSpec],
        video_params: VideoParams,
        update_row: Callable[[str, dict], None],
        *,
        submit_gap: float = IMAGE_REQUEST_TIME_GAP,
        poll_timeout: int = 180,
        poll_interval: int = 5,
        interrupt: Optional[asyncio.Event] = None,
        on_completed: Optional[Callable[[str, dict], Optional[dict]]] = None,
    ) -> list[tuple[str, str]]:
        """批量生图：间隔提交 + 并发轮询；单张失败标 failed 继续跑

        Returns: 已提交成功的 (image_id, request_id) 列表
        """
        submitted: list[tuple[str, str]] = []
        for i, task in enumerate(tasks):
            if interrupt and interrupt.is_set():
                raise self.error("已取消", reason="cancelled")
            if i > 0:
                await asyncio.sleep(submit_gap)
            try:
                submit = await image_service.submit_image_task(task.prompt, video_params, task.reference_paths)
                if submit.get("success"):
                    submitted.append((task.image_id, submit["request_id"]))
                    update_row(task.image_id, {"task_id": submit["request_id"], "task_status": "processing"})
                else:
                    update_row(task.image_id, {"task_status": "failed"})
                    logger.error(f"[生图] 提交失败 {task.image_id}: {submit.get('error')}")
            except Exception as e:  # noqa: BLE001
                update_row(task.image_id, {"task_status": "failed"})
                logger.error(f"[生图] 提交异常 {task.image_id}: {e}")

        async def poll_one(image_id: str, request_id: str) -> None:
            poll = await image_service.poll_i2i_task(request_id, timeout=poll_timeout, poll_interval=poll_interval)
            if poll.get("success"):
                fields = {"image_path": poll.get("image_url", ""), "task_status": "completed"}
                if on_completed:
                    extra = await _run_completed_hook(on_completed, image_id, poll)
                    if extra:
                        fields.update(extra)
                update_row(image_id, fields)
            else:
                update_row(image_id, {"task_status": "failed"})
                logger.error(f"[生图] 生成失败 {image_id}: {poll.get('error')}")

        if submitted:
            await asyncio.gather(*(poll_one(iid, rid) for iid, rid in submitted))
        return submitted

    async def run_single(
        self,
        image_service,
        task: ImageTaskSpec,
        video_params: VideoParams,
        update_row: Callable[[str, dict], None],
        *,
        label: str = "",
        poll_timeout: int = 180,
        poll_interval: int = 5,
        interrupt: Optional[object] = None,
        pre_update: Optional[dict] = None,
        on_completed: Optional[Callable[[str, dict], Optional[dict]]] = None,
    ) -> dict:
        """单张同步生图：失败标 failed 并抛业务异常（label 拼错误前缀，如「素材图」）

        on_completed 返回 dict 时并入完成态回写（归档钩子改写 image_path/meta）。
        Returns: poll 结果（含 image_url）
        """
        if pre_update:
            update_row(task.image_id, pre_update)
        try:
            if interrupt is not None and getattr(interrupt, "is_set", lambda: False)():
                raise self.error("已取消", reason="cancelled")
            submit = await image_service.submit_image_task(task.prompt, video_params, task.reference_paths)
            if not submit.get("success"):
                update_row(task.image_id, {"task_status": "failed"})
                raise self.error(f"{label}提交失败: {submit.get('error')}")
            update_row(task.image_id, {"task_id": submit["request_id"], "task_status": "processing"})
            poll = await image_service.poll_i2i_task(
                submit["request_id"], timeout=poll_timeout, poll_interval=poll_interval,
            )
            if not poll.get("success"):
                update_row(task.image_id, {"task_status": "failed"})
                raise self.error(f"{label}生成失败: {poll.get('error')}")
        except WorkflowError:
            raise
        except Exception as e:  # noqa: BLE001
            update_row(task.image_id, {"task_status": "failed"})
            raise self.error(f"{label}生成异常: {e}")

        fields = {"image_path": poll.get("image_url", ""), "task_status": "completed"}
        if on_completed:
            extra = await _run_completed_hook(on_completed, task.image_id, poll)
            if extra:
                fields.update(extra)
        update_row(task.image_id, fields)
        return poll
