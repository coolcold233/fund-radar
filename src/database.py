# -*- coding: utf-8 -*-
"""
数据库管理模块
第一阶段：基础框架
第五阶段：用户偏好（投资风格/设置）与持仓追踪持久化

线程安全说明：
Streamlit 的 on_change 回调运行在独立线程，与主脚本线程不同。
SQLite Connection 不能跨线程复用，因此本模块不缓存 Connection，
每个业务方法内通过上下文管理器创建独立连接并在退出时关闭。
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Union, Dict, Any, List


class DatabaseManager:
    """SQLite 数据库管理器（每个业务方法内自管连接生命周期）"""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is None:
            project_root = Path(__file__).parent.parent
            self.db_path = project_root / "data" / "fund_radar.db"
        else:
            self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """创建一个短生命周期的连接，退出时自动关闭。"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # -----------------------------------------------------------------
    # 兼容旧的 context manager 用法（with db:）
    # 不建议在业务代码中使用，仅供测试脚本和遗留代码过渡。
    # -----------------------------------------------------------------
    def __enter__(self):
        self._ctx_conn = sqlite3.connect(self.db_path)
        self._ctx_conn.execute("PRAGMA foreign_keys = ON")
        self._ctx_conn.row_factory = sqlite3.Row
        return self._ctx_conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, "_ctx_conn") and self._ctx_conn is not None:
            self._ctx_conn.close()
            self._ctx_conn = None

    def initialize_database(self):
        with self._conn() as conn:
            cursor = conn.cursor()
            # 用户偏好表：单行存储（id=1），JSON 保存所有偏好
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    data TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )
            # 持仓表：每行一只基金
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio (
                    fund_code TEXT PRIMARY KEY,
                    fund_name TEXT,
                    amount REAL NOT NULL DEFAULT 0,
                    note TEXT,
                    added_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # 关注（收藏）表：每行一只关注的基金
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS followed_funds (
                    fund_code TEXT PRIMARY KEY,
                    fund_name TEXT,
                    followed_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    # -----------------------------------------------------------------
    # 用户偏好（投资风格评估结果 + 设置）
    # -----------------------------------------------------------------
    def save_preferences(self, data: Dict[str, Any]) -> None:
        """保存/覆盖用户偏好（合并写入，在单次连接内完成读-改-写）。"""
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT data FROM user_preferences WHERE id=1"
            ).fetchone()
            if row is not None and row["data"]:
                try:
                    existing = json.loads(row["data"])
                except (ValueError, TypeError):
                    existing = {}
            else:
                existing = {}
            existing.update(data)
            conn.execute(
                """
                INSERT INTO user_preferences (id, data, updated_at) VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
                """,
                (json.dumps(existing, ensure_ascii=False), now),
            )
            conn.commit()

    def load_preferences(self) -> Dict[str, Any]:
        """读取用户偏好（无记录返回空 dict）。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT data FROM user_preferences WHERE id=1"
            ).fetchone()
            if row is None:
                return {}
            try:
                return json.loads(row["data"]) if row["data"] else {}
            except (ValueError, TypeError):
                return {}

    def clear_preferences(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM user_preferences WHERE id=1")
            conn.commit()

    # -----------------------------------------------------------------
    # 持仓追踪
    # -----------------------------------------------------------------
    def upsert_holding(self, fund_code: str, fund_name: str, amount: float, note: str = "") -> None:
        """新增或更新一只持仓基金。"""
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO portfolio (fund_code, fund_name, amount, note, added_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(fund_code) DO UPDATE SET
                    fund_name=excluded.fund_name,
                    amount=excluded.amount,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (str(fund_code), str(fund_name), float(amount), note, now, now),
            )
            conn.commit()

    def delete_holding(self, fund_code: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM portfolio WHERE fund_code=?", (str(fund_code),))
            conn.commit()

    def list_holdings(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT fund_code, fund_name, amount, note, added_at, updated_at "
                "FROM portfolio ORDER BY added_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def clear_holdings(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM portfolio")
            conn.commit()

    # -----------------------------------------------------------------
    # 基金关注（收藏）
    # -----------------------------------------------------------------
    def follow_fund(self, fund_code: str, fund_name: str = "") -> None:
        """关注一只基金（已关注则更新名称）。"""
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO followed_funds (fund_code, fund_name, followed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(fund_code) DO UPDATE SET
                    fund_name=excluded.fund_name
                """,
                (str(fund_code).zfill(6), str(fund_name), now),
            )
            conn.commit()

    def unfollow_fund(self, fund_code: str) -> None:
        """取消关注。"""
        with self._conn() as conn:
            conn.execute("DELETE FROM followed_funds WHERE fund_code=?", (str(fund_code).zfill(6),))
            conn.commit()

    def list_followed(self) -> List[Dict[str, Any]]:
        """按关注时间倒序列出所有关注的基金。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT fund_code, fund_name, followed_at FROM followed_funds "
                "ORDER BY followed_at DESC, rowid DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def clear_follows(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM followed_funds")
            conn.commit()


def get_default_db() -> DatabaseManager:
    return DatabaseManager()


if __name__ == "__main__":
    print("测试数据库模块...")
    db = DatabaseManager()
    print(f"数据库路径: {db.db_path}")
    db.initialize_database()
    with db._conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT sqlite_version()")
        version = cursor.fetchone()[0]
        print(f"SQLite 版本: {version}")
    print("✅ 数据库模块测试通过!")
