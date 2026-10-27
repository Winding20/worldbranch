"""命令行工具：建表、灌入内置世界、推进与查看。

用法（先激活环境：. tools/dev-env.ps1）::

    flask --app run.py init-db
    flask --app run.py seed
    flask --app run.py new-branch tang_750 --precision standard --seed 1
    flask --app run.py advance 1 --months 12
    flask --app run.py show 1
"""

from __future__ import annotations

import json

import click
from flask import Flask

from .app_factory import get_db
from .engine import SimulationEngine
from .models import SimEvent
from .seed import seed_all
from .services import create_branch, get_branch, get_world_by_key
from .utils import format_date


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db() -> None:
        """创建全部数据表。"""
        get_db().create_all()
        click.echo("数据表已创建")

    @app.cli.command("drop-db")
    @click.confirmation_option(prompt="确定要删除所有数据表吗？")
    def drop_db() -> None:
        get_db().drop_all()
        click.echo("数据表已删除")

    @app.cli.command("seed")
    def seed() -> None:
        """写入内置世界（幂等）。"""
        from .seed import seed_knowledge as seed_kb

        with get_db().session() as session:
            worlds = seed_all(session)
            for w in worlds:
                click.echo(f"世界 {w.key} - {w.name}（{len(w.regions)} 地区）")
        with get_db().session() as session:
            count = seed_kb(session)
            click.echo(f"知识库资料 {count} 篇")

    @app.cli.command("new-branch")
    @click.argument("world_key")
    @click.option("--precision", default="standard")
    @click.option("--seed", "seed_value", default=1, type=int)
    @click.option("--name", default=None)
    def new_branch(world_key: str, precision: str, seed_value: int, name: str | None) -> None:
        """从世界模板开一条新分支。"""
        with get_db().session() as session:
            world = get_world_by_key(session, world_key)
            branch = create_branch(
                session, world, name=name, precision=precision, seed=seed_value
            )
            click.echo(f"已创建分支 {branch.id}: {branch.name}")

    @app.cli.command("advance")
    @click.argument("branch_id", type=int)
    @click.option("--months", default=1, type=int)
    @click.option("--precision", default=None)
    def advance(branch_id: int, months: int, precision: str | None) -> None:
        """推进若干个月。"""
        with get_db().session() as session:
            branch = get_branch(session, branch_id)
            report = SimulationEngine(session).advance(
                branch, months=months, precision=precision
            )
            click.echo(
                f"{format_date(report.from_date)} -> {format_date(report.to_date)} 共 {len(report.events)} 条事件"
            )
            for e in report.events[:20]:
                click.echo(f"  [{e['game_date']}] {e['scope']}/{e['kind']}: {e['title']}")

    @app.cli.command("show")
    @click.argument("branch_id", type=int)
    def show(branch_id: int) -> None:
        """打印分支当前状态。"""
        with get_db().session() as session:
            branch = get_branch(session, branch_id)
            click.echo(json.dumps(branch.to_dict(), ensure_ascii=False, indent=2))
            events = session.query(SimEvent).filter_by(branch_id=branch_id).count()
            click.echo(f"事件总数: {events}")