---
name: sqlite-fd-leak
摘要: BaseSQLiteManager._connect() 返回未显式关闭的连接，长驻进程数天后堆积数百个 sqlite fd；改为 @contextmanager 在 finally 中 conn.close() 修复。
tags: [sqlite, 连接泄漏, BaseSQLiteManager, contextmanager]
---

# SQLite 连接 fd 泄漏

**最后更新:** 2026-09-21

## 问题

`BaseSQLiteManager._connect()` 原实现每次操作新建 sqlite3 连接并直接返回，但从不显式 `close()`。后端是长驻进程，数天后连接 fd 持续堆积（lsof 可见数百个打开的 `data/sessions.db` 连接），最终可能触及进程 fd 上限，导致新的数据库操作失败。

## 根因

- sqlite3.Connection 依赖 GC 回收，而 CPython 引用周期下回收时机不确定，连接长期滞留；
- `check_same_thread=False` + 多线程共享 Manager 的场景加剧了连接生命周期的不可控。

## 解决

`backend/core/persistence/base.py`：

- `_connect()` 改为 `@contextmanager`，yield 前 try/finally 中显式 `conn.close()`；
- `_init_database()` 同步改造为 `with self._connect() as conn:` 形态。

## 避免

- 所有 SQLite 访问统一走 `with self._connect() as conn:` 形态，由上下文管理器保证关闭；
- 新增 Manager 时禁止返回裸连接（不要绕过 `_connect()` 自行 `sqlite3.connect(...)` 后直接返回）。
