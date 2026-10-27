"""模拟规则：纯函数，不碰数据库、不碰随机数。

把「条件变化后会发生什么」写成可执行、可单测的公式，
是设计文档里「模拟规则」这一层的落地。

数值口径（单一世界的内部单位，不对外承诺史实精度）：
- 人口：人
- 粮食：石
- 财政：贯（示意）
所有系数都放在常量里，方便日后按世界替换成不同规则包。
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# 参数
# --------------------------------------------------------------------------- #
#: 人均每月口粮（石）
GRAIN_PER_CAPITA_MONTH = 0.42

#: 各月农事强度系数（1.0 为常年平均），秋收月显著偏高
SEASON_FACTOR: tuple[float, ...] = (
    0.35, 0.40, 0.75, 0.95, 1.05, 1.05,   # 1-6 月
    1.10, 1.20, 1.85, 1.75, 0.95, 0.55,   # 7-12 月，8-10 月秋收
)

#: 粮价对存粮月数的敏感度
PRICE_ELASTICITY = 0.55
#: 价格回归目标所需的存粮安全月数
SAFE_STOCK_MONTHS = 4.0
#: 价格每月回归速度
PRICE_RECOVERY = 0.25
#: 单月粮价涨幅上限（饥荒时价格会跳，但不会一个月翻十倍）
MAX_PRICE_JUMP = 1.9
#: 粮价封顶
PRICE_CAP = 6.0

#: 缺粮对民变的推动系数
UNREST_PER_SHORTAGE = 2.2
#: 民变自然回落速度
UNREST_DECAY = 0.06
#: 粮价高于该值开始累积民变
UNREST_PRICE_THRESHOLD = 1.6

#: 每名军士每月的军费（贯）。募兵制下军队是财政最大的开销。
MILITARY_UPKEEP_RATIO = 2.0
#: 百官俸禄、宫廷与行政等固定开销占岁入的比重
COURT_OVERHEAD_RATIO = 0.3
#: 财政赤字的合法性惩罚：按"每百万贯赤字扣 0.04"计，
#: 而不是按贯数直接乘系数（那样一次 50 万贯赤字就会把合法性一次打光）
LEGITIMACY_DEFICIT_SCALE = 1_000_000.0
LEGITIMACY_DEFICIT_PENALTY = 0.04

#: 调出方至少要保住的存粮月数（不能把保命粮卖光）
EXPORT_SAFETY_MONTHS = 3.0
#: 每单位粮食跨道调运的默认途耗
DEFAULT_TRADE_LOSS = 0.08


@dataclass(frozen=True)
class RegionTick:
    """一个地区单月结算的中间结果。"""

    production: float
    consumption: float
    shortage: float
    tax_revenue: float
    stock_after: float
    price_after: float
    unrest_after: float


def season_factor(month: int) -> float:
    """month 取 1..12。"""
    return SEASON_FACTOR[(month - 1) % 12]


def target_price(stock: float, consumption: float) -> float:
    """存粮越薄，价格越高；达到安全月数时回到 1.0。"""
    if consumption <= 0:
        return 1.0
    months = max(stock, 0.0) / consumption
    ratio = max(months, 0.05) / SAFE_STOCK_MONTHS
    price = ratio ** (-PRICE_ELASTICITY)
    return min(max(price, 0.55), PRICE_CAP)


def step_region(
    *,
    population: int,
    grain_stock: float,
    farmland: float,
    tax_rate: float,
    price_index: float,
    unrest: float,
    month: int,
    production_multiplier: float = 1.0,
) -> RegionTick:
    """推进一个地区一个月。

    ``production_multiplier`` 由灾害、战乱等外部冲击给出，默认 1.0。
    """
    production = max(farmland * season_factor(month) * production_multiplier, 0.0)
    consumption = population * GRAIN_PER_CAPITA_MONTH

    net = grain_stock + production - consumption
    if net >= 0:
        shortage = 0.0
        stock_after = net
    else:
        shortage = -net
        stock_after = 0.0

    # 财政：按实际产量与税率征收，粮价影响折算
    tax_revenue = production * tax_rate * price_index

    # 粮价：先因短缺跳涨，再向目标价回归
    price = price_index
    if shortage > 0 and consumption > 0:
        jump = min(1.0 + UNREST_PER_SHORTAGE * (shortage / consumption), MAX_PRICE_JUMP)
        price = min(price * jump, PRICE_CAP)
    tgt = target_price(stock_after, consumption)
    price = price + (tgt - price) * PRICE_RECOVERY
    price = min(max(price, 0.55), PRICE_CAP)

    # 民变：缺粮直接推高，粮价过高缓慢累积，否则自然回落
    delta = 0.0
    if shortage > 0 and consumption > 0:
        delta += UNREST_PER_SHORTAGE * (shortage / consumption)
    if price > UNREST_PRICE_THRESHOLD:
        delta += 0.08 * (price - UNREST_PRICE_THRESHOLD)
    unrest_after = unrest + delta - UNREST_DECAY * unrest
    unrest_after = min(max(unrest_after, 0.0), 1.0)

    return RegionTick(
        production=production,
        consumption=consumption,
        shortage=shortage,
        tax_revenue=tax_revenue,
        stock_after=stock_after,
        price_after=price,
        unrest_after=unrest_after,
    )


def step_faction(
    *,
    treasury: float,
    legitimacy: float,
    military: float,
    revenue: float,
) -> tuple[float, float, float]:
    """势力单月结算，返回 (treasury, legitimacy, military)。

募兵制下军费是财政的最大项，再加上百官俸禄与宫廷开销，
岁入必须覆盖这两块才可能有结余——这也正是唐廷"看着富、其实紧"的原因。
"""
    upkeep = military * MILITARY_UPKEEP_RATIO
    overhead = revenue * COURT_OVERHEAD_RATIO
    net = treasury + revenue - overhead - upkeep
    if net < 0:
        penalty = min(abs(net) / LEGITIMACY_DEFICIT_SCALE, 1.0) * LEGITIMACY_DEFICIT_PENALTY
        legitimacy = max(legitimacy - penalty, 0.0)
    else:
        legitimacy = min(legitimacy + 0.002, 1.0)
    return net, legitimacy, military


def severity_from_ratio(ratio: float) -> int:
    """把「严重程度比例」映射到 1..5 的等级。"""
    if ratio <= 0:
        return 1
    if ratio < 0.15:
        return 2
    if ratio < 0.4:
        return 3
    if ratio < 0.8:
        return 4
    return 5


# --------------------------------------------------------------------------- #
# 跨区域调运
# --------------------------------------------------------------------------- #
def exportable_surplus(
    stock: float,
    consumption: float,
    safety_months: float = EXPORT_SAFETY_MONTHS,
) -> float:
    """调出方最多能拿出多少粮：高于「安全存粮线」的部分才算余粮。"""
    return max(stock - consumption * safety_months, 0.0)


def delivered_amount(amount: float, loss: float = DEFAULT_TRADE_LOSS) -> float:
    """扣除途耗后实际到达对方手里的粮量。"""
    return max(amount, 0.0) * (1.0 - max(0.0, min(loss, 0.9)))


def price_after_import(price: float, stock_after: float, consumption: float) -> float:
    """进口方补上粮之后，价格向新的目标价回落（不会一步到位）。"""
    return price + (target_price(stock_after, consumption) - price) * 0.55


def price_after_export(price: float, stock_after: float, consumption: float) -> float:
    """调出方存粮减少，价格向新的目标价上抬。"""
    return price + (target_price(stock_after, consumption) - price) * 0.35