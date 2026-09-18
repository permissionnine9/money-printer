"""模型配置管理 - 支持添加多个生图/chat/agent 模型（key/baseUrl/modelId 关联）"""
import logging
import sqlite3
import uuid

from backend.core.persistence.base import BaseSQLiteManager

logger = logging.getLogger(__name__)

# 支持的模型类型
MODEL_TYPES = ("image", "chat", "agent")


class ModelManager(BaseSQLiteManager):
    """模型配置管理器

    负责 model 配置表（image_models）的 CRUD 与默认模型查询。
    model_type: 'image'（生图模型）、'chat'（对话/LLM 模型）、
    'agent'（Claude Agent SDK 端点，Anthropic 协议），每类各自独立默认。
    """

    def _create_schema(self, conn):
        """初始化模型配置表"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS image_models (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                api_key TEXT NOT NULL DEFAULT '',
                base_url TEXT NOT NULL DEFAULT '',
                model_id TEXT NOT NULL DEFAULT '',
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # 旧表迁移：增加 model_type 列（已存在则忽略）
        self._add_columns_if_missing(conn, "image_models", {"model_type": "TEXT NOT NULL DEFAULT 'image'"})

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        data = dict(row)
        data["is_default"] = bool(data.get("is_default", 0))
        data["model_type"] = data.get("model_type", "image")
        return data

    def list_models(self, model_type: str | None = None) -> list[dict]:
        """列出模型配置（默认的排前面，可按类型过滤）"""
        with self._connect() as conn:
            if model_type:
                cursor = conn.execute(
                    "SELECT * FROM image_models WHERE model_type = ? ORDER BY is_default DESC, created_at ASC",
                    (model_type,)
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM image_models ORDER BY model_type ASC, is_default DESC, created_at ASC"
                )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_model(self, model_id: str) -> dict | None:
        """获取单个模型配置"""
        row = self._fetch_one("SELECT * FROM image_models WHERE id = ?", (model_id,))
        return self._row_to_dict(row) if row else None

    def get_default_model(self, model_type: str = "image") -> dict | None:
        """获取指定类型的默认模型配置（无默认时返回 None，使用系统内置配置）"""
        row = self._fetch_one(
            "SELECT * FROM image_models WHERE is_default = 1 AND model_type = ? LIMIT 1",
            (model_type,)
        )
        return self._row_to_dict(row) if row else None

    def create_model(
        self,
        name: str,
        api_key: str,
        base_url: str,
        model_id: str,
        is_default: bool = False,
        model_type: str = "image",
    ) -> dict:
        """新增模型配置"""
        if model_type not in MODEL_TYPES:
            raise ValueError(f"model_type 仅支持 {MODEL_TYPES}")

        model_uuid = str(uuid.uuid4())
        now = self._now()

        with self._connect() as conn:
            if is_default:
                conn.execute(
                    "UPDATE image_models SET is_default = 0 WHERE model_type = ?",
                    (model_type,)
                )
            conn.execute(
                "INSERT INTO image_models (id, name, api_key, base_url, model_id, is_default, model_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (model_uuid, name, api_key, base_url, model_id, 1 if is_default else 0, model_type, now, now)
            )
            conn.commit()

        logger.info(f"[模型管理] 新增模型配置: [{model_type}] {name} ({model_uuid[:8]}...)")
        return self.get_model(model_uuid)

    def update_model(
        self,
        model_id: str,
        name: str,
        api_key: str,
        base_url: str,
        model_id_field: str,
        is_default: bool = False,
        model_type: str = "image",
    ) -> dict | None:
        """更新模型配置"""
        if model_type not in MODEL_TYPES:
            raise ValueError(f"model_type 仅支持 {MODEL_TYPES}")

        now = self._now()
        with self._connect() as conn:
            if is_default:
                conn.execute(
                    "UPDATE image_models SET is_default = 0 WHERE model_type = ? AND id != ?",
                    (model_type, model_id)
                )
            cursor = conn.execute(
                """UPDATE image_models
                   SET name = ?, api_key = ?, base_url = ?, model_id = ?, is_default = ?, model_type = ?, updated_at = ?
                   WHERE id = ?""",
                (name, api_key, base_url, model_id_field, 1 if is_default else 0, model_type, now, model_id)
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None

        return self.get_model(model_id)

    def set_default(self, model_id: str) -> dict | None:
        """设置默认模型（同类型内互斥）"""
        model = self.get_model(model_id)
        if not model:
            return None
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE image_models SET is_default = 0 WHERE model_type = ?",
                (model["model_type"],)
            )
            conn.execute(
                "UPDATE image_models SET is_default = 1, updated_at = ? WHERE id = ?",
                (now, model_id)
            )
            conn.commit()
        return self.get_model(model_id)

    def delete_model(self, model_id: str) -> bool:
        """删除模型配置"""
        return self._delete("DELETE FROM image_models WHERE id = ?", (model_id,))

