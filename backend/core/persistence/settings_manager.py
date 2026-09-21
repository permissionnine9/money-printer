"""系统设置管理 - 通用 key-value 配置持久化（app_settings 表）"""
from backend.core.persistence.base import BaseSQLiteManager

# Agent 并发上限的设置键（值为整数字符串）
AGENT_CONCURRENCY_KEY = "agent_max_concurrency"


class SettingsManager(BaseSQLiteManager):
    """系统设置管理器

    负责 app_settings key-value 表的读写（如 Agent 并发上限），
    与 SessionManager 等共用同一个 SQLite（data/sessions.db）。
    """

    def _create_schema(self, conn):
        """初始化设置表"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

    def get(self, key: str, default: str | None = None) -> str | None:
        """读取一项设置，不存在返回 default"""
        row = self._fetch_one("SELECT value FROM app_settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        """写入一项设置（UPSERT）"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, self._now()),
            )
