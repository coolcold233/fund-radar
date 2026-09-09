# -*- coding: utf-8 -*-
"""
当日股市复盘 - 数据拉取模块
直接调用新浪/东方财富底层 HTTP 接口，不依赖 AKShare 上层封装。
"""

import datetime
import re
import warnings
from typing import Optional, Any, Dict, List, Tuple

import pandas as pd
import requests

warnings.filterwarnings("ignore")


# ================================================================
# 新浪实时行情解析
# ================================================================

SINA_INDEX_CODES = {
    "shanghai": ("sh000001", "上证指数"),
    "shenzhen": ("sz399001", "深证成指"),
    "chinext": ("sz399006", "创业板指"),
    "star50": ("sh000688", "科创50"),
}


def _fetch_sina_hq(codes: List[str]) -> Dict[str, List[str]]:
    """批量拉取新浪实时行情，返回 {code: [fields...]}。"""
    if not codes:
        return {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    url = f"https://hq.sinajs.cn/list={','.join(codes)}"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "gbk"
        result = {}
        for line in r.text.strip().split("\n"):
            m = re.match(r'var\s+hq_str_(\w+)="(.*)";', line)
            if m:
                code = m.group(1)
                fields = m.group(2).split(",")
                result[code] = fields
        return result
    except Exception:
        return {}


def _parse_sina_index(fields: List[str]) -> Optional[Dict[str, Any]]:
    """新浪指数字段解析。
    字段顺序：名称,今开,昨收,当前价,最高,最低,...,成交量(手),成交额,...,日期,时间
    """
    try:
        if len(fields) < 32:
            return None
        name = fields[0]
        prev_close = float(fields[2])
        close = float(fields[3])
        high = float(fields[4])
        low = float(fields[5])
        volume = float(fields[8])   # 手
        amount = float(fields[9])   # 元
        date_str = fields[30]
        time_str = fields[31]

        change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0
        return {
            "name": name,
            "close": round(close, 2),
            "prev_close": round(prev_close, 2),
            "change_pct": change_pct,
            "high": round(high, 2),
            "low": round(low, 2),
            "volume": round(volume / 1e4, 2),  # 万手
            "amount": round(amount / 1e8, 2),  # 亿
            "time": f"{date_str} {time_str}",
        }
    except Exception:
        return None


# ================================================================
# 新浪日K历史（计算成交额同比等）
# ================================================================

def _fetch_sina_daily(symbol: str, days: int = 5) -> Optional[pd.DataFrame]:
    """新浪日K线历史数据。"""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.sina.com.cn/",
    }
    # 新浪财经历史 K 接口
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": symbol, "scale": 240, "datalen": days}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200 and r.text.strip().startswith("["):
            import json
            data = json.loads(r.text)
            if data:
                df = pd.DataFrame(data)
                df.columns = [c.strip() for c in df.columns]
                if "day" in df.columns:
                    df = df.rename(columns={"day": "date"})
                for c in ["open", "high", "low", "close", "volume"]:
                    if c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors="coerce")
                return df
    except Exception:
        pass
    return None


# ================================================================
# 东方财富涨跌停（之前可用）
# ================================================================

def _fetch_limit_pool_em(which: str = "up") -> Optional[pd.DataFrame]:
    """which='up' 涨停，which='down' 跌停。"""
    try:
        import akshare as ak
        today = datetime.date.today().strftime("%Y%m%d")
        if which == "up":
            return ak.stock_zt_pool_em(date=today)
        else:
            return ak.stock_zt_pool_dtgc_em(date=today)
    except Exception:
        return None


# ================================================================
# 金十新闻
# ================================================================

NEWS_LEVELS = {
    "critical": "🔴 重大",
    "important": "🟠 重要",
    "watch": "🟡 关注",
    "normal": "⚪ 一般",
}

# 重大关键词
CRITICAL_KEYWORDS = [
    "美联储", "Fed", "降息", "加息", "议息", "决议",
    "中美", "关税", "制裁", "封锁",
    "IPO", "注册制", "退市",
    "爆雷", "违约", "债券",
    "降准", "央行", "MLF", "LPR",
    "战争", "冲突", "袭击",
    "熔断", "暴跌", "千股跌停",
]

IMPORTANT_KEYWORDS = [
    "GDP", "CPI", "PPI", "社融", "PMI", "M2",
    "财报", "业绩", "超预期", "不及预期",
    "回购", "减持", "增持", "解禁",
    "政策", "监管", "新规",
    "板块", "概念", "涨停", "跌停",
    "北向", "外资",
]


def _classify_news_level(title: str) -> str:
    """根据标题关键词自动分级。"""
    t = title.upper()
    for kw in CRITICAL_KEYWORDS:
        if kw.upper() in t:
            return "critical"
    for kw in IMPORTANT_KEYWORDS:
        if kw.upper() in t:
            return "important"
    return "normal"


def _fetch_cls_news(hours: int = 24) -> List[Dict]:
    """拉取金十数据快讯并自动分级。"""
    try:
        import akshare as ak
        df = ak.stock_info_global_cls()
        if df is None or len(df) == 0:
            return []
    except Exception:
        return []

    try:
        now = datetime.datetime.now()
        cutoff = now - datetime.timedelta(hours=hours)

        time_col = next((c for c in df.columns if "时间" in str(c) or "发布" in str(c)), None)
        title_col = next((c for c in df.columns if "标题" in str(c) or "内容" in str(c)), None)
        if time_col is None or title_col is None:
            return []

        df = df.copy()
        df["_time"] = pd.to_datetime(df[time_col], errors="coerce")
        df = df[df["_time"] >= cutoff].sort_values("_time", ascending=False)

        news_list = []
        for _, row in df.iterrows():
            title = str(row[title_col]).strip()
            if not title or len(title) < 5:
                continue
            level = _classify_news_level(title)
            news_list.append({
                "time": row["_time"].strftime("%Y-%m-%d %H:%M") if pd.notna(row["_time"]) else "",
                "title": title,
                "level": level,
                "level_label": NEWS_LEVELS.get(level, "⚪ 一般"),
            })

        # 按重要性排序：critical > important > watch > normal
        level_order = {"critical": 0, "important": 1, "watch": 2, "normal": 3}
        news_list.sort(key=lambda x: level_order.get(x["level"], 99))
        return news_list[:60]
    except Exception:
        return []


# ================================================================
# 一站式拉取
# ================================================================

def fetch_all_daily() -> Dict[str, Any]:
    """拉取所有当日数据。"""
    print("[fetch_all_daily] 开始...")
    t0 = datetime.datetime.now()

    today = datetime.date.today()
    result: Dict[str, Any] = {
        "date": today.strftime("%Y-%m-%d"),
        "weekday": ["周一","周二","周三","周四","周五","周六","周日"][today.weekday()],
        "review_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_status": "closed" if datetime.datetime.now().hour >= 15 else "intraday",
        "market": {},
        "sectors": {},
        "external": {},
        "news": [],
    }

    # 1. 大盘指数（新浪实时行情）
    print("  -> 大盘指数...")
    codes = [c for c, _ in SINA_INDEX_CODES.values()]
    raw = _fetch_sina_hq(codes)

    total_amount = 0
    for key, (code, name) in SINA_INDEX_CODES.items():
        fields = raw.get(code, [])
        parsed = _parse_sina_index(fields)
        if parsed:
            result["market"][key] = parsed
            if parsed.get("close"):
                total_amount += parsed.get("amount", 0)

    # 计算两市成交额同比
    try:
        sh_hist = _fetch_sina_daily("sh000001", days=2)
        sz_hist = _fetch_sina_daily("sz399001", days=2)
        yest_amount = 0
        for h in [sh_hist, sz_hist]:
            if h is not None and len(h) >= 2 and "volume" in h.columns:
                yest_amount += float(h.iloc[-2]["volume"]) * 0.0001  # 估算
        # 直接用当前成交额对比
        if total_amount > 0:
            # 简化：假设昨收大概是今天的 95% 成交额（粗略）
            pass
    except Exception:
        pass

    result["market"]["total_amount"] = round(total_amount, 2)

    # 2. 涨跌停
    print("  -> 涨跌停...")
    zt = _fetch_limit_pool_em("up")
    dt = _fetch_limit_pool_em("down")
    result["market"]["limit_up_count"] = len(zt) if zt is not None else 0
    result["market"]["limit_down_count"] = len(dt) if dt is not None else 0

    # 3. 板块涨跌（东方财富，可能失败）
    print("  -> 板块涨跌...")
    try:
        import akshare as ak
        sector_df = ak.stock_board_industry_name_em()
        if sector_df is not None and len(sector_df) > 0:
            name_col = next((c for c in sector_df.columns if "名称" in str(c)), None)
            pct_col = next((c for c in sector_df.columns if "涨跌幅" in str(c)), None)
            if pct_col and name_col:
                sector_df[pct_col] = pd.to_numeric(sector_df[pct_col], errors="coerce").fillna(0)
                top10 = sector_df.head(10)[[name_col, pct_col]].to_dict("records")
                bot10 = sector_df.tail(10).iloc[::-1][[name_col, pct_col]].to_dict("records")
                up_ratio = (sector_df[pct_col] > 0).mean()
                result["sectors"] = {
                    "top_gainers": [{"name": r[name_col], "change_pct": r[pct_col]} for r in top10],
                    "top_losers": [{"name": r[name_col], "change_pct": r[pct_col]} for r in bot10],
                    "up_ratio": round(up_ratio, 3),
                    "spread": round(sector_df[pct_col].max() - sector_df[pct_col].min(), 2),
                }
    except Exception as e:
        print(f"  板块涨跌失败: {type(e).__name__}")

    # 4. 新闻
    print("  -> 财经新闻...")
    result["news"] = _fetch_cls_news(hours=24)

    # 5. 情绪评分
    result["market"]["sentiment_score"], result["market"]["sentiment_label"] = _calc_sentiment_score(result)

    elapsed = round((datetime.datetime.now() - t0).total_seconds(), 1)
    print(f"[fetch_all_daily] 完成 {elapsed}s, 指数={len([k for k in result['market'] if k in SINA_INDEX_CODES])} 新闻={len(result['news'])}")
    return result


def _calc_sentiment_score(data: Dict) -> Tuple[int, str]:
    score = 50
    sectors = data.get("sectors", {})
    up_ratio = sectors.get("up_ratio", 0.5)
    if up_ratio > 0.67:
        score += 15
    elif up_ratio < 0.33:
        score -= 15

    # 大盘涨跌
    market = data.get("market", {})
    sh = market.get("shanghai") or {}
    sh_chg = sh.get("change_pct", 0)
    if sh_chg > 1:
        score += 10
    elif sh_chg < -1:
        score -= 10

    # 涨跌停
    limit_up = market.get("limit_up_count", 0)
    if limit_up > 50:
        score += 10
    elif limit_up < 20:
        score -= 5

    score = max(0, min(100, score))
    if score < 30:
        label = "极度恐慌"
    elif score < 50:
        label = "偏弱震荡"
    elif score < 70:
        label = "偏强震荡"
    else:
        label = "情绪亢奋"
    return score, label
