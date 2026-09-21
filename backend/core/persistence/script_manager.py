"""剧本数据管理 - 定妆照 / 分集素材图任务表（DB 侧状态机）

markdown 类产物（故事逻辑/大纲/分集设计/实体卡/分镜）已文件化到 workspace/
（权威源见 workspace_store.py）；本管理器只保留生图任务状态机两张表：
- lookbook_images:        剧本定妆照（agent 出 prompt + 确定性生图的状态机）
- episode_material_images: 分集素材图（视频工作流分镜参考图生成的状态机）

（episodes / script_entities 两张影子表已退役：不再建 DDL、不再读写，
仅由 migrate_db_to_workspace.py 在旧库中维护用于迁移对账。）
"""
import logging
import sqlite3
import uuid
from typing import Optional

from backend.core.persistence.base import BaseSQLiteManager, row_to_dict
from backend.core.utils.json_utils import dump_json

logger = logging.getLogger(__name__)


class ScriptManager(BaseSQLiteManager):
    """剧本数据管理器（定妆照 / 分集素材图任务状态机）"""

    def _create_schema(self, conn):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lookbook_images (
                image_id TEXT PRIMARY KEY,
                script_session_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                prompt TEXT DEFAULT '',
                description TEXT DEFAULT '',
                image_path TEXT DEFAULT '',
                task_id TEXT DEFAULT '',
                task_status TEXT DEFAULT 'pending',
                meta TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS episode_material_images (
                image_id TEXT PRIMARY KEY,
                script_session_id TEXT NOT NULL,
                episode_id TEXT NOT NULL,
                title TEXT DEFAULT '',
                description TEXT DEFAULT '',
                image_path TEXT DEFAULT '',
                prompt TEXT DEFAULT '',
                task_id TEXT DEFAULT '',
                task_status TEXT DEFAULT 'pending',
                meta TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

    # ==================== 定妆照 ====================

    def insert_lookbook(
        self,
        script_session_id: str,
        entity_id: str,
        prompt: str,
        description: str = "",
        task_status: str = "pending",
        image_path: str = "",
        meta: Optional[dict] = None,
    ) -> dict:
        image_id = f"lb_{uuid.uuid4().hex[:10]}"
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO lookbook_images (image_id, script_session_id, entity_id, prompt, description, task_status, image_path, meta, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (image_id, script_session_id, entity_id, prompt, description, task_status, image_path, dump_json(meta or {}), now, now),
            )
            conn.commit()
        return self.get_lookbook(image_id)

    def update_lookbook(self, image_id: str, fields: dict) -> Optional[dict]:
        allowed = {"prompt", "description", "image_path", "task_id", "task_status", "meta"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_lookbook(image_id)
        if "meta" in updates:
            updates["meta"] = dump_json(updates["meta"])
        sets = ", ".join(f"{k} = ?" for k in updates)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE lookbook_images SET {sets}, updated_at = ? WHERE image_id = ?",
                (*updates.values(), self._now(), image_id),
            )
            conn.commit()
        return self.get_lookbook(image_id)

    def get_lookbook(self, image_id: str) -> Optional[dict]:
        row = self._fetch_one("SELECT * FROM lookbook_images WHERE image_id = ?", (image_id,))
        return self._lookbook_to_dict(row) if row else None

    def list_lookbook(
        self,
        script_session_id: str,
        entity_id: Optional[str] = None,
        task_status: Optional[str] = None,
    ) -> list[dict]:
        query = "SELECT * FROM lookbook_images WHERE script_session_id = ?"
        params: list = [script_session_id]
        if entity_id:
            query += " AND entity_id = ?"
            params.append(entity_id)
        if task_status:
            query += " AND task_status = ?"
            params.append(task_status)
        query += " ORDER BY created_at ASC"
        with self._connect() as conn:
            cursor = conn.execute(query, params)
            return [self._lookbook_to_dict(row) for row in cursor.fetchall()]

    def delete_lookbook(self, script_session_id: str, image_id: str) -> bool:
        return self._delete(
            "DELETE FROM lookbook_images WHERE image_id = ? AND script_session_id = ?",
            (image_id, script_session_id),
        )

    def list_completed_lookbooks(self) -> list[dict]:
        """素材库：全部剧本会话已完成且有图的定妆照（跨会话，新 → 旧）"""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM lookbook_images "
                "WHERE task_status = 'completed' AND IFNULL(image_path, '') != '' "
                "ORDER BY created_at DESC"
            )
            return [self._lookbook_to_dict(row) for row in cursor.fetchall()]

    def list_completed_episode_materials(self) -> list[dict]:
        """素材管理：全部剧本会话已完成且有图的分集素材图（跨会话，新 → 旧）"""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM episode_material_images "
                "WHERE task_status = 'completed' AND IFNULL(image_path, '') != '' "
                "ORDER BY created_at DESC"
            )
            return [row_to_dict(row, {"meta": {}}) for row in cursor.fetchall()]

    @staticmethod
    def _lookbook_to_dict(row: sqlite3.Row) -> dict:
        return row_to_dict(row, {"meta": {}})

    # ==================== 分集素材图 ====================

    def insert_episode_material(
        self,
        script_session_id: str,
        episode_id: str,
        title: str = "",
        description: str = "",
        prompt: str = "",
        task_status: str = "pending",
        meta: Optional[dict] = None,
    ) -> dict:
        """登记一张分集素材图（pending 状态，生成完成后 update 回写路径）"""
        image_id = f"mat_{uuid.uuid4().hex[:10]}"
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO episode_material_images (image_id, script_session_id, episode_id, title, description, prompt, task_status, meta, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (image_id, script_session_id, episode_id, title, description, prompt, task_status, dump_json(meta or {}), now, now),
            )
            conn.commit()
        return self.get_episode_material(image_id)

    def update_episode_material(self, image_id: str, fields: dict) -> Optional[dict]:
        """部分字段更新（title/description/image_path/prompt/task_id/task_status/meta）"""
        allowed = {"title", "description", "image_path", "prompt", "task_id", "task_status", "meta"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_episode_material(image_id)
        if "meta" in updates:
            updates["meta"] = dump_json(updates["meta"])
        sets = ", ".join(f"{k} = ?" for k in updates)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE episode_material_images SET {sets}, updated_at = ? WHERE image_id = ?",
                (*updates.values(), self._now(), image_id),
            )
            conn.commit()
        return self.get_episode_material(image_id)

    def get_episode_material(self, image_id: str) -> Optional[dict]:
        row = self._fetch_one("SELECT * FROM episode_material_images WHERE image_id = ?", (image_id,))
        return row_to_dict(row, {"meta": {}}) if row else None

    def list_episode_materials(
        self,
        script_session_id: str,
        episode_id: Optional[str] = None,
        task_status: Optional[str] = None,
    ) -> list[dict]:
        """列出分集素材图（story 隔离：仅查本 script_session_id；episode_id 仅用于过滤）"""
        query = "SELECT * FROM episode_material_images WHERE script_session_id = ?"
        params: list = [script_session_id]
        if episode_id:
            query += " AND episode_id = ?"
            params.append(episode_id)
        if task_status:
            query += " AND task_status = ?"
            params.append(task_status)
        query += " ORDER BY created_at ASC"
        with self._connect() as conn:
            cursor = conn.execute(query, params)
            return [row_to_dict(row, {"meta": {}}) for row in cursor.fetchall()]

    def delete_episode_material(self, script_session_id: str, image_id: str) -> bool:
        return self._delete(
            "DELETE FROM episode_material_images WHERE image_id = ? AND script_session_id = ?",
            (image_id, script_session_id),
        )

    # ==================== 级联清理 ====================

    def delete_script_data(self, script_session_id: str, keep_completed_lookbooks: bool = False) -> dict:
        """清空剧本会话的全部分集/实体/定妆照/分集素材图（大纲重生成时清下游）

        keep_completed_lookbooks=True 时保留已完成且有图的定妆照行（作为历史素材，
        供第 4 步素材库复用）；未完成/失败行仍删除（避免前端死轮询）。
        分集素材图两种模式都全删（与集号强绑定，保留只会污染素材池）。
        """
        with self._connect() as conn:
            lookbooks = conn.execute("SELECT COUNT(*) FROM lookbook_images WHERE script_session_id = ?", (script_session_id,)).fetchone()[0]
            materials = conn.execute("SELECT COUNT(*) FROM episode_material_images WHERE script_session_id = ?", (script_session_id,)).fetchone()[0]
            if keep_completed_lookbooks:
                deleted = conn.execute(
                    "DELETE FROM lookbook_images WHERE script_session_id = ? "
                    "AND NOT (task_status = 'completed' AND IFNULL(image_path, '') != '')",
                    (script_session_id,),
                ).rowcount
                kept = lookbooks - deleted
            else:
                conn.execute("DELETE FROM lookbook_images WHERE script_session_id = ?", (script_session_id,))
                kept = 0
            conn.execute("DELETE FROM episode_material_images WHERE script_session_id = ?", (script_session_id,))
            conn.commit()
        counts = {"lookbook_images": lookbooks, "lookbook_images_kept": kept, "episode_material_images": materials}
        logger.info(f"[剧本] 清理下游数据 {script_session_id[:8]}...: {counts}")
        return counts
