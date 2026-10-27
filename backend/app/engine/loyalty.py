"""忠诚与离心。

唐史后半段的核心机制：**功高震主**。

郭子仪、李光弼、仆固怀恩都是平叛功臣，但朝廷越依赖他们，
他们的处境越危险——赏无可赏，疑则生变。仆固怀恩最终叛走，
后来的河朔三镇也是同一逻辑。

规则只看本模拟里的数据：
- 某人掌控的兵力占唐军总战力的比重（功高）；
- 朝廷威望（威望低则难以服众）；
- 人物野心（野心大者更容易走极端）。

产出三种结果：忠诚缓慢流失、拥兵自重的警告、以及最终的叛离。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ..models import ArmyState, Branch, CharacterState, FactionState, RegionState

#: 每月自然流失
BASE_DRIFT = -0.0015
#: 势力占比超过此值开始"功高震主"
POWER_CONCERN_SHARE = 0.22
#: 拥兵自重的警告线
WARNING_LOYALTY = 0.45
#: 叛离线
DEFECT_LOYALTY = 0.18
#: 叛离所需的最低野心
DEFECT_AMBITION = 0.5


@dataclass
class LoyaltyChange:
    character_key: str
    name: str
    before: float
    after: float
    reason: str


def _power_share(
    character: CharacterState, armies: dict[str, ArmyState], total: float
) -> float:
    if total <= 0:
        return 0.0
    own = sum(
        a.troops for a in armies.values() if a.commander_key == character.character_key
    )
    return own / max(total, 1)


def monthly_drift(
    characters: dict[str, CharacterState],
    armies: dict[str, ArmyState],
    tang: FactionState | None,
) -> list[LoyaltyChange]:
    """计算本月忠诚变化。返回发生变化的人。"""
    total_troops = sum(
        a.troops for a in armies.values() if a.faction_key == "tang" and a.raised
    )
    legitimacy = tang.legitimacy if tang else 0.5

    changes: list[LoyaltyChange] = []
    for person in characters.values():
        if not person.alive or person.faction_key != "tang":
            continue
        if person.role in {"emperor"}:
            continue

        share = _power_share(person, armies, total_troops)
        delta = BASE_DRIFT
        reason = "自然耗损"

        if share > POWER_CONCERN_SHARE:
            extra = (share - POWER_CONCERN_SHARE) / max(1 - POWER_CONCERN_SHARE, 1e-6)
            delta -= 0.006 * extra
            reason = "功高震主"

        # 朝廷威望高时，人心自然向附
        delta += (legitimacy - 0.5) * 0.006
        if legitimacy < 0.35:
            delta -= 0.002
            reason = "朝廷威望不振" if reason == "自然耗损" else reason

        if person.ambition >= 0.6:
            delta -= 0.002
            if reason == "自然耗损":
                reason = "其志不小"

        before = person.loyalty
        person.loyalty = max(0.0, min(1.0, before + delta))
        if abs(person.loyalty - before) >= 1e-9:
            changes.append(
                LoyaltyChange(
                    character_key=person.character_key,
                    name=person.name,
                    before=round(before, 3),
                    after=round(person.loyalty, 3),
                    reason=reason,
                )
            )
    return changes


def check_defection(
    session: Session,
    branch: Branch,
    characters: dict[str, CharacterState],
    armies: dict[str, ArmyState],
) -> list[dict[str, Any]]:
    """检查有没有人该叛了。返回叛离记录。"""
    results: list[dict[str, Any]] = []
    for person in characters.values():
        if not person.alive or person.faction_key != "tang":
            continue
        if person.loyalty > DEFECT_LOYALTY:
            continue
        if person.ambition < DEFECT_AMBITION:
            continue

        own_armies = [
            a
            for a in armies.values()
            if a.commander_key == person.character_key and a.troops > 0
        ]
        if not own_armies:
            continue

        # 叛归燕军：带走自己的兵
        person.faction_key = "yan"
        person.defected = True
        moved = 0
        for army in own_armies:
            army.faction_key = "yan"
            moved += army.troops

        # 驻地若在其掌控下，一并易手
        lost_regions: list[str] = []
        if person.location_region_key:
            region = session.query(RegionState).filter_by(
                branch_id=branch.id, region_key=person.location_region_key
            ).one_or_none()
            if region is not None and region.faction_key == "tang":
                region.faction_key = "yan"
                lost_regions.append(region.name)

        results.append(
            {
                "character_key": person.character_key,
                "name": person.name,
                "loyalty": round(person.loyalty, 3),
                "ambition": round(person.ambition, 3),
                "troops": moved,
                "regions": lost_regions,
            }
        )
    return results


def loyalty_overview(
    characters: dict[str, CharacterState], armies: dict[str, ArmyState]
) -> list[dict[str, Any]]:
    """给界面用的忠诚一览：谁在带兵、兵有多少、忠不忠。"""
    total = sum(a.troops for a in armies.values() if a.faction_key == "tang" and a.raised)
    rows = []
    for person in characters.values():
        if person.role == "emperor":
            continue
        # 燕方人物不进唐廷的忠诚一览；但从唐廷叛出的要留着，好让人看见
        if person.faction_key != "tang" and not person.defected:
            continue
        troops = sum(
            a.troops
            for a in armies.values()
            if a.commander_key == person.character_key and a.troops > 0
        )
        if not person.alive and troops == 0:
            rows.append(
                {
                    "key": person.character_key,
                    "name": person.name,
                    "office": person.office,
                    "office_rank": person.office_rank,
                    "office_kind": person.office_kind,
                    "faction": person.faction_key,
                    "alive": False,
                    "loyalty": round(person.loyalty, 3),
                    "ambition": round(person.ambition, 3),
                    "troops": 0,
                    "share": 0.0,
                    "status": "已殁",
                }
            )
            continue
        share = troops / total if total else 0.0
        # "拥兵自重"与"将叛"都得以手里真有兵为前提
        if person.defected:
            status = "已叛"
        elif troops == 0:
            status = "已殁" if not person.alive else "在朝"
        elif person.loyalty <= DEFECT_LOYALTY:
            status = "将叛"
        elif person.loyalty <= WARNING_LOYALTY:
            status = "拥兵自重"
        elif share >= POWER_CONCERN_SHARE:
            status = "功高"
        else:
            status = "恭顺"
        rows.append(
            {
                "key": person.character_key,
                "name": person.name,
                "office": person.office,
                "office_rank": person.office_rank,
                "office_kind": person.office_kind,
                "faction": person.faction_key,
                "alive": person.alive,
                "loyalty": round(person.loyalty, 3),
                "ambition": round(person.ambition, 3),
                "troops": troops,
                "share": round(share, 3),
                "status": status,
            }
        )
    rows.sort(key=lambda r: (r["loyalty"], -r["troops"]))
    return rows