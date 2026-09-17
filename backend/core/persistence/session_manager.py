"""会话状态管理 - 持久化每个步骤的结果"""
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SessionManager:
    """会话状态管理器

    负责：
    1. 创建和管理会话
    2. 持久化每个步骤的结果
    3. 查询会话状态和步骤结果
    4. 支持从任意步骤继续执行
    """

    # 定义所有步骤（按顺序，7步流程）
    STEPS = [
        "submit_script_and_params",  # 1. 提交脚本和参数
        "optimize_script",           # 2. 优化脚本
        "generate_mindmap",          # 3. 生成思维导图
        "generate_material_images",  # 4. 生成素材图
        "generate_segment_scripts",  # 5. 生成分片脚本
        "generate_segment_frames",   # 6. 生成首尾帧
        "generate_videos",           # 7. 生成视频
    ]

    def __init__(self, db_path: str = "data/sessions.db"):
        """初始化会话管理器

        Args:
            db_path: SQLite数据库路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def _init_database(self):
        """初始化数据库表"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    current_step TEXT,
                    status TEXT DEFAULT 'active'
                )
            """)

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

            conn.commit()

    def create_session(self, session_id: str) -> dict:
        """创建新会话

        Args:
            session_id: 会话ID

        Returns:
            会话信息
        """
        now = datetime.now().isoformat()

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, created_at, updated_at, current_step, status) VALUES (?, ?, ?, ?, ?)",
                (session_id, now, now, self.STEPS[0], "active")
            )
            conn.commit()

        return {
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
            "current_step": self.STEPS[0],
            "status": "active"
        }

    def get_session(self, session_id: str) -> Optional[dict]:
        """获取会话信息

        Args:
            session_id: 会话ID

        Returns:
            会话信息，不存在则返回None
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()

            if not row:
                return None

            return dict(row)

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

        now = datetime.now().isoformat()
        # 在 result_data 中记录成功状态
        result_data_with_status = {**result_data, "_success": success}
        result_json = json.dumps(result_data_with_status, ensure_ascii=False)

        with sqlite3.connect(str(self.db_path)) as conn:
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

    def get_step_result(self, session_id: str, step_name: str) -> Optional[dict]:
        """获取步骤结果

        Args:
            session_id: 会话ID
            step_name: 步骤名称

        Returns:
            步骤结果，不存在则返回None
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM step_results WHERE session_id = ? AND step_name = ?",
                (session_id, step_name)
            )
            row = cursor.fetchone()

            if not row:
                return None

            result = dict(row)
            result['result_data'] = json.loads(result['result_data'])
            return result

    def get_all_step_results(self, session_id: str) -> dict:
        """获取所有步骤结果

        Args:
            session_id: 会话ID

        Returns:
            所有步骤的结果字典
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
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

    def get_completed_steps(self, session_id: str) -> list[str]:
        """获取已成功完成的步骤列表

        Args:
            session_id: 会话ID

        Returns:
            已成功完成的步骤名称列表（只包含 _success 为 True 的步骤）
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
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
                # 特殊处理：执行步骤6时，如果步骤5未完成，检查是否满足特殊模式的完成条件
                if step_name == "generate_videos" and prev_step == "generate_segment_frames":
                    if self._check_frames_completion_with_special_modes(session_id):
                        # 自动更新步骤5状态为完成
                        self.check_and_update_frames_step_status(session_id)
                        continue
                return False, f"前置步骤 {prev_step} 尚未完成"

        return True, "可以执行"

    def _check_frames_completion_with_special_modes(self, session_id: str) -> bool:
        """检查步骤5是否已完成（考虑特殊模式）

        支持的特殊模式：
        - 首帧+参考图模式 (first_frame_reference)：只需要首帧，不需要尾帧
        - 视频快照模式 (use_video_snapshot)：首帧在视频生成阶段获取，只需要尾帧

        Args:
            session_id: 会话ID

        Returns:
            是否所有分片的首尾帧都已配置完成
        """
        step_result = self.get_step_result(session_id, "generate_segment_frames")
        if not step_result:
            return False

        result_data = step_result['result_data']
        segment_frames = result_data.get('segment_frames', [])

        if not segment_frames:
            return False

        # 获取分片脚本数据
        segments_result = self.get_step_result(session_id, "generate_segment_scripts")
        segment_scripts = segments_result.get('result_data', {}).get('segment_scripts', []) if segments_result else []

        # 构建分片索引到模式的映射
        segment_modes = {}
        for seg in segment_scripts:
            idx = seg.get('index', -1)
            if idx >= 0:
                segment_modes[idx] = {
                    'first_frame_mode': seg.get('first_frame_mode', 'generate'),
                    'video_generation_mode': seg.get('video_generation_mode', 'first_last_frame')
                }

        # 检查所有帧是否都已配置完成
        for frame in segment_frames:
            segment_index = frame.get('segment_index', -1)
            first_path = frame.get('first_image_path', '')
            last_path = frame.get('last_image_path', '')

            # 获取该分片的模式
            modes = segment_modes.get(segment_index, {})
            first_frame_mode = modes.get('first_frame_mode', 'generate')
            video_generation_mode = modes.get('video_generation_mode', 'first_last_frame')

            # 判断该分片是否完成
            if video_generation_mode == 'first_frame_reference':
                # 首帧+参考图模式：只需要首帧
                # 但如果首帧模式是 use_video_snapshot，则首帧会在第6步获取，也认为配置完成
                if first_frame_mode == 'use_video_snapshot':
                    # 首帧将从视频快照获取，配置已完成
                    continue
                if not first_path:
                    return False
            elif first_frame_mode == 'use_video_snapshot':
                # 视频快照模式：首帧在视频生成阶段获取，只需要尾帧
                if not last_path:
                    return False
            else:
                # 普通模式：需要首尾帧都完成
                if not first_path or not last_path:
                    return False

        return True

    def update_session_status(self, session_id: str, status: str):
        """更新会话状态

        Args:
            session_id: 会话ID
            status: 状态 (active, completed, error)
        """
        now = datetime.now().isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
                (status, now, session_id)
            )
            conn.commit()

    def delete_step_result(self, session_id: str, step_name: str) -> bool:
        """删除指定步骤的结果

        Args:
            session_id: 会话ID
            step_name: 步骤名称

        Returns:
            是否成功
        """
        if step_name not in self.STEPS:
            return False

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute(
                    "DELETE FROM step_results WHERE session_id = ? AND step_name = ?",
                    (session_id, step_name)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"删除步骤结果失败: {e}")
            return False

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
            with sqlite3.connect(str(self.db_path)) as conn:
                # 删除这些步骤的结果
                placeholders = ','.join('?' * len(steps_to_clear))
                conn.execute(
                    f"DELETE FROM step_results WHERE session_id = ? AND step_name IN ({placeholders})",
                    (session_id, *steps_to_clear)
                )

                # 更新会话状态为 active（如果之前是 completed）
                conn.execute(
                    "UPDATE sessions SET status = 'active', updated_at = ? WHERE session_id = ?",
                    (datetime.now().isoformat(), session_id)
                )

                conn.commit()

            return True

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"清空后续步骤失败: {e}")
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
            with sqlite3.connect(str(self.db_path)) as conn:
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
            with sqlite3.connect(str(self.db_path)) as conn:
                # 更新 current_step 为该步骤（即重新执行该步骤）
                conn.execute(
                    "UPDATE sessions SET current_step = ?, updated_at = ? WHERE session_id = ?",
                    (step_name, datetime.now().isoformat(), session_id)
                )
                conn.commit()

            return True

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"重置当前步骤失败: {e}")
            return False

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

        now = datetime.now().isoformat()
        # 保留原有的 _success 状态
        existing_result = self.get_step_result(session_id, step_name)
        if existing_result:
            existing_data = existing_result.get('result_data', {})
            success = existing_data.get('_success', True)
        else:
            success = True

        result_data_with_status = {**result_data, "_success": success}
        result_json = json.dumps(result_data_with_status, ensure_ascii=False)

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
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
            import logging
            logging.getLogger(__name__).error(f"更新步骤结果失败: {e}")
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

    def get_latest_session(self) -> Optional[str]:
        """获取最近更新的活动会话ID

        Returns:
            会话ID，如果没有活动会话则返回None
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "SELECT session_id FROM sessions WHERE status = 'active' ORDER BY updated_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def list_sessions(self) -> list[dict]:
        """列出所有会话

        Returns:
            会话列表
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
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
            with sqlite3.connect(str(self.db_path)) as conn:
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
            import logging
            logging.getLogger(__name__).error(f"删除会话失败: {e}")
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
        import uuid as _uuid
        asset_id = str(_uuid.uuid4())
        now = datetime.now().isoformat()

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO session_assets (asset_id, session_id, asset_type, name, file_path, meta, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (asset_id, session_id, asset_type, name, file_path, json.dumps(meta or {}, ensure_ascii=False), now)
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
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
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
            rows = cursor.fetchall()
            results = []
            for row in rows:
                asset = dict(row)
                try:
                    asset['meta'] = json.loads(asset.get('meta') or '{}')
                except (ValueError, TypeError):
                    asset['meta'] = {}
                results.append(asset)
            return results

    def get_asset(self, asset_id: str) -> Optional[dict]:
        """获取单个资产

        Args:
            asset_id: 资产ID

        Returns:
            资产记录，不存在则返回 None
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM session_assets WHERE asset_id = ?",
                (asset_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            asset = dict(row)
            try:
                asset['meta'] = json.loads(asset.get('meta') or '{}')
            except (ValueError, TypeError):
                asset['meta'] = {}
            return asset

    def delete_asset(self, session_id: str, asset_id: str) -> bool:
        """删除会话资产记录（不删除磁盘文件）

        Args:
            session_id: 会话ID
            asset_id: 资产ID

        Returns:
            是否删除成功
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "DELETE FROM session_assets WHERE asset_id = ? AND session_id = ?",
                (asset_id, session_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    # ==================== 分片脚本编辑方法 ====================

    def update_segment_script(self, session_id: str, segment_index: int, segment_data: dict) -> bool:
        """更新单个分片脚本

        Args:
            session_id: 会话ID
            segment_index: 分片索引
            segment_data: 分片数据字典

        Returns:
            是否更新成功
        """
        step_result = self.get_step_result(session_id, "generate_segment_scripts")
        if not step_result:
            return False

        result_data = step_result['result_data']
        segment_scripts = result_data.get('segment_scripts', [])

        # 如果 segment_data 是 Pydantic 对象，转换为字典
        if hasattr(segment_data, 'model_dump'):
            segment_data = segment_data.model_dump()
        elif hasattr(segment_data, 'dict'):
            segment_data = segment_data.dict()

        # 查找并更新对应索引的分片
        updated = False
        for i, seg in enumerate(segment_scripts):
            if seg.get('index') == segment_index:
                # 保留索引，更新其他字段
                segment_data['index'] = segment_index
                segment_scripts[i] = segment_data
                updated = True
                break

        if not updated:
            return False

        # 保存更新后的数据
        result_data['segment_scripts'] = segment_scripts
        now = datetime.now().isoformat()
        result_json = json.dumps(result_data, ensure_ascii=False)

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                UPDATE step_results
                SET result_data = ?, completed_at = ?
                WHERE session_id = ? AND step_name = ?
            """, (result_json, now, session_id, "generate_segment_scripts"))
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id)
            )
            conn.commit()

        return True

    def delete_segment(self, session_id: str, segment_index: int) -> bool:
        """删除分片脚本（及其对应的首尾帧）

        Args:
            session_id: 会话ID
            segment_index: 分片索引

        Returns:
            是否删除成功
        """
        # 更新分片脚本
        step_result = self.get_step_result(session_id, "generate_segment_scripts")
        if not step_result:
            return False

        result_data = step_result['result_data']
        segment_scripts = result_data.get('segment_scripts', [])

        # 删除指定索引的分片
        new_scripts = [seg for seg in segment_scripts if seg.get('index') != segment_index]
        if len(new_scripts) == len(segment_scripts):
            return False  # 没有找到要删除的分片

        # 重新编号索引
        for i, seg in enumerate(new_scripts):
            seg['index'] = i

        result_data['segment_scripts'] = new_scripts
        result_data['segment_count'] = len(new_scripts)

        now = datetime.now().isoformat()
        result_json = json.dumps(result_data, ensure_ascii=False)

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                UPDATE step_results
                SET result_data = ?, completed_at = ?
                WHERE session_id = ? AND step_name = ?
            """, (result_json, now, session_id, "generate_segment_scripts"))

            # 同步删除对应的首尾帧
            frames_result = self.get_step_result(session_id, "generate_segment_frames")
            if frames_result:
                frames_data = frames_result['result_data']
                segment_frames = frames_data.get('segment_frames', [])
                new_frames = [f for f in segment_frames if f.get('segment_index') != segment_index]
                # 重新编号首尾帧索引
                for i, frame in enumerate(new_frames):
                    frame['segment_index'] = i
                frames_data['segment_frames'] = new_frames
                frames_data['frame_count'] = len(new_frames)
                frames_json = json.dumps(frames_data, ensure_ascii=False)
                conn.execute("""
                    UPDATE step_results
                    SET result_data = ?, completed_at = ?
                    WHERE session_id = ? AND step_name = ?
                """, (frames_json, now, session_id, "generate_segment_frames"))

            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id)
            )
            conn.commit()

        return True

    def add_segment(self, session_id: str, segment_data: dict, insert_after: int = -1) -> bool:
        """新增分片脚本

        修复：插入分片时不清空已有的首尾帧数据，而是智能调整帧数据索引

        Args:
            session_id: 会话ID
            segment_data: 分片数据字典
            insert_after: 插入位置（-1表示末尾，否则在指定索引之后插入）

        Returns:
            是否添加成功
        """
        step_result = self.get_step_result(session_id, "generate_segment_scripts")
        if not step_result:
            return False

        result_data = step_result['result_data']
        segment_scripts = result_data.get('segment_scripts', [])

        # 确定插入位置
        if insert_after < 0 or insert_after >= len(segment_scripts):
            insert_pos = len(segment_scripts)
        else:
            insert_pos = insert_after + 1

        # 设置新分片的索引
        segment_data['index'] = insert_pos

        # 插入新分片
        segment_scripts.insert(insert_pos, segment_data)

        # 重新编号索引
        for i, seg in enumerate(segment_scripts):
            seg['index'] = i

        result_data['segment_scripts'] = segment_scripts
        result_data['segment_count'] = len(segment_scripts)

        now = datetime.now().isoformat()
        result_json = json.dumps(result_data, ensure_ascii=False)

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                UPDATE step_results
                SET result_data = ?, completed_at = ?
                WHERE session_id = ? AND step_name = ?
            """, (result_json, now, session_id, "generate_segment_scripts"))
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id)
            )
            conn.commit()

        # 修复：不清空步骤5和步骤6，而是智能调整帧数据
        self._adjust_frames_after_insert(session_id, insert_pos)

        return True

    def _adjust_frames_after_insert(self, session_id: str, insert_pos: int) -> bool:
        """插入分片后调整帧数据

        保留已有的首尾帧数据，为新分片创建空的帧数据，调整后续分片的索引

        Args:
            session_id: 会话ID
            insert_pos: 新分片插入的位置

        Returns:
            是否成功
        """
        try:
            # 获取现有的帧数据
            frames_result = self.get_step_result(session_id, "generate_segment_frames")
            if not frames_result:
                # 没有帧数据，无需调整
                return True

            result_data = frames_result['result_data']
            segment_frames = result_data.get('segment_frames', [])

            if not segment_frames:
                return True

            # 为新分片创建空的帧数据
            new_frame = {
                "segment_index": insert_pos,
                "first_image_id": "",
                "first_image_path": "",
                "last_image_id": "",
                "last_image_path": "",
                "first_prompt": "",
                "last_prompt": "",
                "first_status": "waiting",
                "last_status": "waiting"
            }

            # 插入新的空帧数据
            segment_frames.insert(insert_pos, new_frame)

            # 调整后续帧的 segment_index
            for i, frame in enumerate(segment_frames):
                frame['segment_index'] = i

            # 更新数据库
            result_data['segment_frames'] = segment_frames
            now = datetime.now().isoformat()
            result_json = json.dumps(result_data, ensure_ascii=False)

            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("""
                    UPDATE step_results
                    SET result_data = ?, completed_at = ?
                    WHERE session_id = ? AND step_name = ?
                """, (result_json, now, session_id, "generate_segment_frames"))
                conn.commit()

            # 清空步骤6（视频数据），因为分片结构变化了
            self.clear_step_result(session_id, "generate_videos")

            logger.info(f"[插入分片] 已调整帧数据，新分片位置: {insert_pos}")
            return True

        except Exception as e:
            logger.error(f"[插入分片] 调整帧数据失败: {e}")
            return False

    def update_mindmap(self, session_id: str, mindmap_markdown: str) -> bool:
        """更新思维导图内容（人工修改，不推进 current_step）

        Args:
            session_id: 会话ID
            mindmap_markdown: 新的思维导图 markdown 文本

        Returns:
            是否更新成功
        """
        step_result = self.get_step_result(session_id, "generate_mindmap")
        if not step_result:
            return False

        result_data = step_result['result_data']
        result_data['mindmap'] = mindmap_markdown
        result_data['edited'] = True

        return self.update_step_result(session_id, "generate_mindmap", result_data)

    def update_material_image(self, session_id: str, image_index: int, update_data: dict) -> bool:
        """更新单个素材图信息

        Args:
            session_id: 会话ID
            image_index: 图片索引
            update_data: 要更新的字段字典（如 image_path, task_status, description 等）

        Returns:
            是否更新成功
        """
        step_result = self.get_step_result(session_id, "generate_material_images")
        if not step_result:
            return False

        result_data = step_result['result_data']
        material_images = result_data.get('material_images', [])

        if image_index < 0 or image_index >= len(material_images):
            return False

        # 更新指定索引的图片信息
        for key, value in update_data.items():
            material_images[image_index][key] = value

        # 保存更新后的数据
        now = datetime.now().isoformat()
        result_json = json.dumps(result_data, ensure_ascii=False)

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                UPDATE step_results
                SET result_data = ?, completed_at = ?
                WHERE session_id = ? AND step_name = ?
            """, (result_json, now, session_id, "generate_material_images"))
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id)
            )
            conn.commit()

        return True

    def _create_frame_data(
        self,
        segment_index: int,
        frame_type: str = None,
        image_path: str = None,
        image_id: str = None,
        prompt: str = None
    ) -> dict:
        """创建帧数据结构的辅助方法

        Args:
            segment_index: 分片索引
            frame_type: 帧类型 ("first" 或 "last")，可选
            image_path: 图片路径，可选
            image_id: 图片ID，可选
            prompt: 生成提示词，可选

        Returns:
            帧数据字典
        """
        frame = {
            'segment_index': segment_index,
            'first_image_path': None,
            'first_image_id': None,
            'first_prompt': None,
            'first_status': 'waiting',
            'last_image_path': None,
            'last_image_id': None,
            'last_prompt': None,
            'last_status': 'waiting',
        }

        # 如果有帧类型和路径，填充对应字段
        if frame_type and image_path:
            prefix = 'first' if frame_type == 'first' else 'last'
            frame[f'{prefix}_image_path'] = image_path
            frame[f'{prefix}_status'] = 'completed'
            if image_id:
                frame[f'{prefix}_image_id'] = image_id
            if prompt:
                frame[f'{prefix}_prompt'] = prompt

        return frame

    def _insert_frame_sorted(self, segment_frames: list, new_frame: dict) -> None:
        """按 segment_index 顺序插入帧数据

        Args:
            segment_frames: 现有帧列表
            new_frame: 要插入的新帧
        """
        segment_index = new_frame['segment_index']
        inserted = False

        for i, frame in enumerate(segment_frames):
            if frame.get('segment_index') > segment_index:
                segment_frames.insert(i, new_frame)
                inserted = True
                break

        if not inserted:
            segment_frames.append(new_frame)

    def update_segment_frame(
        self,
        session_id: str,
        segment_index: int,
        frame_type: str,
        image_path: str,
        image_id: str = None,
        prompt: str = None
    ) -> bool:
        """更新单个首/尾帧路径

        Args:
            session_id: 会话ID
            segment_index: 分片索引
            frame_type: 帧类型 ("first" 或 "last")
            image_path: 新的图片路径
            image_id: 新的图片ID（可选）
            prompt: 生成提示词（可选）

        Returns:
            是否更新成功
        """
        if frame_type not in ("first", "last"):
            return False

        step_result = self.get_step_result(session_id, "generate_segment_frames")

        # 如果步骤5不存在，需要先初始化
        if not step_result:
            segments_result = self.get_step_result(session_id, "generate_segment_scripts")
            if not segments_result:
                return False

            segment_scripts = segments_result['result_data'].get('segment_scripts', [])
            if not segment_scripts:
                return False

            # 使用辅助方法初始化帧数据结构
            segment_frames = [
                self._create_frame_data(seg.get('index', i))
                for i, seg in enumerate(segment_scripts)
            ]

            result_data = {
                'segment_frames': segment_frames,
                '_generating': False,
                '_cancelled': False,
            }

            self.save_step_result(session_id, "generate_segment_frames", result_data, success=False)
            step_result = self.get_step_result(session_id, "generate_segment_frames")

        result_data = step_result['result_data']
        segment_frames = result_data.get('segment_frames', [])

        # 查找并更新对应索引的帧
        updated = False
        for frame in segment_frames:
            if frame.get('segment_index') == segment_index:
                prefix = 'first' if frame_type == 'first' else 'last'
                frame[f'{prefix}_image_path'] = image_path
                frame[f'{prefix}_status'] = 'completed'
                if image_id:
                    frame[f'{prefix}_image_id'] = image_id
                if prompt:
                    frame[f'{prefix}_prompt'] = prompt
                updated = True
                break

        # 如果没找到对应的帧数据，添加新的帧数据
        if not updated:
            new_frame = self._create_frame_data(
                segment_index, frame_type, image_path, image_id, prompt
            )
            self._insert_frame_sorted(segment_frames, new_frame)

        # 保存更新后的数据
        now = datetime.now().isoformat()
        result_json = json.dumps(result_data, ensure_ascii=False)

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                UPDATE step_results
                SET result_data = ?, completed_at = ?
                WHERE session_id = ? AND step_name = ?
            """, (result_json, now, session_id, "generate_segment_frames"))
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id)
            )
            conn.commit()

        return True

        # 保存更新后的数据
        now = datetime.now().isoformat()
        result_json = json.dumps(result_data, ensure_ascii=False)

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                UPDATE step_results
                SET result_data = ?, completed_at = ?
                WHERE session_id = ? AND step_name = ?
            """, (result_json, now, session_id, "generate_segment_frames"))
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id)
            )
            conn.commit()

        return True

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

        now = datetime.now().isoformat()
        result_json = json.dumps(result_data, ensure_ascii=False)

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
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
            import logging
            logging.getLogger(__name__).error(f"设置取消标志失败: {e}")
            return False

    def is_step_cancelled(self, session_id: str, step_name: str) -> bool:
        """检查步骤是否已被取消

        Args:
            session_id: 会话ID
            step_name: 步骤名称

        Returns:
            是否已取消
        """
        step_result = self.get_step_result(session_id, step_name)
        if not step_result:
            return False
        return step_result.get('result_data', {}).get('_cancelled', False)

    def check_and_update_frames_step_status(self, session_id: str) -> bool:
        """检查所有首尾帧是否都已生成完成，如果是则更新步骤状态为成功

        在单独重新生成帧后调用此方法，检查是否所有帧都已成功生成。
        支持特殊模式：
        - 首帧+参考图模式 (first_frame_reference)：只需要首帧，不需要尾帧
        - 视频快照模式 (use_video_snapshot)：首帧在视频生成阶段获取，只需要尾帧

        如果所有帧都成功，则更新步骤的 _success 状态为 True，并将 current_step 前进到下一步。

        Args:
            session_id: 会话ID

        Returns:
            是否所有帧都已成功生成（并且步骤状态已更新）
        """
        step_result = self.get_step_result(session_id, "generate_segment_frames")
        if not step_result:
            return False

        result_data = step_result['result_data']
        segment_frames = result_data.get('segment_frames', [])

        if not segment_frames:
            return False

        # 获取分片脚本数据，用于判断每个分片的模式
        segments_result = self.get_step_result(session_id, "generate_segment_scripts")
        segment_scripts = segments_result.get('result_data', {}).get('segment_scripts', []) if segments_result else []

        # 构建分片索引到模式的映射
        segment_modes = {}
        for seg in segment_scripts:
            idx = seg.get('index', -1)
            if idx >= 0:
                segment_modes[idx] = {
                    'first_frame_mode': seg.get('first_frame_mode', 'generate'),
                    'video_generation_mode': seg.get('video_generation_mode', 'first_last_frame')
                }

        # 检查所有帧是否都已生成完成（考虑特殊模式）
        all_complete = True
        error_count = 0
        for frame in segment_frames:
            segment_index = frame.get('segment_index', -1)
            first_path = frame.get('first_image_path', '')
            last_path = frame.get('last_image_path', '')

            # 获取该分片的模式
            modes = segment_modes.get(segment_index, {})
            first_frame_mode = modes.get('first_frame_mode', 'generate')
            video_generation_mode = modes.get('video_generation_mode', 'first_last_frame')

            # 判断该分片是否完成
            segment_complete = False

            if video_generation_mode == 'first_frame_reference':
                # 首帧+参考图模式：只需要首帧
                # 但如果首帧模式是 use_video_snapshot，则首帧会在第6步获取，也认为配置完成
                if first_frame_mode == 'use_video_snapshot':
                    # 首帧将从视频快照获取，配置已完成
                    segment_complete = True
                else:
                    segment_complete = bool(first_path)
            elif first_frame_mode == 'use_video_snapshot':
                # 视频快照模式：首帧在视频生成阶段获取，只需要尾帧
                segment_complete = bool(last_path)
            else:
                # 普通模式（首尾帧模式）：需要首尾帧都完成
                segment_complete = bool(first_path) and bool(last_path)

            if not segment_complete:
                all_complete = False
                error_count += 1

        if not all_complete:
            return False

        # 所有帧都已成功生成，更新步骤状态
        # 更新 _success 字段和 error_count
        result_data['_success'] = True
        result_data['error_count'] = 0

        now = datetime.now().isoformat()
        result_json = json.dumps(result_data, ensure_ascii=False)

        with sqlite3.connect(str(self.db_path)) as conn:
            # 更新步骤结果
            conn.execute("""
                UPDATE step_results
                SET result_data = ?, completed_at = ?
                WHERE session_id = ? AND step_name = ?
            """, (result_json, now, session_id, "generate_segment_frames"))

            # 更新 current_step 到下一步
            next_step = self._get_next_step("generate_segment_frames")
            conn.execute(
                "UPDATE sessions SET current_step = ?, updated_at = ? WHERE session_id = ?",
                (next_step, now, session_id)
            )
            conn.commit()

        return True
