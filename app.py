# -*- coding: utf-8 -*-
import io
import math
import re
import sys
import time
import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

project_root = Path(__file__).parent
src_path = project_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from src.config import get_config
from src.data_fetcher import get_default_fetcher
from src.analysis import drawdown_series, summary_metrics
from src.portfolio_analytics import build_smart_allocation
from src.database import get_default_db

# 当日股市复盘模块
try:
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from modules.daily_review.main import render_daily_review
except Exception as _e:
    def render_daily_review():
        st.error(f"当日复盘模块加载失败：{_e}")

config = get_config()
_db = get_default_db()
_db.initialize_database()

# ---------------- 页面配置 ----------------
st.set_page_config(
    page_title="基金雷达 - 基金分析与筛选工具",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------- 全局 CSS 美化 ----------------
st.markdown(
    """
    <style>
    /* 整体字体和间距 */
    .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    section[data-testid="stSidebar"] { padding-top: 0.5rem; }

    /* 标题美化 */
    h1 { font-size: 1.8rem !important; }
    h2 { font-size: 1.3rem !important; padding-bottom: 0.3rem; border-bottom: 1px solid #eee; }
    h3 { font-size: 1.1rem !important; }

    /* Metric 卡片美化 */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #f8f9fa, #ffffff);
        border-radius: 12px;
        padding: 0.8rem 1rem;
        border: 1px solid #e9ecef;
    }

    /* Checkbox 紧凑模式 */
    div[data-testid="stCheckbox"] {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 0.2rem 0.5rem;
        margin: 0.15rem;
        min-width: 70px;
        text-align: center;
        font-size: 0.8rem;
        font-family: monospace;
        border: 1px solid #e9ecef;
        transition: all 0.15s;
    }
    div[data-testid="stCheckbox"]:hover {
        background: #e9ecef;
        border-color: #ced4da;
    }
    div[data-testid="stCheckbox"] label {
        font-size: 0.8rem !important;
        font-family: monospace !important;
    }

    /* 选中的 checkbox 高亮 */
    .stCheckbox:has(input:checked) > div:first-child {
        background: linear-gradient(135deg, #4dabf7, #339af0) !important;
        color: white !important;
        border-color: #339af0 !important;
        font-weight: 600;
    }
    .stCheckbox:has(input:checked) label { color: white !important; }

    /* Dataframe 美化 */
    div[data-testid="stDataFrame"] table { font-size: 0.85rem; }
    div[data-testid="stDataFrame"] th {
        background: #f1f3f5 !important;
        font-weight: 600;
        color: #495057;
    }

    /* Success/Info/Warning 条 */
    div[data-testid="stAlert"] { border-radius: 10px; }

    /* Sidebar 美化 */
    section[data-testid="stSidebar"] label { font-weight: 600; }

    /* Expander 美化 */
    details summary { font-weight: 600 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📊 基金雷达")
st.markdown("---")

# ---------------- 页面常量 ----------------
PAGE_HOME = "🏠 首页"
PAGE_DATA = "🔍 基金数据"
PAGE_SINGLE = "📈 单基金分析"
PAGE_COMPARE = "⚖️ 多基金对比"
PAGE_RISK = "🧭 投资风格评估"
PAGE_PORTFOLIO = "💼 持仓追踪"
PAGE_DAILY_REVIEW = "📅 当日股市复盘"
PAGE_MANAGE = "💾 数据管理"
PAGE_SETTINGS = "⚙️ 设置"
PAGES = [PAGE_HOME, PAGE_DATA, PAGE_SINGLE, PAGE_COMPARE, PAGE_RISK, PAGE_PORTFOLIO, PAGE_DAILY_REVIEW, PAGE_MANAGE, PAGE_SETTINGS]


# ===============================
# 用户偏好持久化（投资风格 / 设置）
# ===============================
def _init_preferences():
    """应用启动时从 SQLite 加载已保存的偏好到 session_state。

    在任何 widget 实例化之前调用，可安全写入 session_state。
    已存在的 session_state 键不会被覆盖（避免影响当前交互）。
    """
    prefs = _db.load_preferences()
    if not prefs:
        return

    # 投资风格评估结果
    mapping = {
        "risk_score": "risk_score",
        "risk_done": "risk_done",
        "risk_profile_name": "risk_profile_name",
        "risk_profile_desc": "risk_profile_desc",
        "risk_amount": "risk_amount",
    }
    for k, sk in mapping.items():
        v = prefs.get(k)
        if v is not None and sk not in st.session_state:
            st.session_state[sk] = v

    # 评估问卷答案（risk_horizon 等）
    answers = prefs.get("risk_answers", {})
    for qk, val in answers.items():
        sk = f"risk_{qk}"
        if sk not in st.session_state:
            st.session_state[sk] = val

    # 设置参数
    settings_map = {
        "settings_rf": "settings_rf",
        "settings_range": "settings_range",
        "settings_page_size": "settings_page_size",
        "settings_theme": "settings_theme",
    }
    for k, sk in settings_map.items():
        if k in prefs and sk not in st.session_state:
            st.session_state[sk] = prefs[k]


_init_preferences()


def save_risk_profile_to_db(score, profile_name, profile_desc, answers, amount):
    """保存投资风格评估结果到数据库。"""
    _db.save_preferences({
        "risk_score": int(score) if score is not None else None,
        "risk_done": True,
        "risk_profile_name": profile_name,
        "risk_profile_desc": profile_desc,
        "risk_answers": {k: v for k, v in (answers or {}).items()},
        "risk_amount": float(amount) if amount is not None else None,
    })


def save_settings_to_db():
    """保存设置参数到数据库。"""
    _db.save_preferences({
        "settings_rf": st.session_state.get("settings_rf"),
        "settings_range": st.session_state.get("settings_range"),
        "settings_page_size": st.session_state.get("settings_page_size"),
        "settings_theme": st.session_state.get("settings_theme"),
    })

# ---------------- 侧边栏 ----------------
with st.sidebar:
    st.header("🧭 导航菜单")
    page = st.radio("选择功能页面", options=PAGES, key="nav")
    st.markdown("---")
    st.caption("基金雷达 v0.5.0 (持仓追踪 + 偏好持久化)")
    st.caption("技术栈：Python + Streamlit + AKShare + SQLite")


# ===============================
# 工具函数：加载基金列表（带缓存）
# ===============================
@st.cache_data(ttl=3600, show_spinner=False)
def _load_fund_cache() -> tuple:
    """
    内部缓存函数：返回 (df, error_str, fetch_time_str)
    注意：如果手动刷新，外部通过 clear_cache 让此函数重新执行。
    """
    fetcher = get_default_fetcher()
    t0 = time.time()
    df, err = fetcher.get_all_fund_list()
    elapsed = round(time.time() - t0, 1)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    info = f"{ts}（耗时 {elapsed} 秒）"
    return df, err, info


def clear_fund_cache():
    """清空基金数据缓存，使下次调用重新从 AKShare 拉取。"""
    _load_fund_cache.clear()


def load_fund_data(force_refresh: bool = False):
    """对外统一入口：加载基金数据。"""
    if force_refresh:
        clear_fund_cache()
    return _load_fund_cache()


# ===============================
# 跨页面跳转工具（通过 session_state 控制导航）
# 说明：以下函数在按钮回调中执行，先于导航组件实例化，因此可安全修改其状态。
# ===============================
def goto_analysis(code: str):
    """跳转到单基金分析页并预填基金代码。"""
    st.session_state["analysis_code"] = str(code)
    st.session_state["nav"] = PAGE_SINGLE


def goto_compare(codes):
    """跳转到多基金对比页并预填基金代码列表。"""
    st.session_state["compare_input"] = ", ".join(str(c) for c in codes)
    st.session_state["nav"] = PAGE_COMPARE


def get_followed_map() -> dict:
    """获取关注基金映射：{6位代码: {"fund_name":..., "followed_at":...}}。"""
    return {str(f["fund_code"]).zfill(6): f for f in _db.list_followed()}


def now_cn() -> datetime.datetime:
    """返回北京时间（UTC+8）。云端 Streamlit 服务器默认是 UTC 时区，
    直接 datetime.now() 会比北京时间晚 8 小时，统一用本函数。"""
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)


def normalize_fund_codes(series: "pd.Series") -> "pd.Series":
    """基金代码列标准化为 6 位字符串（去掉可能的后缀）。"""
    return series.astype(str).str.split(".").str[0].str.strip().str.zfill(6)


# ===============================
# 页面：首页
# ===============================
def render_home():
    st.header("👋 欢迎使用基金雷达！")
    st.write("这是一个本地化的基金分析与筛选工具，帮助您分析和筛选优质基金。")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.info("**✅ 环境准备**\n\n- Python 3.12\n- Streamlit 已安装\n- AKShare 已安装\n- SQLite 已内置")

    with col2:
        st.warning(
            "**🔄 当前进度：第五阶段**\n\n"
            "- ✅ 项目目录已创建\n"
            "- ✅ 虚拟环境已配置\n"
            "- ✅ 依赖包已安装\n"
            "- ✅ 网页框架已搭建\n"
            "- ✅ 接入真实基金数据\n"
            "- ✅ 单基金分析 + 多基金对比\n"
            "- ✅ 基金档案 + 重仓股\n"
            "- ✅ 数据管理 + 投资风格评估 + 设置\n"
            "- ✅ 投资风格 / 设置 持久化保存（本阶段）\n"
            "- ✅ 持仓追踪：记录持仓基金，实时看重仓股涨跌（本阶段）\n"
            "- ⏳ 资产配置回测 / Flourish 导出（下一阶段）"
        )

    with col3:
        st.success(
            "**📋 后续计划**\n\n"
            "1. SQLite 本地缓存\n"
            "2. 多维度基金筛选\n"
            "3. 基金走势分析图表\n"
            "4. 多基金对比功能\n"
            "5. 更多功能..."
        )

    st.markdown("---")
    st.subheader("🖥️ 系统信息")
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"- **项目路径**: `{project_root}`")
        st.write(f"- **数据目录**: `{project_root / 'data'}`")
    with col2:
        st.write(f"- **源码目录**: `{project_root / 'src'}`")
        st.write(f"- **Python 版本**: `{sys.version.split()[0]}`")

    st.markdown("---")
    with st.expander("📖 如何使用（快速开始）", expanded=False):
        st.markdown(
            """
            ### 本地启动

            ```bash
            streamlit run app.py
            ```

            ### 在线访问

            本应用已部署到 Streamlit Cloud，可直接通过浏览器访问（手机/电脑均可）。

            > 💡 数据说明：基金行情数据通过 AKShare 和新浪财经 API 实时获取。用户偏好、持仓等数据存储在本地 SQLite，平台重启后可能重置。
            """
        )

    st.markdown("---")
    st.subheader("🧪 功能测试区")
    st.write("这里可以测试 Streamlit 的基础组件是否正常工作：")

    test_text = st.text_input("输入一些文字试试：", value="你好，基金雷达！")
    if test_text:
        st.success(f"✅ 输入成功！你输入的是：{test_text}")

    test_number = st.slider("选择一个数字：", 0, 100, 50)
    st.write(f"你选择的数字是：**{test_number}**")

    if st.button("🎉 点击测试一下"):
        st.balloons()
        st.success("太棒了！按钮点击成功，Streamlit 运行正常！")


# ===============================
# 页面：基金数据
# ===============================
def render_fund_data():
    st.header("🔍 基金数据")
    st.caption(
        "数据来源：AKShare（东方财富-天天基金网-开放式基金排行）。"
        "在表格左侧勾选基金行，可一键跳转到单基金分析或多基金对比。"
    )

    # ---- 顶部操作区 ----
    col_btn, col_info = st.columns([1, 4])
    with col_btn:
        refresh_clicked = st.button("🔄 刷新基金数据", type="primary", use_container_width=True)
    with col_info:
        st.caption("缓存 1 小时。点击按钮可强制从 AKShare 重新拉取。")

    # ---- 加载数据（含加载动画） ----
    force = bool(refresh_clicked)

    with st.spinner("正在从 AKShare 获取基金数据（首次约需 10~30 秒）..."):
        df, err, fetch_time = load_fund_data(force_refresh=force)

    # ---- 错误处理 ----
    if err is not None or df is None or len(df) == 0:
        st.error("基金数据获取失败，请检查网络连接或数据接口。")
        with st.expander("查看错误详情"):
            st.code(err if err else "未知错误：返回数据为空。", language="text")
        return

    total_count = len(df)

    # ---- 我的关注（置顶展示，打开页面即可注意到） ----
    followed_map = get_followed_map()
    with st.container(border=True):
        sub1, sub2 = st.columns([3, 2])
        with sub1:
            st.subheader(f"⭐ 我的关注（{len(followed_map)}）")
        with sub2:
            if followed_map:
                # 取消关注控件
                pick_options = [
                    f"{c} {m.get('fund_name') or '（名称未知）'}"
                    for c, m in followed_map.items()
                ]
                pick = st.selectbox(
                    "管理关注",
                    options=pick_options,
                    key="unfollow_pick",
                    label_visibility="collapsed",
                )
                if st.button("💔 取消关注", key="unfollow_btn"):
                    _db.unfollow_fund(str(pick).split(" ")[0])
                    st.rerun()

        if not followed_map:
            st.info(
                "💡 暂无关注的基金：在下方表格左侧勾选基金行，然后点击「⭐ 关注选中」即可关注；"
                "关注的基金会在这里置顶展示，并在表格中高亮提醒。"
            )
        else:
            # 合并关注列表与最新行情指标
            fdf = pd.DataFrame(
                [
                    {
                        "基金代码": c,
                        "基金简称": m.get("fund_name") or "",
                        "关注时间": m.get("followed_at", ""),
                    }
                    for c, m in followed_map.items()
                ]
            )
            df_norm = df.copy()
            if "基金代码" in df_norm.columns:
                df_norm["_code"] = normalize_fund_codes(df_norm["基金代码"])
                metric_cols = [
                    c for c in ["单位净值", "日增长率", "近1月", "近3月", "近1年", "今年来"]
                    if c in df_norm.columns
                ]
                fdf = fdf.merge(
                    df_norm[["_code"] + metric_cols].drop_duplicates("_code"),
                    left_on="基金代码",
                    right_on="_code",
                    how="left",
                ).drop(columns=["_code"])
            fdf["关注"] = "⭐"
            show_cols = ["关注", "基金代码", "基金简称"] + metric_cols + ["关注时间"]
            show_cols = [c for c in show_cols if c in fdf.columns]
            fmt_follow = {
                c: "{:.2f}%"
                for c in ["日增长率", "近1月", "近3月", "近1年", "今年来"]
                if c in fdf.columns
            }
            if "单位净值" in fdf.columns:
                fmt_follow["单位净值"] = "{:.4f}"
            st.dataframe(
                fdf[show_cols].style.format(formatter=fmt_follow, na_rep="—"),
                use_container_width=True,
                hide_index=True,
                height=min(46 * max(len(fdf), 1) + 38, 300),
            )

    # ---- 搜索 & 过滤 ----
    st.markdown("---")
    keyword = st.text_input(
        "搜索基金名称或代码",
        value="",
        placeholder="例如：161725 或 招商",
        key="fund_search",
    )

    shown_df = df
    if keyword:
        kw = str(keyword).strip().lower()
        if kw:
            mask = pd.Series(False, index=df.index)
            if "基金代码" in df.columns:
                mask = mask | df["基金代码"].astype(str).str.lower().str.contains(kw, na=False)
            if "基金简称" in df.columns:
                mask = mask | df["基金简称"].astype(str).str.lower().str.contains(kw, na=False)
            shown_df = df[mask].reset_index(drop=True)

    # 只看关注的基金
    if followed_map and "基金代码" in shown_df.columns:
        only_followed = st.checkbox(
            "⭐ 只看关注的基金",
            value=False,
            key="fd_only_followed",
            help="勾选后仅显示已关注的基金",
        )
        if only_followed:
            mask_f = normalize_fund_codes(shown_df["基金代码"]).isin(followed_map.keys())
            shown_df = shown_df[mask_f].reset_index(drop=True)

    shown_count = len(shown_df)

    # ---- 分页控件（真分页：每页仅渲染一页数据） ----
    page_size = int(st.selectbox("每页行数", [20, 50, 100, 200], index=1, key="fd_page_size"))
    max_page = max(1, math.ceil(shown_count / page_size))
    cur_page = int(st.session_state.get("fd_page", 1))
    cur_page = min(max(1, cur_page), max_page)
    st.session_state["fd_page"] = cur_page

    col_prev, col_page, col_next, col_info2 = st.columns([1, 1, 1, 4])
    with col_prev:
        st.button(
            "◀ 上一页",
            disabled=(cur_page <= 1),
            on_click=lambda: st.session_state.update(
                fd_page=max(1, st.session_state.get("fd_page", 1) - 1)
            ),
            use_container_width=True,
        )
    with col_page:
        st.number_input("页码", min_value=1, max_value=max_page, key="fd_page")
    with col_next:
        st.button(
            "下一页 ▶",
            disabled=(cur_page >= max_page),
            on_click=lambda: st.session_state.update(
                fd_page=min(max_page, st.session_state.get("fd_page", 1) + 1)
            ),
            use_container_width=True,
        )
    with col_info2:
        st.caption(
            f"共 {shown_count} 只基金 / {max_page} 页 ｜ 基金总数 {total_count} ｜ 数据更新时间：{fetch_time}"
        )

    start_idx = (int(st.session_state["fd_page"]) - 1) * page_size
    page_df = shown_df.iloc[start_idx : start_idx + page_size].copy().reset_index(drop=True)

    # ---- 红涨绿跌着色（A股习惯：涨红跌绿） ----
    rate_cols = [
        "日增长率", "近1周", "近1月", "近3月", "近6月",
        "近1年", "近2年", "近3年", "今年来", "成立来", "自定义",
    ]
    nav_cols = ["单位净值", "累计净值"]
    rate_present = [c for c in rate_cols if c in page_df.columns]
    nav_present = [c for c in nav_cols if c in page_df.columns]

    if "基金代码" in page_df.columns:
        page_df["基金代码"] = normalize_fund_codes(page_df["基金代码"])
        # 关注标记列（放在第一列，醒目）
        page_df.insert(0, "关注", page_df["基金代码"].map(lambda c: "⭐" if c in followed_map else ""))
    if "序号" in page_df.columns:
        page_df = page_df.drop(columns=["序号"])

    def _growth_color(val):
        """涨红跌绿着色规则。"""
        try:
            v = float(val)
        except (TypeError, ValueError):
            return None
        if pd.isna(v):
            return None
        if v > 0:
            return "color:#e03131;font-weight:600"
        if v < 0:
            return "color:#2f9e44;font-weight:600"
        return None

    styler = page_df.style
    fmt_dict = {c: "{:.2f}%" for c in rate_present}
    fmt_dict.update({c: "{:.4f}" for c in nav_present})
    styler = styler.format(formatter=fmt_dict, na_rep="")
    for c in rate_present:
        styler = styler.map(_growth_color, subset=[c])

    # 关注行整行高亮
    if followed_map and "关注" in page_df.columns:
        def _followed_row_hl(row):
            if row.get("关注"):
                return ["background-color:#fff9db"] * len(row)
            return [""] * len(row)

        styler = styler.apply(_followed_row_hl, axis=1)

    # ---- 用 checkbox 列替代 dataframe 内置 selection ----
    # 选中状态按基金代码存 session_state，翻页不错位、不丢失
    if "fd_selected" not in st.session_state:
        st.session_state["fd_selected"] = set()

    # 渲染表格（不用 selection_mode）
    st.dataframe(
        styler,
        use_container_width=True,
        hide_index=True,
        height=560,
    )

    # 选中操作栏 + checkbox 区
    cur_page_codes = [
        str(row.get("基金代码", "")).strip().split(".")[0].zfill(6)
        for _, row in page_df.iterrows()
    ]

    op_col1, op_col2, op_col3, op_col4, op_col5, op_count = st.columns([1, 1, 1, 1, 1, 3])
    with op_col1:
        if st.button("✅ 全选本页", key="fd_sel_all", use_container_width=True):
            st.session_state["fd_selected"].update(cur_page_codes)
            st.rerun()
    with op_col2:
        if st.button("🔄 反选本页", key="fd_invert", use_container_width=True):
            for c in cur_page_codes:
                if c in st.session_state["fd_selected"]:
                    st.session_state["fd_selected"].discard(c)
                else:
                    st.session_state["fd_selected"].add(c)
            st.rerun()
    with op_col3:
        if st.button("🧹 清空全部", key="fd_clear", use_container_width=True):
            st.session_state["fd_selected"] = set()
            st.rerun()
    with op_count:
        st.caption(
            f"已选 **{len(st.session_state['fd_selected'])}** 只基金"
            f"（跨页累积，翻页不会丢失）"
        )

    # checkbox 网格：6 列，紧凑 chip 样式
    cols = st.columns(6)
    for i, (_, row) in enumerate(page_df.iterrows()):
        c = str(row.get("基金代码", "")).strip().split(".")[0].zfill(6)
        n = str(row.get("基金简称", ""))
        with cols[i % 6]:
            checked = st.checkbox(
                c,
                value=(c in st.session_state["fd_selected"]),
                key=f"fd_cb_{c}",
                help=n,
            )
            if checked and c not in st.session_state["fd_selected"]:
                st.session_state["fd_selected"].add(c)
            elif not checked and c in st.session_state["fd_selected"]:
                st.session_state["fd_selected"].discard(c)

    # 收集当前页选中的基金信息
    sel_codes = sorted(st.session_state["fd_selected"])
    sel_names = []
    for c in sel_codes:
        match = shown_df[normalize_fund_codes(shown_df["基金代码"]) == c]
        if len(match) > 0:
            sel_names.append(str(match.iloc[0].get("基金简称", "")))
        else:
            sel_names.append(c)

    if sel_codes:
        label = "、".join(f"{c} {n}" for c, n in zip(sel_codes, sel_names))
        st.success(f"✅ 已选择 {len(sel_codes)} 只基金：{label}")
        act1, act2, act3, act4, act_tip = st.columns([1.1, 1.1, 1.1, 1.1, 3])
        if len(sel_codes) == 1:
            act1.button(
                "📊 跳转单基金分析",
                type="primary",
                on_click=goto_analysis,
                args=(sel_codes[0],),
                use_container_width=True,
                key="fd_act1",
            )
            act2.button(
                "⚖️ 跳转多基金对比",
                disabled=True,
                use_container_width=True,
                help="对比需要至少勾选 2 只基金",
                key="fd_act2",
            )
        else:
            act1.button(
                "📊 跳转单基金分析",
                type="primary",
                on_click=goto_analysis,
                args=(sel_codes[0],),
                use_container_width=True,
                key="fd_act1",
            )
            act2.button(
                "⚖️ 跳转多基金对比",
                type="primary",
                on_click=goto_compare,
                args=(sel_codes,),
                use_container_width=True,
                key="fd_act2",
            )
        if act3.button(
            "⭐ 关注选中",
            use_container_width=True,
            help="关注后会在本页顶部与表格中醒目展示，并持久保存",
            key="fd_act3",
        ):
            for c, n in zip(sel_codes, sel_names):
                _db.follow_fund(c, n)
            st.rerun()
        if act4.button("💔 取消关注选中", use_container_width=True, key="fd_act4"):
            for c in sel_codes:
                _db.unfollow_fund(c)
            st.rerun()
        with act_tip:
            st.caption(
                "💡 翻页不会丢失选择——选中状态按基金代码保存。"
                "跳转单基金分析时使用第一只；跳转对比时使用全部选中的。"
            )
    else:
        st.caption("💡 勾选上方 checkbox 选择基金——1 只可跳转单基金分析，多只可跳转多基金对比。翻页不会丢失选择。")


# ===============================
# 净值数据加载（带缓存）与分析工具
# ===============================
PRESET_RANGES = ["近3月", "近6月", "近1年", "近3年", "近5年", "今年以来", "成立以来", "自定义"]


@st.cache_data(ttl=3600, show_spinner=False)
def _load_nav_cache(code: str):
    """缓存单基金净值历史，返回 (基金名称, DataFrame, 错误信息)。"""
    fetcher = get_default_fetcher()
    return fetcher.get_fund_nav_history(code)


def load_fund_nav(code: str):
    return _load_nav_cache(str(code).strip())


def fmt_pct(v, ndigits: int = 2) -> str:
    """小数 → 百分比字符串（NaN 显示为 —）。"""
    return "—" if pd.isna(v) else f"{v * 100:.{ndigits}f}%"


def fmt_ratio(v, ndigits: int = 2) -> str:
    """比率数值 → 字符串（NaN 显示为 —）。"""
    return "—" if pd.isna(v) else f"{v:.{ndigits}f}"


def resolve_date_range(preset: str, date_min, date_max, start_custom=None, end_custom=None):
    """根据预设区间名解析分析起止日期（自动夹取到数据范围内）。"""
    if preset == "自定义" and start_custom is not None and end_custom is not None:
        start, end = pd.Timestamp(start_custom), pd.Timestamp(end_custom)
    else:
        end = pd.Timestamp(date_max)
        months_map = {"近3月": 3, "近6月": 6, "近1年": 12, "近3年": 36, "近5年": 60}
        if preset in months_map:
            start = end - pd.DateOffset(months=months_map[preset])
        elif preset == "今年以来":
            start = pd.Timestamp(end.year, 1, 1)
        else:  # 成立以来
            start = pd.Timestamp(date_min)
    start = max(start, pd.Timestamp(date_min))
    end = min(end, pd.Timestamp(date_max))
    if start > end:
        start = end
    return start, end


def _default_custom_start(date_min, date_max):
    """自定义区间的默认开始日期（最早日期与一年前取较大者）。"""
    return max(pd.Timestamp(date_min), pd.Timestamp(date_max) - pd.DateOffset(years=1)).date()


def to_excel_bytes(sheets: dict) -> bytes:
    """将 {工作表名: DataFrame} 导出为 Excel 文件二进制。"""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=str(sheet_name)[:31], index=False)
    return buf.getvalue()


# ===============================
# Altair 图表辅助（全中文轴标签 + 交互提示）
# ===============================
def _alt_single_line(series: pd.Series, y_title: str, height: int = 320, color: str = "#1f77b4"):
    """单条折线图（中文坐标轴、悬浮提示、缩放交互）。"""
    df = series.reset_index()
    df.columns = ["净值日期", y_title]
    return (
        alt.Chart(df)
        .mark_line(color=color, strokeWidth=2)
        .encode(
            x=alt.X("净值日期:T", title="日期", axis=alt.Axis(labelFontSize=11, titleFontSize=13)),
            y=alt.Y(f"{y_title}:Q", title=y_title, axis=alt.Axis(labelFontSize=11, titleFontSize=13)),
            tooltip=[
                alt.Tooltip("净值日期:T", title="日期"),
                alt.Tooltip(f"{y_title}:Q", format=".4f", title=y_title),
            ],
        )
        .properties(height=height)
        .interactive()
    )


def _alt_area(series: pd.Series, y_title: str, height: int = 200, color: str = "#e03131"):
    """面积图（回撤水下曲线）。"""
    df = series.reset_index()
    df.columns = ["净值日期", y_title]
    y_min = float(df[y_title].min()) * 1.1
    return (
        alt.Chart(df)
        .mark_area(color=color, opacity=0.6)
        .encode(
            x=alt.X("净值日期:T", title="日期", axis=alt.Axis(labelFontSize=11, titleFontSize=13)),
            y=alt.Y(f"{y_title}:Q", title=y_title, scale=alt.Scale(domain=[y_min, 0]),
                     axis=alt.Axis(labelFontSize=11, titleFontSize=13, format="%")),
            tooltip=[
                alt.Tooltip("净值日期:T", title="日期"),
                alt.Tooltip(f"{y_title}:Q", format=".2%", title=y_title),
            ],
        )
        .properties(height=height)
    )


def _alt_multi_line(df: pd.DataFrame, y_title: str, height: int = 360):
    """多条折线图（归一化净值对比，中文图例）。"""
    plot_df = df.reset_index().melt(id_vars=df.index.name or "净值日期", var_name="基金代码", value_name=y_title)
    x_col = df.index.name or "净值日期"
    return (
        alt.Chart(plot_df)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X(f"{x_col}:T", title="日期", axis=alt.Axis(labelFontSize=11, titleFontSize=13)),
            y=alt.Y(f"{y_title}:Q", title=y_title, axis=alt.Axis(labelFontSize=11, titleFontSize=13)),
            color=alt.Color("基金代码:N", legend=alt.Legend(title="基金代码", labelFontSize=12, titleFontSize=13)),
            tooltip=[
                alt.Tooltip("基金代码:N", title="基金代码"),
                alt.Tooltip(f"{x_col}:T", title="日期"),
                alt.Tooltip(f"{y_title}:Q", format=".4f", title=y_title),
            ],
        )
        .properties(height=height)
        .interactive()
    )


# ===============================
# 基金档案 / 重仓股加载（带缓存）
# ===============================
PROFILE_ORDER = [
    "基金类型", "成立日期/规模", "净资产规模", "份额规模", "基金管理人",
    "基金托管人", "基金经理人", "管理费率", "托管费率", "销售服务费率",
    "最高申购费率", "最高赎回费率", "跟踪标的", "业绩比较基准",
]


@st.cache_data(ttl=86400, show_spinner=False)
def _load_profile_cache(code: str):
    """缓存基金档案（24 小时）。"""
    return get_default_fetcher().get_fund_profile(code)


def load_fund_profile(code: str):
    return _load_profile_cache(str(code).strip())


@st.cache_data(ttl=43200, show_spinner=False)
def _load_holdings_cache(code: str):
    """缓存重仓股数据（12 小时）。"""
    return get_default_fetcher().get_fund_holdings(code)


def load_fund_holdings(code: str):
    return _load_holdings_cache(str(code).strip())


# ===============================
# 页面：单基金分析
# ===============================
def render_fund_analysis():
    st.header("📈 单基金分析")
    st.caption("输入基金代码，查看收益走势与风险指标（数据来源：天天基金网，指标基于复权净值）")

    col_code, col_rf = st.columns([3, 1])
    with col_code:
        code = st.text_input(
            "基金代码（6 位数字）",
            value=st.session_state.get("analysis_code", ""),
            key="analysis_code",
            placeholder="例如：161725（招商中证白酒）、005827（易方达蓝筹精选）",
        ).strip()
    with col_rf:
        risk_free = st.number_input(
            "无风险利率（年化小数）",
            min_value=0.0,
            max_value=0.10,
            value=0.02,
            step=0.005,
            format="%.3f",
            help="用于计算夏普比率",
        )

    if not code:
        st.info("请先输入基金代码，例如：161725、005827、110011")
        return
    if not (code.isdigit() and len(code) == 6):
        st.error("基金代码应为 6 位数字，请检查后重试。")
        return

    with st.spinner(f"正在获取基金 {code} 的净值数据..."):
        name, nav_df, err = load_fund_nav(code)

    if err is not None or nav_df is None:
        st.error(f"基金 {code} 数据获取失败")
        with st.expander("查看错误详情"):
            st.code(err if err else "未知错误：返回数据为空。", language="text")
        return

    date_min, date_max = nav_df["净值日期"].min(), nav_df["净值日期"].max()

    # ---- 分析区间选择 ----
    col_range, col_s, col_e = st.columns([1, 1, 1])
    with col_range:
        preset = st.selectbox("分析区间", PRESET_RANGES, index=2)
    start_custom, end_custom = None, None
    if preset == "自定义":
        with col_s:
            start_custom = st.date_input(
                "开始日期",
                value=_default_custom_start(date_min, date_max),
                min_value=date_min.date(),
                max_value=date_max.date(),
            )
        with col_e:
            end_custom = st.date_input(
                "结束日期",
                value=date_max.date(),
                min_value=date_min.date(),
                max_value=date_max.date(),
            )
    start, end = resolve_date_range(preset, date_min, date_max, start_custom, end_custom)

    sel = nav_df[(nav_df["净值日期"] >= start) & (nav_df["净值日期"] <= end)].reset_index(drop=True)
    if len(sel) < 2:
        st.warning("所选区间内净值数据不足（少于 2 个交易日），请调整区间。")
        return

    title = f"{name}（{code}）" if name else f"基金 {code}"
    title_col, follow_col = st.columns([5, 1])
    with title_col:
        st.subheader(title)
    with follow_col:
        _is_followed = code in get_followed_map()
        if st.button(
            "💔 取消关注" if _is_followed else "⭐ 关注",
            key="fa_follow_btn",
            use_container_width=True,
        ):
            if _is_followed:
                _db.unfollow_fund(code)
            else:
                _db.follow_fund(code, name or "")
            st.rerun()
    st.caption(
        f"统计区间：{start.date()} ~ {end.date()} ｜ 共 {len(sel)} 个净值交易日 ｜ 数据截至 {date_max.date()}"
    )

    nav = sel.set_index("净值日期")["复权净值"]
    metrics = summary_metrics(nav, risk_free)

    # ---- 风险指标面板 ----
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("区间累计收益率", fmt_pct(metrics["区间累计收益率"]))
    with m2:
        st.metric("年化收益率", fmt_pct(metrics["年化收益率"]))
    with m3:
        st.metric("年化波动率", fmt_pct(metrics["年化波动率"]))
    with m4:
        st.metric("最大回撤", fmt_pct(metrics["最大回撤"]))
    m5, m6, m7, m8 = st.columns(4)
    with m5:
        st.metric("夏普比率", fmt_ratio(metrics["夏普比率"]))
    with m6:
        st.metric("卡玛比率", fmt_ratio(metrics["卡玛比率"]))
    with m7:
        st.metric("最新单位净值", f"{sel['单位净值'].iloc[-1]:.4f}")
    with m8:
        st.metric("最新净值日期", str(date_max.date()))

    # ---- 走势图 ----
    st.markdown("---")
    st.subheader("📈 复权净值走势（起点 = 1）")
    st.altair_chart(_alt_single_line(nav, "复权净值", height=320), use_container_width=True)

    st.subheader("📉 回撤走势（水下曲线）")
    st.altair_chart(_alt_area(drawdown_series(nav), "回撤", height=200), use_container_width=True)

    # ---- 基金档案（类型 / 经理 / 费率 / 重仓股） ----
    st.markdown("---")
    st.subheader("🗂️ 基金档案")
    profile, prof_err = load_fund_profile(code)
    holdings, hold_err = load_fund_holdings(code)

    col_p, col_h = st.columns([2, 3])
    with col_p:
        if profile:
            for k in PROFILE_ORDER:
                v = profile.get(k)
                if v:
                    st.markdown(f"- **{k}**：{v}")
            for k, v in profile.items():
                if k not in PROFILE_ORDER and v and len(v) <= 40:
                    st.markdown(f"- **{k}**：{v}")
        elif prof_err:
            st.caption(f"档案信息获取失败：{prof_err}")
    with col_h:
        if holdings is not None and len(holdings) > 0:
            h_period = "最新报告期"
            if "季度" in holdings.columns:
                h_period = str(holdings["季度"].iloc[0]).replace("股票投资明细", "").strip()
            st.caption(f"重仓持股（{h_period}，共 {len(holdings)} 只）")
            h_disp = holdings.copy()
            if "占净值比例" in h_disp.columns:
                h_disp["占净值比例"] = h_disp["占净值比例"].map(
                    lambda v: "" if pd.isna(v) else f"{v:.2f}%"
                )
            st.dataframe(h_disp, use_container_width=True, hide_index=True, height=320)
        else:
            st.caption(hold_err or "暂无持仓数据")

    # ---- 明细与导出 ----
    st.markdown("---")
    detail = sel.copy()
    detail["净值日期"] = detail["净值日期"].dt.date

    metrics_export = pd.DataFrame(
        {
            "指标": [
                "基金名称", "基金代码", "统计开始日期", "统计结束日期", "净值交易日数",
                "区间累计收益率", "年化收益率", "年化波动率", "最大回撤",
                "夏普比率", "卡玛比率", "最新单位净值", "无风险利率",
            ],
            "数值": [
                name or "", code, str(start.date()), str(end.date()), len(sel),
                metrics["区间累计收益率"], metrics["年化收益率"], metrics["年化波动率"],
                metrics["最大回撤"], metrics["夏普比率"], metrics["卡玛比率"],
                float(sel["单位净值"].iloc[-1]), risk_free,
            ],
        }
    )

    col_btn, col_tip = st.columns([1, 3])
    with col_btn:
        st.download_button(
            "📥 导出 Excel",
            data=to_excel_bytes({"指标汇总": metrics_export, "净值明细": detail}),
            file_name=f"单基金分析_{code}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with col_tip:
        st.caption("导出内容：指标汇总 + 区间内净值明细")

    with st.expander("📋 查看净值明细（区间内）"):
        st.dataframe(detail, use_container_width=True, hide_index=True, height=320)


# ===============================
# 页面：多基金对比
# ===============================
def render_fund_compare():
    import altair as alt

    st.header("⚖️ 多基金对比")
    st.caption("输入多只基金代码（逗号 / 空格分隔，最多 8 只），横向对比收益与风险")

    col_codes, col_rf = st.columns([3, 1])
    with col_codes:
        codes_text = st.text_input(
            "基金代码列表",
            value=st.session_state.get("compare_input", ""),
            key="compare_input",
            placeholder="例如：161725, 005827, 110011",
        )
    with col_rf:
        risk_free = st.number_input(
            "无风险利率（年化小数）",
            min_value=0.0,
            max_value=0.10,
            value=0.02,
            step=0.005,
            format="%.3f",
            key="cmp_rf",
        )

    codes = [c.strip() for c in re.split(r"[,，、;；\s]+", codes_text) if c.strip()]
    codes = list(dict.fromkeys(codes))
    invalid = [c for c in codes if not (c.isdigit() and len(c) == 6)]
    codes = [c for c in codes if c not in invalid][:8]
    if invalid:
        st.warning(f"以下代码不合法，已忽略：{'、'.join(invalid)}")
    if len(codes) > 8:
        st.warning("基金数量超过 8 只，仅保留前 8 只。")
    if len(codes) < 2:
        st.info("请至少输入 2 只有效的 6 位基金代码进行对比。")
        return

    # ---- 逐只获取净值 ----
    data = {}
    failed = []
    progress = st.progress(0.0, text="正在获取基金净值数据...")
    for i, c in enumerate(codes):
        name, df, err = load_fund_nav(c)
        if err is not None or df is None:
            failed.append(c)
        else:
            data[c] = (name, df)
        progress.progress((i + 1) / len(codes), text=f"已获取 {i + 1}/{len(codes)}：{c}")
    progress.empty()
    if failed:
        st.warning(f"以下基金数据获取失败，已跳过：{'、'.join(failed)}")
    if len(data) < 2:
        st.error("有效基金不足 2 只，无法对比。")
        return

    # ---- 按共同日期对齐 ----
    nav_wide = None
    for c, (_name, df) in data.items():
        s = df.set_index("净值日期")["复权净值"].rename(c)
        nav_wide = s.to_frame() if nav_wide is None else nav_wide.join(s, how="inner")
    nav_wide = nav_wide.dropna(how="any").sort_index()
    if len(nav_wide) < 2:
        st.error("所选基金没有足够的共同净值日期（成立时间差异过大），无法对比。")
        return

    date_min, date_max = nav_wide.index.min(), nav_wide.index.max()

    # ---- 对比区间选择 ----
    col_range, col_s, col_e = st.columns([1, 1, 1])
    with col_range:
        preset = st.selectbox("对比区间", PRESET_RANGES, index=2, key="cmp_range")
    start_custom, end_custom = None, None
    if preset == "自定义":
        with col_s:
            start_custom = st.date_input(
                "开始日期",
                value=_default_custom_start(date_min, date_max),
                min_value=date_min.date(),
                max_value=date_max.date(),
                key="cmp_start",
            )
        with col_e:
            end_custom = st.date_input(
                "结束日期",
                value=date_max.date(),
                min_value=date_min.date(),
                max_value=date_max.date(),
                key="cmp_end",
            )
    start, end = resolve_date_range(preset, date_min, date_max, start_custom, end_custom)

    sel = nav_wide[(nav_wide.index >= start) & (nav_wide.index <= end)]
    if len(sel) < 2:
        st.warning("所选区间内共同交易日数据不足，请调整区间。")
        return

    st.caption(
        f"统计区间：{start.date()} ~ {end.date()} ｜ 共 {len(sel)} 个共同净值交易日 ｜ 参与对比：{len(sel.columns)} 只"
    )

    # ---- 归一化净值曲线 ----
    norm = sel / sel.iloc[0]
    st.subheader("📈 归一化净值走势（起点 = 1）")
    st.altair_chart(_alt_multi_line(norm, "归一化净值", height=360), use_container_width=True)

    # ---- 指标对比表 ----
    st.subheader("📊 风险收益指标对比")
    rows = []
    for c in sel.columns:
        m = summary_metrics(sel[c], risk_free)
        rows.append({"基金代码": c, "基金简称": data[c][0] or "", **m})
    cmp_df = pd.DataFrame(rows).set_index("基金代码")
    cmp_df = cmp_df[["基金简称", "区间累计收益率", "年化收益率", "最大回撤", "年化波动率", "夏普比率", "卡玛比率"]]

    disp = cmp_df.copy()
    for c in ["区间累计收益率", "年化收益率", "最大回撤", "年化波动率"]:
        disp[c] = disp[c].map(fmt_pct)
    for c in ["夏普比率", "卡玛比率"]:
        disp[c] = disp[c].map(fmt_ratio)
    st.dataframe(disp, use_container_width=True)

    # ---- 基金档案对比 ----
    st.subheader("🗂️ 基金档案对比")
    PROFILE_COMPARE_KEYS = [
        "基金类型", "基金经理人", "管理费率", "托管费率",
        "销售服务费率", "最高申购费率", "最高赎回费率",
        "净资产规模", "成立日期/规模", "基金管理人", "跟踪标的",
    ]
    prof_rows = []
    with st.spinner("正在获取基金档案..."):
        for c in sel.columns:
            p, _ = load_fund_profile(c)
            row = {"基金代码": c, "基金简称": data[c][0] or ""}
            if p:
                for k in PROFILE_COMPARE_KEYS:
                    row[k] = p.get(k, "—")
            else:
                for k in PROFILE_COMPARE_KEYS:
                    row[k] = "—"
            prof_rows.append(row)
    prof_df = pd.DataFrame(prof_rows).set_index("基金代码")
    st.dataframe(prof_df, use_container_width=True, height=320)

    # ---- 重仓股对比 ----
    st.subheader("📦 重仓股对比")
    all_holdings = {}
    with st.spinner("正在获取重仓股数据..."):
        for c in sel.columns:
            h, _ = load_fund_holdings(c)
            if h is not None and len(h) > 0:
                all_holdings[c] = h

    if all_holdings:
        # 1) 每只基金的重仓股列表
        col_h1, col_h2 = st.columns([3, 2])
        with col_h1:
            st.caption("**各基金重仓股明细**")
            for c, h in all_holdings.items():
                fname = data[c][0] or c
                h_period = h["季度"].iloc[0].replace("股票投资明细", "").strip() if "季度" in h.columns else ""
                with st.expander(f"{c} {fname}（{len(h)} 只，{h_period}）", expanded=False):
                    h_disp = h.copy()
                    if "占净值比例" in h_disp.columns:
                        h_disp["占净值比例"] = h_disp["占净值比例"].map(
                            lambda v: "" if pd.isna(v) else f"{v:.2f}%"
                        )
                    show_cols = [col for col in ["序号", "股票代码", "股票名称", "占净值比例", "持股数", "持仓市值"] if col in h_disp.columns]
                    st.dataframe(h_disp[show_cols], use_container_width=True, hide_index=True, height=280)

        # 2) 共识持仓分析（被多只基金同时持有的股票）
        with col_h2:
            st.caption("**共识持仓**（被多只基金同时持有）")
            stock_funds = {}
            for c, h in all_holdings.items():
                fname = data[c][0] or c
                if "股票名称" in h.columns:
                    for _, row in h.iterrows():
                        sname = str(row.get("股票名称", "")).strip()
                        if sname and sname != "nan":
                            stock_funds.setdefault(sname, []).append(fname)

            overlap = {s: funds for s, funds in stock_funds.items() if len(funds) >= 2}
            if overlap:
                overlap_rows = sorted(overlap.items(), key=lambda x: len(x[1]), reverse=True)
                for sname, funds in overlap_rows:
                    st.markdown(f"- **{sname}**（{len(funds)} 只基金）：{'、'.join(funds)}")
            else:
                st.info("各基金重仓股无重叠。")
    else:
        st.info("所选基金均无股票持仓数据（可能为债券型 / 货币型基金）。")

    # ---- 相关性热力图（Altair 实现，无需 matplotlib）----
    st.subheader("🔥 日收益率相关性矩阵")
    rets = sel.pct_change().dropna(how="all")
    corr = rets.corr()
    corr_long = (
        corr.reset_index()
        .melt(id_vars="index", var_name="基金B", value_name="相关系数")
        .rename(columns={"index": "基金A"})
    )
    heat = alt.Chart(corr_long).mark_rect().encode(
        x=alt.X("基金A:N", title=None, axis=alt.Axis(labelFontSize=12)),
        y=alt.Y("基金B:N", title=None, sort="descending", axis=alt.Axis(labelFontSize=12)),
        color=alt.Color(
            "相关系数:Q",
            scale=alt.Scale(scheme="redyellowgreen", domain=[-1, 1]),
            legend=alt.Legend(title="相关系数"),
        ),
        tooltip=[
            alt.Tooltip("基金A:N", title="基金A"),
            alt.Tooltip("基金B:N", title="基金B"),
            alt.Tooltip("相关系数:Q", format=".3f", title="相关系数"),
        ],
    )
    heat_text = heat.mark_text(fontSize=12).encode(
        text=alt.Text("相关系数:Q", format=".2f"),
        color=alt.condition(
            "datum['相关系数'] > 0.6 || datum['相关系数'] < -0.6",
            alt.value("white"),
            alt.value("black"),
        ),
    )
    st.altair_chart((heat + heat_text).properties(height=300), use_container_width=True)

    # ---- 风险收益散点图 ----
    st.subheader("🎯 风险收益散点图")

    scat = cmp_df.reset_index()
    scat["年化收益率(%)"] = scat["年化收益率"] * 100
    scat["年化波动率(%)"] = scat["年化波动率"] * 100
    points = alt.Chart(scat).mark_circle(size=160, opacity=0.85).encode(
        x=alt.X("年化波动率(%):Q", title="年化波动率（%，越靠左越稳）",
                axis=alt.Axis(labelFontSize=11, titleFontSize=13)),
        y=alt.Y("年化收益率(%):Q", title="年化收益率（%，越靠上越赚）",
                axis=alt.Axis(labelFontSize=11, titleFontSize=13)),
        color=alt.Color("基金代码:N", legend=alt.Legend(title="基金代码", labelFontSize=12, titleFontSize=13)),
        tooltip=[
            alt.Tooltip("基金代码:N", title="基金代码"),
            alt.Tooltip("基金简称:N", title="基金简称"),
            alt.Tooltip("年化收益率(%):Q", format=".2f", title="年化收益率"),
            alt.Tooltip("年化波动率(%):Q", format=".2f", title="年化波动率"),
            alt.Tooltip("最大回撤:Q", format=".2%", title="最大回撤"),
            alt.Tooltip("夏普比率:Q", format=".2f", title="夏普比率"),
        ],
    )
    labels = points.mark_text(align="left", dx=8, dy=0, fontSize=12).encode(text="基金代码:N")
    st.altair_chart((points + labels).interactive(), use_container_width=True)

    # ---- Excel 导出 ----
    st.markdown("---")
    norm_export = norm.reset_index()
    norm_export = norm_export.rename(columns={"index": "净值日期"})
    corr_export = corr.reset_index().rename(columns={"index": "基金代码"})
    cmp_export = cmp_df.reset_index()
    st.download_button(
        "📥 导出对比结果 Excel",
        data=to_excel_bytes(
            {
                "指标对比": cmp_export,
                "基金档案": prof_df.reset_index(),
                "归一化净值": norm_export,
                "相关性矩阵": corr_export,
            }
        ),
        file_name="多基金对比.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ===============================
# 页面：数据管理
# ===============================
def render_fund_management():
    st.header("💾 数据管理")
    st.caption("管理本地缓存数据、导出基金列表、查看数据库与缓存状态")

    # ---- 数据概览 ----
    st.subheader("📊 数据概览")
    df, err, fetch_time = load_fund_data()
    total = len(df) if df is not None else 0
    holdings_count = len(_db.list_holdings())
    prefs = _db.load_preferences()
    risk_name = prefs.get("risk_profile_name") or "未评估"

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("基金数据总数", f"{total}")
    with col2:
        db_size = config.db_path.stat().st_size / 1024 if config.db_path.exists() else 0
        st.metric("数据库大小", f"{db_size:.1f} KB" if db_size else "—")
    with col3:
        st.metric("持仓基金数", f"{holdings_count}")
    with col4:
        st.metric("投资风格", risk_name)

    st.markdown("---")

    # ---- 持久化数据管理 ----
    st.subheader("💾 持久化数据（投资风格 / 持仓）")
    st.caption("以下数据保存在本地 SQLite，重启或刷新后仍然保留，无需重新填写。")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        if prefs.get("risk_done"):
            score_str = prefs.get("risk_score", "—")
            amount_str = f"{prefs.get('risk_amount'):,.0f} 元" if prefs.get("risk_amount") else "未设置"
            st.info(
                f"**投资风格评估**：{risk_name}\n\n"
                f"- 评估分数：{score_str}\n"
                f"- 投资金额：{amount_str}"
            )
        else:
            st.info(f"**投资风格评估**：{risk_name}\n\n尚未保存评估结果。")
    with col_p2:
        st.info(f"**持仓追踪**：共 {holdings_count} 只基金")

    col_pa, col_pb = st.columns(2)
    with col_pa:
        if st.button("🗑️ 清除投资风格评估记录", use_container_width=True):
            _db.clear_preferences()
            st.session_state["risk_done"] = False
            st.session_state["risk_score"] = None
            st.session_state["risk_profile_name"] = None
            st.session_state["risk_profile_desc"] = None
            st.success("已清除投资风格评估记录。")
            st.rerun()
    with col_pb:
        if st.button("🗑️ 清空全部持仓", use_container_width=True):
            _db.clear_holdings()
            st.success("已清空全部持仓。")
            st.rerun()

    st.markdown("---")

    # ---- 缓存管理 ----
    st.subheader("🗑️ 缓存管理（临时数据）")
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.info(
            "**当前缓存项**\n"
            "- 基金列表（1 小时过期）\n"
            "- 基金净值历史（1 小时过期）\n"
            "- 基金档案（24 小时过期）\n"
            "- 重仓股数据（12 小时过期）\n"
            "- 持仓看盘实时行情（60 秒过期）"
        )
    with col_c2:
        if st.button("🧹 清除全部临时缓存", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.success("临时缓存已清除（不影响已保存的投资风格和持仓），页面即将刷新...")
            st.rerun()

    st.markdown("---")

    # ---- 数据导出 ----
    st.subheader("📤 数据导出")
    if df is not None and len(df) > 0:
        export_fmt = st.radio("选择导出格式", ["Excel (.xlsx)", "CSV (.csv)"], horizontal=True)
        if st.button("📥 导出基金列表", type="primary"):
            export_df = df.copy()
            if "序号" in export_df.columns:
                export_df = export_df.drop(columns=["序号"])
            if export_fmt == "Excel (.xlsx)":
                st.download_button(
                    "下载 Excel 文件",
                    data=to_excel_bytes({"基金列表": export_df}),
                    file_name=f"基金列表_{datetime.date.today()}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                csv = export_df.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "下载 CSV 文件",
                    data=csv,
                    file_name=f"基金列表_{datetime.date.today()}.csv",
                    mime="text/csv",
                )
    else:
        st.warning("基金数据未加载，无法导出。")

    st.markdown("---")

    # ---- 系统信息 ----
    st.subheader("🖥️ 系统信息")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.write(f"- **项目路径**：`{config.project_root}`")
        st.write(f"- **数据目录**：`{config.data_dir}`")
        st.write(f"- **数据库路径**：`{config.db_path}`")
    with col_s2:
        st.write(f"- **Python 版本**：{sys.version.split()[0]}")
        st.write(f"- **Streamlit 版本**：{st.__version__}")
        st.write(f"- **缓存时长**：{config.cache_ttl} 秒")


# ===============================
# 基金类型推断（根据基金简称关键词）
# ===============================
FUND_TYPE_RULES = [
    ("货币市场型", ["货币", "宝", "现金"]),
    ("债券型", ["债券", "信债", "纯债", "信用", "债"]),
    ("QDII", ["QDII", "全球", "海外", "纳斯达克", "标普"]),
    ("指数型", ["指数", "ETF联接", "增强"]),
    ("股票型", ["股票"]),
    ("混合型", ["混合", "灵活配置", "策略", "成长", "价值", "主题", "机遇", "回报"]),
    ("FOF", ["FOF", "养老"]),
]


def classify_fund_type(name: str) -> str:
    """根据基金简称推断基金类型。"""
    if not name:
        return "其他"
    for ftype, keywords in FUND_TYPE_RULES:
        for kw in keywords:
            if kw in name:
                return ftype
    return "其他"


# 各风险等级的资产配置模型（比例之和 = 100%）
RISK_ALLOCATION = {
    "保守型": [
        ("货币市场型", 30, "流动性管理，本金安全"),
        ("债券型", 50, "核心底仓，稳健收益"),
        ("混合型", 15, "少量增厚收益"),
        ("指数型", 5, "微量权益敞口"),
    ],
    "稳健型": [
        ("货币市场型", 10, "应急流动性"),
        ("债券型", 40, "核心底仓"),
        ("混合型", 30, "股债均衡"),
        ("指数型", 20, "被动权益增厚"),
    ],
    "平衡型": [
        ("货币市场型", 5, "应急流动性"),
        ("债券型", 20, "稳健底仓"),
        ("混合型", 35, "主动管理核心"),
        ("指数型", 25, "宽基被动配置"),
        ("股票型", 15, "行业主题进攻"),
    ],
    "进取型": [
        ("债券型", 10, "风险缓冲"),
        ("混合型", 20, "主动管理"),
        ("指数型", 30, "宽基核心"),
        ("股票型", 30, "行业主题进攻"),
        ("QDII", 10, "海外分散"),
    ],
    "激进型": [
        ("混合型", 15, "少量主动管理"),
        ("指数型", 30, "行业主题核心"),
        ("股票型", 35, "高波动进攻"),
        ("QDII", 20, "海外高弹性"),
    ],
}
RISK_QUESTIONS = [
    {
        "key": "horizon",
        "question": "1. 您计划的投资期限是多久？",
        "options": [
            ("1 年以内", 1),
            ("1 ~ 3 年", 2),
            ("3 ~ 5 年", 3),
            ("5 年以上", 5),
        ],
    },
    {
        "key": "loss_tolerance",
        "question": "2. 如果您的投资组合在一个季度内亏损了 20%，您会怎么做？",
        "options": [
            ("立即全部赎回，止损为上", 1),
            ("赎回一部分，观望再说", 2),
            ("持有不动，等待市场恢复", 4),
            ("逢低加仓，认为是机会", 5),
        ],
    },
    {
        "key": "experience",
        "question": "3. 您的基金 / 股票投资经验有多久？",
        "options": [
            ("没有经验，刚开始了解", 1),
            ("1 ~ 3 年，基本了解", 2),
            ("3 ~ 5 年，比较熟悉", 4),
            ("5 年以上，经验丰富", 5),
        ],
    },
    {
        "key": "return_target",
        "question": "4. 您的年化收益预期大约是？",
        "options": [
            ("跑赢通胀即可（3~6%）", 1),
            ("稳健增长（6~12%）", 2),
            ("较高回报（12~20%）", 4),
            ("追求高增长（20% 以上）", 5),
        ],
    },
    {
        "key": "allocation",
        "question": "5. 您可用于投资闲钱的资金占可支配收入的比例是？",
        "options": [
            ("10% 以内", 1),
            ("10% ~ 30%", 2),
            ("30% ~ 50%", 4),
            ("50% 以上", 5),
        ],
    },
    {
        "key": "max_drawdown",
        "question": "6. 您能接受的最大亏损幅度是？",
        "options": [
            ("5% 以内（不能亏太多）", 1),
            ("10% 以内（有一定承受力）", 2),
            ("20% 以内（可以容忍较大波动）", 4),
            ("不设上限（追求最大回报）", 5),
        ],
    },
    {
        "key": "reaction",
        "question": "7. 当市场大跌时（单日跌幅 > 3%），您的第一反应是？",
        "options": [
            ("焦虑，后悔投资", 1),
            ("关注新闻，考虑减仓", 2),
            ("正常波动，不用管", 4),
            ("好机会，准备买入", 5),
        ],
    },
]

RISK_PROFILES = [
    (7, 11, "保守型", "您偏好低风险投资，适合配置货币基金和纯债基金，追求本金安全和稳定收益。", ["货币市场型", "中长期纯债", "短期纯债"]),
    (12, 18, "稳健型", "您可以承受小幅波动，适合以债券基金为主、少量配置偏债混合基金。", ["中长期纯债", "混合债券型", "偏债混合"]),
    (19, 25, "平衡型", "您能承受中等波动，适合混合型基金和宽基指数基金的均衡配置。", ["混合型", "指数型", "灵活配置"]),
    (26, 30, "进取型", "您追求较高回报、能承受较大波动，适合股票型基金和行业主题基金。", ["股票型", "指数型", "联接基金"]),
    (31, 35, "激进型", "您风险承受能力强、追求最大化回报，可配置高波动的行业主题和 QDII 基金。", ["股票型", "指数型", "QDII"]),
]


def render_risk_assessment():
    st.header("🧭 投资风格评估")
    st.caption("通过 7 道问题评估您的风险承受能力，据此推荐适合您的基金类型和配置方案")

    answers = {}
    for q in RISK_QUESTIONS:
        choice = st.radio(q["question"], [opt[0] for opt in q["options"]], key=f"risk_{q['key']}")
        for opt_text, score in q["options"]:
            if choice == opt_text:
                answers[q["key"]] = score
                break

    st.markdown("---")
    total_score = sum(answers.values())

    col_btn, col_reset = st.columns([2, 1])
    with col_btn:
        assess_clicked = st.button("📊 评估我的投资风格", type="primary", use_container_width=True)
    with col_reset:
        reset_clicked = st.button(
            "🔄 重新评估",
            use_container_width=True,
            help="清除已保存的评估结果，重新答题",
        )

    if assess_clicked:
        score = total_score
        profile_name = "未知"
        profile_desc = ""
        for lo, hi, name, desc, _ in RISK_PROFILES:
            if lo <= score <= hi:
                profile_name = name
                profile_desc = desc
                break
        st.session_state["risk_score"] = int(score)
        st.session_state["risk_done"] = True
        st.session_state["risk_profile_name"] = profile_name
        st.session_state["risk_profile_desc"] = profile_desc
        answers_text = {q["key"]: st.session_state.get(f"risk_{q['key']}") for q in RISK_QUESTIONS}
        # 金额：优先用已输入值，否则用默认 100000
        _amt = st.session_state.get("risk_amount")
        if _amt is None:
            _amt = 100000
            st.session_state["risk_amount"] = _amt
        save_risk_profile_to_db(score, profile_name, profile_desc, answers_text, _amt)
        st.success("✅ 评估结果已保存，下次打开无需重新选择。")

    if reset_clicked:
        st.session_state["risk_done"] = False
        st.session_state["risk_score"] = None
        st.session_state["risk_profile_name"] = None
        st.session_state["risk_profile_desc"] = None
        _db.save_preferences({
            "risk_done": False, "risk_score": None,
            "risk_profile_name": None, "risk_profile_desc": None,
        })
        st.rerun()

    if st.session_state.get("risk_done"):
        score = st.session_state.get("risk_score", total_score)
        profile_name = st.session_state.get("risk_profile_name") or "未知"
        profile_desc = st.session_state.get("risk_profile_desc") or ""
        if not profile_desc:
            for lo, hi, name, desc, _ in RISK_PROFILES:
                if lo <= score <= hi:
                    profile_name = name
                    profile_desc = desc
                    break

        st.success(f"## 您的投资风格：**{profile_name}**\n\n总分：{score} / 35 分\n\n{profile_desc}")

        # ---- 投资总额输入 ----
        st.markdown("---")
        st.subheader("� 投资金额与配置方案")
        if "risk_amount" not in st.session_state:
            st.session_state["risk_amount"] = 100000
        total_amount = st.number_input(
            "请输入您准备投入的总金额（元）",
            min_value=1000,
            max_value=100000000,
            step=10000,
            format="%d",
            key="risk_amount",
            on_change=lambda: _db.save_preferences(
                {"risk_amount": st.session_state.get("risk_amount")}
            ),
        )
        total_amount = float(total_amount) if total_amount is not None else 100000

        allocation = RISK_ALLOCATION.get(profile_name, [])
        if allocation:
            total_pct = sum(a[1] for a in allocation)
            st.caption(f"投资风格「{profile_name}」的科学配置模型（比例合计 {total_pct}%）")

            # ---- 配置总览表 ----
            rows = []
            for ftype, pct, note in allocation:
                amount = total_amount * pct / 100
                rows.append({
                    "基金类型": ftype,
                    "建议比例": f"{pct}%",
                    "建议金额（元）": f"{amount:,.0f}",
                    "配置说明": note,
                })
            alloc_df = pd.DataFrame(rows)
            st.dataframe(alloc_df, use_container_width=True, hide_index=True)

            # ---- 配置饼图 ----
            pie_data = pd.DataFrame([
                {"基金类型": a[0], "金额": total_amount * a[1] / 100}
                for a in allocation
            ])
            pie = alt.Chart(pie_data).mark_arc(innerRadius=60).encode(
                theta=alt.Theta("金额:Q", title="金额"),
                color=alt.Color("基金类型:N", legend=alt.Legend(title="基金类型", labelFontSize=12, titleFontSize=13)),
                tooltip=[
                    alt.Tooltip("基金类型:N", title="基金类型"),
                    alt.Tooltip("金额:Q", format=",.0f", title="建议金额（元）"),
                ],
            )
            st.altair_chart(pie.properties(height=300), use_container_width=True)

            # ---- 持仓 / 关注 vs 配置方案对比 ----
            st.markdown("---")
            st.subheader("📊 持仓 vs 配置方案对比")
            st.caption(
                "下方汇总您**持仓基金**（含投入金额）和**关注但尚未持仓**的基金，"
                "按类型统计实际比例，与建议配置对比。"
            )

            # 1) 收集数据：持仓（有金额）+ 关注但未持仓（金额待输入）
            holdings_list = _db.list_holdings()
            followed_map_local = get_followed_map()
            holding_codes = {str(h["fund_code"]).zfill(6) for h in holdings_list}
            followed_only = [
                {"fund_code": c, "fund_name": m.get("fund_name", ""), "amount": 0.0}
                for c, m in followed_map_local.items()
                if c not in holding_codes
            ]

            # 持仓表格显示
            if holdings_list or followed_only:
                # 构造明细 DataFrame
                detail_rows = []
                for h in holdings_list:
                    c = str(h["fund_code"]).zfill(6)
                    detail_rows.append({
                        "基金代码": c,
                        "基金名称": h.get("fund_name", ""),
                        "数据来源": "持仓",
                        "投入金额": float(h.get("amount", 0)),
                        "基金类型": classify_fund_type(h.get("fund_name", "")),
                    })
                for f in followed_only:
                    c = f["fund_code"]
                    detail_rows.append({
                        "基金代码": c,
                        "基金名称": f.get("fund_name", ""),
                        "数据来源": "关注",
                        "投入金额": 0.0,
                        "基金类型": classify_fund_type(f.get("fund_name", "")),
                    })
                all_df = pd.DataFrame(detail_rows)

                # --- 按类型汇总 ---
                actual_by_type = all_df.groupby("基金类型", as_index=False)["投入金额"].sum()
                actual_by_type = actual_by_type.rename(columns={"投入金额": "实际金额"})
                total_actual = actual_by_type["实际金额"].sum()

                # --- 对比表：建议 vs 实际 ---
                cmp_rows = []
                for ftype, pct, note in allocation:
                    suggested_amt = total_amount * pct / 100
                    # 找实际金额
                    match = actual_by_type[actual_by_type["基金类型"] == ftype]
                    actual_amt = float(match["实际金额"].iloc[0]) if len(match) > 0 else 0.0
                    actual_pct = (actual_amt / total_actual * 100) if total_actual > 0 else 0.0
                    diff = actual_amt - suggested_amt

                    if actual_amt == 0 and suggested_amt > 0:
                        status = "⚠️ 缺失"
                    elif abs(diff) <= suggested_amt * 0.05:
                        status = "✅ 达标"
                    elif diff < 0:
                        status = f"⚠️ 不足 {abs(diff):,.0f}"
                    else:
                        status = f"⚠️ 超配 {diff:,.0f}"

                    cmp_rows.append({
                        "基金类型": ftype,
                        "建议比例": f"{pct}%",
                        "建议金额": f"{suggested_amt:,.0f}",
                        "实际金额": f"{actual_amt:,.0f}",
                        "实际比例": f"{actual_pct:.1f}%",
                        "差额": f"{diff:,.0f}",
                        "状态": status,
                    })
                # 处理配置方案中没有但实际持有的类型
                suggested_types = {a[0] for a in allocation}
                extra_types = actual_by_type[~actual_by_type["基金类型"].isin(suggested_types)]
                for _, row in extra_types.iterrows():
                    ftype = row["基金类型"]
                    actual_amt = float(row["实际金额"])
                    actual_pct = (actual_amt / total_actual * 100) if total_actual > 0 else 0.0
                    cmp_rows.append({
                        "基金类型": ftype,
                        "建议比例": "—",
                        "建议金额": "—",
                        "实际金额": f"{actual_amt:,.0f}",
                        "实际比例": f"{actual_pct:.1f}%",
                        "差额": f"{actual_amt:,.0f}",
                        "状态": "ℹ️ 建议外",
                    })

                cmp_df = pd.DataFrame(cmp_rows)
                st.dataframe(cmp_df, use_container_width=True, hide_index=True, height=min(46 * max(len(cmp_rows), 1) + 38, 400))

                # --- 双饼图对比 ---
                st.markdown("**建议 vs 实际**")
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("💡 建议配置")
                    pie_suggest = pd.DataFrame([
                        {"基金类型": a[0], "金额": total_amount * a[1] / 100}
                        for a in allocation
                    ])
                    pie_s = alt.Chart(pie_suggest).mark_arc(innerRadius=50).encode(
                        theta=alt.Theta("金额:Q"),
                        color=alt.Color("基金类型:N", legend=None),
                        tooltip=["基金类型:N", alt.Tooltip("金额:Q", format=",.0f")],
                    ).properties(height=220)
                    st.altair_chart(pie_s, use_container_width=True)

                with c2:
                    st.markdown("📌 实际配置")
                    if total_actual > 0:
                        pie_actual = pd.DataFrame([
                            {"基金类型": r["基金类型"], "金额": r["实际金额"]}
                            for _, r in actual_by_type.iterrows() if r["实际金额"] > 0
                        ])
                        pie_a = alt.Chart(pie_actual).mark_arc(innerRadius=50).encode(
                            theta=alt.Theta("金额:Q"),
                            color=alt.Color("基金类型:N", legend=None),
                            tooltip=["基金类型:N", alt.Tooltip("金额:Q", format=",.0f")],
                        ).properties(height=220)
                        st.altair_chart(pie_a, use_container_width=True)
                    else:
                        st.info("暂无持仓金额，实际饼图待补充。")

                # --- 明细列表 ---
                st.markdown("**持仓/关注明细**")
                all_disp = all_df.copy()
                all_disp["投入金额"] = all_disp["投入金额"].map(lambda v: f"{v:,.2f}")
                all_disp = all_disp.sort_values("基金类型")
                st.dataframe(all_disp[["基金代码", "基金名称", "基金类型", "数据来源", "投入金额"]],
                             use_container_width=True, hide_index=True, height=min(46 * max(len(all_disp), 1) + 38, 300))

                # --- 快捷操作 ---
                if followed_only:
                    st.info(
                        f"📌 有 **{len(followed_only)}** 只关注基金尚未持仓（金额为 0），"
                        f"请在「💼 持仓追踪」页添加金额，以便精确对比。"
                    )

                # ---- 🤖 智能配置建议（风险平价 / 最小方差）----
                st.markdown("---")
                st.subheader("🤖 智能配置建议（基于基金历史波动）")
                st.caption(
                    "采用机构常用的**风险平价**（桥水全天候策略核心思想：波动小的基金多配、"
                    "波动大的少配）与**最小方差**（Markowitz 均值-方差模型）方法，"
                    "根据每只基金近 1 年的真实净值波动，计算您该给每只基金投多少钱。"
                )

                fund_options = [
                    f"{r['基金代码']} {r['基金名称']}" for _, r in all_df.iterrows()
                ]
                if len(fund_options) > 10:
                    st.caption(f"共 {len(fund_options)} 只基金，为控制计算量每次最多分析 10 只。")
                default_picks = fund_options[:10]
                picked = st.multiselect(
                    "选择参与智能配置的基金（建议 2-10 只，风格越分散效果越好）",
                    options=fund_options,
                    default=default_picks,
                    key="sa_picked_funds",
                )

                col_run, col_info = st.columns([1, 3])
                with col_run:
                    run_smart = st.button("🤖 生成智能配置", use_container_width=True, type="primary")
                with col_info:
                    st.caption(f"投资总金额：¥{total_amount:,.0f}（在上方「投资金额」处修改）")

                if run_smart:
                    if len(picked) < 2:
                        st.warning("请至少选择 2 只基金进行配置分析。")
                    else:
                        funds_input = []
                        for p in picked[:10]:
                            parts = str(p).split(" ", 1)
                            funds_input.append((parts[0], parts[1] if len(parts) > 1 else ""))

                        with st.spinner(f"正在拉取 {len(funds_input)} 只基金的净值数据并计算风险指标…（约需 10-30 秒）"):
                            sa_df, sa_warnings = build_smart_allocation(
                                funds_input, total_amount, fetcher=get_default_fetcher()
                            )

                        if sa_warnings:
                            for w in sa_warnings:
                                st.warning(w)

                        if len(sa_df) >= 1:
                            st.markdown("##### 📈 基金风险体检（按波动率从低到高）")
                            show_df = sa_df.copy()
                            show_df["年化收益"] = show_df["年化收益"].map(lambda x: f"{x*100:.2f}%")
                            show_df["年化波动"] = show_df["年化波动"].map(lambda x: f"{x*100:.2f}%")
                            show_df["最大回撤"] = show_df["最大回撤"].map(lambda x: f"{x*100:.2f}%")
                            show_df["夏普比率"] = show_df["夏普比率"].map(lambda x: f"{x:.2f}")
                            show_df["风险平价权重"] = show_df["风险平价权重"].map(lambda x: f"{x*100:.1f}%")
                            money_cols = ["建议金额(风险平价)", "等权金额"]
                            if "建议金额(最小方差)" in show_df.columns:
                                money_cols.append("建议金额(最小方差)")
                                show_df["最小方差权重"] = show_df["最小方差权重"].map(lambda x: f"{x*100:.1f}%")
                            for c in money_cols:
                                show_df[c] = show_df[c].map(lambda x: f"¥{x:,.0f}")
                            st.dataframe(
                                show_df[["基金代码", "基金名称", "年化收益", "年化波动", "夏普比率",
                                         "最大回撤", "风险平价权重", "建议金额(风险平价)"] +
                                        (["最小方差权重", "建议金额(最小方差)"] if "最小方差权重" in show_df.columns else []) +
                                        ["等权金额"]],
                                use_container_width=True, hide_index=True,
                            )

                            st.markdown("##### 💡 新手怎么看这张表？")
                            with st.expander("点击查看指标解读"):
                                st.markdown(
                                    "- **年化波动**：基金一年涨跌的'颠簸程度'。低于 15% 算稳健，"
                                    "超过 30% 说明大起大落，新手要少配。\n"
                                    "- **最大回撤**：历史上从最高点亏得最惨的幅度。-40% 意味着曾经 1 万块亏到只剩 6 千，"
                                    "买之前先问自己能不能承受。\n"
                                    "- **夏普比率**：每承担 1 份风险换来多少超额收益。大于 1 算优秀，"
                                    "越高说明'性价比'越好。\n"
                                    "- **风险平价权重**：波动越小的基金权重越高，让组合整体更稳——"
                                    "这是桥水基金「全天候策略」的核心思想。\n"
                                    "- **等权金额**：每只基金投一样多的钱，作为对照。"
                                    "你会发现风险平价建议'往低波基金倾斜'，而不是平均撒钱。"
                                )

                            low_vol = sa_df.iloc[0]
                            high_vol = sa_df.iloc[-1]
                            st.success(
                                f"📌 **配置建议**：最稳的是「{low_vol['基金名称'] or low_vol['基金代码']}」"
                                f"（年化波动 {low_vol['年化波动']*100:.1f}%），"
                                f"建议投入 ¥{low_vol['建议金额(风险平价)']:,.0f}；"
                                f"波动最大的是「{high_vol['基金名称'] or high_vol['基金代码']}」"
                                f"（年化波动 {high_vol['年化波动']*100:.1f}%），"
                                f"建议只投 ¥{high_vol['建议金额(风险平价)']:,.0f}。"
                            )
            else:
                st.info(
                    "暂无持仓或关注基金。\n\n"
                    "1. 前往「💼 持仓追踪」添加持仓并输入金额\n"
                    "2. 或在「📋 基金数据」页关注感兴趣的基金\n\n"
                    "添加后，这里会自动对比您的配置方案。"
                )

            # ---- 各类型推荐基金 ----
            st.markdown("---")
            st.subheader("📌 各类型推荐基金")
            st.caption("每类推荐 12 只，按「近1年收益」降序 + 「手续费」升序排列（高回报低费率优先）。勾选表格行可跳转对比。")
            df, err, _ = load_fund_data()

            if df is not None and len(df) > 0 and "基金简称" in df.columns:
                df = df.copy()
                df["推断类型"] = df["基金简称"].apply(classify_fund_type)

                sort_col = None
                for c in ["近1年", "近6月", "近3月", "日增长率"]:
                    if c in df.columns:
                        sort_col = c
                        break

                # 手续费列转数值（用于排序）
                fee_col = "手续费"
                if fee_col in df.columns:
                    df["_fee_num"] = pd.to_numeric(
                        df[fee_col].astype(str).str.replace("%", "", regex=False).str.replace("---", "999", regex=False),
                        errors="coerce",
                    ).fillna(999)
                else:
                    df["_fee_num"] = 999

                if sort_col:
                    df[sort_col] = pd.to_numeric(df[sort_col], errors="coerce")

                all_recommendations = []
                for ftype, pct, note in allocation:
                    subset = df[df["推断类型"] == ftype].copy()
                    if len(subset) == 0:
                        continue
                    if sort_col:
                        subset = subset.dropna(subset=[sort_col]).sort_values(
                            by=[sort_col, "_fee_num"], ascending=[False, True]
                        )
                    top = subset.head(12).copy()
                    top["基金类型"] = ftype
                    top["建议比例"] = f"{pct}%"
                    all_recommendations.append(top)

                if all_recommendations:
                    rec_df = pd.concat(all_recommendations, ignore_index=True)
                    rec_cols = ["基金代码", "基金简称", "基金类型", "建议比例"]
                    if sort_col:
                        rec_cols.append(sort_col)
                    if fee_col in rec_df.columns:
                        rec_cols.append(fee_col)
                    rec_df = rec_df[rec_cols]
                    rec_df["基金代码"] = rec_df["基金代码"].astype(str)

                    disp = rec_df.copy()
                    if sort_col and sort_col in disp.columns:
                        disp[sort_col] = disp[sort_col].map(lambda v: "" if pd.isna(v) else f"{v:.2f}%")
                    if fee_col in disp.columns:
                        disp[fee_col] = disp[fee_col].astype(str).where(disp[fee_col].astype(str) != "---", "—")

                    event = st.dataframe(
                        disp,
                        use_container_width=True,
                        hide_index=True,
                        height=450,
                        on_select="rerun",
                        selection_mode="multi-row",
                        key="risk_rec_table",
                    )

                    sel_rows = [i for i in event.selection.rows if i < len(disp)]
                    if sel_rows:
                        sel_codes = [
                            str(disp.iloc[i]["基金代码"]).strip().split(".")[0].zfill(6)
                            for i in sel_rows
                        ]
                        sel_names = [str(disp.iloc[i]["基金简称"]) for i in sel_rows]
                        label = "、".join(f"{c} {n}" for c, n in zip(sel_codes, sel_names))
                        st.success(f"已勾选 {len(sel_codes)} 只基金：{label}")
                        col_a, col_b = st.columns([1, 3])
                        with col_a:
                            st.button(
                                "📊 跳转单基金分析",
                                type="primary",
                                on_click=goto_analysis,
                                args=(sel_codes[0],),
                                use_container_width=True,
                            )
                        with col_b:
                            if len(sel_codes) >= 2:
                                st.button(
                                    "⚖️ 跳转多基金对比",
                                    type="primary",
                                    on_click=goto_compare,
                                    args=(sel_codes,),
                                    use_container_width=True,
                                )
                            else:
                                st.caption("勾选 2 只以上可跳转多基金对比")
                    else:
                        st.caption("💡 勾选表格左侧复选框 → 跳转单基金分析（1只）或多基金对比（2只以上）")

                    # ---- 导出配置方案 ----
                    st.markdown("---")
                    st.download_button(
                        "📥 导出配置方案 Excel",
                        data=to_excel_bytes({"配置总览": alloc_df, "推荐基金": disp}),
                        file_name=f"投资配置方案_{profile_name}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                else:
                    st.info("暂未找到匹配类型的基金，请先在「基金数据」页面刷新数据。")
            else:
                st.info("基金数据未加载，请先在「基金数据」页面加载数据。")


# ===============================
# 页面：持仓追踪（看盘）
# ===============================
@st.cache_data(ttl=60, show_spinner=False)
def _load_realtime_quote_cache(stock_codes_tuple):
    """缓存实时行情 60 秒，避免频繁请求。"""
    fetcher = get_default_fetcher()
    return fetcher.get_stocks_realtime_quote(list(stock_codes_tuple))


def _portfolio_growth_color(val):
    """涨红跌绿着色。"""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if pd.isna(v):
        return None
    if v > 0:
        return "color:#e03131;font-weight:600"
    if v < 0:
        return "color:#2f9e44;font-weight:600"
    return None


def render_portfolio():
    st.header("💼 持仓追踪")
    st.caption(
        "记录您已投入的基金和金额，聚合各基金重仓股，像看盘一样实时查看它们的变化。"
        "数据来源：天天基金重仓股 + 东方财富 A 股实时行情。"
    )

    # ---- 持仓管理 ----
    st.subheader("📋 我的持仓")
    holdings = _db.list_holdings()

    with st.expander("➕ 添加 / 更新持仓", expanded=(len(holdings) == 0)):
        # ---- 从关注基金快速添加 ----
        followed_map_portfolio = get_followed_map()
        holding_codes_portfolio = {str(h["fund_code"]).zfill(6) for h in holdings}
        followed_only_portfolio = [
            {"fund_code": c, "fund_name": m.get("fund_name", "")}
            for c, m in followed_map_portfolio.items()
            if c not in holding_codes_portfolio
        ]

        if followed_only_portfolio:
            st.markdown("**⭐ 从关注基金快速添加（免输代码）**")
            fc1, fc2, fc3 = st.columns([3, 2, 1])
            with fc1:
                quick_opts = ["（选择一只关注的基金）"] + [
                    f"{f['fund_code']} {f['fund_name']}" for f in followed_only_portfolio
                ]
                quick_pick = st.selectbox(
                    "选择关注基金", quick_opts, key="pf_quick_pick", label_visibility="collapsed"
                )
            with fc2:
                quick_amount = st.number_input(
                    "投入金额（元）", min_value=0.0, step=1000.0, format="%.2f",
                    key="pf_quick_amount", label_visibility="collapsed",
                    placeholder="投入金额",
                )
            with fc3:
                st.write("")
                st.write("")
                quick_btn = st.button(
                    "添加", type="primary", use_container_width=True, key="pf_quick_btn",
                    disabled=(quick_pick == "（选择一只关注的基金）"),
                )

            if quick_btn:
                qcode = quick_pick.split(" ")[0]
                qname = quick_pick[len(qcode)+1:]
                _db.upsert_holding(qcode, qname, float(quick_amount), "")
                st.success(f"✅ 已添加持仓：{qcode} {qname}，金额 {quick_amount:,.2f} 元")
                st.rerun()

            st.markdown("---")

        # ---- 手动输入基金代码 ----
        st.markdown("**手动输入基金代码**")
        col_c, col_a, col_n, col_btn = st.columns([2, 2, 3, 1])
        with col_c:
            new_code = st.text_input("基金代码（6 位）", key="pf_new_code", placeholder="如 161725")
        with col_a:
            new_amount = st.number_input("投入金额（元）", min_value=0.0, step=1000.0, format="%.2f", key="pf_new_amount")
        with col_n:
            new_note = st.text_input("备注（可选）", key="pf_new_note", placeholder="如 2026-08 买入")
        with col_btn:
            st.write("")
            st.write("")
            add_clicked = st.button("保存", type="primary", use_container_width=True, key="pf_add_btn")

        if add_clicked:
            code = str(new_code).strip()
            if not (code.isdigit() and len(code) == 6):
                st.error("基金代码应为 6 位数字。")
            else:
                with st.spinner("正在获取基金信息..."):
                    name, _nav_df, _err = load_fund_nav(code)
                fname = name or code
                _db.upsert_holding(code, fname, float(new_amount), new_note)
                st.success(f"✅ 已保存持仓：{code} {fname}，金额 {new_amount:,.2f} 元")
                st.rerun()

    if not holdings:
        st.info("您还没有记录任何持仓。请在上方添加您已投入的基金。")
        return

    # 持仓表
    h_df = pd.DataFrame(holdings)
    total_amount = float(h_df["amount"].sum())
    disp = h_df[["fund_code", "fund_name", "amount", "note", "added_at"]].copy()
    disp.columns = ["基金代码", "基金名称", "投入金额", "备注", "添加时间"]
    disp["投入金额"] = disp["投入金额"].map(lambda v: f"{v:,.2f}")
    st.dataframe(disp, use_container_width=True, hide_index=True, height=200)

    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("持仓基金数", f"{len(holdings)}")
    with m2:
        st.metric("总投入金额", f"{total_amount:,.2f} 元")
    with m3:
        if st.button("🗑️ 清空全部持仓", use_container_width=True):
            _db.clear_holdings()
            st.success("已清空全部持仓。")
            st.rerun()

    # ---- 删除单个持仓（常驻显示，不藏在折叠面板里）----
    del_col1, del_col2, del_col3 = st.columns([3, 1, 1])
    with del_col1:
        del_opts = [f"{h['fund_code']} {h['fund_name']}" for h in holdings]
        del_code = st.selectbox("选择要删除的持仓", del_opts, key="pf_del_sel")
    with del_col2:
        st.write("")
        st.write("")
        if st.button("❌ 删除", key="pf_del_btn", use_container_width=True):
            code_to_del = del_code.split(" ")[0]
            _db.delete_holding(code_to_del)
            st.success(f"已删除持仓：{code_to_del}")
            st.rerun()
    with del_col3:
        st.write("")
        st.write("")
        # 一键把全部持仓基金添加为关注
        if st.button("⭐ 关注全部持仓", key="pf_follow_all_btn", use_container_width=True,
                      help="把您当前持仓的基金全部添加到关注列表，方便在基金数据页快速查看"):
            added = 0
            for h in holdings:
                c = str(h["fund_code"]).zfill(6)
                _db.follow_fund(c, h.get("fund_name", ""))
                added += 1
            st.success(f"✅ 已将 {added} 只持仓基金全部添加到关注列表")
            st.rerun()

    # ---- 看盘区 ----
    st.markdown("---")
    st.subheader("📈 重仓股实时看盘")

    col_ref, col_auto = st.columns([1, 3])
    with col_ref:
        refresh = st.button("🔄 刷新实时行情", type="primary", use_container_width=True, key="pf_refresh")
    with col_auto:
        st.caption("行情缓存 60 秒；点击按钮可立即获取最新数据。仅交易日交易时段返回实时价，否则为收盘价。")

    # 1) 拉取各基金重仓股
    fund_holdings = {}
    fund_holdings_err = {}
    progress = st.progress(0.0, text="正在获取各基金重仓股...")
    for i, h in enumerate(holdings):
        code = h["fund_code"]
        hdf, herr = load_fund_holdings(code)
        if hdf is not None and len(hdf) > 0:
            fund_holdings[code] = hdf
        else:
            fund_holdings_err[code] = herr or "无重仓股数据"
        progress.progress((i + 1) / len(holdings), text=f"已获取 {i + 1}/{len(holdings)} 只基金重仓股")
    progress.empty()

    if not fund_holdings:
        st.warning("您的持仓基金均无重仓股数据（可能是债券型 / 货币型 / QDII），无法看盘。")
        return

    # 2) 聚合重仓股，按持仓金额加权
    stock_rows = []
    for h in holdings:
        code = h["fund_code"]
        amount = float(h["amount"])
        fund_ratio = amount / total_amount if total_amount > 0 else 0.0
        hdf = fund_holdings.get(code)
        if hdf is None or len(hdf) == 0:
            continue
        for _, row in hdf.iterrows():
            scode = str(row.get("股票代码", "")).strip()
            sname = str(row.get("股票名称", "")).strip()
            pct = row.get("占净值比例")
            try:
                pct = float(pct)
            except (TypeError, ValueError):
                pct = 0.0
            if not scode or scode == "nan":
                continue
            stock_rows.append({
                "股票代码": scode,
                "股票名称": sname,
                "基金代码": code,
                "基金名称": h["fund_name"],
                "持仓金额占比": fund_ratio,
                "占净值比例(%)": pct,
            })

    if not stock_rows:
        st.warning("未能从持仓基金中聚合出任何重仓股。")
        return

    rows_df = pd.DataFrame(stock_rows)
    rows_df["_w"] = rows_df["持仓金额占比"] * rows_df["占净值比例(%)"] / 100.0
    agg = rows_df.groupby("股票代码", as_index=False).agg(
        股票名称=("股票名称", "first"),
        综合权重=("_w", "sum"),
        持有基金数=("基金代码", "nunique"),
    )
    agg["综合权重(%)"] = agg["综合权重"] * 100
    agg = agg.sort_values("综合权重", ascending=False).reset_index(drop=True)

    # 3) 拉取实时行情
    all_codes = agg["股票代码"].tolist()
    if refresh:
        _load_realtime_quote_cache.clear()
    with st.spinner("正在获取 A 股实时行情（约需数秒）..."):
        quote_df, qerr = _load_realtime_quote_cache(tuple(all_codes))

    if qerr is not None or quote_df is None or len(quote_df) == 0:
        # 友好提示 + 降级展示（不暴露技术堆栈）
        st.warning("📡 当前网络暂时无法获取实时行情，以下为重仓股汇总信息（不含实时涨跌）")
        with st.expander("🔍 查看重仓股列表"):
            st.dataframe(
                agg[["股票代码", "股票名称", "综合权重(%)", "持有基金数"]],
                use_container_width=True, hide_index=True,
            )
        if qerr:
            with st.expander("🛠️ 技术详情（供排查）"):
                st.caption(qerr)
        return

    # 4) 合并行情 + 综合权重
    merged = agg.merge(quote_df, on="股票代码", how="left")

    # 处理合并后的重复列（两侧都有"股票名称"，merge 会加 _x/_y 后缀）
    if "股票名称_x" in merged.columns and "股票名称_y" in merged.columns:
        merged["股票名称"] = merged["股票名称_x"].fillna(merged["股票名称_y"])
        merged = merged.drop(columns=["股票名称_x", "股票名称_y"])
    elif "股票名称_x" in merged.columns:
        merged = merged.rename(columns={"股票名称_x": "股票名称"})
    elif "股票名称_y" in merged.columns:
        merged = merged.rename(columns={"股票名称_y": "股票名称"})

    merged["预估影响金额"] = total_amount * merged["综合权重"] * merged["涨跌幅"] / 100.0

    valid = merged.dropna(subset=["涨跌幅"]).copy()
    weighted_change = float((valid["综合权重"] * valid["涨跌幅"]).sum()) if len(valid) else 0.0
    est_total_pnl = float(valid["预估影响金额"].sum()) if len(valid) else 0.0

    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.metric("重仓股数量", f"{len(merged)}")
    with s2:
        st.metric("综合加权涨跌", fmt_pct(weighted_change / 100))
    with s3:
        st.metric("预估影响金额", f"{est_total_pnl:,.2f} 元")
    with s4:
        st.metric("行情时间", now_cn().strftime("%H:%M:%S（北京时间）"))

    st.caption(
        "⚠️ 以上为基于各基金前十大重仓股的粗略估算，仅反映重仓股部分（通常占净值 30~50%），"
        "不代表基金实际净值涨跌，仅供看盘参考。"
    )

    # 看盘表
    show_cols = ["股票代码", "股票名称", "最新价", "涨跌幅", "涨跌额", "今开", "昨收",
                 "综合权重(%)", "持有基金数", "预估影响金额"]
    show_cols = [c for c in show_cols if c in merged.columns]
    disp_q = merged[show_cols].copy()

    fmt_map = {}
    for c in ["最新价", "今开", "昨收", "涨跌额"]:
        if c in disp_q.columns:
            fmt_map[c] = "{:.2f}"
    if "涨跌幅" in disp_q.columns:
        fmt_map["涨跌幅"] = "{:.2f}%"
    if "综合权重(%)" in disp_q.columns:
        fmt_map["综合权重(%)"] = "{:.2f}%"
    if "预估影响金额" in disp_q.columns:
        fmt_map["预估影响金额"] = "{:,.2f}"

    styler = disp_q.style.format(formatter=fmt_map, na_rep="—")
    for c in ["涨跌幅", "涨跌额", "预估影响金额"]:
        if c in disp_q.columns:
            styler = styler.map(_portfolio_growth_color, subset=[c])
    st.dataframe(styler, use_container_width=True, hide_index=True, height=520)

    # 涨跌幅分布图
    if len(valid) > 0:
        st.markdown("---")
        st.subheader("📊 重仓股涨跌幅分布（前 30）")
        bar_df = valid.sort_values("涨跌幅", ascending=False).head(30).copy()
        bar_df["涨跌幅(%)"] = bar_df["涨跌幅"]
        bar = alt.Chart(bar_df).mark_bar().encode(
            x=alt.X("涨跌幅(%):Q", title="涨跌幅（%）"),
            y=alt.Y("股票名称:N", sort="-x", title=None, axis=alt.Axis(labelFontSize=11)),
            color=alt.condition(
                alt.datum["涨跌幅(%)"] > 0,
                alt.value("#e03131"),
                alt.value("#2f9e44"),
            ),
            tooltip=[
                alt.Tooltip("股票名称:N", title="股票"),
                alt.Tooltip("涨跌幅(%):Q", format=".2f", title="涨跌幅"),
                alt.Tooltip("综合权重(%):Q", format=".2f", title="综合权重"),
            ],
        ).properties(height=max(200, min(28 * len(bar_df), 600)))
        st.altair_chart(bar, use_container_width=True)

    # 各基金重仓股明细
    st.markdown("---")
    st.subheader("🗂️ 各基金重仓股明细")
    for h in holdings:
        code = h["fund_code"]
        fname = h["fund_name"]
        hdf = fund_holdings.get(code)
        if hdf is None or len(hdf) == 0:
            st.caption(f"- {code} {fname}：{fund_holdings_err.get(code, '无重仓股数据')}")
            continue
        h_period = str(hdf["季度"].iloc[0]).replace("股票投资明细", "").strip() if "季度" in hdf.columns else "最新报告期"
        with st.expander(f"{code} {fname}（投入 {h['amount']:,.2f} 元，{h_period}，{len(hdf)} 只）"):
            h_disp = hdf.copy()
            if "占净值比例" in h_disp.columns:
                h_disp["占净值比例"] = h_disp["占净值比例"].map(
                    lambda v: "" if pd.isna(v) else f"{v:.2f}%"
                )
            show_cols2 = [c for c in ["序号", "股票代码", "股票名称", "占净值比例", "持股数", "持仓市值"] if c in h_disp.columns]
            st.dataframe(h_disp[show_cols2], use_container_width=True, hide_index=True, height=300)

    # ---- 持仓基金分析 ----
    st.markdown("---")
    st.subheader("📊 持仓基金分析（风险体检）")
    st.caption(
        "基于每只基金近 1 年真实净值波动，计算年化收益、年化波动、夏普比率、最大回撤。"
        "并采用**风险平价**模型给出配置优化建议（波动小的基金多配、波动大的少配）。"
    )

    col_an1, col_an2 = st.columns([1, 3])
    with col_an1:
        run_analysis = st.button("🔍 分析持仓", type="primary", use_container_width=True, key="pf_analyze_btn")
    with col_an2:
        st.caption("点击后将逐只拉取近 1 年净值数据（约 10-30 秒），给出风险体检 + 配置优化建议。")

    if run_analysis:
        funds_to_analyze = [
            (str(h["fund_code"]).zfill(6), h.get("fund_name", ""))
            for h in holdings
        ]
        if len(funds_to_analyze) < 1:
            st.info("没有持仓基金可分析。")
        elif len(funds_to_analyze) > 10:
            st.warning("持仓基金较多，仅分析前 10 只（按添加顺序）。")
            funds_to_analyze = funds_to_analyze[:10]

        if funds_to_analyze:
            progress_bar = st.progress(0.0, text="正在拉取净值数据...")
            current_amount = float(h_df["amount"].sum())

            def _progress_cb(idx, total, code):
                progress_bar.progress(idx / total, text=f"正在获取 {idx}/{total}：{code} 的净值数据...")

            with st.spinner(f"正在分析 {len(funds_to_analyze)} 只持仓基金..."):
                an_df, an_warnings = build_smart_allocation(
                    funds_to_analyze, current_amount,
                    fetcher=get_default_fetcher(),
                    progress_callback=_progress_cb,
                )
            progress_bar.empty()

            for w in an_warnings:
                st.warning(w)

            if len(an_df) >= 1:
                # --- 风险体检表 ---
                st.markdown("##### 📈 持仓风险体检（按波动率从低到高排序）")
                show_an = an_df.copy()
                show_an["年化收益"] = show_an["年化收益"].map(lambda x: f"{x*100:.2f}%")
                show_an["年化波动"] = show_an["年化波动"].map(lambda x: f"{x*100:.2f}%")
                show_an["最大回撤"] = show_an["最大回撤"].map(lambda x: f"{x*100:.2f}%")
                show_an["夏普比率"] = show_an["夏普比率"].map(lambda x: f"{x:.2f}")
                show_an["风险平价权重"] = show_an["风险平价权重"].map(lambda x: f"{x*100:.1f}%")
                show_an["建议金额(风险平价)"] = show_an["建议金额(风险平价)"].map(lambda x: f"¥{x:,.0f}")
                show_an["等权金额"] = show_an["等权金额"].map(lambda x: f"¥{x:,.0f}")
                if "最小方差权重" in show_an.columns:
                    show_an["最小方差权重"] = show_an["最小方差权重"].map(lambda x: f"{x*100:.1f}%")
                    show_an["建议金额(最小方差)"] = show_an["建议金额(最小方差)"].map(lambda x: f"¥{x:,.0f}")
                    disp_cols = ["基金代码", "基金名称", "年化收益", "年化波动", "夏普比率",
                                 "最大回撤", "风险平价权重", "建议金额(风险平价)",
                                 "最小方差权重", "建议金额(最小方差)", "等权金额"]
                else:
                    disp_cols = ["基金代码", "基金名称", "年化收益", "年化波动", "夏普比率",
                                 "最大回撤", "风险平价权重", "建议金额(风险平价)", "等权金额"]
                st.dataframe(show_an[disp_cols], use_container_width=True, hide_index=True)

                # --- 关键发现 ---
                st.markdown("##### 💡 关键发现")
                lowest_vol = an_df.iloc[0]
                highest_vol = an_df.iloc[-1]
                findings = []
                findings.append(
                    f"- 📌 最稳健的持仓：「{lowest_vol['基金名称'] or lowest_vol['基金代码']}」"
                    f"（年化波动 {lowest_vol['年化波动']*100:.1f}%，最大回撤 {lowest_vol['最大回撤']*100:.1f}%）"
                )
                findings.append(
                    f"- ⚠️ 波动最大的持仓：「{highest_vol['基金名称'] or highest_vol['基金代码']}」"
                    f"（年化波动 {highest_vol['年化波动']*100:.1f}%，最大回撤 {highest_vol['最大回撤']*100:.1f}%），"
                    f"建议控制仓位"
                )
                # 看看有没有夏普为负的
                neg_sharpe = an_df[an_df["夏普比率"] < 0]
                if len(neg_sharpe) > 0:
                    findings.append(
                        f"- 🚫 有 {len(neg_sharpe)} 只基金夏普比率为负（承担风险却没获得超额收益），"
                        f"建议考虑是否继续持有"
                    )
                # 配置建议
                # 计算实际权重 vs 建议权重差异
                an_df["_actual_w"] = an_df["基金代码"].map(
                    {str(h["fund_code"]).zfill(6): float(h["amount"]) / current_amount for h in holdings}
                )
                an_df["_diff"] = an_df["_actual_w"] - an_df["风险平价权重"]
                over_weighted = an_df[an_df["_diff"] > 0.05]
                if len(over_weighted) > 0:
                    names = ", ".join(
                        f"「{r['基金名称'] or r['基金代码']}」(超配{(r['_diff']*100):.0f}%)"
                        for _, r in over_weighted.head(3).iterrows()
                    )
                    findings.append(f"- 📊 相对风险平价建议，以下基金可能**超配**：{names}")
                under_weighted = an_df[an_df["_diff"] < -0.05]
                if len(under_weighted) > 0:
                    names = ", ".join(
                        f"「{r['基金名称'] or r['基金代码']}」(低配{(r['_diff']*100):.0f}%)"
                        for _, r in under_weighted.head(3).iterrows()
                    )
                    findings.append(f"- 📊 相对风险平价建议，以下基金可能**低配**：{names}")

                for f in findings:
                    st.markdown(f)

                with st.expander("📖 指标解读（新手必读）"):
                    st.markdown(
                        "- **年化波动**：基金一年涨跌的'颠簸程度'。低于 15% 算稳健，"
                        "超过 30% 说明大起大落。\n"
                        "- **最大回撤**：历史上从最高点亏得最惨的幅度。"
                        "-40% 意味着曾经 1 万块亏到只剩 6 千。\n"
                        "- **夏普比率**：每承担 1 份风险换来多少超额收益。"
                        "大于 1 算优秀，负数意味着还不如不投。\n"
                        "- **风险平价权重**：波动越小的基金建议配越多，"
                        "让组合整体更稳（桥水全天候策略核心思想）。\n"
                        "- **超配/低配**：你的实际配置 vs 建议配置的差距。"
                        "超配 = 你投太多了，低配 = 投太少了。"
                    )


# ===============================
# 页面：设置
# ===============================
def render_settings():
    st.header("⚙️ 设置")
    st.caption("配置应用参数，设置会持久化保存到本地，下次打开自动恢复")

    # 确保默认值存在（未保存过时）
    defaults = {
        "settings_rf": 0.02,
        "settings_range": PRESET_RANGES[2],
        "settings_page_size": 50,
        "settings_theme": "默认蓝色",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # ---- 分析参数 ----
    st.subheader("📈 分析参数")
    col1, col2 = st.columns(2)
    with col1:
        st.number_input(
            "默认无风险利率（年化小数）",
            min_value=0.0, max_value=0.10, step=0.005, format="%.3f",
            help="用于计算夏普比率，国内常用 2%（对应一年期国债收益率）",
            key="settings_rf",
            on_change=save_settings_to_db,
        )
    with col2:
        st.selectbox(
            "默认分析区间", PRESET_RANGES,
            key="settings_range",
            on_change=save_settings_to_db,
        )

    # ---- 显示参数 ----
    st.subheader("🖥️ 显示参数")
    col3, col4 = st.columns(2)
    with col3:
        st.selectbox(
            "基金数据每页行数", [20, 50, 100, 200],
            key="settings_page_size",
            on_change=save_settings_to_db,
        )
    with col4:
        st.selectbox(
            "图表配色主题", ["默认蓝色", "暖色", "冷色"],
            key="settings_theme",
            on_change=save_settings_to_db,
        )

    st.success("✅ 设置已自动保存到本地，刷新或重启后仍然有效。")

    st.markdown("---")

    # ---- 数据源 ----
    st.subheader("📡 数据源信息")
    st.info(
        "**数据来源**：东方财富-天天基金网\n\n"
        "- 基金列表：AKShare fund_open_fund_rank_em\n"
        "- 基金净值：天天基金 pingzhongdata 接口\n"
        "- 基金档案：天天基金 fundf10 基本概况页\n"
        "- 重仓股：AKShare fund_portfolio_hold_em\n\n"
        "数据仅供个人学习参考，不构成投资建议。"
    )

    st.markdown("---")

    # ---- 关于 ----
    st.subheader("ℹ️ 关于")
    st.write(f"- **应用名称**：{config.app_name}")
    st.write(f"- **版本**：v0.5.0")
    st.write(f"- **技术栈**：Python + Streamlit + AKShare + Altair")
    st.write(f"- **运行环境**：{sys.version.split()[0]}")
    st.write(f"- **项目路径**：`{config.project_root}`")

    st.markdown("---")
    st.caption("⚠️ 以上设置已持久化保存到本地数据库，刷新或重启后自动恢复。")


# ===============================
# 页面：通用占位（保留兼容）
# ===============================
def render_placeholder(title: str):
    st.header(f"{title} - 敬请期待")
    st.info("该功能正在开发中，将在后续阶段实现...")


# ===============================
# 主路由
# ===============================
if page == PAGE_HOME:
    render_home()
elif page == PAGE_DATA:
    render_fund_data()
elif page == PAGE_SINGLE:
    render_fund_analysis()
elif page == PAGE_COMPARE:
    render_fund_compare()
elif page == PAGE_RISK:
    render_risk_assessment()
elif page == PAGE_PORTFOLIO:
    render_portfolio()
elif page == PAGE_DAILY_REVIEW:
    render_daily_review()
elif page == PAGE_MANAGE:
    render_fund_management()
elif page == PAGE_SETTINGS:
    render_settings()

# 页脚
st.markdown("---")
st.caption("💼 基金雷达 - 仅供个人学习使用，不构成投资建议")
