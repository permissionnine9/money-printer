"""剧本数据管理 - 全局实体注册表 / 分集设计 / 定妆照 / 分集素材图

同一 data/sessions.db 中的四张表：
- script_entities:        全局实体注册表（character/scene/clue/foreshadow，ID 由后端分配）
- episodes:               分集设计（矛盾链/因果链/结尾摘要 + 实体引用）
- lookbook_images:        剧本定妆照（agent 出 prompt + 确定性生图的状态机）
- episode_material_images: 分集素材图（视频工作流分镜参考图生成的状态机）

ID 规则：只由后端分配（next_entity_id: SELECT MAX+1）：
- character → chr_001, scene → scn_001, clue → clu_001, foreshadow → fs_001
- episode   → ep_01（由调用方按集数传入）
"""
import logging
import sqlite3
import uuid
from typing import Optional

from backend.core.persistence.base import BaseSQLiteManager, row_to_dict
from backend.core.utils.json_utils import dump_json

logger = logging.getLogger(__name__)

ENTITY_TYPES = ("character", "scene", "clue", "foreshadow")
ENTITY_ID_PREFIXES = {
    "character": "chr",
    "scene": "scn",
    "clue": "clu",
    "foreshadow": "fs",
}


class ScriptManager(BaseSQLiteManager):
    """剧本数据管理器（实体 / 分集 / 定妆照）"""

    def _create_schema(self, conn):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS script_entities (
                entity_id TEXT PRIMARY KEY,
                script_session_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                meta TEXT DEFAULT '{}',
                lookbook_image_id TEXT DEFAULT '',
                lookbook_image_path TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                episode_id TEXT NOT NULL,
                script_session_id TEXT NOT NULL,
                title TEXT DEFAULT '',
                logline TEXT DEFAULT '',
                conflict_chain TEXT DEFAULT '',
                causality_chain TEXT DEFAULT '',
                ending_summary TEXT DEFAULT '',
                story_progress TEXT DEFAULT '',
                character_ids TEXT DEFAULT '[]',
                scene_ids TEXT DEFAULT '[]',
                clue_refs TEXT DEFAULT '[]',
                foreshadow_refs TEXT DEFAULT '[]',
                meta TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(script_session_id, episode_id)
            )
        """)
        # 旧表迁移：增加 story_progress 列（已存在则忽略）
        self._add_columns_if_missing(conn, "episodes", {"story_progress": "TEXT NOT NULL DEFAULT ''"})
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

    # ==================== 实体注册表 ====================

    def next_entity_id(self, script_session_id: str, entity_type: str) -> str:
        """分配下一个实体 ID（chr_001 / scn_001 / clu_001 / fs_001 ...）

        entity_id 是全局主键，因此按全局该类型的 MAX+1 分配（跨会话不撞号）。
        """
        prefix = ENTITY_ID_PREFIXES[entity_type]
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT entity_id FROM script_entities WHERE entity_type = ?",
                (entity_type,),
            )
            max_num = 0
            for (entity_id,) in cursor.fetchall():
                try:
                    num = int(entity_id.rsplit("_", 1)[-1])
                    max_num = max(max_num, num)
                except ValueError:
                    continue
            return f"{prefix}_{max_num + 1:03d}"

    def upsert_entity(
        self,
        script_session_id: str,
        entity_type: str,
        name: str,
        description: str = "",
        meta: Optional[dict] = None,
        entity_id: Optional[str] = None,
    ) -> dict:
        """新增或更新实体；entity_id 为空时分配新 ID"""
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"entity_type 仅支持 {ENTITY_TYPES}")
        now = self._now()
        if entity_id:
            with self._connect() as conn:
                cursor = conn.execute(
                    """UPDATE script_entities
                       SET name = ?, description = ?, meta = ?, updated_at = ?
                       WHERE entity_id = ? AND script_session_id = ?""",
                    (name, description, dump_json(meta or {}), now, entity_id, script_session_id),
                )
                conn.commit()
                if cursor.rowcount == 0:
                    raise ValueError(f"实体不存在: {entity_id}")
            return self.get_entity(entity_id)

        entity_id = self.next_entity_id(script_session_id, entity_type)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO script_entities (entity_id, script_session_id, entity_type, name, description, meta, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (entity_id, script_session_id, entity_type, name, description, dump_json(meta or {}), now, now),
            )
            conn.commit()
        return self.get_entity(entity_id)

    def get_entity(self, entity_id: str) -> Optional[dict]:
        row = self._fetch_one("SELECT * FROM script_entities WHERE entity_id = ?", (entity_id,))
        return row_to_dict(row, {"meta": {}}) if row else None

    def list_entities(self, script_session_id: str, entity_type: Optional[str] = None) -> list[dict]:
        with self._connect() as conn:
            if entity_type:
                cursor = conn.execute(
                    "SELECT * FROM script_entities WHERE script_session_id = ? AND entity_type = ? ORDER BY entity_id ASC",
                    (script_session_id, entity_type),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM script_entities WHERE script_session_id = ? ORDER BY entity_type ASC, entity_id ASC",
                    (script_session_id,),
                )
            return [row_to_dict(row, {"meta": {}}) for row in cursor.fetchall()]

    def delete_entity(self, script_session_id: str, entity_id: str) -> bool:
        """删除实体（调用方需先校验分集反向引用）"""
        return self._delete(
            "DELETE FROM script_entities WHERE entity_id = ? AND script_session_id = ?",
            (entity_id, script_session_id),
        )

    def set_entity_lookbook(self, entity_id: str, image_id: str, image_path: str) -> bool:
        """回写实体的定妆照引用"""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE script_entities SET lookbook_image_id = ?, lookbook_image_path = ?, updated_at = ? WHERE entity_id = ?",
                (image_id, image_path, self._now(), entity_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # ==================== 分集设计 ====================

    def upsert_episode(self, script_session_id: str, episode: dict) -> dict:
        """插入或覆写一集（episode_id 必填，如 ep_01；单集重设计时 episode_id 不变）"""
        episode_id = episode.get("episode_id", "")
        if not episode_id:
            raise ValueError("episode_id 不能为空")
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO episodes (
                       episode_id, script_session_id, title, logline,
                       conflict_chain, causality_chain, ending_summary, story_progress,
                       character_ids, scene_ids, clue_refs, foreshadow_refs, meta,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(script_session_id, episode_id) DO UPDATE SET
                       title = excluded.title,
                       logline = excluded.logline,
                       conflict_chain = excluded.conflict_chain,
                       causality_chain = excluded.causality_chain,
                       ending_summary = excluded.ending_summary,
                       story_progress = excluded.story_progress,
                       character_ids = excluded.character_ids,
                       scene_ids = excluded.scene_ids,
                       clue_refs = excluded.clue_refs,
                       foreshadow_refs = excluded.foreshadow_refs,
                       meta = excluded.meta,
                       updated_at = excluded.updated_at""",
                (
                    episode_id, script_session_id,
                    episode.get("title", ""), episode.get("logline", ""),
                    episode.get("conflict_chain", ""), episode.get("causality_chain", ""),
                    episode.get("ending_summary", ""), episode.get("story_progress", ""),
                    dump_json(episode.get("character_ids", [])),
                    dump_json(episode.get("scene_ids", [])),
                    dump_json(episode.get("clue_refs", [])),
                    dump_json(episode.get("foreshadow_refs", [])),
                    dump_json(episode.get("meta", {})),
                    now, now,
                ),
            )
            conn.commit()
        return self.get_episode(script_session_id, episode_id)

    def update_episode_fields(self, script_session_id: str, episode_id: str, fields: dict) -> Optional[dict]:
        """人工编辑：部分字段更新（文本字段 + 引用 JSON 字段，引用校验由调用方负责）"""
        allowed = {
            "title", "logline", "conflict_chain", "causality_chain", "ending_summary", "story_progress",
            "character_ids", "scene_ids", "clue_refs", "foreshadow_refs",
        }
        json_fields = {"character_ids", "scene_ids", "clue_refs", "foreshadow_refs"}
        updates = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k in json_fields:
                v = dump_json(v if v is not None else [])
            updates[k] = v
        if not updates:
            return self.get_episode(script_session_id, episode_id)
        sets = ", ".join(f"{k} = ?" for k in updates)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE episodes SET {sets}, updated_at = ? WHERE script_session_id = ? AND episode_id = ?",
                (*updates.values(), self._now(), script_session_id, episode_id),
            )
            conn.commit()
        return self.get_episode(script_session_id, episode_id)

    def get_episode(self, script_session_id: str, episode_id: str) -> Optional[dict]:
        row = self._fetch_one(
            "SELECT * FROM episodes WHERE script_session_id = ? AND episode_id = ?",
            (script_session_id, episode_id),
        )
        return self._episode_to_dict(row) if row else None

    def list_episodes(self, script_session_id: str) -> list[dict]:
        rows = self._fetch_all(
            "SELECT * FROM episodes WHERE script_session_id = ? ORDER BY episode_id ASC",
            (script_session_id,),
        )
        return [self._episode_to_dict(row) for row in rows]

    def delete_episode(self, script_session_id: str, episode_id: str) -> bool:
        return self._delete(
            "DELETE FROM episodes WHERE script_session_id = ? AND episode_id = ?",
            (script_session_id, episode_id),
        )

    def delete_all_episodes(self, script_session_id: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM episodes WHERE script_session_id = ?", (script_session_id,))
            conn.commit()
            return cursor.rowcount

    @staticmethod
    def _episode_to_dict(row: sqlite3.Row) -> dict:
        return row_to_dict(row, {
            "character_ids": [],
            "scene_ids": [],
            "clue_refs": [],
            "foreshadow_refs": [],
            "meta": {},
        })

    # ==================== 定妆照 ====================

    def insert_lookbook(
        self,
        script_session_id: str,
        entity_id: str,
        prompt: str,
        description: str = "",
        task_status: str = "pending",
    ) -> dict:
        image_id = f"lb_{uuid.uuid4().hex[:10]}"
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO lookbook_images (image_id, script_session_id, entity_id, prompt, description, task_status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (image_id, script_session_id, entity_id, prompt, description, task_status, now, now),
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

    def delete_script_data(self, script_session_id: str) -> dict:
        """清空剧本会话的全部分集/实体/定妆照/分集素材图（大纲重生成时清下游）"""
        with self._connect() as conn:
            episodes = conn.execute("SELECT COUNT(*) FROM episodes WHERE script_session_id = ?", (script_session_id,)).fetchone()[0]
            entities = conn.execute("SELECT COUNT(*) FROM script_entities WHERE script_session_id = ?", (script_session_id,)).fetchone()[0]
            lookbooks = conn.execute("SELECT COUNT(*) FROM lookbook_images WHERE script_session_id = ?", (script_session_id,)).fetchone()[0]
            materials = conn.execute("SELECT COUNT(*) FROM episode_material_images WHERE script_session_id = ?", (script_session_id,)).fetchone()[0]
            conn.execute("DELETE FROM episodes WHERE script_session_id = ?", (script_session_id,))
            conn.execute("DELETE FROM script_entities WHERE script_session_id = ?", (script_session_id,))
            conn.execute("DELETE FROM lookbook_images WHERE script_session_id = ?", (script_session_id,))
            conn.execute("DELETE FROM episode_material_images WHERE script_session_id = ?", (script_session_id,))
            conn.commit()
        counts = {"episodes": episodes, "entities": entities, "lookbook_images": lookbooks, "episode_material_images": materials}
        logger.info(f"[剧本] 清理下游数据 {script_session_id[:8]}...: {counts}")
        return counts
