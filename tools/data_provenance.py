"""把当前 WorldBranch 里"每个数字从哪来"打印出来。

史理说得通的前提，是使用者知道哪些是史料、哪些是建模假设。

    python tools/data_provenance.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.seed import anlushan_755 as m  # noqa: E402

#: 逐项说明。凡未列入者，一律视为"未在本切片建模"。
FIELD_NOTES = {
    "人口": ("量级估算", "取史载州口数的量级，不逐州复原"),
    "耕地": ("由人口与丰度反推", "保证存粮/产出不自相矛盾，非史载数字"),
    "存粮": ("模拟假设", "按人口 × 人均月耗 × 存粮月数设定"),
    "粮价指数": ("模拟假设", "以 1.00 为常态基准，非史载物价"),
    "民变指数": ("模拟假设", "0–1 归一，0.35 起视为动荡"),
    "税率": ("按制度设定", "租庸调大致相当于产出的 8%，不作精确复原"),
    "府库": ("量级估算", "唐廷与燕军各给一个可支撑数年战事的量级"),
    "人物才略": ("建模估值", "0–1，由史载战绩与评价折算，非原文数据"),
    "人物忠诚": ("建模估值", "由本模拟的功高/威望/野心规则演化"),
    "人物野心": ("建模估值", "由史载行事风格折算，用于驱动离心"),
    "兵力": ("史载量级", "取各军史载兵额的近似值，作示意"),
    "士气/补给": ("模拟假设", "0–1，用于让战力有可比较的差异"),
    "战力": ("规则推导", "兵员 × 士气/补给系数 × 主帅系数，非史载"),
    "事件日期": ("史载年月", "只记年或只记月者按最可能月份归位"),
    "事件条件": ("建模设定", "为让史实可被改道而设的判断条件"),
    "朝议立场": ("规则推导", "由角色/才略/忠诚/野心与选项后果算出，非奏议原文"),
}

NOT_MODELED = [
    "逐州人口与户口",
    "真实物价与货币购买力",
    "具体的行军路线与地形",
    "个人性格的细节差异",
    "回纥、吐蕃的独立意志",
    "朝廷内部的党争细节",
]


def main() -> int:
    print("=" * 76)
    print("安史之乱切片（755–763）数据来源说明")
    print("=" * 76)
    print()
    print("史料依据：")
    for source in m.SOURCE_NOTES["sources"]:
        print(f"  · {source}")
    print()
    print("逐项来源：")
    print(f"  {'项目':<12}{'性质':<16}说明")
    for field, (kind, note) in FIELD_NOTES.items():
        print(f"  {field:<12}{kind:<16}{note}")
    print()
    print("全局声明：")
    for note in m.SOURCE_NOTES["notes"]:
        print(f"  · {note}")
    print()
    print("本切片未建模：")
    for item in NOT_MODELED:
        print(f"  · {item}")
    print()
    print("=" * 76)
    print(f"人物 {len(m.CHARACTERS)} · 军队 {len(m.ARMIES)} · "
          f"史实事件 {len(m.HISTORICAL_EVENTS)} · "
          f"岔路口 {sum(1 for e in m.HISTORICAL_EVENTS if e.get('fork'))}")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())