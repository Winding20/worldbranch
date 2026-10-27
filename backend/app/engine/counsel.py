"""进谏：让人物在决策前开口。

设计原则（重要）：
- 立场由**建模规则**推出，不是史料原话。规则只看人物在本模拟里的属性
  （角色、才略、忠诚、野心）与选项的**实际后果**，因此可复现、可解释。
- "按史载"的选项本身不带 effects，后果写在史实事件里。判断时必须把
  事件的效果算进去，否则"照史办"会被误当成"不花代价"而人人推荐。
- 每条建议都附依据（才略/忠诚），让用户自己判断该听谁的。
"""

from __future__ import annotations

from typing import Any

from ..models import ArmyState, CharacterState, Decision, HistoricalEvent

#: 一个决策最多给出几条建议
MAX_ADVICE = 3


def effective_effects(option: dict, event: HistoricalEvent | None) -> dict[str, Any]:
    """这个选项真正会造成的后果。

    按史载的选项，后果记录在史实事件上；其余选项用自己的 effects。
    """
    if option.get("outcome") == "historical" and event is not None:
        return event.effects or {}
    return option.get("effects") or {}


def _utility(character: CharacterState, effects: dict[str, Any]) -> float:
    """某个人如何看待这个后果。

    数值不是历史评价，只是让不同角色对同一后果有不同偏好：
    - 武将最先在意失地与军心；
    - 文臣最先在意度支与名分；
    - 野心大的人，别人的军心下滑对自己未必是坏事。
    """
    money = float(effects.get("treasury") or 0.0) / 1_000_000
    legitimacy = float(effects.get("legitimacy") or 0.0)
    morale = sum(float(v) for v in (effects.get("morale") or {}).values())
    lost_region = 1.0 if effects.get("lose_region") else 0.0
    gained_region = 1.0 if effects.get("gain_region") else 0.0

    if character.role == "general":
        score = morale * 3.0 + legitimacy - lost_region * 1.5 + gained_region * 0.8
    elif character.role == "minister":
        score = money * 2.0 + legitimacy * 3.0 - lost_region * 0.6 + gained_region * 0.6
    elif character.role == "eunuch":
        score = legitimacy * 3.0 + money
    else:
        score = legitimacy * 2.0 + money

    if character.ambition >= 0.6:
        # 诸将功高则己身见轻，军心下滑对他反而有利
        score -= morale * 1.5
    if character.loyalty <= 0.4:
        score -= lost_region * 0.5
    return score


def _phrase(role: str, label: str, historical: bool) -> str:
    if historical:
        return f"请{label}，此乃正办。"
    if role == "general":
        return f"军中之事，臣请{label}。"
    if role == "minister":
        return f"度支所系，臣以为当{label}。"
    if role == "eunuch":
        return f"陛下明鉴，宜{label}。"
    return f"臣请{label}。"


def _stance_tag(character: CharacterState, historical: bool) -> str:
    if character.ambition >= 0.7 and character.loyalty <= 0.6:
        return "其言未必为公"
    if character.ability >= 0.8:
        return "老于兵事" if character.role == "general" else "练于政事"
    if historical:
        return "与史载相合"
    return ""


def advise(
    decision: Decision,
    characters: dict[str, CharacterState],
    *,
    event: HistoricalEvent | None = None,
    limit: int = MAX_ADVICE,
) -> list[dict[str, Any]]:
    """为一道决策生成建议。只从在世、属唐廷的人里挑。"""
    options = decision.options or []
    if not options:
        return []

    pool = [
        c
        for c in characters.values()
        if c.alive and c.faction_key == "tang" and c.role != "emperor"
    ]
    if not pool:
        return []

    # 才略高的人先开口；同一角色最多两位
    pool.sort(key=lambda c: c.ability, reverse=True)
    chosen: list[CharacterState] = []
    role_count: dict[str, int] = {}
    for person in pool:
        if role_count.get(person.role, 0) >= 2:
            continue
        chosen.append(person)
        role_count[person.role] = role_count.get(person.role, 0) + 1
        if len(chosen) >= limit:
            break

    scored = [
        (option, effective_effects(option, event))
        for option in options
    ]

    advice: list[dict[str, Any]] = []
    for person in chosen:
        best, _ = max(scored, key=lambda pair: _utility(person, pair[1]))
        historical = best.get("outcome") == "historical"
        advice.append(
            {
                "character_key": person.character_key,
                "name": person.name,
                "office": person.office,
                "role": person.role,
                "ability": round(person.ability, 2),
                "loyalty": round(person.loyalty, 2),
                "option_key": best.get("key"),
                "option_label": best.get("label"),
                "text": _phrase(person.role, best.get("label", ""), historical),
                "tag": _stance_tag(person, historical),
            }
        )
    return advice


def attach_advice(
    decision: Decision,
    characters: dict[str, CharacterState],
    event: HistoricalEvent | None = None,
    armies: dict[str, ArmyState] | None = None,
) -> None:
    """把建议写进决策。没有可用人物时留空，不编造。"""
    del armies
    decision.advice = advise(decision, characters, event=event)