"""官职：品级、性质，以及迁转的后果。

设计目的：让"夺兵权"这类事不只是清空一个字段，而是**真的换了个官**——
节度使变成太子太保，兵权没了、体面还在，人也就此离心。

规则只看本模拟里的数据：
- 品级越高，威望加成越大；
- 只有 military / envoy 性质的官才能统兵；
- 由实权转闲职，忠诚会掉；加官进爵，忠诚会涨。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import CharacterState

#: 只有这些性质的官职可以统兵
COMMAND_KINDS = {"military", "envoy"}

#: 常见闲职：给个崇高的空衔，兵权收回
SINECURE = {"title": "太子太保", "rank": 2, "kind": "sinecure"}
#: 常见的加官：宰相
CHANCELLOR = {"title": "同中书门下平章事", "rank": 2, "kind": "civil"}


@dataclass
class OfficeChange:
    character_key: str
    name: str
    before: str
    after: str
    rank_before: int
    rank_after: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_key": self.character_key,
            "name": self.name,
            "before": self.before,
            "after": self.after,
            "rank_before": self.rank_before,
            "rank_after": self.rank_after,
        }


def can_command(person: CharacterState) -> bool:
    """此人现在有没有资格统兵。"""
    return person.alive and person.office_kind in COMMAND_KINDS


def apply_office(
    person: CharacterState,
    *,
    title: str,
    rank: int,
    kind: str,
) -> OfficeChange:
    """改授官职，返回变化记录。"""
    change = OfficeChange(
        character_key=person.character_key,
        name=person.name,
        before=person.office or "（无）",
        after=title,
        rank_before=person.office_rank,
        rank_after=rank,
    )
    person.office = title
    person.office_rank = rank
    person.office_kind = kind
    return change


def rank_label(rank: int) -> str:
    """品级的中文说法。"""
    names = {1: "一品", 2: "二品", 3: "三品", 4: "四品", 5: "五品"}
    return names.get(rank, f"{rank} 品")


def kind_label(kind: str) -> str:
    return {
        "military": "统兵",
        "civil": "文职",
        "envoy": "使职",
        "sinecure": "闲职",
    }.get(kind, kind)