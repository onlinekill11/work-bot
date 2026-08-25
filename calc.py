"""Расчёты по отчёту: профит, процент, фикс, итоговая выплата."""
from __future__ import annotations

import math
from dataclasses import dataclass

from config import BLOCK_FIX_PER_HOUR, BLOCK_PAY_MODE, PERCENT_TIERS


def percent_for(profit: float) -> float:
    """Процент работника в зависимости от общего профита."""
    for limit, percent in PERCENT_TIERS:
        if limit is None or profit < limit:
            return percent
    return PERCENT_TIERS[-1][1]


def money(value: float) -> str:
    """Красивый вывод денег: 96 -> «96$», 96.5 -> «96.5$»."""
    if abs(value - round(value)) < 0.005:
        return f"{int(round(value))}$"
    return f"{value:.2f}".rstrip("0").rstrip(".") + "$"


def hours_str(hours: float) -> str:
    total_minutes = int(round(hours * 60))
    h, m = divmod(total_minutes, 60)
    if m == 0:
        return f"{h} ч"
    return f"{h} ч {m} мин"


@dataclass(slots=True)
class Payout:
    start: float
    end: float
    disputes: float
    profit: float          # (end - disputes) - start
    percent: float         # ставка, %
    percent_pay: float     # заработок по проценту
    hours: float           # отработано часов (дробно)
    whole_hours: int       # целых часов — база для фикса
    has_blocks: bool
    fix_pay: float         # фикс за блоки (0, если блоков нет)
    total: float           # итог к выплате
    basis: str             # «процент» / «фикс»


def calculate(
    *,
    start: float,
    end: float,
    disputes: float,
    hours: float,
    has_blocks: bool,
) -> Payout:
    """Главная формула.

    Диспуты вычитаются из фактического конечного баланса, и только потом
    считается профит и процент работника.
    """
    clean_end = end - disputes
    profit = clean_end - start
    percent = percent_for(profit)
    percent_pay = round(profit / 100 * percent, 2) if profit > 0 else 0.0

    whole_hours = max(0, math.floor(hours))
    fix_pay = round(whole_hours * BLOCK_FIX_PER_HOUR, 2) if has_blocks else 0.0

    if has_blocks and BLOCK_PAY_MODE == "fix":
        total, basis = fix_pay, "фикс"
    elif has_blocks and fix_pay > percent_pay:
        total, basis = fix_pay, "фикс"
    else:
        total, basis = percent_pay, "процент"

    return Payout(
        start=start,
        end=end,
        disputes=disputes,
        profit=round(profit, 2),
        percent=percent,
        percent_pay=percent_pay,
        hours=hours,
        whole_hours=whole_hours,
        has_blocks=has_blocks,
        fix_pay=fix_pay,
        total=round(total, 2),
        basis=basis,
    )
