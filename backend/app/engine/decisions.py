"""决策：世界主动向用户提出的问题。

设计目的：让"用户不知道该干什么"变成"世界告诉你要决定什么"。
每道决策都带 2–3 个选项，每个选项写明代价与后果，选完立即生效并留下事件。
"""

from __future__ import annotations

import datetime as dt
import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ArmyState,
    Branch,
    CharacterState,
    Decision,
    FactionState,
    RegionState,
    RelationState,
    SimEvent,
)
from ..utils import format_date
from .counsel import attach_advice
from .offices import SINECURE, apply_office
from .military import candidates_for_command

#: 同一类决策在这段时间内不重复提出（月）
COOLDOWN_TICKS = 12


# --------------------------------------------------------------------------- #
# 触发
# --------------------------------------------------------------------------- #
def _first_region(by_key: dict, keys: tuple[str, ...]) -> str | None:
    """从候选里挑第一个真实存在的地点，找不到就不聚光。"""
    for key in keys:
        if key in by_key:
            return key
    return None


def _has_recent(
    session: Session, branch_id: int, kind: str, tick: int, key: str | None = None
) -> bool:
    """同类决策在冷却期内是否已经提过；给了 key 就按对象分开算。"""
    stmt = select(Decision.id).where(
        Decision.branch_id == branch_id,
        Decision.kind == kind,
        Decision.tick_index >= tick - COOLDOWN_TICKS,
    )
    if key is not None:
        stmt = stmt.where(Decision.ref_key == key)
    return session.scalar(stmt.limit(1)) is not None


def _get_relation(relations: dict[str, RelationState], key: str) -> RelationState | None:
    return relations.get(key)


def raise_decisions(
    session: Session,
    branch: Branch,
    regions: list[RegionState],
    factions: dict[str, FactionState],
    relations: dict[str, RelationState],
    shocked_keys: set[str] | None = None,
    rng: random.Random | None = None,
    characters: dict[str, CharacterState] | None = None,
    armies: dict[str, ArmyState] | None = None,
) -> list[Decision]:
    """按当前局势决定要不要向用户提问题。

    ``shocked_keys`` 是本轮发生过灾害的道，用于触发赈济；
    ``rng`` 由引擎按 (seed, tick) 派生，保证同一分支可复现。
    """
    created: list[Decision] = []
    tick = branch.tick_index
    shocked_keys = shocked_keys or set()
    characters = characters or {}
    armies = armies or {}
    rng = rng or random.Random(f"{branch.seed}:{tick}:decisions")
    by_key = {r.region_key: r for r in regions}
    fanzhen = factions.get("fanzhen")
    tang = factions.get("tang")
    allegiance = _get_relation(relations, "fanzhen")

    # 1) 藩镇府库见底，上表请饷
    if (
        fanzhen is not None
        and tang is not None
        and fanzhen.treasury < 0
        and not _has_recent(session, branch.id, "warlord_supply", tick)
    ):
        need = int(min(abs(fanzhen.treasury) + 200_000, 1_500_000))
        created.append(
            _make(
                branch,
                kind="warlord_supply",
                focus_region=_first_region(by_key, ("hebei", "fanyang", "hebei_plain")),
                title="河北藩镇上表请饷",
                description=(
                    f"河北藩镇府库已透支 {abs(fanzhen.treasury):,.0f} 贯，"
                    f"节度使上表请求朝廷拨付 {need:,} 贯军饷，言辞恭敬，但边军已在议论。"
                ),
                options=[
                    {
                        "key": "grant_full",
                        "label": "如数拨付",
                        "detail": f"府库 −{need:,} 贯，藩镇臣属度 +0.12，年内不会生事",
                        "effects": {
                            "treasury": -need,
                            "relation": {"fanzhen": 0.12},
                        },
                    },
                    {
                        "key": "grant_half",
                        "label": "折半给付",
                        "detail": f"府库 −{need // 2:,} 贯，臣属度 +0.03，边军或有怨言",
                        "effects": {
                            "treasury": -need // 2,
                            "relation": {"fanzhen": 0.03},
                            "unrest": {"hebei": 0.06},
                        },
                    },
                    {
                        "key": "refuse",
                        "label": "断然拒绝",
                        "detail": "府库不减，臣属度 −0.18，河北民变与兵变风险上升",
                        "effects": {
                            "relation": {"fanzhen": -0.18},
                            "unrest": {"hebei": 0.14},
                            "legitimacy": -0.02,
                        },
                    },
                ],
            )
        )

    # 2) 某道缺粮、受灾或民变升高，是否赈济
    troubled = [
        r
        for r in regions
        if r.unrest >= 0.2 or r.grain_stock <= 0 or r.region_key in shocked_keys
    ]
    if troubled and not _has_recent(session, branch.id, "famine_relief", tick):
        worst = max(troubled, key=lambda r: (r.unrest, r.price_index))
        cost = int(worst.population * 0.42 * 1.2)
        created.append(
            _make(
                branch,
                kind="famine_relief",
                focus_region=worst.region_key,
                title=f"{worst.name}请求赈济",
                description=(
                    f"{worst.name}粮价指数已达 {worst.price_index:.2f}，"
                    f"民变指数 {worst.unrest:.2f}，地方官员请求朝廷开仓或减免赋税。"
                ),
                options=[
                    {
                        "key": "open_granary",
                        "label": "开仓放粮",
                        "detail": f"府库 −{cost:,} 贯，{worst.name}民变 −0.22，粮价回落",
                        "effects": {
                            "treasury": -cost,
                            "unrest": {worst.region_key: -0.22},
                            "grain": {worst.region_key: int(worst.population * 0.42 * 0.9)},
                            "legitimacy": 0.01,
                        },
                    },
                    {
                        "key": "tax_relief",
                        "label": "减免赋税",
                        "detail": f"{worst.name}民变 −0.12，但来年该道税入下降",
                        "effects": {
                            "unrest": {worst.region_key: -0.12},
                            "tax": {worst.region_key: -0.02},
                        },
                    },
                    {
                        "key": "ignore",
                        "label": "暂不处置",
                        "detail": f"不花钱，{worst.name}民变 +0.10，粮价可能继续走高",
                        "effects": {"unrest": {worst.region_key: 0.1}},
                    },
                ],
            )
        )

    # 3) 藩镇离心，是否削藩
    if (
        allegiance is not None
        and allegiance.value < 0.25
        and tang is not None
        and tang.treasury > 0
        and not _has_recent(session, branch.id, "cut_warlord", tick)
    ):
        created.append(
            _make(
                branch,
                kind="cut_warlord",
                focus_region=_first_region(by_key, ("hebei", "fanyang", "hebei_plain")),
                title="朝议：是否削藩",
                description=(
                    f"河北藩镇臣属度已降至 {allegiance.value:.2f}，"
                    "朝中有大臣主张趁其未强先行削夺，也有人认为此举必致兵变。"
                ),
                options=[
                    {
                        "key": "cut",
                        "label": "下诏削藩",
                        "detail": "臣属度 −0.30，河北民变 +0.20，朝廷威望 +0.05（成则大治，败则大乱）",
                        "effects": {
                            "relation": {"fanzhen": -0.3},
                            "unrest": {"hebei": 0.2},
                            "legitimacy": 0.05,
                        },
                    },
                    {
                        "key": "appease",
                        "label": "加官安抚",
                        "detail": "府库 −300,000 贯，臣属度 +0.10",
                        "effects": {
                            "treasury": -300_000,
                            "relation": {"fanzhen": 0.1},
                        },
                    },
                    {
                        "key": "wait",
                        "label": "留待后议",
                        "detail": "什么也不做，但臣属度每月自然下滑",
                        "effects": {"relation": {"fanzhen": -0.02}},
                    },
                ],
            )
        )

    # 4) 吐蕃犯边：西北边防的周期性压力
    longyou = by_key.get("longyou")
    if (
        longyou is not None
        and rng.random() < 0.08
        and not _has_recent(session, branch.id, "border_raid", tick)
    ):
        created.append(
            _make(
                branch,
                kind="border_raid",
                focus_region="longyou",
                title="吐蕃寇边",
                description=(
                    "陇右急报：吐蕃骑兵越境掠边，鄯州告急。"
                    "边将请求增兵，朝中则有人主张以财帛换安宁。"
                ),
                options=[
                    {
                        "key": "reinforce",
                        "label": "增兵戍边",
                        "detail": "府库 −400,000 贯，陇右民变 −0.05，军威立",
                        "effects": {
                            "treasury": -400_000,
                            "unrest": {"longyou": -0.05},
                            "legitimacy": 0.03,
                        },
                    },
                    {
                        "key": "bribe",
                        "label": "赐帛议和",
                        "detail": "府库 −250,000 贯，暂得安宁，但边镇离心 +0.04",
                        "effects": {
                            "treasury": -250_000,
                            "relation": {"fanzhen": -0.04},
                            "legitimacy": -0.02,
                        },
                    },
                    {
                        "key": "ignore",
                        "label": "置之不理",
                        "detail": "不花钱，陇右民变 +0.12，边患可能扩大",
                        "effects": {"unrest": {"longyou": 0.12}, "legitimacy": -0.04},
                    },
                ],
            )
        )

    # 5) 漕运受阻：江淮粮米运不出来
    huainan = by_key.get("huainan")
    jiangnan = by_key.get("jiangnan")
    if (
        huainan is not None
        and jiangnan is not None
        and (huainan.price_index > 1.25 or jiangnan.price_index > 1.25)
        and not _has_recent(session, branch.id, "transport_break", tick)
    ):
        created.append(
            _make(
                branch,
                kind="transport_break",
                focus_region=_first_region(by_key, ("huainan", "jiangnan", "suiyang")),
                title="漕运受阻",
                description=(
                    "江淮粮船滞留，漕运不畅，关内粮价已有抬头的迹象。"
                    "转运使请示：是改走陆路加急，还是暂缓漕运以减少损耗？"
                ),
                options=[
                    {
                        "key": "land_route",
                        "label": "改走陆路",
                        "detail": "府库 −350,000 贯，关内、河南粮价回落",
                        "effects": {
                            "treasury": -350_000,
                            "unrest": {"guannei": -0.04, "henan": -0.04},
                            "grain": {"guannei": 400_000},
                        },
                    },
                    {
                        "key": "suspend",
                        "label": "暂缓漕运",
                        "detail": "省下运费，但关内粮价 +0.15，民怨上升",
                        "effects": {"unrest": {"guannei": 0.08}, "legitimacy": -0.01},
                    },
                    {
                        "key": "requisition",
                        "label": "就地强征民船",
                        "detail": "不花钱，江淮民变 +0.12",
                        "effects": {"unrest": {"huainan": 0.12, "jiangnan": 0.08}},
                    },
                ],
            )
        )

    # 6) 藩镇彻底翻脸，兵锋相向
    if (
        allegiance is not None
        and allegiance.value < -0.15
        and not _has_recent(session, branch.id, "warlord_revolt", tick)
    ):
        created.append(
            _make(
                branch,
                kind="warlord_revolt",
                focus_region=_first_region(by_key, ("hebei", "fanyang", "hebei_plain")),
                title="河北举兵",
                description=(
                    f"河北藩镇臣属度已跌至 {allegiance.value:.2f}，粮道断绝、使者不至。"
                    "斥候报称其已在境内集结兵马，朝中议论纷纷。"
                ),
                options=[
                    {
                        "key": "suppress",
                        "label": "下诏讨伐",
                        "detail": "府库 −1,200,000 贯，威望 +0.10；若府库不足则威望大跌",
                        "effects": {
                            "treasury": -1_200_000,
                            "legitimacy": 0.10,
                            "unrest": {"hebei": 0.15},
                            "relation": {"fanzhen": 0.05},
                        },
                    },
                    {
                        "key": "conciliate",
                        "label": "遣使怀柔",
                        "detail": "府库 −600,000 贯，臣属度 +0.25，但朝廷威望受损",
                        "effects": {
                            "treasury": -600_000,
                            "relation": {"fanzhen": 0.25},
                            "legitimacy": -0.05,
                        },
                    },
                    {
                        "key": "hold",
                        "label": "固守关隘",
                        "detail": "不花钱，但河北民变 +0.10，粮道继续断绝",
                        "effects": {
                            "unrest": {"hebei": 0.10},
                            "legitimacy": -0.03,
                        },
                    },
                ],
            )
        )

    # 7) 主帅空缺：某支军队没了主将，得派人去带
    #: 已在带兵的人，不再重复任命
    busy = {
        a.commander_key
        for a in armies.values()
        if a.commander_key and a.army_key != ""
    }
    for army in armies.values():
        if army.faction_key != "tang":
            continue
        if not getattr(army, "raised", True):
            continue  # 还没成军的部队不需要主帅
        commander = characters.get(army.commander_key or "")
        if commander is not None and commander.alive:
            continue
        if _has_recent(session, branch.id, "appoint_commander", tick, key=army.army_key):
            continue
        pool = [
            person
            for person in candidates_for_command(characters, "tang", limit=8)
            if person.character_key not in busy
        ][:3]
        if not pool:
            continue

        options = [
            {
                "key": f"appoint_{person.character_key}",
                "label": f"以{person.name}为帅",
                "detail": (
                    f"{person.office or '将领'}，才略 {person.ability:.2f}；"
                    f"接掌{army.name}后士气回升"
                ),
                "effects": {
                    "commander": {army.army_key: person.character_key},
                    "morale": {army.army_key: 0.10},
                },
            }
            for person in pool
        ]
        options.append(
            {
                "key": "appoint_none",
                "label": "暂不遣帅，令副将权领",
                "detail": "不费钱粮，但无主帅之军战力大减，士气继续下滑",
                "effects": {"morale": {army.army_key: -0.08}},
            }
        )
        created.append(
            _make(
                branch,
                kind="appoint_commander",
                ref_key=army.army_key,
                focus_region=army.region_key or None,
                title=f"{army.name}无主帅",
                description=(
                    f"{army.name}主帅{commander.name if commander else '（空缺）'}"
                    f"{'已殁' if commander else ''}，军中无主，诸将相持不下。"
                    "朝廷须择人接掌，否则战力日削。"
                ),
                options=options,
            )
        )

    # 8) 功臣拥兵自重：赏则费财，削则生变
    from .loyalty import DEFECT_LOYALTY, WARNING_LOYALTY

    for person in characters.values():
        if not person.alive or person.faction_key != "tang":
            continue
        if person.role == "emperor":
            continue
        if not (DEFECT_LOYALTY < person.loyalty <= WARNING_LOYALTY):
            continue
        own = [a for a in armies.values() if a.commander_key == person.character_key]
        if not own or sum(a.troops for a in own) <= 0:
            continue
        if _has_recent(session, branch.id, "reward_general", tick, key=person.character_key):
            continue

        cost = int(sum(a.troops for a in own) * 3)  # 兵越多，赏格越高
        created.append(
            _make(
                branch,
                kind="reward_general",
                ref_key=person.character_key,
                focus_region=person.location_region_key,
                title=f"{person.name}拥兵自重",
                description=(
                    f"{person.name}（{person.office}）统兵在外，忠诚已降至 "
                    f"{person.loyalty:.2f}，屡请入朝而托辞不至。"
                    "朝中或请加赏以安其心，或请削其兵权。"
                ),
                options=[
                    {
                        "key": "reward",
                        "label": "加官厚赏",
                        "detail": (
                            f"府库 −{cost:,} 贯，授同中书门下平章事，"
                            "忠诚回升，然此例一开，诸将效尤"
                        ),
                        "effects": {
                            "treasury": -cost,
                            "loyalty": {person.character_key: 0.15},
                            "office": {
                                person.character_key: {
                                    "title": "同中书门下平章事",
                                    "rank": 2,
                                    "kind": "civil",
                                }
                            },
                            "legitimacy": -0.02,
                        },
                    },
                    {
                        "key": "strip_command",
                        "label": "削其兵权",
                        "detail": (
                            f"夺其军，改授{SINECURE['title']}（闲职）；"
                            "忠诚大跌，若其部曲不服则生变"
                        ),
                        "effects": {
                            "loyalty": {person.character_key: -0.15},
                            "disarm": [a.army_key for a in own],
                            "office": {
                                person.character_key: {
                                    "title": SINECURE["title"],
                                    "rank": SINECURE["rank"],
                                    "kind": SINECURE["kind"],
                                }
                            },
                            "legitimacy": 0.04,
                        },
                    },
                    {
                        "key": "ignore",
                        "label": "不闻不问",
                        "detail": "不费钱粮，但其离心日甚，恐终为患",
                        "effects": {"loyalty": {person.character_key: -0.04}},
                    },
                ],
            )
        )

    for decision in created:
        session.add(decision)
    if created:
        session.flush()
        # 决策落库后立刻让朝臣开口：有话说就说，没人可问就留空
        for decision in created:
            attach_advice(decision, characters, armies)
        session.flush()
    return created


def _make(
    branch: Branch,
    *,
    kind: str,
    title: str,
    description: str,
    options: list[dict],
    trigger_event_id: int | None = None,
    ref_key: str | None = None,
    focus_region: str | None = None,
) -> Decision:
    return Decision(
        branch_id=branch.id,
        game_date=branch.current_date,
        tick_index=branch.tick_index,
        kind=kind,
        title=title,
        description=description,
        trigger_event_id=trigger_event_id,
        ref_key=ref_key,
        focus_region=focus_region,
        options=options,
        status="pending",
    )


# --------------------------------------------------------------------------- #
# 决议
# --------------------------------------------------------------------------- #
class DecisionError(ValueError):
    pass


def resolve_decision(
    session: Session,
    branch: Branch,
    decision: Decision,
    option_key: str,
) -> SimEvent:
    """执行用户的选择，把它写回世界并留下一条事件。"""
    if decision.status != "pending":
        raise DecisionError("这道决策已经处理过了")

    # 历史岔路口交给 history 处理：它要按"是否照史载"决定后续走向
    if decision.kind == "history_fork":
        from .history import resolve_fork

        return resolve_fork(session, branch, decision, option_key)

    option = next((o for o in (decision.options or []) if o["key"] == option_key), None)
    if option is None:
        raise DecisionError(f"没有这个选项: {option_key}")

    effects: dict[str, Any] = option.get("effects") or {}
    #: 实际发生的变化，用于给用户"选完之后到底怎么了"的即时反馈
    applied: list[dict[str, Any]] = []

    tang = session.scalar(
        select(FactionState).where(
            FactionState.branch_id == branch.id, FactionState.faction_key == "tang"
        )
    )
    if tang is not None:
        if effects.get("treasury"):
            before = tang.treasury
            tang.treasury += float(effects["treasury"])
            applied.append(
                {
                    "label": "朝廷府库",
                    "before": round(before, 0),
                    "after": round(tang.treasury, 0),
                    "unit": "贯",
                }
            )
        if effects.get("legitimacy"):
            before = tang.legitimacy
            tang.legitimacy = min(max(tang.legitimacy + float(effects["legitimacy"]), 0.0), 1.0)
            applied.append(
                {
                    "label": "朝廷威望",
                    "before": round(before, 3),
                    "after": round(tang.legitimacy, 3),
                    "unit": "",
                }
            )

    for key, delta in (effects.get("relation") or {}).items():
        rel = session.scalar(
            select(RelationState).where(
                RelationState.branch_id == branch.id,
                RelationState.from_key == key,
            )
        )
        if rel is not None:
            before = rel.value
            rel.value = min(max(rel.value + float(delta), -1.0), 1.0)
            applied.append(
                {
                    "label": "河北藩镇臣属度",
                    "before": round(before, 3),
                    "after": round(rel.value, 3),
                    "unit": "",
                }
            )

    for key, delta in (effects.get("unrest") or {}).items():
        region = session.scalar(
            select(RegionState).where(
                RegionState.branch_id == branch.id, RegionState.region_key == key
            )
        )
        if region is not None:
            before = region.unrest
            region.unrest = min(max(region.unrest + float(delta), 0.0), 1.0)
            applied.append(
                {
                    "label": f"{region.name}民变",
                    "before": round(before, 3),
                    "after": round(region.unrest, 3),
                    "unit": "",
                }
            )

    for key, delta in (effects.get("grain") or {}).items():
        region = session.scalar(
            select(RegionState).where(
                RegionState.branch_id == branch.id, RegionState.region_key == key
            )
        )
        if region is not None:
            before = region.grain_stock
            region.grain_stock = max(region.grain_stock + float(delta), 0.0)
            applied.append(
                {
                    "label": f"{region.name}存粮",
                    "before": round(before, 0),
                    "after": round(region.grain_stock, 0),
                    "unit": "石",
                }
            )

    for key, delta in (effects.get("tax") or {}).items():
        region = session.scalar(
            select(RegionState).where(
                RegionState.branch_id == branch.id, RegionState.region_key == key
            )
        )
        if region is not None:
            before = region.tax_rate
            region.tax_rate = min(max(region.tax_rate + float(delta), 0.0), 0.5)
            applied.append(
                {
                    "label": f"{region.name}税率",
                    "before": round(before, 3),
                    "after": round(region.tax_rate, 3),
                    "unit": "",
                }
            )

    # 忠诚变化：赏则回心，削则见疑
    for key, delta in (effects.get("loyalty") or {}).items():
        person = session.scalar(
            select(CharacterState).where(
                CharacterState.branch_id == branch.id, CharacterState.character_key == key
            )
        )
        if person is not None:
            before = person.loyalty
            person.loyalty = min(max(person.loyalty + float(delta), 0.0), 1.0)
            applied.append(
                {
                    "label": f"{person.name}忠诚",
                    "before": round(before, 3),
                    "after": round(person.loyalty, 3),
                    "unit": "",
                }
            )

    # 改授官职：实权转闲职，或加官进爵
    for char_key, spec in (effects.get("office") or {}).items():
        person = session.scalar(
            select(CharacterState).where(
                CharacterState.branch_id == branch.id,
                CharacterState.character_key == char_key,
            )
        )
        if person is not None:
            change = apply_office(
                person,
                title=spec["title"],
                rank=int(spec.get("rank", person.office_rank)),
                kind=spec.get("kind", person.office_kind),
            )
            applied.append(
                {
                    "label": f"{person.name}官职",
                    "before": change.before,
                    "after": change.after,
                    "unit": "",
                }
            )

    # 削兵权：解主帅之职，兵额折损
    for army_key in effects.get("disarm") or []:
        army = session.scalar(
            select(ArmyState).where(
                ArmyState.branch_id == branch.id, ArmyState.army_key == army_key
            )
        )
        if army is not None:
            before_troops = army.troops
            army.commander_key = None
            army.troops = int(army.troops * 0.7)
            army.morale = max(army.morale - 0.10, 0.0)
            applied.append(
                {
                    "label": f"{army.name}兵额",
                    "before": before_troops,
                    "after": army.troops,
                    "unit": "",
                }
            )

    # 任命主帅：换人之后，这支军队的战力会立刻变
    for army_key, person_key in (effects.get("commander") or {}).items():
        army = session.scalar(
            select(ArmyState).where(
                ArmyState.branch_id == branch.id, ArmyState.army_key == army_key
            )
        )
        person = session.scalar(
            select(CharacterState).where(
                CharacterState.branch_id == branch.id,
                CharacterState.character_key == person_key,
            )
        )
        if army is not None and person is not None:
            before = army.commander_key or "（空缺）"
            army.commander_key = person_key
            applied.append(
                {
                    "label": f"{army.name}主帅",
                    "before": before,
                    "after": person.name,
                    "unit": "",
                }
            )

    for army_key, delta in (effects.get("morale") or {}).items():
        army = session.scalar(
            select(ArmyState).where(
                ArmyState.branch_id == branch.id, ArmyState.army_key == army_key
            )
        )
        if army is not None:
            before = army.morale
            army.morale = min(max(army.morale + float(delta), 0.0), 1.0)
            applied.append(
                {
                    "label": f"{army.name}士气",
                    "before": round(before, 3),
                    "after": round(army.morale, 3),
                    "unit": "",
                }
            )

    event = SimEvent(
        branch_id=branch.id,
        game_date=branch.current_date,
        tick_index=branch.tick_index,
        scope="nation",
        kind="decision",
        severity=4,
        duration_months=1,
        title=f"决策：{decision.title} → {option['label']}",
        summary=option.get("detail") or "",
        region_keys=[],
        faction_keys=["tang"],
        causes=(
            [{"event_id": decision.trigger_event_id, "rel": "caused_by"}]
            if decision.trigger_event_id
            else [{"rule": "decision", "kind": decision.kind}]
        ),
        metrics={"decision_kind": decision.kind, "option": option_key, "applied": applied},
    )
    session.add(event)
    session.flush()

    decision.status = "resolved"
    decision.resolved_option = option_key
    decision.resolved_at = dt.datetime.now(dt.timezone.utc)
    decision.result_event_id = event.id
    session.flush()
    return event


def pending_decisions(session: Session, branch_id: int) -> list[Decision]:
    return list(
        session.scalars(
            select(Decision)
            .where(Decision.branch_id == branch_id, Decision.status == "pending")
            .order_by(Decision.tick_index.desc(), Decision.id.desc())
        )
    )


def decision_history(session: Session, branch_id: int, limit: int = 50) -> list[Decision]:
    return list(
        session.scalars(
            select(Decision)
            .where(Decision.branch_id == branch_id)
            .order_by(Decision.id.desc())
            .limit(limit)
        )
    )


def describe_relation(session: Session, branch_id: int) -> list[dict]:
    """把关系翻译成人能读的话。"""
    rows = list(
        session.scalars(
            select(RelationState).where(RelationState.branch_id == branch_id)
        )
    )
    out = []
    for rel in rows:
        value = rel.value
        if value >= 0.6:
            label = "恭顺"
        elif value >= 0.35:
            label = "听命"
        elif value >= 0.2:
            label = "阳奉阴违"
        elif value >= 0.0:
            label = "离心"
        else:
            label = "敌视"
        out.append({**rel.snapshot(), "label": label, "date": format_date(dt.date.today())})
    return out