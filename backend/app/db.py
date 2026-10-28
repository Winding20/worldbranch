"""数据库连接与会话管理。

默认用 Python 自带的 SQLite（零安装、免配置）；
需要多机共享时把 WORLDBRANCH_DATABASE_URL 指向 MySQL 即可，代码不用改。

SQLite 在并发下容易报 "database is locked"，这里统一开了三件事：
  - WAL 日志：读写不互相阻塞
  - busy_timeout：锁冲突时等一会儿再试，而不是立刻报错
  - foreign_keys：外键约束生效（默认是关的）
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

#: SQLite 下等待锁的毫秒数
SQLITE_BUSY_TIMEOUT_MS = 5000


def _prepare_sqlite(url: str) -> dict:
    """建好目录，返回 connect_args。"""
    if not url.startswith("sqlite"):
        return {}
    # sqlite:///相对路径 或 sqlite:////绝对路径
    raw = url.split("sqlite:///", 1)[-1]
    if raw and raw != ":memory:":
        Path(raw).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return {"check_same_thread": False, "timeout": SQLITE_BUSY_TIMEOUT_MS / 1000}


class Database:
    """一个连接串对应一个 Database 实例。"""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        self.is_sqlite = url.startswith("sqlite")
        self.engine = create_engine(
            url,
            echo=echo,
            future=True,
            pool_pre_ping=True,
            connect_args=_prepare_sqlite(url),
        )
        if self.is_sqlite:
            self._tune_sqlite()
        self.session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, future=True
        )

    def _tune_sqlite(self) -> None:
        @event.listens_for(self.engine, "connect")
        def _set_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        Base.metadata.drop_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


__all__ = ["Database", "SQLITE_BUSY_TIMEOUT_MS"]