# -*- coding: utf-8 -*-
"""
数据获取模块
第二阶段：实现真实基金列表获取
"""

import json
import re
import traceback
from typing import Optional, Any, Tuple, Dict

import pandas as pd
import requests


class FundDataFetcher:
    """基金数据获取器（封装 AKShare 接口）"""

    def __init__(self):
        self.akshare_available = False
        self.ak = None
        self._check_akshare()

    def _check_akshare(self):
        try:
            import akshare as ak
            self.ak = ak
            self.akshare_available = True
        except ImportError:
            self.akshare_available = False

    def is_available(self) -> bool:
        return self.akshare_available

    def _require_akshare(self) -> Tuple[bool, str]:
        """检查 AKShare 是否可用，返回 (可用, 错误信息)"""
        if not self.akshare_available:
            return False, "AKShare 未安装，请先安装依赖：pip install akshare"
        if self.ak is None:
            return False, "AKShare 模块未正确加载"
        return True, ""

    # -----------------------------------------------------------------
    # 公共接口
    # -----------------------------------------------------------------

    def get_all_fund_list(self) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """
        获取公募基金列表（含净值、增长率等）。

        优先使用 fund_open_fund_rank_em（含净值/增长率等丰富字段）。

        Returns:
            (DataFrame 或 None, 错误信息或 None)
            - 成功：(DataFrame, None)
            - 失败：(None, 错误信息字符串)
        """
        ok, err = self._require_akshare()
        if not ok:
            return None, err

        try:
            # 调用 AKShare 开放式基金排行接口（含净值、日增长率等）
            df = self.ak.fund_open_fund_rank_em(symbol="全部")
            if df is None or len(df) == 0:
                return None, "接口返回空数据"

            # 统一清洗和列名标准化
            df = self._clean_fund_rank_df(df)
            return df, None

        except Exception as e:
            tb = traceback.format_exc()
            msg = f"{type(e).__name__}: {e}\n\n{tb}"
            return None, msg

    def get_fund_nav_history(
        self, fund_code: str
    ) -> Tuple[Optional[str], Optional[pd.DataFrame], Optional[str]]:
        """
        获取单只开放式基金的历史净值（全历史）。

        数据来源：天天基金网 pingzhongdata 接口（直接 HTTP 请求 + 正则解析，
        不依赖 AKShare 的 py_mini_racer JS 引擎）。

        返回的 DataFrame 列：
            净值日期 (datetime64), 单位净值, 日增长率(%),
            累计净值, 复权净值（起点=1，分红再投口径）

        Returns:
            (基金名称或 None, DataFrame 或 None, 错误信息或 None)
        """
        code = str(fund_code).strip()
        if not (code.isdigit() and len(code) == 6):
            return None, None, f"基金代码不合法：{fund_code!r}（应为 6 位数字）"

        try:
            url = f"https://fund.eastmoney.com/pingzhongdata/{code}.js"
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": "https://fund.eastmoney.com/",
            }
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"
            text = r.text

            if "Data_netWorthTrend" not in text:
                return None, None, f"未查到基金 {code} 的净值数据（代码可能不存在或非开放式基金）"

            # ---- 基金名称 ----
            name = None
            name_match = re.search(r'fS_name\s*=\s*"([^"]*)"', text)
            if name_match:
                name = name_match.group(1).strip()

            # ---- 单位净值走势（含日增长率，分红口径已修正） ----
            trend_match = re.search(
                r"Data_netWorthTrend\s*=\s*(\[.*?\])\s*;", text, re.S
            )
            if not trend_match:
                return None, None, f"基金 {code} 返回数据中缺少净值走势字段"
            trend_raw = json.loads(trend_match.group(1))
            if not trend_raw:
                return None, None, f"基金 {code} 的净值走势为空"

            df = pd.DataFrame(trend_raw)
            df["净值日期"] = pd.to_datetime(df["x"], unit="ms", utc=True).dt.tz_convert(
                "Asia/Shanghai"
            ).dt.normalize().dt.tz_localize(None)
            df["单位净值"] = pd.to_numeric(df["y"], errors="coerce")
            df["日增长率"] = pd.to_numeric(df.get("equityReturn"), errors="coerce")

            # ---- 累计净值走势（[时间戳, 累计净值] 二维数组） ----
            ac_match = re.search(r"Data_ACWorthTrend\s*=\s*(\[.*?\])\s*;", text, re.S)
            if ac_match:
                try:
                    ac_raw = json.loads(ac_match.group(1))
                    ac_df = pd.DataFrame(
                        [row[:2] for row in ac_raw if isinstance(row, (list, tuple))],
                        columns=["ts", "累计净值"],
                    )
                    ac_df["净值日期"] = pd.to_datetime(
                        ac_df["ts"], unit="ms", utc=True
                    ).dt.tz_convert("Asia/Shanghai").dt.normalize().dt.tz_localize(None)
                    ac_df["累计净值"] = pd.to_numeric(ac_df["累计净值"], errors="coerce")
                    df = df.merge(
                        ac_df[["净值日期", "累计净值"]], on="净值日期", how="left"
                    )
                except Exception:
                    df["累计净值"] = float("nan")
            else:
                df["累计净值"] = float("nan")

            # ---- 复权净值：日增长率累乘（分红再投口径，起点=1） ----
            growth = df["日增长率"].fillna(0.0) / 100.0
            df["复权净值"] = (1.0 + growth).cumprod()

            df = df[["净值日期", "单位净值", "日增长率", "累计净值", "复权净值"]]
            df = df.dropna(subset=["净值日期"]).sort_values("净值日期").reset_index(drop=True)

            if len(df) == 0:
                return None, None, f"基金 {code} 净值数据为空"

            return name, df, None

        except requests.exceptions.Timeout:
            return None, None, "请求天天基金网超时，请稍后重试"
        except Exception as e:
            tb = traceback.format_exc()
            msg = f"{type(e).__name__}: {e}\n\n{tb}"
            return None, None, msg

    def get_fund_profile(
        self, fund_code: str
    ) -> Tuple[Optional[dict], Optional[str]]:
        """
        获取基金档案信息（基金类型 / 成立日期 / 规模 / 管理人 / 基金经理 / 各项费率）。

        数据来源：天天基金网 f10 基本概况页（fundf10.eastmoney.com/jbgk_{code}.html），
        解析页面中的 th/td 键值对。

        Returns:
            (档案 dict 或 None, 错误信息或 None)
        """
        code = str(fund_code).strip()
        if not (code.isdigit() and len(code) == 6):
            return None, f"基金代码不合法：{fund_code!r}（应为 6 位数字）"

        try:
            url = f"https://fundf10.eastmoney.com/jbgk_{code}.html"
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": "https://fundf10.eastmoney.com/",
            }
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"
            text = r.text

            if "基本概况" not in text:
                return None, f"未查到基金 {code} 的档案信息（代码可能不存在）"

            profile: dict = {}
            # 按 <th> 切分页面，每个键取其后面第一个 <td> 的文本
            parts = re.split(r"(<th[^>]*>.*?</th>)", text, flags=re.S)
            for i in range(1, len(parts) - 1, 2):
                key = re.sub(r"<[^>]+>", " ", parts[i]).strip()
                chunk = parts[i + 1]
                td_m = re.search(r"<td[^>]*>(.*?)</td>", chunk, re.S)
                val_html = td_m.group(1) if td_m else chunk
                val = re.sub(r"<[^>]+>", " ", val_html)
                val = val.replace("&nbsp;", " ")
                val = re.sub(r"\s+", " ", val).strip()
                if key and val and key not in profile:
                    profile[key] = val

            # 页面存在键值合并展示的情况（如"基金代码"格内附带"基金类型"），拆分处理
            for embedded in ("基金类型", "份额规模"):
                for k in list(profile.keys()):
                    v = profile[k]
                    pos = v.find(embedded)
                    if k != embedded and pos != -1:
                        before = v[:pos].strip()
                        after = v[pos + len(embedded):].strip()
                        if before:
                            profile[k] = before
                        else:
                            profile.pop(k, None)
                        if after:
                            profile[embedded] = after

            if not profile:
                return None, "档案页解析失败（页面结构可能已变化）"
            return profile, None

        except requests.exceptions.Timeout:
            return None, "请求天天基金网超时，请稍后重试"
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    def get_fund_holdings(
        self, fund_code: str
    ) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """
        获取基金前十大重仓股（最新报告期）。

        数据来源：天天基金网 f10 投资组合（基于 AKShare fund_portfolio_hold_em，
        纯 HTTP 实现，无需 JS 引擎）。返回列：
        序号 / 股票代码 / 股票名称 / 占净值比例 / 持股数(万股) / 持仓市值(万元) / 季度

        Returns:
            (DataFrame 或 None, 错误信息或 None)
        """
        code = str(fund_code).strip()
        if not (code.isdigit() and len(code) == 6):
            return None, f"基金代码不合法：{fund_code!r}（应为 6 位数字）"

        try:
            df = self.ak.fund_portfolio_hold_em(symbol=code, date="")
            if df is None or len(df) == 0:
                return (
                    None,
                    "暂无股票持仓数据（可能是债券型 / 货币型 / QDII 基金，或最新报告期未披露）",
                )
            if "相关资讯" in df.columns:
                df = df.drop(columns=["相关资讯"])
            # 占净值比例列可能为 "9.85%" 字符串，统一转为数值
            if "占净值比例" in df.columns:
                df["占净值比例"] = pd.to_numeric(
                    df["占净值比例"].astype(str).str.replace("%", "", regex=False),
                    errors="coerce",
                )
            # 仅保留最新报告期（akshare 返回最新年份的各季度，最新季度在最前）
            if "季度" in df.columns and len(df) > 0:
                latest = df["季度"].iloc[0]
                df = df[df["季度"] == latest]
            return df.reset_index(drop=True), None

        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    def _request_with_retry(self, url: str, params: dict, headers: dict,
                            timeout: int = 10, retries: int = 3) -> Optional[requests.Response]:
        """带指数退避的重试请求，处理 RemoteDisconnected / ConnectionError 等瞬时网络错误。
        全部重试失败时返回 None，不抛出异常。
        """
        import urllib3
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=timeout)
                resp.raise_for_status()
                return resp
            except (requests.exceptions.ConnectionError,
                    urllib3.exceptions.ProtocolError,
                    urllib3.exceptions.ReadTimeoutError) as e:
                last_err = e
                if attempt < retries:
                    import time as _time
                    sleep_s = 0.6 * (2 ** (attempt - 1))
                    _time.sleep(sleep_s)
                    continue
                # 最后一次：记录错误但不抛出，返回 None 让调用方处理
                return None
            except requests.exceptions.Timeout:
                return None
            except Exception:
                return None
        return None

    def _fetch_quote_batch(self, codes: list) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """主路径：push2 批量行情接口。"""
        def _market_prefix(code: str) -> str:
            return "1" if code.startswith("6") else "0"

        secids = ",".join(f"{_market_prefix(c)}.{c}" for c in codes)
        url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
        params = {
            "fltt": "2",
            "fields": "f2,f3,f4,f12,f14,f15,f16,f17,f18",
            "secids": secids,
        }
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cache-Control": "no-cache",
        }
        resp = self._request_with_retry(url, params, headers, timeout=10, retries=3)
        if resp is None:
            return None, "批量行情接口请求失败"
        data = resp.json()
        diff = (data.get("data") or {}).get("diff") or []
        if not diff:
            return None, "批量行情接口返回空数据"
        rows = []
        for item in diff:
            rows.append({
                "股票代码": str(item.get("f12", "")).strip(),
                "股票名称": item.get("f14", ""),
                "最新价": item.get("f2"),
                "涨跌幅": item.get("f3"),
                "涨跌额": item.get("f4"),
                "最高": item.get("f15"),
                "最低": item.get("f16"),
                "今开": item.get("f17"),
                "昨收": item.get("f18"),
            })
        return pd.DataFrame(rows), None

    def _fetch_quote_single(self, codes: list) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """降级路径 1：逐个请求 stock/get 接口（单只更稳定，可并发）。"""
        def _market_prefix(code: str) -> str:
            return "1" if code.startswith("6") else "0"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://quote.eastmoney.com/",
        }
        rows = []
        failed = []
        for c in codes:
            secid = f"{_market_prefix(c)}.{c}"
            url = "https://push2.eastmoney.com/api/qt/stock/get"
            params = {
                "fltt": "2",
                "fields": "f57,f58,f43,f170,f169,f44,f45,f46,f60",
                "secid": secid,
            }
            try:
                resp = self._request_with_retry(url, params, headers, timeout=8, retries=2)
                if resp is None:
                    failed.append(c)
                    continue
                data = resp.json()
                d = data.get("data") or {}
                if not d:
                    failed.append(c)
                    continue
                rows.append({
                    "股票代码": str(d.get("f57", c)).strip(),
                    "股票名称": d.get("f58", ""),
                    "最新价": d.get("f43"),
                    "涨跌幅": d.get("f170"),
                    "涨跌额": d.get("f169"),
                    "最高": d.get("f44"),
                    "最低": d.get("f45"),
                    "今开": d.get("f46"),
                    "昨收": d.get("f60"),
                })
            except Exception:
                failed.append(c)
                continue
        if not rows:
            return None, f"单只行情接口全部失败（{len(codes)} 只）"
        if failed:
            # 部分失败不返回错误，仅记录
            pass
        df = pd.DataFrame(rows)
        return df, None

    def _fetch_quote_akshare(self, codes: list) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """降级路径 2：AKShare 全市场行情（最慢但最稳，最后兜底）。"""
        ok, err = self._require_akshare()
        if not ok:
            return None, err
        try:
            df = self.ak.stock_zh_a_spot_em()
            if df is None or len(df) == 0:
                return None, "AKShare 全市场行情返回空数据"
            code_col = "代码" if "代码" in df.columns else None
            if code_col is None:
                return None, "AKShare 数据缺少代码列"
            df[code_col] = df[code_col].astype(str).str.zfill(6)
            filtered = df[df[code_col].isin(codes)].copy()
            if len(filtered) == 0:
                return None, "AKShare 全市场行情未匹配到目标股票"
            rename = {
                code_col: "股票代码",
                "名称": "股票名称",
                "最新价": "最新价",
                "涨跌幅": "涨跌幅",
                "涨跌额": "涨跌额",
                "今开": "今开",
                "昨收": "昨收",
                "最高": "最高",
                "最低": "最低",
            }
            out_cols = [c for c in rename.values() if c in filtered.columns]
            filtered = filtered.rename(columns=rename)[out_cols]
            for c in ["最新价", "涨跌幅", "涨跌额", "今开", "昨收", "最高", "最低"]:
                if c in filtered.columns:
                    filtered[c] = pd.to_numeric(filtered[c], errors="coerce")
            order = {c: i for i, c in enumerate(codes)}
            filtered["_o"] = filtered["股票代码"].map(order)
            filtered = filtered.sort_values("_o").drop(columns="_o").reset_index(drop=True)
            return filtered, None
        except Exception as e:
            return None, f"AKShare 全市场行情失败：{type(e).__name__}: {e}"

    def _fetch_quote_sina(self, codes: list) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """跨系统降级：新浪财经行情 API（hq.sinajs.cn）。
        与东方财富/AKShare 完全不同的服务器体系，可绕过东财服务器阻断。
        """
        def _sina_prefix(code: str) -> str:
            """新浪前缀：6xx→sh（沪），0xx/3xx/8xx→sz（深/北）"""
            return "sh" if code.startswith("6") else "sz"

        symbol_list = ",".join(f"{_sina_prefix(c)}{c}" for c in codes)
        url = "https://hq.sinajs.cn/list=" + symbol_list
        headers = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
        }

        # 新浪接口一次请求即可返回所有股票，超时稍长给足机会
        resp = self._request_with_retry(url, {}, headers, timeout=12, retries=2)
        if resp is None:
            return None, "新浪行情接口请求失败"

        # 新浪返回格式：
        # var hq_str_sh600519="贵州茅台,昨收,今开,当前价,最高,最低,...,日期,时间";
        # 解析：以分号分隔每条记录，再以逗号分隔字段
        text = resp.text.strip()
        # 移除前缀 var hq_str_ 和最后的分号
        rows = []
        for line in text.split(";"):
            line = line.strip()
            if not line or '=""' in line:
                continue
            # 提取 var hq_str_XXXX="..." 中的内容
            m = re.match(r'var hq_str_(\w+)="(.*)"', line)
            if not m:
                continue
            raw_symbol = m.group(1)  # e.g. sh600519
            data_str = m.group(2)
            # 从 symbol 提取 6 位代码
            code = raw_symbol[2:].zfill(6) if len(raw_symbol) >= 8 else ""
            if not data_str or not code:
                continue

            fields = data_str.split(",")
            if len(fields) < 32:
                continue

            try:
                name = fields[0]
                pre_close = float(fields[1]) if fields[1] else 0
                open_price = float(fields[2]) if fields[2] else 0
                current = float(fields[3]) if fields[3] else 0
                high = float(fields[4]) if fields[4] else 0
                low = float(fields[5]) if fields[5] else 0

                change = current - pre_close if pre_close else 0
                change_pct = (change / pre_close * 100) if pre_close else 0

                rows.append({
                    "股票代码": code,
                    "股票名称": name,
                    "最新价": current,
                    "涨跌幅": round(change_pct, 2),
                    "涨跌额": round(change, 2),
                    "最高": high,
                    "最低": low,
                    "今开": open_price,
                    "昨收": pre_close,
                })
            except (ValueError, IndexError):
                continue

        if not rows:
            return None, "新浪行情接口返回空数据"

        df = pd.DataFrame(rows)
        # 按请求顺序排序
        order = {c: i for i, c in enumerate(codes)}
        df["_o"] = df["股票代码"].map(order)
        df = df.sort_values("_o").drop(columns="_o").reset_index(drop=True)
        return df, None

    def get_stocks_realtime_quote(
        self, stock_codes: list
    ) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """
        获取指定 A 股股票的实时行情（用于持仓追踪看盘）。

        四级降级 + 合并补全策略：
        依次尝试各数据源，每个数据源只负责拉取「当前仍缺失」的股票，
        最后合并所有结果。这样即使东财 push2 在海外只返回部分股票，
        剩余股票也会由新浪等独立数据源补齐，避免大片 None。

        返回列：股票代码 / 股票名称 / 最新价 / 涨跌幅 / 涨跌额 / 今开 / 昨收 / 最高 / 最低
        """
        codes = [str(c).strip().zfill(6) for c in (stock_codes or []) if str(c).strip()]
        if not codes:
            return None, "未提供股票代码"

        merged_rows: Dict[str, dict] = {}
        errors = []

        def _absorb(df) -> None:
            """把数据源返回的 DataFrame 合并进结果（已有的代码不覆盖）。"""
            if df is None or len(df) == 0:
                return
            for _, row in df.iterrows():
                c = str(row.get("股票代码", "")).strip().zfill(6)
                # 只收有有效价格的行
                if c and c not in merged_rows and pd.notna(row.get("最新价")):
                    merged_rows[c] = row.to_dict()

        def _missing() -> list:
            return [c for c in codes if c not in merged_rows]

        # 尝试 1：批量接口（东财 push2，最快；海外可能只返回部分）
        try:
            df, err = self._fetch_quote_batch(codes)
            _absorb(df)
            if err:
                errors.append(f"批量: {err}")
        except Exception as e:
            errors.append(f"批量: {type(e).__name__}: {e}")

        # 尝试 2：单只接口补全缺失股票
        miss = _missing()
        if miss:
            try:
                df, err = self._fetch_quote_single(miss)
                _absorb(df)
                if err:
                    errors.append(f"单只: {err}")
            except Exception as e:
                errors.append(f"单只: {type(e).__name__}: {e}")

        # 尝试 3：AKShare 全市场兜底补全
        miss = _missing()
        if miss:
            try:
                df, err = self._fetch_quote_akshare(miss)
                _absorb(df)
                if err:
                    errors.append(f"AKShare: {err}")
            except Exception as e:
                errors.append(f"AKShare: {type(e).__name__}: {e}")

        # 尝试 4：新浪财经跨系统兜底（与东财完全独立，海外也能访问）
        miss = _missing()
        if miss:
            try:
                df, err = self._fetch_quote_sina(miss)
                _absorb(df)
                if err:
                    errors.append(f"新浪: {err}")
            except Exception as e:
                errors.append(f"新浪: {type(e).__name__}: {e}")

        if not merged_rows:
            msg = "实时行情获取失败（所有数据源均不可用）：" + " | ".join(errors)
            return None, msg

        result_df = pd.DataFrame(list(merged_rows.values()))
        # 按请求顺序排序
        order = {c: i for i, c in enumerate(codes)}
        result_df["_o"] = result_df["股票代码"].map(order)
        result_df = result_df.sort_values("_o").drop(columns="_o").reset_index(drop=True)

        final_missing = _missing()
        if final_missing:
            # 仍有缺失：为缺失股票补空行，保证表格行数完整（显示 None/—）
            empty_rows = [{"股票代码": c, "股票名称": ""} for c in final_missing]
            result_df = pd.concat([result_df, pd.DataFrame(empty_rows)], ignore_index=True)
            result_df["_o"] = result_df["股票代码"].map(order)
            result_df = result_df.sort_values("_o").drop(columns="_o").reset_index(drop=True)

        return result_df, None

    # -----------------------------------------------------------------
    # 内部工具
    # -----------------------------------------------------------------

    @staticmethod
    def _clean_fund_rank_df(df: pd.DataFrame) -> pd.DataFrame:
        """
        清洗 fund_open_fund_rank_em 返回的 DataFrame：
        - 重命名列为通用英文名（保留中文展示用，但内部处理更方便）
        - 确保基金代码为 6 位字符串，避免科学计数或浮点数
        - 处理数值列
        """

        # AKShare 1.18.91 返回的列名（中文）:
        # 序号, 基金代码, 基金简称, 日期, 单位净值, 累计净值, 日增长率,
        # 近1周, 近1月, 近3月, 近6月, 近1年, 近2年, 近3年,
        # 今年来, 成立来, 自定义, 手续费

        # 先建立一个 中文列 -> 标准英文 key 的映射（展示仍用中文）
        rename_map = {
            "序号": "序号",
            "基金代码": "基金代码",
            "基金简称": "基金简称",
            "日期": "净值日期",
            "单位净值": "单位净值",
            "累计净值": "累计净值",
            "日增长率": "日增长率",
            "近1周": "近1周",
            "近1月": "近1月",
            "近3月": "近3月",
            "近6月": "近6月",
            "近1年": "近1年",
            "近2年": "近2年",
            "近3年": "近3年",
            "今年来": "今年来",
            "成立来": "成立来",
            "自定义": "自定义",
            "手续费": "手续费",
        }
        existing = {k: v for k, v in rename_map.items() if k in df.columns}
        df = df.rename(columns=existing)

        # 1) 基金代码强制转 6 位字符串，去除空格，补前导零
        if "基金代码" in df.columns:
            def fmt_code(x):
                if pd.isna(x):
                    return ""
                s = str(x).strip()
                # 去掉可能的 .0 后缀
                if s.endswith(".0"):
                    s = s[:-2]
                # 只保留数字部分
                digits = "".join(ch for ch in s if ch.isdigit())
                return digits.zfill(6) if digits else s

            df["基金代码"] = df["基金代码"].apply(fmt_code).astype(str)

        # 2) 数值列转 float（容错）
        numeric_cols = [
            "单位净值", "累计净值", "日增长率",
            "近1周", "近1月", "近3月", "近6月",
            "近1年", "近2年", "近3年", "今年来", "成立来", "自定义",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 3) 净值日期规范化
        if "净值日期" in df.columns:
            df["净值日期"] = pd.to_datetime(df["净值日期"], errors="coerce").dt.strftime("%Y-%m-%d")
            df["净值日期"] = df["净值日期"].fillna("")

        # 去掉 基金代码 为空的异常行
        if "基金代码" in df.columns:
            df = df[df["基金代码"].astype(str).str.len() > 0].reset_index(drop=True)

        return df


def get_default_fetcher() -> FundDataFetcher:
    return FundDataFetcher()


if __name__ == "__main__":
    import os
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    print("测试数据获取模块...")
    fetcher = FundDataFetcher()
    print(f"AKShare 可用状态: {fetcher.is_available()}")

    if fetcher.is_available():
        print("\n正在获取基金列表，可能需要 10~30 秒...")
        df, err = fetcher.get_all_fund_list()
        if err:
            print(f"获取失败:\n{err}")
        else:
            print(f"获取成功！共 {len(df)} 条基金")
            print(f"列: {list(df.columns)}")
            print(df.head(3).to_string())
    print("测试完成")
