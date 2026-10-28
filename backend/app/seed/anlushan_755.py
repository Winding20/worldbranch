"""天宝十四载至广德元年（755–763）：安史之乱。

这是安史之乱模拟器的第一个完整切片。选它的理由：
- 起止清晰：755 年十一月范阳起兵 → 763 年史朝义自尽；
- 结局众所周知，推演结果可以直接与史实对照；
- 人物集中、关键节点明确，适合检验"因果是否经得起推敲"。

内容说明（务必保留）：
- 人物的能力/忠诚/野心是**建模估值**，不是史料原文，用来驱动推演；
- 兵力数字取史书所载量级，作**示意**，不追求精确；
- 事件日期按史书所载年月，个别只记年或只记月者按最可能月份归位。
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..models import (
    Army,
    Character,
    Faction,
    FactionRelation,
    HistoricalEvent,
    Region,
    TradeLink,
    World,
)

WORLD_KEY = "tang_755"
START_DATE = dt.date(755, 11, 1)

SOURCE_NOTES: dict[str, Any] = {
    "sources": [
        "《旧唐书》玄宗/肃宗/代宗本纪、安禄山/史思明传",
        "《新唐书》兵志、食货志",
        "《资治通鉴》卷二一七至二二二（天宝十四载至广德元年）",
    ],
    "notes": [
        "人物能力、忠诚、野心为建模估值，用于驱动推演，非史料原文。",
        "各军兵力取史载量级作示意，不做精确复原。",
        "事件日期按史载年月；只记年或只记月者按最可能月份归位。",
        "州郡数目与人口为量级估算，仅覆盖本切片涉及的关键地区。",
    ],
}

SCENARIO: dict[str, Any] = {
    "role": "唐廷 · 天宝十四载",
    "goal": "在叛乱中保住社稷：不失两京，不让藩镇坐大，不让天下崩解。",
    "briefing": (
        "天宝十四载十一月，范阳、平卢、河东三镇节度使安禄山以「清君侧」为名起兵，"
        "率十五万众南下。承平四十年的天下，一时竟无可用之兵。"
        "朝廷要在仓促间决定：守哪里、用谁、信谁。八年之后这段历史会写下结局——"
        "而这一次，你可以改写它。"
    ),
    "pressures": [
        "安禄山拥三镇之兵，河北州县望风而降",
        "朝廷精锐多在边镇，京畿空虚",
        "杨国忠与安禄山势同水火，朝议激烈",
    ],
    "watch": ["洛阳是否失守", "潼关守军", "朔方军动向", "府库与人心"],
}

# --------------------------------------------------------------------------- #
# 地理：只保留与本切片相关的关键地区
# --------------------------------------------------------------------------- #
REGIONS: list[dict[str, Any]] = [
    {"key": "changan", "name": "京兆", "lat": 34.34, "lon": 108.94, "population": 2_000_000, "faction_key": "tang"},
    {"key": "luoyang", "name": "河南府", "lat": 34.62, "lon": 112.45, "population": 1_800_000, "faction_key": "tang"},
    {"key": "fanyang", "name": "范阳", "lat": 39.45, "lon": 115.97, "population": 1_200_000, "faction_key": "yan"},
    {"key": "taiyuan", "name": "太原", "lat": 37.87, "lon": 112.55, "population": 800_000, "faction_key": "tang"},
    {"key": "lingwu", "name": "灵武", "lat": 38.10, "lon": 106.33, "population": 300_000, "faction_key": "tang"},
    {"key": "tongguan", "name": "潼关", "lat": 34.55, "lon": 110.25, "population": 200_000, "faction_key": "tang"},
    {"key": "suiyang", "name": "睢阳", "lat": 34.42, "lon": 115.65, "population": 600_000, "faction_key": "tang"},
    {"key": "hebei_plain", "name": "河北诸州", "lat": 37.20, "lon": 115.30, "population": 2_400_000, "faction_key": "yan"},
]

FACTIONS: list[dict[str, Any]] = [
    {
        "key": "tang",
        "name": "唐廷",
        "kind": "state",
        "capital_region_key": "changan",
        "treasury": 2_400_000.0,
        "legitimacy": 0.70,
        "military": 90_000.0,
    },
    {
        "key": "yan",
        "name": "燕（安禄山）",
        "kind": "warlord",
        "capital_region_key": "fanyang",
        "treasury": 1_600_000.0,
        "legitimacy": 0.45,
        "military": 150_000.0,
    },
]

RELATIONS: list[dict[str, Any]] = [
    {"from_key": "yan", "to_key": "tang", "kind": "hostility", "value": -0.9},
]

#: 粮道（乱的八年里，漕运几乎是朝廷的命脉）
TRADE_PAIRS: list[tuple[str, str, float]] = [
    ("changan", "luoyang", 180_000),
    ("luoyang", "suiyang", 120_000),
    ("taiyuan", "changan", 60_000),
    ("lingwu", "changan", 50_000),
]

# --------------------------------------------------------------------------- #
# 人物
# --------------------------------------------------------------------------- #
#: 品级与官职性质。品级 1 最高（三公），9 最低；闲职有官位而无实权。
#: 这些是**建模估值**，按唐代官制的大致序列给定，不作精确复原。
OFFICE_META: dict[str, tuple[int, str]] = {
    "li_longji": (1, "civil"),
    "li_heng": (1, "civil"),
    "li_chu": (2, "civil"),
    "yang_guozhong": (2, "civil"),
    "gao_xianzhi": (3, "military"),
    "feng_changqing": (3, "military"),
    "geshu_han": (2, "military"),
    "guo_ziyi": (3, "military"),
    "li_guangbi": (3, "military"),
    "zhang_xun": (6, "civil"),
    "li_bi": (5, "civil"),
    "yu_chaoen": (4, "envoy"),
    "pugu_huai_en": (3, "military"),
    "an_lushan": (2, "military"),
    "shi_siming": (3, "military"),
    "an_qingxu": (3, "military"),
    "shi_chaoyi": (3, "military"),
}

#: role: emperor / minister / general / eunuch / rebel
CHARACTERS: list[dict[str, Any]] = [
    {
        "key": "li_longji", "name": "李隆基", "alias": "玄宗", "role": "emperor",
        "office": "皇帝", "faction_key": "tang", "born": 685, "died": 762,
        "ability": 0.62, "loyalty": 1.0, "ambition": 0.0,
        "location_region_key": "changan",
        "bio": "在位四十余年，开元盛世的开创者，晚年倦于政事，宠信安禄山。",
        "source": "《旧唐书·玄宗本纪》",
    },
    {
        "key": "li_heng", "name": "李亨", "alias": "肃宗", "role": "emperor",
        "office": "太子（后即位）", "faction_key": "tang", "born": 711, "died": 762,
        "ability": 0.55, "loyalty": 1.0, "ambition": 0.5,
        "location_region_key": "changan",
        "bio": "玄宗第三子。乱起后北上灵武即位，主持平叛，然受制于宦官与藩镇。",
        "source": "《旧唐书·肃宗本纪》",
    },
    {
        "key": "yang_guozhong", "name": "杨国忠", "role": "minister",
        "office": "宰相", "faction_key": "tang", "born": None, "died": 756,
        "ability": 0.30, "loyalty": 0.55, "ambition": 0.6,
        "location_region_key": "changan",
        "bio": "杨贵妃族兄，以聚敛与迎合得幸。与安禄山交恶，屡言其必反。",
        "source": "《旧唐书·杨国忠传》",
    },
    {
        "key": "gao_xianzhi", "name": "高仙芝", "role": "general",
        "office": "副元帅", "faction_key": "tang", "born": None, "died": 756,
        "ability": 0.78, "loyalty": 0.70, "ambition": 0.2,
        "location_region_key": "tongguan",
        "bio": "高丽人，安西名将。守潼关，因退守被宦官构陷而死。",
        "source": "《旧唐书·高仙芝传》",
    },
    {
        "key": "feng_changqing", "name": "封常清", "role": "general",
        "office": "范阳节度使（名义）", "faction_key": "tang", "born": None, "died": 756,
        "ability": 0.76, "loyalty": 0.72, "ambition": 0.15,
        "location_region_key": "luoyang",
        "bio": "安西名将，临时募兵守洛阳，兵不堪战而败，退守潼关，与高仙芝同死。",
        "source": "《旧唐书·封常清传》",
    },
    {
        "key": "geshu_han", "name": "哥舒翰", "role": "general",
        "office": "兵马副元帅", "faction_key": "tang", "born": None, "died": 757,
        "ability": 0.80, "loyalty": 0.60, "ambition": 0.25,
        "location_region_key": "tongguan",
        "bio": "突厥人，陇右名将，病废在家，被强起守潼关。出战而败，被俘降燕。",
        "source": "《旧唐书·哥舒翰传》",
    },
    {
        "key": "guo_ziyi", "name": "郭子仪", "role": "general",
        "office": "朔方节度使", "faction_key": "tang", "born": 697, "died": 781,
        "ability": 0.85, "loyalty": 0.95, "ambition": 0.10,
        "location_region_key": "lingwu",
        "bio": "朔方军统帅，平叛主力。用兵持重，善抚士卒，为唐廷所倚。",
        "source": "《旧唐书·郭子仪传》",
    },
    {
        "key": "li_guangbi", "name": "李光弼", "role": "general",
        "office": "河东节度使", "faction_key": "tang", "born": 708, "died": 764,
        "ability": 0.88, "loyalty": 0.80, "ambition": 0.20,
        "location_region_key": "taiyuan",
        "bio": "契丹人，与郭子仪齐名。太原之战以少胜多，号为中兴第一。",
        "source": "《旧唐书·李光弼传》",
    },
    {
        "key": "zhang_xun", "name": "张巡", "role": "general",
        "office": "真源令", "faction_key": "tang", "born": 709, "died": 757,
        "ability": 0.75, "loyalty": 0.95, "ambition": 0.05,
        "location_region_key": "suiyang",
        "bio": "守睢阳十月，屏蔽江淮，粮尽而城破，与许远同死。",
        "source": "《旧唐书·张巡传》",
    },
    {
        "key": "an_lushan", "name": "安禄山", "role": "rebel",
        "office": "范阳平卢河东节度使", "faction_key": "yan", "born": 703, "died": 757,
        "ability": 0.70, "loyalty": 0.0, "ambition": 1.0,
        "location_region_key": "fanyang",
        "bio": "营州杂胡，以骁勇与逢迎得玄宗宠信，兼领三镇，拥兵最盛。起兵四年后为子所杀。",
        "source": "《旧唐书·安禄山传》",
    },
    {
        "key": "shi_siming", "name": "史思明", "role": "rebel",
        "office": "平卢兵马使", "faction_key": "yan", "born": 703, "died": 761,
        "ability": 0.78, "loyalty": 0.0, "ambition": 0.95,
        "location_region_key": "fanyang",
        "bio": "与安禄山同乡里，同日起兵。禄山死后自立，再陷洛阳，终为子所杀。",
        "source": "《旧唐书·史思明传》",
    },
    {
        "key": "an_qingxu", "name": "安庆绪", "role": "rebel",
        "office": "晋王", "faction_key": "yan", "born": None, "died": 759,
        "ability": 0.40, "loyalty": 0.0, "ambition": 0.7,
        "location_region_key": "luoyang",
        "bio": "安禄山次子。杀父自立，不能驭众，弃洛阳走邺，为史思明所杀。",
        "source": "《旧唐书·安庆绪传》",
    },
    {
        "key": "shi_chaoyi", "name": "史朝义", "role": "rebel",
        "office": "怀王", "faction_key": "yan", "born": None, "died": 763,
        "ability": 0.42, "loyalty": 0.0, "ambition": 0.6,
        "location_region_key": "fanyang",
        "bio": "史思明长子。杀父自立，为诸将所轻，兵败自缢于温泉栅，乱由此平。",
        "source": "《旧唐书·史朝义传》",
    },
    {
        "key": "li_chu", "name": "李俶", "alias": "代宗", "role": "emperor",
        "office": "广平王（后即位）", "faction_key": "tang", "born": 727, "died": 779,
        "ability": 0.58, "loyalty": 1.0, "ambition": 0.4,
        "location_region_key": "changan",
        "bio": "肃宗长子。以天下兵马元帅名义收复两京，后即位，借回纥兵平乱，然藩镇之势已成。",
        "source": "《旧唐书·代宗本纪》",
    },
    {
        "key": "pugu_huai_en", "name": "仆固怀恩", "role": "general",
        "office": "朔方节度使", "faction_key": "tang", "born": None, "died": 765,
        "ability": 0.72, "loyalty": 0.65, "ambition": 0.55,
        "location_region_key": "lingwu",
        "bio": "铁勒族，朔方名将，平乱后期主力。功高而为人所忌，终至叛走。",
        "source": "《旧唐书·仆固怀恩传》",
    },
    {
        "key": "yu_chaoen", "name": "鱼朝恩", "role": "eunuch",
        "office": "观军容使", "faction_key": "tang", "born": 722, "died": 770,
        "ability": 0.30, "loyalty": 0.45, "ambition": 0.80,
        "location_region_key": "changan",
        "bio": "宦官，监九节度之军于邺城。不通兵事而掣肘诸将，邺城之败与其相关。",
        "source": "《旧唐书·鱼朝恩传》",
    },
    {
        "key": "li_bi", "name": "李泌", "role": "minister",
        "office": "谋臣（未任宰相）", "faction_key": "tang", "born": 722, "died": 789,
        "ability": 0.86, "loyalty": 0.85, "ambition": 0.15,
        "location_region_key": "lingwu",
        "bio": "肃宗为太子时旧识，乱中赴行在，屡献平叛之策，多为人所阻。",
        "source": "《旧唐书·李泌传》",
    },
]

# --------------------------------------------------------------------------- #
# 军队
# --------------------------------------------------------------------------- #
ARMIES: list[dict[str, Any]] = [
    {"key": "fanyang_army", "name": "范阳军", "faction_key": "yan", "commander_key": "an_lushan",
     "region_key": "fanyang", "troops": 150_000, "morale": 0.85, "supply": 0.80},
    {"key": "hebei_army", "name": "河北降军", "faction_key": "yan", "commander_key": "shi_siming",
     "region_key": "hebei_plain", "troops": 80_000, "morale": 0.65, "supply": 0.60},
    {"key": "tongguan_army", "name": "潼关守军", "faction_key": "tang", "commander_key": "geshu_han",
     "region_key": "tongguan", "troops": 200_000, "morale": 0.45, "supply": 0.50},
    {"key": "shuofang_army", "name": "朔方军", "faction_key": "tang", "commander_key": "guo_ziyi",
     "region_key": "lingwu", "troops": 60_000, "morale": 0.80, "supply": 0.70},
    {"key": "hedong_army", "name": "河东军", "faction_key": "tang", "commander_key": "li_guangbi",
     "region_key": "taiyuan", "troops": 50_000, "morale": 0.75, "supply": 0.65},
    {"key": "suiyang_army", "name": "睢阳守军", "faction_key": "tang", "commander_key": "zhang_xun",
     "region_key": "suiyang", "troops": 7_000, "morale": 0.90, "supply": 0.35},
    {"key": "huihu_cavalry", "name": "回纥骑兵", "faction_key": "tang", "commander_key": None,
     "region_key": "lingwu", "troops": 4_000, "morale": 0.90, "supply": 0.85,
     "raises_at": dt.date(762, 10, 1)},
    {"key": "yecheng_army", "name": "九节度之师", "faction_key": "tang", "commander_key": "pugu_huai_en",
     "region_key": "luoyang", "troops": 200_000, "morale": 0.55, "supply": 0.45,
     "raises_at": dt.date(758, 9, 1)},
]

# --------------------------------------------------------------------------- #
# 史实事件年表
# --------------------------------------------------------------------------- #
#: conditions 可用的键：
#:   region_held: 某地区仍在某势力手中
#:   region_lost: 某地区已失
#:   character_alive: 某人仍在世
#: 不满足 conditions 时，事件标记为 diverged，写入史实改道记录。
HISTORICAL_EVENTS: list[dict[str, Any]] = [
    {
        "key": "uprising_fanyang",
        "date": dt.date(755, 11, 9),
        "title": "安禄山起兵范阳",
        "category": "rebellion",
        "description": "安禄山以奉密诏讨杨国忠为名，率范阳、平卢、河东三镇兵十五万南下。",
        "conditions": {"character_alive": "an_lushan"},
        "effects": {"morale": {"fanyang_army": 0.1}},
        "divergence_note": "安禄山已不在，范阳之变未发。",
        "source": "《资治通鉴》卷二一七",
    },
    {
        "key": "luoyang_falls",
        "date": dt.date(755, 12, 12),
        "title": "洛阳失守",
        "category": "battle",
        "description": "封常清募兵守洛阳，皆市井庸保，一触即溃。洛阳陷，安禄山称帝于洛阳。",
        "conditions": {"region_held": "luoyang", "character_alive": "feng_changqing"},
        "effects": {"lose_region": "luoyang", "legitimacy": -0.06, "treasury": -200_000},
        "divergence_note": "洛阳未失，叛军南下的势头在此被遏止。",
        "source": "《资治通鉴》卷二一七",
    },
    {
        "key": "tongguan_falls",
        "date": dt.date(756, 6, 8),
        "title": "潼关失守",
        "category": "battle",
        "description": "哥舒翰被迫出关野战，中伏大败，潼关陷落，关中门户洞开。",
        "conditions": {"region_held": "tongguan", "character_alive": "geshu_han"},
        "effects": {"lose_region": "tongguan", "legitimacy": -0.10, "treasury": -250_000},
        "divergence_note": "潼关未失，长安暂安。",
        "source": "《资治通鉴》卷二一八",
        # 史书说"使者相继"，催战的是玄宗与杨国忠。这里把决定权交给用户。
        "fork": {
            "title": "催哥舒翰出战",
            "description": (
                "哥舒翰守潼关，坚壁不出，奏称「利在坚守，不利轻出」。"
                "杨国忠疑其拥兵自重，力请催促出战。使者已至潼关，去与不去，系于此诏。"
            ),
            "options": [
                {
                    "key": "order_attack",
                    "label": "遣使催战",
                    "detail": "按史载：唐军出关遇伏大败，潼关失守，长安门户洞开",
                    "outcome": "historical",
                },
                {
                    "key": "hold_position",
                    "label": "令其坚守",
                    "detail": "潼关不失，长安得安；但二十万大军坐食，府库月耗十余万贯",
                    "outcome": "diverge",
                    "effects": {
                        "treasury": -400_000,
                        "legitimacy": 0.04,
                        "morale": {"tongguan_army": -0.05},
                    },
                },
                {
                    "key": "replace_commander",
                    "label": "换将出战",
                    "detail": "临阵易帅，军心浮动：潼关未必失，但守军战力大损",
                    "outcome": "diverge",
                    "effects": {
                        "treasury": -200_000,
                        "legitimacy": -0.03,
                        "morale": {"tongguan_army": -0.20},
                    },
                },
            ],
        },
    },
    {
        "key": "changan_falls",
        "date": dt.date(756, 6, 13),
        "title": "玄宗奔蜀，长安陷落",
        "category": "politics",
        "description": "潼关既失，玄宗仓皇出奔，长安为叛军所占。",
        "conditions": {"region_lost": "tongguan"},
        "effects": {"lose_region": "changan", "legitimacy": -0.12},
        "divergence_note": "潼关仍在唐军之手，长安未陷，朝廷得以坐镇关中。",
        "source": "《资治通鉴》卷二一八",
    },
    {
        "key": "mawei",
        "date": dt.date(756, 7, 15),
        "title": "马嵬驿之变",
        "category": "court",
        "description": "禁军哗变，杀杨国忠，逼玄宗缢杀杨贵妃。",
        "conditions": {"character_alive": "yang_guozhong"},
        "effects": {"kill": ["yang_guozhong"], "legitimacy": -0.05},
        "divergence_note": "杨国忠未死，朝局走向不同。",
        "source": "《资治通鉴》卷二一八",
    },
    {
        "key": "suzong_enthroned",
        "date": dt.date(756, 8, 12),
        "title": "肃宗即位灵武",
        "category": "politics",
        "description": "太子李亨于灵武即位，遥尊玄宗为太上皇，重整号令。",
        "conditions": {"character_alive": "li_heng"},
        "effects": {"legitimacy": 0.06},
        "divergence_note": "李亨已不在，唐廷未能另立中枢。",
        "source": "《资治通鉴》卷二一八",
    },
    {
        "key": "suiyang_siege",
        "date": dt.date(756, 11, 1),
        "title": "睢阳被围",
        "category": "battle",
        "description": "张巡、许远守睢阳，屏蔽江淮漕运，被围十月。",
        "conditions": {"region_held": "suiyang", "character_alive": "zhang_xun"},
        "effects": {"supply": {"suiyang_army": -0.3}},
        "divergence_note": "睢阳未受围，江淮漕运安稳。",
        "source": "《资治通鉴》卷二一九",
        "fork": {
            "title": "睢阳告急",
            "description": (
                "睢阳被围，城中兵不满万，粮将尽。张巡遣使求援，"
                "而周边唐军各拥兵观望。救与不救，朝廷须给个说法。"
            ),
            "options": [
                {
                    "key": "send_relief",
                    "label": "严令周边赴援",
                    "detail": "府库 −300,000 贯，睢阳可久守，江淮漕运不绝",
                    "outcome": "diverge",
                    "effects": {
                        "treasury": -300_000,
                        "supply": {"suiyang_army": 0.35},
                        "legitimacy": 0.05,
                    },
                },
                {
                    "key": "abandon",
                    "label": "弃睢阳，退保江淮",
                    "detail": "按史载：援军不至，城破，张巡死节；江淮震动",
                    "outcome": "historical",
                },
                {
                    "key": "order_hold",
                    "label": "责其死守，不加援兵",
                    "detail": "不花钱，但睢阳必陷，张巡生死难料，天下寒心",
                    "outcome": "diverge",
                    "effects": {
                        "legitimacy": -0.06,
                        "supply": {"suiyang_army": -0.30},
                    },
                },
            ],
        },
    },
    {
        "key": "an_lushan_killed",
        "date": dt.date(757, 2, 1),
        "title": "安禄山为其子所杀",
        "category": "rebellion",
        "description": "安庆绪与近侍谋杀安禄山，自称帝位，叛军内部开始离心。",
        "conditions": {"character_alive": "an_lushan"},
        "effects": {"kill": ["an_lushan"], "morale": {"fanyang_army": -0.15}},
        "divergence_note": "安禄山仍在，叛军号令如一。",
        "source": "《资治通鉴》卷二一九",
    },
    {
        "key": "changan_recovered",
        "date": dt.date(757, 10, 18),
        "title": "收复长安",
        "category": "battle",
        "description": "广平王俶与郭子仪率军收复长安，肃宗还京。",
        "conditions": {"region_lost": "changan", "character_alive": "guo_ziyi"},
        "effects": {"gain_region": "changan", "gain_region_extra": ["tongguan"], "legitimacy": 0.10},
        "divergence_note": "长安未复，或已由唐军掌握。",
        "source": "《资治通鉴》卷二二〇",
    },
    {
        "key": "luoyang_recovered",
        "date": dt.date(757, 12, 3),
        "title": "收复洛阳",
        "category": "battle",
        "description": "唐军收复洛阳，安庆绪北走邺城。",
        "conditions": {"region_lost": "luoyang", "character_alive": "guo_ziyi"},
        "effects": {"gain_region": "luoyang", "legitimacy": 0.08},
        "divergence_note": "洛阳仍在叛军手中。",
        "source": "《资治通鉴》卷二二〇",
    },
    # ---------------- 758–763 ----------------
    {
        "key": "yecheng_siege",
        "date": dt.date(758, 10, 1),
        "title": "九节度围邺城",
        "category": "battle",
        "description": "唐廷以九节度之师合围邺城，然不置元帅，以宦官鱼朝恩为观军容使，诸军不相统属。",
        "conditions": {"region_held": "luoyang"},
        "effects": {"treasury": -600_000},
        "divergence_note": "洛阳已失，邺城之围未成。",
        "source": "《资治通鉴》卷二二〇",
    },
    {
        "key": "yecheng_defeat",
        "date": dt.date(759, 3, 1),
        "title": "邺城之败",
        "category": "battle",
        "description": "史思明自范阳南下救邺，唐军九节度各自溃退，甲仗资粮尽失。",
        "conditions": {"region_held": "luoyang", "character_alive": "shi_siming"},
        "effects": {
            "morale": {"yecheng_army": -0.25, "shuofang_army": -0.10},
            "legitimacy": -0.10,
            "treasury": -400_000,
        },
        "divergence_note": "史思明未能南下，邺城之败未发生。",
        "source": "《资治通鉴》卷二二一",
        "fork": {
            "title": "邺城久围不下",
            "description": (
                "九节度的军队把邺城围了半年，城破在即，但诸军无统属，"
                "监军鱼朝恩又屡屡掣肘。是催促急攻，还是再等一等？"
            ),
            "options": [
                {
                    "key": "rush_attack",
                    "label": "催诸军急攻",
                    "detail": "按史载：史思明南下，唐军大溃，甲仗尽失",
                    "outcome": "historical",
                },
                {
                    "key": "wait_and_starve",
                    "label": "久围待其自溃",
                    "detail": "府库 −350,000 贯；不冒险野战，然师老于外",
                    "outcome": "diverge",
                    "effects": {
                        "treasury": -350_000,
                        "morale": {"yecheng_army": -0.10},
                        "legitimacy": 0.03,
                    },
                },
                {
                    "key": "unify_command",
                    "label": "授一人总统诸军",
                    "detail": "府库 −150,000 贯；诸军归一，邺城未必即下，但可免大溃",
                    "outcome": "diverge",
                    "effects": {
                        "treasury": -150_000,
                        "legitimacy": 0.05,
                        "morale": {"yecheng_army": 0.10},
                    },
                },
            ],
        },
    },
    {
        "key": "pursue_qingxu",
        "date": dt.date(758, 1, 5),
        "title": "是否穷追安庆绪",
        "category": "battle",
        "description": (
            "两京既复，安庆绪北走邺城，余众尚十万。"
            "诸将请乘胜追之，朝中则有议：师老兵疲，宜先休整。"
        ),
        "conditions": {"region_held": "luoyang", "character_alive": "an_qingxu"},
        "effects": {"treasury": -300_000, "morale": {"yecheng_army": -0.10}},
        "divergence_note": "安庆绪已不在，无从追讨。",
        "source": "《资治通鉴》卷二二〇",
        "fork": {
            "title": "邺城未下",
            "description": (
                "唐军已复两京，安庆绪退保邺城。诸将请乘胜急攻，"
                "监军以为士卒疲敝，宜待来春。追与不追，在此一决。"
            ),
            "options": [
                {
                    "key": "pursue",
                    "label": "乘胜急攻",
                    "detail": "府库 −300,000 贯；叛乱可望速平，然师老兵疲，若顿兵城下则陷于被动",
                    "outcome": "historical",
                },
                {
                    "key": "rest",
                    "label": "休整再图",
                    "detail": "府库 −150,000 贯，士气回升；但安庆绪得以喘息，史思明有时间整合其众",
                    "outcome": "diverge",
                    "effects": {
                        "treasury": -150_000,
                        "morale": {"yecheng_army": 0.15},
                        "legitimacy": -0.02,
                    },
                },
                {
                    "key": "offer_amnesty",
                    "label": "许其归降",
                    "detail": "不费兵戈；若安庆绪受抚，乱可早平，若诈降则养虎为患",
                    "outcome": "diverge",
                    "effects": {"treasury": -80_000, "legitimacy": 0.03},
                },
            ],
        },
    },
    {
        "key": "strip_guo_ziyi",
        "date": dt.date(759, 5, 1),
        "title": "郭子仪被夺兵权",
        "category": "court",
        "description": (
            "邺城之败，监军鱼朝恩归罪于郭子仪，肃宗召其还京，以李光弼代领朔方军。"
            "临阵易帅，诸将不平。"
        ),
        "conditions": {"character_alive": "guo_ziyi"},
        "effects": {"morale": {"shuofang_army": -0.20}, "legitimacy": -0.04},
        "divergence_note": "郭子仪已不在，无从夺其兵权。",
        "source": "《资治通鉴》卷二二一",
        "fork": {
            "title": "邺城败后，谁任朔方",
            "description": (
                "九节度溃于邺城，总要有人担这个责。一步错，军心便散——"
                "是留郭子仪，还是听监军之言换人？"
            ),
            "options": [
                {
                    "key": "replace_guo",
                    "label": "召郭子仪还京，以李光弼代之",
                    "detail": "按史载：临阵易帅，朔方军心大损；李光弼虽能，然将士不服",
                    "outcome": "historical",
                },
                {
                    "key": "keep_guo",
                    "label": "留郭子仪领朔方",
                    "detail": "军心不散，然监军与朝中非议不止，朝廷威望略损",
                    "outcome": "diverge",
                    "effects": {
                        "morale": {"shuofang_army": 0.10},
                        "legitimacy": -0.03,
                    },
                },
                {
                    "key": "dual_command",
                    "label": "郭、李并任，分领其军",
                    "detail": "府库 −200,000 贯；两将相济，然事权不一，号令难齐",
                    "outcome": "diverge",
                    "effects": {
                        "treasury": -200_000,
                        "morale": {"shuofang_army": 0.05, "hedong_army": 0.05},
                    },
                },
            ],
        },
    },
    {
        "key": "shi_siming_kills_qingxu",
        "date": dt.date(759, 4, 1),
        "title": "史思明杀安庆绪自立",
        "category": "rebellion",
        "description": "史思明入邺城，杀安庆绪，收其众，自称大燕皇帝。叛军换了主人，势头反而更盛。",
        "conditions": {"character_alive": "shi_siming"},
        "effects": {"morale": {"hebei_army": 0.10}, "kill": ["an_qingxu"]},
        "divergence_note": "史思明已不在，安庆绪未为所杀。",
        "source": "《资治通鉴》卷二二一",
    },
    {
        "key": "luoyang_falls_again",
        "date": dt.date(759, 9, 1),
        "title": "史思明再陷洛阳",
        "category": "battle",
        "description": "史思明乘胜南下，再据洛阳，唐军退保陕州。",
        "conditions": {"region_held": "luoyang", "character_alive": "shi_siming"},
        "effects": {"lose_region": "luoyang", "legitimacy": -0.08},
        "divergence_note": "洛阳未再失守。",
        "source": "《资治通鉴》卷二二一",
    },
    {
        "key": "shi_siming_killed",
        "date": dt.date(761, 3, 1),
        "title": "史思明为其子所杀",
        "category": "rebellion",
        "description": "史朝义与部将谋杀史思明，自立。叛军连杀两主，人心渐散。",
        "conditions": {"character_alive": "shi_siming"},
        "effects": {"kill": ["shi_siming"], "morale": {"hebei_army": -0.20}},
        "divergence_note": "史思明仍在，叛军号令如一。",
        "source": "《资治通鉴》卷二二二",
    },
    {
        "key": "borrow_huihu",
        "date": dt.date(762, 10, 1),
        "title": "借回纥兵",
        "category": "politics",
        "description": "代宗即位，欲借回纥骑兵平乱，许以厚赏。回纥可汗亲率精锐南下。",
        "conditions": {"region_lost": "luoyang", "character_alive": "li_chu"},
        "effects": {"treasury": -500_000, "legitimacy": -0.03},
        "divergence_note": "洛阳未失，或无需借兵。",
        "source": "《资治通鉴》卷二二二",
        "fork": {
            "title": "是否借回纥兵",
            "description": (
                "回纥可汗愿以精骑助战，条件是破城之后任其劫掠。"
                "朝中有人以为可解燃眉之急，也有人以为引狼入室。"
            ),
            "options": [
                {
                    "key": "borrow",
                    "label": "借兵平乱",
                    "detail": "按史载：回纥助战，洛阳收复，然东都再遭劫掠，民心大失",
                    "outcome": "historical",
                },
                {
                    "key": "refuse_huihu",
                    "label": "不借，自以唐军平之",
                    "detail": "府库 −700,000 贯；不欠回纥人情，但战事拖延，伤亡更重",
                    "outcome": "diverge",
                    "effects": {
                        "treasury": -700_000,
                        "legitimacy": 0.04,
                        "morale": {"yecheng_army": -0.10},
                    },
                },
                {
                    "key": "borrow_with_terms",
                    "label": "借兵但约法三章",
                    "detail": "府库 −900,000 贯；重金换取约束，洛阳可保，府库大损",
                    "outcome": "diverge",
                    "effects": {
                        "treasury": -900_000,
                        "legitimacy": 0.08,
                    },
                },
            ],
        },
    },
    {
        "key": "luoyang_recovered_2",
        "date": dt.date(762, 11, 1),
        "title": "再复洛阳",
        "category": "battle",
        "description": "唐军与回纥合兵，再克洛阳，史朝义北走。",
        "conditions": {"region_lost": "luoyang"},
        "effects": {"gain_region": "luoyang", "legitimacy": 0.08},
        "divergence_note": "洛阳未复。",
        "source": "《资治通鉴》卷二二二",
    },
    {
        "key": "reward_warlords",
        "date": dt.date(763, 2, 1),
        "title": "如何安置河北降将",
        "category": "politics",
        "description": (
            "史朝义既死，其部将田承嗣、李怀仙等以河北降。"
            "朝中或请尽徙其众以绝后患，或请就地授以节度使以安反侧。"
        ),
        "conditions": {"character_dead": "shi_chaoyi"},
        "effects": {"legitimacy": 0.06},
        "divergence_note": "乱事未平，无从安置。",
        "source": "《资治通鉴》卷二二二",
        "fork": {
            "title": "河北归降，如何处置",
            "description": (
                "降将拥兵数万，交出战马甲仗，却仍据其城、统其众。"
                "朝廷若强徙其众，恐激而生变；若就地授节，则河北自此不复为朝廷所有。"
            ),
            "options": [
                {
                    "key": "appoint_them",
                    "label": "就地授节度使",
                    "detail": "按史载：田承嗣等各领其州，河朔三镇自此形成，割据近百年",
                    "outcome": "historical",
                    "effects": {"nominal_control": ["fanyang", "hebei_plain"]},
                },
                {
                    "key": "relocate",
                    "label": "尽徙其众于关中",
                    "detail": "府库 −800,000 贯；藩镇之患可免，然途中生变之险极大",
                    "outcome": "diverge",
                    "effects": {
                        "treasury": -800_000,
                        "legitimacy": 0.08,
                        "unrest": {"hebei_plain": 0.15},
                    },
                },
                {
                    "key": "divide",
                    "label": "分其众为数镇，互不统属",
                    "detail": "府库 −300,000 贯；强弱相制，可收其权，然需长期经营",
                    "outcome": "diverge",
                    "effects": {
                        "treasury": -300_000,
                        "legitimacy": 0.05,
                        "unrest": {"hebei_plain": 0.05},
                    },
                },
            ],
        },
    },
    {
        "key": "shi_chaoyi_dead",
        "date": dt.date(763, 1, 1),
        "title": "史朝义自尽，安史之乱平",
        "category": "rebellion",
        "description": "史朝义走投无路，自缢于温泉栅。历时八年的安史之乱至此平定。",
        "conditions": {"character_alive": "shi_chaoyi", "region_held": "luoyang"},
        "effects": {"kill": ["shi_chaoyi"], "legitimacy": 0.10, "morale": {"hebei_army": -0.40}},
        "divergence_note": "史朝义未败，乱事未平。",
        "source": "《资治通鉴》卷二二二",
    },
]


# --------------------------------------------------------------------------- #
# 写入
# --------------------------------------------------------------------------- #
#: 真实边界：由唐朝七道按历史情形切分而来，见 tools/build_geo_755.py
_GEO_PATH = Path(__file__).with_name("data") / "tang_755_geo.json"
_GEO: dict[str, Any] = (
    json.loads(_GEO_PATH.read_text(encoding="utf-8"))["dao"]
    if _GEO_PATH.exists()
    else {}
)


def _geo(key: str):
    """取真实边界；缺失时明确报错，不退回方块糊弄。"""
    if key not in _GEO:
        raise LookupError(f"缺少 {key} 的地理数据，请先运行 tools/build_geo_755.py")
    return _GEO[key]


def seed(session: Session) -> World:
    world = World(
        key=WORLD_KEY,
        name="安史之乱",
        era="天宝十四载至广德元年（755–763）",
        description=(
            "安史之乱模拟器的第一个切片：安禄山起兵至史朝义败亡的八年。"
            "玩家以唐廷身份，在真实历史起点上做决策，看历史如何分叉。"
        ),
        start_date=START_DATE,
        provenance=SOURCE_NOTES,
        scenario=SCENARIO,
    )
    session.add(world)
    session.flush()

    from ..engine.rules import GRAIN_PER_CAPITA_MONTH, SEASON_FACTOR

    season_sum = sum(SEASON_FACTOR)
    for item in REGIONS:
        annual_need = item["population"] * GRAIN_PER_CAPITA_MONTH * 12
        session.add(
            Region(
                world_id=world.id,
                key=item["key"],
                name=item["name"],
                level="region",
                lat=item["lat"],
                lon=item["lon"],
                geo=_geo(item["key"]),
                population=item["population"],
                farmland=round(annual_need * 1.02 / season_sum, 1),
                grain_stock=round(item["population"] * GRAIN_PER_CAPITA_MONTH * 4, 1),
                tax_rate=0.08,
                price_index=1.0,
                unrest=0.0,
                faction_key=item["faction_key"],
                data_quality={
                    "population": "estimate",
                    "grain_stock": "assumption",
                    "geo": "approximate",
                },
            )
        )

    for item in FACTIONS:
        session.add(Faction(world_id=world.id, **item))

    for item in RELATIONS:
        session.add(FactionRelation(world_id=world.id, **item))

    for a_key, b_key, capacity in TRADE_PAIRS:
        for src, dst in ((a_key, b_key), (b_key, a_key)):
            session.add(
                TradeLink(
                    world_id=world.id,
                    from_key=src,
                    to_key=dst,
                    kind="grain",
                    capacity=capacity,
                    loss=0.08,
                )
            )

    for item in CHARACTERS:
        rank, kind = OFFICE_META.get(item["key"], (5, "civil"))
        session.add(
            Character(world_id=world.id, office_rank=rank, office_kind=kind, **item)
        )

    for item in ARMIES:
        session.add(Army(world_id=world.id, **item))

    for item in HISTORICAL_EVENTS:
        session.add(HistoricalEvent(world_id=world.id, **item))

    session.flush()
    return world


KNOWLEDGE: list[dict[str, Any]] = [
    {
        "slug": "anlushan-background",
        "title": "安史之乱的起因",
        "source": "《资治通鉴》卷二一七概述",
        "reliability": "secondary",
        "content": (
            "安禄山兼领范阳、平卢、河东三镇，拥兵近二十万，占天下劲兵之半。"
            "他与宰相杨国忠交恶，双方屡次在玄宗面前互告，朝廷既不能制，又不能抚。\n\n"
            "天宝十四载十一月，安禄山以「奉密诏讨杨国忠」为名起兵。"
            "承平既久，河北州县望风瓦解，朝廷仓促募兵，多市井之人，不习战阵。\n\n"
            "叛军南下的直接后果是洛阳失守；而潼关能否守住，决定了长安的安危。"
        ),
    },
    {
        "slug": "tongguan-decision",
        "title": "潼关之败的争议",
        "source": "《资治通鉴》卷二一八概述",
        "reliability": "secondary",
        "content": (
            "哥舒翰守潼关，主张据险坚守、待叛军自疲。杨国忠疑其拥兵自重，"
            "力促玄宗催战，使者相继，翰不得已出关。\n\n"
            "唐军出关后遭伏大败，潼关失守，长安门户洞开，玄宗西奔。"
            "后世论者多以为：若坚守不出，长安或不至陷落，历史将大不相同。"
        ),
    },
    {
        "slug": "pingpan-forces",
        "title": "平叛的主力",
        "source": "《旧唐书》郭子仪、李光弼传概述",
        "reliability": "secondary",
        "content": (
            "平叛主要依靠朔方军与河东军。郭子仪以朔方节度使起兵，"
            "李光弼守太原，以少胜多，二人并称中兴名将。\n\n"
            "唐廷为求速胜，借兵回纥，并许以厚赏；又以节度使名号酬功，"
            "藩镇之势由此愈重——平叛成功的同时，也埋下了此后百年的割据。"
        ),
    },
    {
        "slug": "suiyang",
        "title": "睢阳之战",
        "source": "《旧唐书·张巡传》概述",
        "reliability": "secondary",
        "content": (
            "张巡、许远守睢阳，以数千之众拒叛军十余万，前后十月。"
            "睢阳当江淮漕运之冲，城在则江淮之粟可输关中，城破则漕运断绝。\n\n"
            "粮尽，食马、食雀鼠，终至城破。时人多以为睢阳一城之守，"
            "保全了江淮，是平叛得以维持的关键。"
        ),
    },
]