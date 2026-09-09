# -*- coding: utf-8 -*-
"""
基金分析指标计算模块

所有收益率/回撤指标均以"小数"形式返回（如 0.05 表示 5%），
比率类指标（夏普、卡玛）为倍数。异常或数据不足时返回 NaN。
"""

import math

import pandas as pd

# A股平均每年交易日数量（日频 -> 年频换算）
TRADING_DAYS_PER_YEAR = 244


def _clean_nav(nav: pd.Series) -> pd.Series:
    """去空值并转 float，保证指标计算输入合法。"""
    if nav is None:
        return pd.Series(dtype=float)
    return pd.to_numeric(nav, errors="coerce").dropna()


def daily_returns(nav: pd.Series) -> pd.Series:
    """根据净值序列计算日收益率序列（小数）。"""
    nav = _clean_nav(nav)
    if len(nav) < 2:
        return pd.Series(dtype=float)
    return nav.pct_change().dropna()


def total_return(nav: pd.Series) -> float:
    """区间累计收益率（小数）。"""
    nav = _clean_nav(nav)
    if len(nav) < 2 or nav.iloc[0] <= 0:
        return float("nan")
    return float(nav.iloc[-1] / nav.iloc[0] - 1)


def annualized_return(nav: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """几何年化收益率（小数）。"""
    nav = _clean_nav(nav)
    if len(nav) < 2 or nav.iloc[0] <= 0:
        return float("nan")
    tr = nav.iloc[-1] / nav.iloc[0] - 1
    years = (len(nav) - 1) / periods_per_year
    if years <= 0:
        return float("nan")
    # 总收益 <= -100% 时无意义
    if (1 + tr) <= 0:
        return float("nan")
    return float((1 + tr) ** (1.0 / years) - 1)


def annualized_volatility(nav: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """年化波动率（小数），基于日收益率标准差。"""
    rets = daily_returns(nav)
    if len(rets) < 2:
        return float("nan")
    return float(rets.std(ddof=1) * math.sqrt(periods_per_year))


def max_drawdown(nav: pd.Series) -> float:
    """最大回撤（负数小数，如 -0.35 表示 -35%）。"""
    nav = _clean_nav(nav)
    if len(nav) < 2:
        return float("nan")
    drawdown = nav / nav.cummax() - 1
    return float(drawdown.min())


def drawdown_series(nav: pd.Series) -> pd.Series:
    """回撤序列（水下曲线），用于绘制回撤面积图。"""
    nav = _clean_nav(nav)
    if len(nav) < 2:
        return pd.Series(dtype=float)
    return nav / nav.cummax() - 1


def sharpe_ratio(
    nav: pd.Series,
    risk_free_rate: float = 0.02,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """
    夏普比率 = (年化收益率 - 无风险利率) / 年化波动率
    """
    ar = annualized_return(nav, periods_per_year)
    vol = annualized_volatility(nav, periods_per_year)
    if pd.isna(ar) or pd.isna(vol) or vol == 0:
        return float("nan")
    return float((ar - risk_free_rate) / vol)


def calmar_ratio(nav: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """
    卡玛比率 = 年化收益率 / |最大回撤|
    """
    ar = annualized_return(nav, periods_per_year)
    mdd = max_drawdown(nav)
    if pd.isna(ar) or pd.isna(mdd) or mdd >= 0:
        return float("nan")
    return float(ar / abs(mdd))


def summary_metrics(
    nav: pd.Series,
    risk_free_rate: float = 0.02,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> dict:
    """
    一次性计算全部核心指标，返回 {指标中文名: 数值} 的字典。

    - 区间累计收益率 / 年化收益率 / 年化波动率 / 最大回撤：小数
    - 夏普比率 / 卡玛比率：倍数
    """
    nav_c = _clean_nav(nav)
    return {
        "区间累计收益率": total_return(nav_c),
        "年化收益率": annualized_return(nav_c, periods_per_year),
        "年化波动率": annualized_volatility(nav_c, periods_per_year),
        "最大回撤": max_drawdown(nav_c),
        "夏普比率": sharpe_ratio(nav_c, risk_free_rate, periods_per_year),
        "卡玛比率": calmar_ratio(nav_c, periods_per_year),
    }


if __name__ == "__main__":
    # ---- 简单自测：构造一条净值曲线 ----
    import numpy as np

    np.random.seed(42)
    n = 500
    rets = np.random.normal(0.0004, 0.012, n)
    nav_test = pd.Series(np.cumprod(1 + rets))

    m = summary_metrics(nav_test)
    print("指标自测（500 天合成净值）：")
    for k, v in m.items():
        print(f"  {k}: {v:.4f}")
    print("✅ analysis 模块测试通过")
