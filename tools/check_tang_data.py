"""校验唐朝切片的数据完整性。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.seed import anlushan_755 as m  # noqa: E402

ALLOWED = {"region_held", "region_lost", "character_alive", "character_dead"}


def main() -> int:
    print(f"人物 {len(m.CHARACTERS)}，军队 {len(m.ARMIES)}，事件 {len(m.HISTORICAL_EVENTS)}")

    keys = [e["key"] for e in m.HISTORICAL_EVENTS]
    dup = {k for k in keys if keys.count(k) > 1}
    assert not dup, f"事件 key 重复: {dup}"

    char_keys = {c["key"] for c in m.CHARACTERS}
    army_keys = {a["key"] for a in m.ARMIES}
    region_keys = {r["key"] for r in m.REGIONS}

    problems = []
    for event in m.HISTORICAL_EVENTS:
        for cond, value in (event.get("conditions") or {}).items():
            if cond not in ALLOWED:
                problems.append(f"{event['key']}: 未知条件 {cond}")
            elif cond in {"region_held", "region_lost"} and value not in region_keys:
                problems.append(f"{event['key']}: 未知地区 {value}")
            elif cond in {"character_alive", "character_dead"} and value not in char_keys:
                problems.append(f"{event['key']}: 未知人物 {value}")

        effects = event.get("effects") or {}
        for person in effects.get("kill") or []:
            if person not in char_keys:
                problems.append(f"{event['key']}: kill 未知人物 {person}")
        for army in (effects.get("morale") or {}):
            if army not in army_keys:
                problems.append(f"{event['key']}: morale 未知军队 {army}")
        for army in (effects.get("supply") or {}):
            if army not in army_keys:
                problems.append(f"{event['key']}: supply 未知军队 {army}")
        for key in ("lose_region", "gain_region"):
            if effects.get(key) and effects[key] not in region_keys:
                problems.append(f"{event['key']}: {key} 未知地区 {effects[key]}")

        fork = event.get("fork") or {}
        for option in fork.get("options") or []:
            if "outcome" not in option:
                problems.append(f"{event['key']}: 选项 {option.get('key')} 缺少 outcome")
            if option.get("outcome") == "historical" and not effects:
                problems.append(f"{event['key']}: 按史载的选项却没有 effects")

    # 每条时间线至少有一个「按史载」选项
    for event in m.HISTORICAL_EVENTS:
        fork = event.get("fork")
        if not fork:
            continue
        outcomes = [o.get("outcome") for o in fork["options"]]
        if "historical" not in outcomes:
            problems.append(f"{event['key']}: 岔路口缺少「按史载」选项")

    if problems:
        print("发现问题：")
        for p in problems:
            print("  ✗", p)
        return 1

    print("校验通过：事件 key、条件、效果引用的人物/军队/地区均存在")
    print(f"岔路口 {sum(1 for e in m.HISTORICAL_EVENTS if e.get('fork'))} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())