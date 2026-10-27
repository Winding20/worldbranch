"""规则层单测：不依赖数据库，保证公式本身正确、可解释。"""

from __future__ import annotations

import pytest

from app.engine import rules


def test_season_factor_peaks_in_autumn():
    assert rules.season_factor(9) > rules.season_factor(2)
    assert rules.season_factor(10) > rules.season_factor(12)
    # 12 个月循环
    assert rules.season_factor(13) == rules.season_factor(1)


def test_target_price_full_stock_is_cheap():
    price = rules.target_price(stock=800.0, consumption=100.0)
    assert price < 1.0


def test_target_price_at_safe_level_is_neutral():
    price = rules.target_price(stock=400.0, consumption=100.0)
    assert price == pytest.approx(1.0)


def test_target_price_low_stock_is_expensive():
    price = rules.target_price(stock=10.0, consumption=100.0)
    assert price > 1.0


def test_region_with_enough_stock_has_no_shortage():
    tick = rules.step_region(
        population=100_000,
        grain_stock=2_000_000,
        farmland=60_000,
        tax_rate=0.08,
        price_index=1.0,
        unrest=0.0,
        month=3,
    )
    assert tick.shortage == 0.0
    assert tick.consumption == pytest.approx(100_000 * rules.GRAIN_PER_CAPITA_MONTH)
    assert tick.stock_after > 0


def test_region_shortage_raises_price_and_unrest():
    tick = rules.step_region(
        population=100_000,
        grain_stock=0.0,
        farmland=0.0,
        tax_rate=0.08,
        price_index=1.0,
        unrest=0.0,
        month=3,
    )
    assert tick.shortage > 0
    assert tick.stock_after == 0.0
    assert tick.price_after > 1.0
    assert tick.unrest_after > 0.0


def test_multiplier_reduces_production():
    base = rules.step_region(
        population=50_000, grain_stock=500_000, farmland=40_000,
        tax_rate=0.08, price_index=1.0, unrest=0.0, month=8,
    )
    shocked = rules.step_region(
        population=50_000, grain_stock=500_000, farmland=40_000,
        tax_rate=0.08, price_index=1.0, unrest=0.0, month=8,
        production_multiplier=0.55,
    )
    assert shocked.production < base.production
    assert shocked.tax_revenue < base.tax_revenue


def test_faction_deficit_lowers_legitimacy():
    treasury, legitimacy, _ = rules.step_faction(
        treasury=100.0, legitimacy=0.6, military=10_000.0, revenue=0.0
    )
    assert treasury < 0
    assert legitimacy < 0.6


def test_faction_surplus_raises_legitimacy():
    treasury, legitimacy, _ = rules.step_faction(
        treasury=100_000.0, legitimacy=0.6, military=0.0, revenue=500.0
    )
    assert treasury > 0
    assert legitimacy > 0.6


def test_severity_mapping_is_monotonic():
    values = [rules.severity_from_ratio(r) for r in (0.0, 0.1, 0.3, 0.6, 1.2)]
    assert values == sorted(values)
    assert values[0] == 1 and values[-1] == 5