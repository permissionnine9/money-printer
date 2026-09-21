"""会话状态管理 - 持久化每个步骤的结果"""
import json
import logging
import uuid
from typing import Optional

from backend.core.persistence.base import BaseSQLiteManager, row_to_dict
from backend.core.utils.json_utils import dump_json

logger = logging.getLogger(__name__)


# 剧本创作工作流 4 步
SCRIPT_STEPS = [
    "story_ideation",     # 1. 故事构思（多轮对话盘问）
    "story_outline",      # 2. 故事大纲（markmap）
    "episode_design",     # 3. 分集设计（agent 工具增量落库）
    "lookbook_images",    # 4. 剧本核心素材（agent 出 prompt + 确定性生图）
]

# 视频生成工作流 4 步（重构后）
VIDEO_STEPS = [
    "select_episode",       # 1. 从剧本选集
    "storyboard_outline",   # 2. 分镜大纲（markmap + 分镜列表）
    "segment_management",   # 3. 分镜管理（分镜形式配置 + 提示词生成）
    "generate_videos",      # 4. 视频生成
]


class SessionManager(BaseSQLiteManager):
    """会话状态管理器

    负责：
    1. 创建和管理会话
    2. 持久化每个步骤的结果
    3. 查询会话状态和步骤结果
    4. 支持从任意步骤继续执行

    步骤序列由构造参数 steps 注入（SCRIPT_STEPS / VIDEO_STEPS）。
    """

    def __init__(self, db_path: str = "data/sessions.db", steps: list[str] | None = None):
        """初始化会话管理器

        Args:
            db_path: SQLite数据库路径
            steps: 本管理器管辖的步骤序列（默认视频工作流 5 步）
        """
        super().__init__(db_path)
        self.STEPS = list(steps) if steps else VIDEO_STEPS

    def _create_schema(self, conn):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                current_step TEXT,
                status TEXT DEFAULT 'active'
            )
        """)
        # 新列迁移：工作流类型与剧本溯源（已存在则忽略）
        self._add_columns_if_missing(conn, "sessions", {
            "workflow_type": "TEXT DEFAULT 'video'",
            "script_session_id": "TEXT DEFAULT NULL",
            "source_episode_id": "TEXT DEFAULT NULL",
            # 文件化工作区锚点：story 目录相对 workspace/ 的名字（如 剧名-1a2b3c4d）
            "workspace_path": "TEXT DEFAULT NULL",
        })

        conn.execute("""
            CREATE TABLE IF NOT EXISTS step_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                step_name TEXT NOT NULL,
                result_data TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id),
                UNIQUE(session_id, step_name)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_assets (
                asset_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                meta TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)

    def create_session(
        self,
        session_id: str,
        workflow_type: str = "video",
        script_session_id: str | None = None,
        source_episode_id: str | None = None,
    ) -> dict:
        """创建新会话

        Args:
            session_id: 会话ID
            workflow_type: 工作流类型（'video' | 'script'）
            script_session_id: 视频会话指向的剧本会话ID
            source_episode_id: 视频会话指向的剧本分集ID

        Returns:
            会话信息
        """
        now = self._now()

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, created_at, updated_at, current_step, status, workflow_type, script_session_id, source_episode_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, now, now, self.STEPS[0], "active", workflow_type, script_session_id, source_episode_id)
            )
            conn.commit()

        return {
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
            "current_step": self.STEPS[0],
            "status": "active",
            "workflow_type": workflow_type,
            "script_session_id": script_session_id,
            "source_episode_id": source_episode_id,
        }

    def get_session(self, session_id: str) -> Optional[dict]:
        """获取会话信息

        Args:
            session_id: 会话ID

        Returns:
            会话信息，不存在则返回None
        """
        row = self._fetch_one("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        return dict(row) if row else None

    def save_step_result(self, session_id: str, step_name: str, result_data: dict, success: bool = True) -> bool:
        """保存步骤结果

        Args:
            session_id: 会话ID
            step_name: 步骤名称
            result_data: 步骤结果数据
            success: 步骤是否成功完成（只有成功时才更新 current_step 到下一步）

        Returns:
            是否保存成功
        """
        if step_name not in self.STEPS:
            raise ValueError(f"Invalid step name: {step_name}")

        now = self._now()
        # 在 result_data 中记录成功状态
        result_data_with_status = {**result_data, "_success": success}
        result_json = dump_json(result_data_with_status)

        with self._connect() as conn:
            # 保存或更新步骤结果
            conn.execute("""
                INSERT INTO step_results (session_id, step_name, result_data, completed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id, step_name)
                DO UPDATE SET result_data = ?, completed_at = ?
            """, (session_id, step_name, result_json, now, result_json, now))

            # 只有成功时才更新会话的当前步骤到下一步
            if success:
                next_step = self._get_next_step(step_name)
                conn.execute(
                    "UPDATE sessions SET current_step = ?, updated_at = ? WHERE session_id = ?",
                    (next_step, now, session_id)
                )
            else:
                # 失败时只更新时间，current_step 保持不变
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                    (now, session_id)
                )

            conn.commit()

        return True

    def save_aux_state(self, session_id: str, key: str, result_data: dict) -> bool:
        """保存辅助状态（如 comfyui_import 导入暂存）

        与 save_step_result 共用 step_results 表，但不校验步骤名、
        不推进 current_step（辅助状态不属于步骤状态机）。
        读取直接用 get_step_result(session_id, key)。
        """
        now = self._now()
        result_json = dump_json(result_data)
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO step_results (session_id, step_name, result_data, completed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id, step_name)
                DO UPDATE SET result_data = ?, completed_at = ?
            """, (session_id, key, result_json, now, result_json, now))
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id)
            )
            conn.commit()
        return True

    def get_step_result(self, session_id: str, step_name: str) -> Optional[dict]:
        """获取步骤结果

        Args:
            session_id: 会话ID
            step_name: 步骤名称

        Returns:
            步骤结果，不存在则返回None
        """
        row = self._fetch_one(
            "SELECT * FROM step_results WHERE session_id = ? AND step_name = ?",
            (session_id, step_name)
        )
        if not row:
            return None

        result = dict(row)
        result['result_data'] = json.loads(result['result_data'])
        return result

    def get_script_title(self, session_id: str) -> str:
        """提取剧本会话展示名（story_outline 大纲根节点 `# 剧名`），未生成大纲返回空串"""
        step = self.get_step_result(session_id, "story_outline")
        if not step:
            return ""
        mindmap = (step.get("result_data") or {}).get("mindmap") or ""
        for line in mindmap.splitlines():
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
        return ""

    def get_all_step_results(self, session_id: str) -> dict:
        """获取所有步骤结果

        Args:
            session_id: 会话ID

        Returns:
            所有步骤的结果字典
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM step_results WHERE session_id = ? ORDER BY id",
                (session_id,)
            )
            rows = cursor.fetchall()

            results = {}
            for row in rows:
                step_name = row['step_name']
                results[step_name] = json.loads(row['result_data'])

            return results

    def list_all_step_results(self) -> list[dict]:
        """全表步骤结果（跨会话）：[{session_id, step_name, result_data(JSON 字符串)}]

        供素材管理扫描视频引用（video_path 只存在于各会话的 result_data JSON 中）。
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT session_id, step_name, result_data FROM step_results ORDER BY id"
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_step_results_map(self, session_id: str) -> dict:
        """按本管理器步骤序列收集步骤结果（无结果的步骤不包含）"""
        results = {}
        for step_name in self.STEPS:
            result = self.get_step_result(session_id, step_name)
            if result:
                results[step_name] = result
        return results

    def get_completed_steps(self, session_id: str) -> list[str]:
        """获取已成功完成的步骤列表

        Args:
            session_id: 会话ID

        Returns:
            已成功完成的步骤名称列表（只包含 _success 为 True 的步骤）
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT step_name, result_data FROM step_results WHERE session_id = ? ORDER BY id",
                (session_id,)
            )
            rows = cursor.fetchall()

            completed = []
            for row in rows:
                result_data = json.loads(row['result_data'])
                # 检查 _success 标志，默认认为旧数据是成功的
                if result_data.get('_success', True):
                    completed.append(row['step_name'])
            return completed

    def is_step_completed(self, session_id: str, step_name: str) -> bool:
        """检查步骤是否已成功完成

        Args:
            session_id: 会话ID
            step_name: 步骤名称

        Returns:
            是否已成功完成（记录存在且 _success 为 True）
        """
        result = self.get_step_result(session_id, step_name)
        if result is None:
            return False
        # 检查 _success 标志，默认认为旧数据是成功的
        return result.get('result_data', {}).get('_success', True)

    def can_execute_step(self, session_id: str, step_name: str) -> tuple[bool, str]:
        """检查是否可以执行某个步骤

        Args:
            session_id: 会话ID
            step_name: 步骤名称

        Returns:
            (是否可以执行, 原因说明)
        """
        if step_name not in self.STEPS:
            return False, f"无效的步骤名称: {step_name}"

        step_index = self.STEPS.index(step_name)

        # 检查前置步骤是否都已完成
        for i in range(step_index):
            prev_step = self.STEPS[i]
            if not self.is_step_completed(session_id, prev_step):
                return False, f"前置步骤 {prev_step} 尚未完成"

        return True, "可以执行"

    def update_session_status(self, session_id: str, status: str):
        """更新会话状态

        Args:
            session_id: 会话ID
            status: 状态 (active, completed, error)
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
                (status, self._now(), session_id)
            )
            conn.commit()

    def set_workspace_path(self, session_id: str, workspace_path: str | None) -> bool:
        """回写剧本会话的工作区锚点（story 目录相对 workspace/ 的名字；纯锚点不影响 updated_at）"""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET workspace_path = ? WHERE session_id = ?",
                (workspace_path, session_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def clear_steps_after(self, session_id: str, step_name: str) -> bool:
        """清空指定步骤之后的所有步骤结果

        用于重新生成某个步骤时，确保后续依赖该步骤的步骤数据被清空。

        Args:
            session_id: 会话ID
            step_name: 步骤名称（该步骤不会被清空，只清空它之后的步骤）

        Returns:
            是否成功
        """
        if step_name not in self.STEPS:
            return False

        # 找到该步骤的索引
        step_index = self.STEPS.index(step_name)

        # 获取需要清空的步骤列表（该步骤之后的所有步骤）
        steps_to_clear = self.STEPS[step_index + 1:]

        if not steps_to_clear:
            # 没有后续步骤，无需清空
            return True

        try:
            with self._connect() as conn:
                # 删除这些步骤的结果
                placeholders = ','.join('?' * len(steps_to_clear))
                conn.execute(
                    f"DELETE FROM step_results WHERE session_id = ? AND step_name IN ({placeholders})",
                    (session_id, *steps_to_clear)
                )

                # 更新会话状态为 active（如果之前是 completed）
                conn.execute(
                    "UPDATE sessions SET status = 'active', updated_at = ? WHERE session_id = ?",
                    (self._now(), session_id)
                )

                conn.commit()

            return True

        except Exception as e:
            logger.error(f"清空后续步骤失败: {e}")
            return False

    def clear_step_result(self, session_id: str, step_name: str) -> bool:
        """清空指定步骤的结果

        Args:
            session_id: 会话ID
            step_name: 步骤名称

        Returns:
            是否成功
        """
        try:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM step_results WHERE session_id = ? AND step_name = ?",
                    (session_id, step_name)
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"清空步骤 {step_name} 失败: {e}")
            return False

    def reset_current_step(self, session_id: str, step_name: str) -> bool:
        """重置当前步骤到指定步骤

        用于重新编辑某个步骤时，将 current_step 重置为该步骤，
        使用户可以重新执行该步骤。

        Args:
            session_id: 会话ID
            step_name: 目标步骤名称

        Returns:
            是否成功
        """
        if step_name not in self.STEPS:
            return False

        try:
            with self._connect() as conn:
                # 更新 current_step 为该步骤（即重新执行该步骤）
                conn.execute(
                    "UPDATE sessions SET current_step = ?, updated_at = ? WHERE session_id = ?",
                    (step_name, self._now(), session_id)
                )
                conn.commit()

            return True

        except Exception as e:
            logger.error(f"重置当前步骤失败: {e}")
            return False

    def rollback_completion(self, session_id: str, step_name: str) -> None:
        """回退某步骤的完成态：清该步骤结果 + 清下游步骤 + current_step 重置到该步骤

        用于「上游数据变化导致完成态失效」的场景（配置变化需重新确认）。
        """
        self.clear_step_result(session_id, step_name)
        self.clear_steps_after(session_id, step_name)
        self.reset_current_step(session_id, step_name)

    def update_step_result(self, session_id: str, step_name: str, result_data: dict) -> bool:
        """更新指定步骤的结果数据（不推进 current_step）

        用于重新编辑某个步骤时，更新该步骤的结果数据，
        但不会推进 current_step。

        Args:
            session_id: 会话ID
            step_name: 步骤名称
            result_data: 新的结果数据

        Returns:
            是否成功
        """
        if step_name not in self.STEPS:
            return False

        now = self._now()
        # 保留原有的 _success 状态
        existing_result = self.get_step_result(session_id, step_name)
        if existing_result:
            existing_data = existing_result.get('result_data', {})
            success = existing_data.get('_success', True)
        else:
            success = True

        result_data_with_status = {**result_data, "_success": success}
        result_json = dump_json(result_data_with_status)

        try:
            with self._connect() as conn:
                conn.execute("""
                    INSERT INTO step_results (session_id, step_name, result_data, completed_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(session_id, step_name)
                    DO UPDATE SET result_data = ?, completed_at = ?
                """, (session_id, step_name, result_json, now, result_json, now))

                # 只更新时间，不改变 current_step
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                    (now, session_id)
                )
                conn.commit()

            return True

        except Exception as e:
            logger.error(f"更新步骤结果失败: {e}")
            return False

    def _get_next_step(self, current_step: str) -> Optional[str]:
        """获取下一个步骤

        Args:
            current_step: 当前步骤名称

        Returns:
            下一个步骤名称，如果是最后一步则返回None
        """
        if current_step not in self.STEPS:
            return None

        index = self.STEPS.index(current_step)
        if index + 1 < len(self.STEPS):
            return self.STEPS[index + 1]
        return None

    def get_session_summary(self, session_id: str) -> dict:
        """获取会话摘要

        Args:
            session_id: 会话ID

        Returns:
            会话摘要信息
        """
        session = self.get_session(session_id)
        if not session:
            return {"error": "会话不存在"}

        completed_steps = self.get_completed_steps(session_id)
        all_results = self.get_all_step_results(session_id)

        return {
            "session_id": session_id,
            "status": session['status'],
            "current_step": session['current_step'],
            "created_at": session['created_at'],
            "updated_at": session['updated_at'],
            "completed_steps": completed_steps,
            "total_steps": len(self.STEPS),
            "progress": f"{len(completed_steps)}/{len(self.STEPS)}",
            "step_results": all_results
        }

    def list_sessions(self, workflow_type: str | None = None) -> list[dict]:
        """列出所有会话（可按工作流类型过滤）

        Args:
            workflow_type: 'video' | 'script'，None 为全部

        Returns:
            会话列表
        """
        with self._connect() as conn:
            if workflow_type:
                cursor = conn.execute(
                    "SELECT * FROM sessions WHERE workflow_type = ? ORDER BY updated_at DESC",
                    (workflow_type,)
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM sessions ORDER BY updated_at DESC"
                )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def delete_session(self, session_id: str) -> bool:
        """删除会话

        Args:
            session_id: 会话ID

        Returns:
            是否删除成功
        """
        try:
            with self._connect() as conn:
                # 先删除步骤结果
                conn.execute(
                    "DELETE FROM step_results WHERE session_id = ?",
                    (session_id,)
                )
                # 删除会话资产记录
                conn.execute(
                    "DELETE FROM session_assets WHERE session_id = ?",
                    (session_id,)
                )
                # 再删除会话
                conn.execute(
                    "DELETE FROM sessions WHERE session_id = ?",
                    (session_id,)
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"删除会话失败: {e}")
            return False

    # ==================== 会话资产管理（音频/图片素材） ====================

    def add_asset(self, session_id: str, asset_type: str, name: str, file_path: str, meta: dict | None = None) -> dict:
        """添加会话资产（音频/图片素材）

        Args:
            session_id: 会话ID
            asset_type: 资产类型 ('audio' 或 'image')
            name: 资产显示名称（通常是原始文件名）
            file_path: 文件相对路径
            meta: 附加信息（如文件大小、时长等）

        Returns:
            新资产记录
        """
        asset_id = str(uuid.uuid4())
        now = self._now()

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO session_assets (asset_id, session_id, asset_type, name, file_path, meta, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (asset_id, session_id, asset_type, name, file_path, dump_json(meta or {}), now)
            )
            conn.commit()

        return {
            "asset_id": asset_id,
            "session_id": session_id,
            "asset_type": asset_type,
            "name": name,
            "file_path": file_path,
            "meta": meta or {},
            "created_at": now,
        }

    def list_assets(self, session_id: str, asset_type: str | None = None) -> list[dict]:
        """列出会话资产

        Args:
            session_id: 会话ID
            asset_type: 可选类型过滤 ('audio' 或 'image')

        Returns:
            资产列表（按创建时间倒序）
        """
        with self._connect() as conn:
            if asset_type:
                cursor = conn.execute(
                    "SELECT * FROM session_assets WHERE session_id = ? AND asset_type = ? ORDER BY created_at DESC",
                    (session_id, asset_type)
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM session_assets WHERE session_id = ? ORDER BY created_at DESC",
                    (session_id,)
                )
            return [row_to_dict(row, {"meta": {}}) for row in cursor.fetchall()]

    def get_asset(self, asset_id: str) -> Optional[dict]:
        """获取单个资产

        Args:
            asset_id: 资产ID

        Returns:
            资产记录，不存在则返回 None
        """
        row = self._fetch_one("SELECT * FROM session_assets WHERE asset_id = ?", (asset_id,))
        return row_to_dict(row, {"meta": {}}) if row else None

    def delete_asset(self, session_id: str, asset_id: str) -> bool:
        """删除会话资产记录（不删除磁盘文件）

        Args:
            session_id: 会话ID
            asset_id: 资产ID

        Returns:
            是否删除成功
        """
        return self._delete(
            "DELETE FROM session_assets WHERE asset_id = ? AND session_id = ?",
            (asset_id, session_id)
        )

    def set_step_cancelled(self, session_id: str, step_name: str, cancelled: bool = True) -> bool:
        """设置步骤的取消标志

        Args:
            session_id: 会话ID
            step_name: 步骤名称
            cancelled: 是否取消

        Returns:
            是否设置成功
        """
        step_result = self.get_step_result(session_id, step_name)
        if not step_result:
            return False

        result_data = step_result['result_data']
        result_data['_cancelled'] = cancelled

        now = self._now()
        result_json = dump_json(result_data)

        try:
            with self._connect() as conn:
                conn.execute("""
                    UPDATE step_results
                    SET result_data = ?, completed_at = ?
                    WHERE session_id = ? AND step_name = ?
                """, (result_json, now, session_id, step_name))
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                    (now, session_id)
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"设置取消标志失败: {e}")
            return False

