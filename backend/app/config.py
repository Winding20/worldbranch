"""应用配置。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent

load_dotenv(BASE_DIR / ".env")


def _default_sqlite_uri() -> str:
    """默认数据库落在 instance 目录，避免污染源码树。"""
    instance = BASE_DIR / "instance"
    instance.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(instance / 'worldbranch.db').as_posix()}"


class Config:
    """默认配置，全部可用环境变量覆盖。"""

    DATABASE_URL: str = os.getenv("WORLDBRANCH_DATABASE_URL") or _default_sqlite_uri()
    DEBUG: bool = os.getenv("WORLDBRANCH_DEBUG", "0") == "1"
    #: 是否打印每条 SQL（调试用，平时关掉，否则日志会淹没输出）
    SQL_ECHO: bool = os.getenv("WORLDBRANCH_SQL_ECHO", "0") == "1"
    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv(
            "WORLDBRANCH_CORS_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ).split(",")
        if o.strip()
    ]
    #: Vue 3 前端的构建产物目录（在 frontend 目录执行 node build.mjs 生成）
    VUE_DIST: Path = PROJECT_DIR / "frontend" / "dist"

    #: 模拟引擎可选的精度档位（详见设计文档第 5 章）
    PRECISION_LEVELS: tuple[str, ...] = ("macro", "standard", "fine", "deep")


def get_config(overrides: dict | None = None) -> Config:
    """返回配置对象，便于测试时覆盖。"""
    cfg = Config()
    if overrides:
        for key, value in overrides.items():
            setattr(cfg, key, value)
    return cfg