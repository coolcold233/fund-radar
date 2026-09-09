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

    # --- 新手友好：术语小词典 ---
    st.subheader("📖 投资术语小词典（新手必读）")
    _render_glossary()


# ================================================================
# 新手友好：投资术语小词典
# ================================================================

# 术语表：词 → 通俗解释
GLOSSARY = [
    ("上证指数", "上海证券交易所最有代表性的股票平均价格指数，代码 000001，常被当作'大盘'的代名词，反映沪市整体涨跌。"),
    ("深证成指", "深圳证券交易所的核心指数，代码 399001，包含深市 500 只主要股票。"),
    ("创业板指", "代码 399006，由创新创业型公司组成，波动比主板大，涨得猛跌得也猛，属于高风险高收益。"),
    ("科创50", "代码 000688，科创板 50 只龙头股（多为半导体、硬科技），对科技行业景气度最敏感。"),
    ("涨停 / 跌停", "A股规定普通股票一天最多涨 10%（涨停）或跌 10%（跌停），到了就无法再成交。涨停家数多说明市场情绪火热。"),
    ("北向资金", "从香港流入内地股市的外资，被称为'聪明钱'。大幅流入通常被视为外资看好，大幅流出则偏谨慎。"),
    ("两市成交额", "上海+深圳两个交易所一天的成交总金额（亿元）。超万亿通常算'放量'（交易活跃），低于 6000 亿算'缩量'（观望情绪浓）。"),
    ("放量 / 缩量", "放量＝成交比平时活跃，趋势更可信；缩量＝交易清淡，行情可能没后劲。"),
    ("板块", "同一类公司的集合，如'半导体板块''医药板块'。板块轮动＝资金在不同行业间来回切换。"),
    ("结构性行情", "不是所有股票一起涨/跌，而是少数板块大涨、其他平淡。选错方向就会'赚了指数不赚钱'。"),
    ("普涨 / 普跌", "大部分股票一起涨（普涨，牛市特征）或一起跌（普跌，系统性调整）。"),
    ("股票仓位", "基金资产中买股票的比例。股票型基金仓位通常 80%-95%，所以基金涨跌≈持仓股票整体涨跌。"),
    ("净值", "基金每份的价格。基金一天只公布一次净值（晚上），不像股票实时跳动。"),
    ("美联储 / 降息 / 加息", "美联储是美国央行。降息＝印钱成本降低，利好股市；加息＝收紧，通常压制股市。它的动作影响全球市场。"),
    ("费城半导体指数", "美股半导体龙头股指数（代号 SOX），是全球科技股的'风向标'，它大涨往往带动 A股科技板块。"),
    ("风险偏好", "投资者愿不愿意承担风险。情绪高涨时大家敢买高风险成长股，情绪低迷时只敢买稳健的银行、消费。"),
]

def _render_glossary():
    """渲染投资术语小词典，新手友好。"""
    st.caption("看不懂复盘里的专业词？这里用大白话解释，点开即可查看。")
    # 用 tabs 分类
    tab1, tab2, tab3 = st.tabs(["📊 指数与行情", "💰 资金与情绪", "🌍 宏观与基金"])
    groups = [
        GLOSSARY[0:4],    # 指数
        GLOSSARY[4:10],   # 行情/资金
        GLOSSARY[10:],    # 宏观/基金
    ]
    for tab, items in zip([tab1, tab2, tab3], groups):
        with tab:
            for term, desc in items:
                with st.expander(f"🔹 {term}"):
                    st.write(desc)
    st.info("💡 **给新手的建议**：先从'定投宽基指数基金'（如跟踪沪深300、中证500的基金）开始，不要一上来就追热点板块。用'投资风格评估'页测测自己能承受多大波动，再决定买什么。")


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
    import html as _html
    news = data.get("news", [])
    if not news:
        st.info("暂无新闻数据。")
        return

    # 筛选器
    col_f1, col_f2, col_f3 = st.columns([1, 1, 2.5])
    with col_f1:
        show_level = st.multiselect(
            "重要性",
            options=["🔴 重大", "🟠 重要", "🟡 关注", "⚪ 一般"],
            default=["🔴 重大", "🟠 重要"],
            key="dr_news_level",
        )
    with col_f2:
        show_limit = st.selectbox("显示数量", [10, 20, 50], index=1, key="dr_news_limit")
    with col_f3:
        st.caption("💡 点击新闻标题可在新标签页打开原文；无原文链接时自动跳转搜索相关报道。")

    filtered = [n for n in news if n.get("level_label") in show_level]
    filtered = filtered[:show_limit]

    if not filtered:
        st.caption("当前筛选条件下无新闻。")
        return

    # 渲染：重要新闻卡片展开，一般新闻折叠
    for n in filtered:
        level = n.get("level", "normal")
        label = n.get("level_label", "⚪ 一般")
        title = _html.escape(n.get("title", ""))
        time = n.get("time", "")
        url = n.get("url", "")
        source = _html.escape(n.get("source", ""))
        summary = _html.escape(n.get("summary", ""))

        # 构造可点击标题
        if url:
            title_html = (
                f"<a href='{url}' target='_blank' rel='noopener noreferrer' "
                f"style='color:inherit;text-decoration:none;font-weight:600;'>"
                f"{title} <span style='color:#1c7ed6;font-size:0.85em;'>🔗原文↗</span></a>"
            )
        else:
            title_html = f"<span style='font-weight:600;'>{title}</span>"

        if level in ("critical", "important"):
            color = "#c92a2a" if level == "critical" else "#e8590c"
            bg = "#fff5f5" if level == "critical" else "#fff9f0"
            summary_html = f"<div style='font-size:0.85rem;color:#666;margin-top:0.3rem;'>{summary}</div>" if summary else ""
            st.markdown(
                f"<div style='padding:0.7rem 0.9rem;border-left:4px solid {color};"
                f"background:{bg};border-radius:6px;margin-bottom:0.5rem;'>"
                f"<div>{title_html}</div>"
                f"{summary_html}"
                f"<div style='font-size:0.78rem;color:#868e96;margin-top:0.3rem;'>⏰ {time} · 📰 {source}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            with st.expander(f"{label} {n.get('title','')[:50]}"):
                if url:
                    st.markdown(f"[🔗 点击查看原文/相关报道]({url})")
                st.caption(f"⏰ {time} · 📰 {source}")
                if summary:
                    st.write(summary)


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
