# -*- coding: utf-8 -*-
"""
投资组合分析模块

方法论来源（业界成熟的开源投资工具的核心方法）：
- empyrical / pyfolio-reloaded：年化收益、年化波动、夏普比率、最大回撤
- PyPortfolioOpt / Riskfolio-Lib：风险平价（Risk Parity，桥水全天候策略核心）、
  最小方差配置（Markowitz 均值-方差模型解析解）

为兼容 Streamlit Cloud（Python 3.14）与 1GB 内存限制，
上述方法均用 numpy 原生实现（cvxpy/scipy 等重依赖的计算结果在
长组合场景下与解析解等价），零额外依赖风险。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


TRADING_DAYS = 252  # A股一年约 252 个交易日


# ================================================================
# 单只基金的风险收益指标
# ================================================================

def compute_fund_metrics(nav_df: pd.DataFrame, window_days: int = 252) -> Optional[Dict]:
    """
    根据净值历史计算风险收益指标。

    参数：
        nav_df: 需含「净值日期」「单位净值」列
        window_days: 取最近多少个交易日（默认 1 年）

    返回：
        {
            "ann_return": 年化收益率(小数),
            "ann_vol": 年化波动率(小数),
            "sharpe": 夏普比率(无风险利率取0),
            "max_drawdown": 最大回撤(负数小数),
            "days": 有效净值天数,
        }
        数据不足返回 None
    """
    if nav_df is None or len(nav_df) < 30:
        return None

    df = nav_df.copy()
    df["净值日期"] = pd.to_datetime(df["净值日期"], errors="coerce")
    df = df.dropna(subset=["净值日期", "单位净值"]).sort_values("净值日期")
    df["单位净值"] = pd.to_numeric(df["单位净值"], errors="coerce")
    df = df.dropna(subset=["单位净值"])

    if len(df) < 30:
        return None

    df = df.tail(window_days).reset_index(drop=True)
    nav = df["单位净值"].values.astype(float)

    # 日收益率
    rets = np.diff(nav) / nav[:-1]
    rets = rets[np.isfinite(rets)]
    if len(rets) < 20:
        return None

    # 年化收益（区间累计收益年化）
    n_years = len(rets) / TRADING_DAYS
    total_return = nav[-1] / nav[0] - 1
    ann_return = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0

    # 年化波动率
    ann_vol = float(np.std(rets, ddof=1) * np.sqrt(TRADING_DAYS))

    # 夏普比率（无风险利率取 0，简化口径）
    sharpe = float(ann_return / ann_vol) if ann_vol > 1e-8 else 0.0

    # 最大回撤
    cummax = np.maximum.accumulate(nav)
    drawdowns = nav / cummax - 1
    max_dd = float(np.min(drawdowns))

    return {
        "ann_return": float(ann_return),
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "days": len(df),
    }


# ================================================================
# 资产配置模型
# ================================================================

def risk_parity_weights(volatilities: Dict[str, float]) -> Dict[str, float]:
    """
    风险平价权重（反波动率法，Risk Parity 的简化经典实现）：
        w_i = (1 / σ_i) / Σ(1 / σ_j)

    直觉：波动越小的基金配越多，让每只基金对组合的风险贡献大致相等。
    这是桥水「全天候策略」的核心思想，适合新手的稳健配置。
    """
    inv = {k: 1.0 / max(v, 1e-6) for k, v in volatilities.items()}
    total = sum(inv.values())
    return {k: v / total for k, v in inv.items()}


def min_variance_weights(returns_dict: Dict[str, pd.Series]) -> Optional[Dict[str, float]]:
    """
    最小方差组合（Markowitz 均值-方差模型的解析解）：
        w = Σ^-1 · 1 / (1' · Σ^-1 · 1)

    若解析解出现负权重（做空），则退化为风险平价（基金只能买入）。
    """
    codes = list(returns_dict.keys())
    if len(codes) < 2:
        return None

    rets = pd.DataFrame({c: returns_dict[c] for c in codes}).dropna()
    if len(rets) < 30:
        return None

    cov = rets.cov().values * TRADING_DAYS
    try:
        ones = np.ones(len(codes))
        inv_cov = np.linalg.pinv(cov)
        w = inv_cov @ ones
        w = w / w.sum()
        if np.any(w < -0.01):  # 出现明显做空权重 → 基金不适用，退化为风险平价
            vols = {c: float(rets[c].std(ddof=1) * np.sqrt(TRADING_DAYS)) for c in codes}
            return risk_parity_weights(vols)
        w = np.clip(w, 0, None)
        w = w / w.sum()
        return {c: float(x) for c, x in zip(codes, w)}
    except np.linalg.LinAlgError:
        return None


# ================================================================
# 一站式：给定基金列表 + 总金额，输出智能配置建议
# ================================================================

def build_smart_allocation(
    funds: List[Tuple[str, str]],
    total_amount: float,
    fetcher=None,
    progress_callback=None,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    参数：
        funds: [(基金代码, 基金名称), ...]
        total_amount: 投资总金额
        fetcher: FundDataFetcher 实例（需有 get_fund_nav_history 方法）
        progress_callback: 可选回调，每处理完一只调用 (idx, total, code)

    返回：
        (结果 DataFrame, 警告列表)
        DataFrame 列：基金代码/基金名称/年化收益/年化波动/夏普比率/最大回撤/
                     风险平价权重/风险平价金额/等权金额
    """
    warnings: List[str] = []
    rows = []
    vols: Dict[str, float] = {}
    returns_dict: Dict[str, pd.Series] = {}

    for idx, (code, name) in enumerate(funds, 1):
        if progress_callback:
            progress_callback(idx, len(funds), code)
        try:
            fname, nav_df, err = fetcher.get_fund_nav_history(code)
            m = compute_fund_metrics(nav_df)
            if m is None:
                warnings.append(f"{code} {name}：净值数据不足（需至少 30 个交易日），已跳过")
                continue
            vols[code] = m["ann_vol"]
            # 收集日收益序列供最小方差模型使用
            tmp = nav_df.copy()
            tmp["净值日期"] = pd.to_datetime(tmp["净值日期"], errors="coerce")
            tmp["单位净值"] = pd.to_numeric(tmp["单位净值"], errors="coerce")
            tmp = tmp.dropna(subset=["净值日期", "单位净值"]).sort_values("净值日期").tail(252)
            returns_dict[code] = tmp.set_index("净值日期")["单位净值"].pct_change().dropna()

            rows.append({
                "基金代码": code,
                "基金名称": name or fname or "",
                "年化收益": m["ann_return"],
                "年化波动": m["ann_vol"],
                "夏普比率": m["sharpe"],
                "最大回撤": m["max_drawdown"],
            })
        except Exception as e:
            warnings.append(f"{code} {name}：数据获取失败（{type(e).__name__}），已跳过")

    if not rows:
        return pd.DataFrame(), warnings

    result = pd.DataFrame(rows)

    # 风险平价权重
    rp = risk_parity_weights({r["基金代码"]: r["年化波动"] for _, r in result.iterrows()})
    result["风险平价权重"] = result["基金代码"].map(rp)
    result["建议金额(风险平价)"] = (result["风险平价权重"] * total_amount).round(2)

    # 等权对比
    n = len(result)
    result["等权金额"] = round(total_amount / n, 2)

    # 最小方差权重（有两只以上共同净值时）
    mv = min_variance_weights(returns_dict) if len(returns_dict) >= 2 else None
    if mv:
        result["最小方差权重"] = result["基金代码"].map(mv).fillna(0.0)
        result["建议金额(最小方差)"] = (result["最小方差权重"] * total_amount).round(2)

    result = result.sort_values("年化波动").reset_index(drop=True)
    return result, warnings


def format_pct(x: float) -> str:
    """格式化为百分比字符串。"""
    try:
        return f"{x * 100:.2f}%"
    except Exception:
        return "—"
