"""数据库连接与会话管理。

不绑定 Flask-SQLAlchemy，直接使用 SQLAlchemy 2.x，便于在测试与脚本中复用，
也便于从 SQLite 平滑切到服务器上的 MySQL（只改连接串）。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


class Database:
    """一个连接串对应一个 Database 实例。"""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(
            url,
            echo=echo,
            future=True,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self.session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, future=True
        )

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


__all__ = ["Database"]