"""持久化公共基类：收敛三个 manager（SessionManager/ScriptManager/ModelManager）的
SQLite 连接、建表迁移、时间戳与 JSON 列序列化样板。"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.core.utils.json_utils import load_json


def row_to_dict(row: sqlite3.Row, json_fields: dict[str, object] | None = None) -> dict:
    """sqlite Row → dict，并把指定 JSON 列反序列化（坏数据回退默认值）"""
    data = dict(row)
    for key, default in (json_fields or {}).items():
        data[key] = load_json(data.get(key), default)
    return data


class BaseSQLiteManager:
    """SQLite 管理器基类

    子类需实现 `_create_schema(conn)`（建表 + 旧表列迁移）。
    """

    def __init__(self, db_path: str = "data/sessions.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def _connect(self) -> sqlite3.Connection:
        """业务连接：Row factory + busy timeout（WAL 下多 manager 并发读写）"""
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    def _init_database(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            # WAL 模式：多连接（video/script 两个 SessionManager + ScriptManager + ModelManager）并发读写
            conn.execute("PRAGMA journal_mode=WAL")
            self._create_schema(conn)
            conn.commit()

    def _create_schema(self, conn: sqlite3.Connection):
        """建表 + 列迁移（子类实现）"""
        raise NotImplementedError

    @staticmethod
    def _add_columns_if_missing(conn: sqlite3.Connection, table: str, columns: dict[str, str]):
        """旧表迁移：增加列（已存在则忽略）"""
        for column, ddl in columns.items():
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            except sqlite3.OperationalError:
                pass  # 列已存在

    def _fetch_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchone()

    def _fetch_all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()

    def _delete(self, sql: str, params: tuple = ()) -> bool:
        """执行 DELETE 并返回是否命中行"""
        with self._connect() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount > 0
