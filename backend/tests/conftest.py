"""pytest 公共夹具：每个测试用独立的 SQLite 文件，互不污染。"""

from __future__ import annotations

import pytest

from app import create_app
from app.app_factory import get_db
from app.seed import seed_all


@pytest.fixture()
def app(tmp_path):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    application = create_app({"DATABASE_URL": url, "DEBUG": False})
    with application.app_context():
        db = get_db()
        db.create_all()
        with db.session() as session:
            seed_all(session)
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db_session(app):
    """在应用上下文里给出一个会提交的 Session。"""
    with app.app_context():
        with get_db().session() as session:
            yield session