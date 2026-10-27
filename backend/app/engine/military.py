"""军事：军队战力与统帅。

设计意图：让人物的能力真正影响结果。郭子仪和李光弼带同一支军队，
结果应当不同；主帅若亡故或易人，军心与战力也要跟着变。

这里不做自主会战——史实线上的胜负仍由史实事件决定，
战力只用于两件事：
  1. 给用户看"这支军队现在有多强"；
  2. 作为决策与史实条件的输入（例如守得住守不住）。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import ArmyState, CharacterState

#: 无主帅时的战力惩罚
NO_COMMANDER_FACTOR = 0.55
#: 士气与补给对战斗力的权重
MORALE_WEIGHT = 0.45
SUPPLY_WEIGHT = 0.25
#: 主帅能力的权重（其余部分来自兵员素质）
ABILITY_WEIGHT = 0.30


@dataclass
class ArmyPower:
    army_key: str
    name: str
    troops: int
    morale: float
    supply: float
    commander: str | None
    commander_name: str
    commander_ability: float
    power: float

    def to_dict(self) -> dict:
        return {
            "army_key": self.army_key,
            "name": self.name,
            "troops": self.troops,
            "morale": round(self.morale, 3),
            "supply": round(self.supply, 3),
            "commander": self.commander,
            "commander_name": self.commander_name,
            "commander_ability": round(self.commander_ability, 3),
            "power": round(self.power, 0),
        }


def army_power(army: ArmyState, commander: CharacterState | None) -> ArmyPower:
    """军队战力 = 兵员 × 士气/补给系数 × 主帅系数。

    兵员是基数；士气与补给决定这支军队还能不能打；主帅能力决定
    同等兵力下能发挥出多少。没有主帅，则大打折扣。
    """
    # 尚未成军的部队不产生战力
    if not getattr(army, "raised", True):
        return ArmyPower(
            army_key=army.army_key,
            name=army.name,
            troops=0,
            morale=army.morale,
            supply=army.supply,
            commander=army.commander_key,
            commander_name="（未成军）",
            commander_ability=0.0,
            power=0.0,
        )

    if commander is None or not commander.alive:
        ability = 0.0
        factor = NO_COMMANDER_FACTOR
        name = "无主帅"
    else:
        ability = commander.ability
        factor = (1 - ABILITY_WEIGHT) + ABILITY_WEIGHT * ability * 2
        name = commander.name

    quality = (
        army.morale * MORALE_WEIGHT
        + army.supply * SUPPLY_WEIGHT
        + (1 - MORALE_WEIGHT - SUPPLY_WEIGHT)
    )
    power = army.troops * quality * factor
    return ArmyPower(
        army_key=army.army_key,
        name=army.name,
        troops=army.troops,
        morale=army.morale,
        supply=army.supply,
        commander=army.commander_key,
        commander_name=name,
        commander_ability=ability,
        power=power,
    )


def all_powers(
    armies: list[ArmyState], characters: dict[str, CharacterState]
) -> list[ArmyPower]:
    return [
        army_power(army, characters.get(army.commander_key or "")) for army in armies
    ]


def side_strength(
    armies: list[ArmyState], characters: dict[str, CharacterState], faction: str
) -> float:
    """某一方所有军队的战力之和。"""
    total = 0.0
    for army in armies:
        if army.faction_key == faction:
            total += army_power(army, characters.get(army.commander_key or "")).power
    return total


def odds(attacker: float, defender: float) -> float:
    """把强弱对比换算成 0–1 的胜算，用于给用户一个直观判断。"""
    if attacker <= 0 and defender <= 0:
        return 0.5
    if defender <= 0:
        return 1.0
    if attacker <= 0:
        return 0.0
    ratio = attacker / defender
    # 1:1 时约 50%，3:1 时约 88%，1:3 时约 12%
    return round(ratio**2 / (ratio**2 + 1), 3)


def candidates_for_command(
    characters: dict[str, CharacterState], faction: str = "tang", limit: int = 3
) -> list[CharacterState]:
    """可选的主帅人选：在世、属于本方、按能力排序。"""
    pool = [
        c
        for c in characters.values()
        if c.alive and c.faction_key == faction and c.role in {"general", "minister", "emperor"}
    ]
    pool.sort(key=lambda c: c.ability, reverse=True)
    return pool[:limit]