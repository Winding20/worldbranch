"""通用小工具。"""

from __future__ import annotations

import datetime as dt


def format_date(value: dt.date | dt.datetime) -> str:
    """游戏内日期格式：年份不补零，例如 ``750-07-01``。

    标准 ISO 会把 750 年写成 ``0750``，在历史世界的界面里读起来很别扭，
    所以对外统一用这个格式；数据库里仍然存标准 Date。
    """
    if isinstance(value, dt.datetime):
        value = value.date()
    return f"{value.year}-{value.month:02d}-{value.day:02d}"