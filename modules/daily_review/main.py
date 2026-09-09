# -*- coding: utf-8 -*-
"""
当日股市复盘 - 页面主入口
组装所有模块渲染，对接 storage 和 data_fetcher。
"""

import datetime
import warnings
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from .storage import (
    save_daily_review, load_daily_review,
)
from .data_fetcher import (
    fetch_all_daily, NEWS_LEVELS, CRITICAL_KEYWORDS, IMPORTANT_KEYWORDS,
)

warnings.filterwarnings("ignore")


# ================================================================
# 渲染入口
# ================================================================

def render_daily_review():
    """当日股市复盘主页面。"""
    st.header("📅 当日股市复盘")

    today = datetime.date.today()
    weekday_cn = ["周一","周二","周三","周四","周五","周六","周日"][today.weekday()]

    is_after_close = datetime.datetime.now().hour >= 15
    is_weekend = today.weekday() >= 5
    target_date = today

    if is_weekend:
        st.info(f"📌 今天是{weekday_cn}，非交易日。默认显示最近一个交易日数据。")
        for offset in range(1, 8):
            d = today - datetime.timedelta(days=offset)
            if d.weekday() < 5:
                target_date = d
                break

    if not is_after_close and not is_weekend:
        st.warning("⚠️ 当前为盘中时间（15:00 前），以下数据为盘中快照，收盘后刷新为完整数据。")

    date_str = target_date.strftime("%Y-%m-%d")

    # 加载数据
    cache_key = f"dr_data_{date_str}"
    if cache_key not in st.session_state:
        cached = load_daily_review(date_str)
        if cached is not None:
            st.session_state[cache_key] = cached
        else:
            with st.spinner("🔄 正在拉取今日数据..."):
                data = fetch_all_daily()
                if data:
                    save_daily_review(date_str, data)
                    st.session_state[cache_key] = data
                else:
                    st.session_state[cache_key] = None

    data = st.session_state.get(cache_key)
    if data is None:
        st.error("数据加载失败，请检查网络后点击刷新按钮。")
        return

    # 刷新按钮 + 时间
    col_refresh, col_date = st.columns([1, 4])
    with col_refresh:
        if st.button("🔄 刷新数据", key="dr_refresh", use_container_width=True):
            st.cache_data.clear() if hasattr(st, 'cache_data') else None
            with st.spinner("重新拉取..."):
                data = fetch_all_daily()
                if data:
                    save_daily_review(date_str, data)
                    st.session_state[cache_key] = data
            st.rerun()
    with col_date:
        st.caption(f"📅 {date_str}（{weekday_cn}）｜更新：{data.get('review_time', '—')}｜数据源：新浪财经 + 东方财富")

    # 检查数据完整度
    market = data.get("market", {})
    has_index = any(k in market for k in ("shanghai", "shenzhen", "chinext", "star50"))
    has_sectors = bool(data.get("sectors", {}).get("top_gainers"))
    has_news = bool(data.get("news"))

    if not has_index:
        st.warning("⚠️ 大盘指数数据暂不可用（可能是交易日尚未结束，或数据源临时波动）。请稍后刷新。")

    # --- 模块1：大盘速览 ---
    st.subheader("📊 大盘速览")
    _render_market_overview(data)

    # --- 模块2：情绪温度计 ---
    st.subheader("🌡️ 市场情绪温度计")
    _render_sentiment(data)

    # --- 模块3：板块龙虎榜 ---
    st.subheader("🐉 板块涨跌龙虎榜")
    if has_sectors:
        _render_sector_ranking(data)
    else:
        st.info("板块涨跌数据暂不可用。")

    # --- 模块6：财经新闻 ---
    st.subheader("📰 今日重要财经新闻")
    _render_news(data)

    # --- 模块7：归因分析 ---
    st.subheader("🔍 今日市场归因分析")
    _render_attribution(data)

    # --- 模块9：基金追踪 ---
    st.subheader("💼 我的基金追踪")
    _render_fund_tracking(data)

    # --- 模块10：复盘笔记 ---
    st.subheader("📝 复盘笔记")
    _render_manual_notes(data, date_str)


# ================================================================
# 模块1：大盘速览
# ================================================================

def _render_market_overview(data: Dict):
    market = data.get("market", {})

    indices = {
        "shanghai": ("上证指数", "🔴/🟢"),
        "shenzhen": ("深证成指", "🔴/🟢"),
        "chinext": ("创业板指", "🔴/🟢"),
        "star50": ("科创50", "🔴/🟢"),
    }

    cols = st.columns(5)
    for i, (key, (label, _)) in enumerate(indices.items()):
        with cols[i]:
            info = market.get(key)
            if info and isinstance(info, dict):
                close = info.get("close", 0)
                pct = info.get("change_pct", 0)
                color = "🔴" if pct >= 0 else "🟢"
                st.metric(
                    label,
                    f"{close:.2f}",
                    f"{color} {pct:+.2f}%",
                    delta_color="normal",
                )
            else:
                st.metric(label, "—")

    # 两市成交额
    with cols[4]:
        total = market.get("total_amount")
        if total and total > 0:
            label = "放量" if total > 10000 else "缩量" if total < 6000 else ""
            st.metric("两市成交额", f"{total:.0f}亿", label if label else "")
        else:
            st.metric("两市成交额", "—")

    # 数据来源标注
    st.caption("数据来源：新浪实时行情（hq.sinajs.cn）｜盘中实时更新，收盘后锁定")


# ================================================================
# 模块2：情绪温度计
# ================================================================

def _render_sentiment(data: Dict):
    market = data.get("market", {})
    score = market.get("sentiment_score", 50)
    label = market.get("sentiment_label", "—")
    limit_up = market.get("limit_up_count", 0)
    limit_down = market.get("limit_down_count", 0)

    col1, col2 = st.columns([1, 3])
    with col1:
        # 情绪大卡片
        if score >= 70:
            bg = "linear-gradient(135deg,#ff6b6b,#ee5a24)"
        elif score >= 50:
            bg = "linear-gradient(135deg,#feca57,#ff9f43)"
        elif score >= 30:
            bg = "linear-gradient(135deg,#48dbfb,#0abde3)"
        else:
            bg = "linear-gradient(135deg,#576574,#222f3e)"

        st.markdown(
            f"<div style='text-align:center;padding:1.5rem;background:{bg};"
            f"border-radius:16px;color:white;box-shadow:0 4px 12px rgba(0,0,0,0.15);'>"
            f"<div style='font-size:3.5rem;font-weight:800;line-height:1;'>{score}</div>"
            f"<div style='font-size:1rem;opacity:0.9;margin-top:0.3rem;'>{label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    with col2:
        items = [
            ("涨停 / 跌停", f"{limit_up} / {limit_down}",
             "情绪活跃 🎆" if limit_up > 50 else ("情绪低迷 😴" if limit_up < 20 else "情绪一般")),
        ]
        sectors = data.get("sectors", {})
        if sectors.get("up_ratio"):
            up_pct = sectors["up_ratio"] * 100
            items.append(("上涨板块占比", f"{up_pct:.0f}%",
                          "普涨 🔥" if up_pct > 70 else ("普跌 ❄️" if up_pct < 30 else "分化 ⚡")))

        df = pd.DataFrame(items, columns=["指标", "数据", "判断"])
        st.dataframe(df, use_container_width=True, hide_index=True)


# ================================================================
# 模块3：板块龙虎榜
# ================================================================

def _render_sector_ranking(data: Dict):
    sectors = data.get("sectors", {})
    top_gainers = sectors.get("top_gainers", [])
    top_losers = sectors.get("top_losers", [])

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🔴 涨幅前10**")
        if top_gainers:
            df = pd.DataFrame(top_gainers)
            st.dataframe(df, use_container_width=True, hide_index=True)
    with c2:
        st.markdown("**🟢 跌幅前10**")
        if top_losers:
            df = pd.DataFrame(top_losers)
            st.dataframe(df, use_container_width=True, hide_index=True)


# ================================================================
# 模块6：财经新闻（分级展示）
# ================================================================

def _render_news(data: Dict):
    news = data.get("news", [])
    if not news:
        st.info("暂无新闻数据。")
        return

    # 筛选器
    col_f1, col_f2, _ = st.columns([1, 1, 3])
    with col_f1:
        show_level = st.multiselect(
            "重要性",
            options=["🔴 重大", "🟠 重要", "🟡 关注", "⚪ 一般"],
            default=["🔴 重大", "🟠 重要"],
            key="dr_news_level",
        )
    with col_f2:
        show_limit = st.selectbox("显示数量", [10, 20, 50], default_index=1, key="dr_news_limit")

    level_map = {v: k for k, v in NEWS_LEVELS.items()}
    filtered = [n for n in news if n.get("level_label") in show_level]
    filtered = filtered[:show_limit]

    if not filtered:
        st.caption("当前筛选条件下无新闻。")
        return

    # 分组展示：重大/重要 展开，一般 折叠
    for n in filtered:
        level = n.get("level", "normal")
        label = n.get("level_label", "⚪ 一般")
        title = n.get("title", "")
        time = n.get("time", "")

        if level in ("critical", "important"):
            # 重要新闻直接展开
            color = "#c92a2a" if level == "critical" else "#e8590c"
            st.markdown(
                f"<div style='padding:0.6rem 0.8rem;border-left:4px solid {color};"
                f"background:#fff5f5;border-radius:4px;margin-bottom:0.4rem;'>"
                f"<div style='font-weight:600;'>{label} {title}</div>"
                f"<div style='font-size:0.8rem;color:#868e96;margin-top:0.2rem;'>⏰ {time}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            # 一般新闻折叠
            with st.expander(f"{label} {title}"):
                st.caption(f"⏰ {time}")


# ================================================================
# 模块7：归因分析（用新闻+板块联动）
# ================================================================

def _render_attribution(data: Dict):
    market = data.get("market", {})
    sectors = data.get("sectors", {})
    news = data.get("news", [])

    # 大盘特征
    sh = market.get("shanghai") or {}
    cn = market.get("chinext") or {}
    sh_chg = sh.get("change_pct", 0)
    cn_chg = cn.get("change_pct", 0)
    up_ratio = sectors.get("up_ratio", 0.5)

    # 综合判断
    if sh_chg > 0.5 and cn_chg > 1:
        judgment = "今日A股收涨，创业板领涨，成长风格占优。"
    elif sh_chg < -0.5 and cn_chg < -1:
        judgment = "今日A股收跌，创业板领跌，风险偏好下降。"
    elif sh_chg > 0.5 and cn_chg < -0.5:
        judgment = "今日A股分化，大盘涨而创业板跌，价值风格占优。"
    elif sh_chg < -0.5 and cn_chg > 0.5:
        judgment = "今日A股分化，大盘跌而创业板涨，成长风格独立行情。"
    else:
        judgment = "今日A股窄幅震荡，多空博弈激烈。"

    # 提取关键新闻（critical + important）
    critical_news = [n for n in news if n.get("level") == "critical"]
    important_news = [n for n in news if n.get("level") == "important"]
    top_news = critical_news + important_news[:3]

    with st.container(border=True):
        st.markdown(f"**【综合判断】** {judgment}")
        st.markdown(f"📊 上证 {sh_chg:+.2f}% ｜ 创业板 {cn_chg:+.2f}% ｜ 上涨板块占比 {up_ratio*100:.0f}%")

        if top_news:
            st.markdown("**【驱动今日行情的核心新闻】**")
            for n in top_news[:5]:
                level_tag = n.get("level_label", "")
                title = n.get("title", "")
                time = n.get("time", "")
                st.markdown(f"- {level_tag} **{title}**（{time}）")
        else:
            st.markdown("今日无重大财经新闻驱动，行情以技术面/资金面为主。")

        st.markdown("**【行情类型】** " + sectors.get("market_type", "震荡分化"))
        st.markdown("**【归因可信度】** ⭐⭐⭐☆☆ （新闻+行情联动可提升可信度）")


# ================================================================
# 模块9：基金追踪
# ================================================================

def _render_fund_tracking(data: Dict):
    import sys
    from pathlib import Path
    project_root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(project_root / "src"))

    try:
        from database import DatabaseManager
        _db = DatabaseManager()
        holdings = _db.list_holdings()
        followed = _db.list_followed()
    except Exception:
        holdings = []
        followed = []

    all_sectors = (
        data.get("sectors", {}).get("top_gainers", []) +
        data.get("sectors", {}).get("top_losers", [])
    )

    def guess_sector(name: str) -> str:
        import re
        kw = [
            ("半导体|芯片|科创|中芯", "半导体"),
            ("新能源|光伏|锂电|电池|隆基", "新能源"),
            ("医药|医疗|健康|恒瑞", "医药"),
            ("消费|白酒|食品|饮料|茅台", "消费"),
            ("AI|人工智能|算力|科大讯飞", "人工智能"),
            ("军工|国防|航天|航发", "国防军工"),
            ("银行|金融|保险|招行", "金融"),
            ("地产|房地产|万科", "房地产"),
            ("煤炭|能源|中国神华", "煤炭"),
            ("有色|金属|铜|黄金|紫金", "有色金属"),
            ("汽车|新能源车|比亚迪", "汽车"),
            ("互联网|信息|软件|腾讯", "计算机"),
            ("白酒", "白酒"),
        ]
        for pattern, sec in kw:
            if re.search(pattern, name):
                return sec
        return "混合"

    def find_sector_change(sector_name: str) -> Optional[float]:
        for s in all_sectors:
            if sector_name in s.get("name", "") or s.get("name", "") in sector_name:
                return s.get("change_pct", 0)
        return None

    fund_list = []
    for h in holdings:
        fund_list.append({"code": h["fund_code"], "name": h.get("fund_name", ""),
                          "amount": float(h.get("amount", 0)), "source": "持仓"})
    for f in followed:
        code = f["fund_code"]
        if not any(h["code"] == code for h in fund_list):
            fund_list.append({"code": code, "name": f.get("fund_name", ""),
                              "amount": 0.0, "source": "关注"})

    if not fund_list:
        st.info("暂无持仓或关注基金。请先在「💼 持仓追踪」或「🔍 基金数据」页添加。")
        return

    rows = []
    for f in fund_list:
        sector = guess_sector(f["name"])
        sec_chg = find_sector_change(sector)
        est_chg = round(sec_chg * 0.85, 2) if sec_chg is not None else None

        if est_chg is not None:
            if est_chg > 2:
                status = "🟢 强势"
            elif est_chg < -2:
                status = "🔴 弱势"
            else:
                status = "🟡 震荡"
        else:
            status = "⏳ 板块数据待更新"

        rows.append({
            "基金代码": f["code"],
            "基金名称": f["name"],
            "数据来源": f["source"],
            "关联板块": sector,
            "板块涨跌": f"{sec_chg:+.2f}%" if sec_chg is not None else "—",
            "估算基金涨跌": f"{est_chg:+.2f}%" if est_chg is not None else "—",
            "状态": status,
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption("💡 估算逻辑：基金预估涨跌 = 关联板块涨跌 × 股票仓位比例（默认85%）。晚间基金净值更新后可对比验证。")


# ================================================================
# 模块10：复盘笔记
# ================================================================

def _render_manual_notes(data: Dict, date_str: str):
    notes_key = f"dr_notes_{date_str}"
    current = st.session_state.get(notes_key, data.get("manual_notes", ""))
    text = st.text_area(
        "今日复盘笔记",
        value=current,
        height=150,
        key=f"dr_notes_input_{date_str}",
        placeholder="记录你今天的判断、情绪、操作想法...",
    )
    if st.button("💾 保存笔记", key="dr_save_notes"):
        st.session_state[notes_key] = text
        data["manual_notes"] = text
        save_daily_review(date_str, data)
        st.success("笔记已保存。")
