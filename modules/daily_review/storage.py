from __future__ import annotations

import csv
import json
import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


def now_cn() -> datetime.datetime:
    """返回北京时间（UTC+8）。云端 Streamlit 服务器默认是 UTC 时区，
    直接 datetime.now() 会比北京时间晚 8 小时，统一用本函数。"""
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)


BASE_DIR = Path(__file__).resolve().parent.parent.parent / "data"

DAILY_REVIEW_DIR = BASE_DIR / "daily_review"
MARKET_DATA_DIR = BASE_DIR / "market_data"
FUND_POOL_DIR = BASE_DIR / "my_funds"

SENTIMENT_EXTREME_FEAR = (0, 30)
SENTIMENT_WEAK_OSCILLATION = (30, 50)
SENTIMENT_STRONG_OSCILLATION = (50, 70)
SENTIMENT_EUPHORIA = (70, 100)


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _sentiment_label(score: float) -> str:
    if score < SENTIMENT_EXTREME_FEAR[1]:
        return "极度恐慌"
    if score < SENTIMENT_WEAK_OSCILLATION[1]:
        return "偏弱震荡"
    if score < SENTIMENT_STRONG_OSCILLATION[1]:
        return "偏强震荡"
    return "情绪亢奋"


def save_daily_review(date_str: str, data: dict) -> Path:
    _ensure_dir(DAILY_REVIEW_DIR)
    file_path = DAILY_REVIEW_DIR / f"{date_str}.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return file_path


def load_daily_review(date_str: str) -> Optional[dict]:
    file_path = DAILY_REVIEW_DIR / f"{date_str}.json"
    if not file_path.exists():
        return None
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_review_dates() -> list[str]:
    if not DAILY_REVIEW_DIR.exists():
        return []
    return sorted(p.stem for p in DAILY_REVIEW_DIR.glob("*.json"))


def save_market_csv(name: str, df: pd.DataFrame, date_column: str = "date") -> Path:
    _ensure_dir(MARKET_DATA_DIR)
    file_path = MARKET_DATA_DIR / f"{name}.csv"
    write_header = not file_path.exists()
    df.to_csv(file_path, mode="a", header=write_header, index=False,
              columns=[date_column] + [c for c in df.columns if c != date_column])
    return file_path


def load_market_csv(name: str) -> pd.DataFrame:
    file_path = MARKET_DATA_DIR / f"{name}.csv"
    if not file_path.exists():
        return pd.DataFrame()
    return pd.read_csv(file_path)


def save_fund_pool(config: dict) -> Path:
    _ensure_dir(FUND_POOL_DIR)
    file_path = FUND_POOL_DIR / "fund_pool.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return file_path


def load_fund_pool() -> dict:
    file_path = FUND_POOL_DIR / "fund_pool.json"
    if not file_path.exists():
        return {}
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _run_tests() -> None:
    import tempfile
    import shutil
    import importlib
    from datetime import datetime

    import modules.daily_review.storage as mod

    test_dir = Path(tempfile.mkdtemp(prefix="daily_review_test_"))
    try:
        mod.BASE_DIR = test_dir
        mod.DAILY_REVIEW_DIR = test_dir / "daily_review"
        mod.MARKET_DATA_DIR = test_dir / "market_data"
        mod.FUND_POOL_DIR = test_dir / "my_funds"

        today = datetime.now().strftime("%Y-%m-%d")

        sample = {
            "date": today,
            "market": {
                "上证综指": {"close": 3150.23, "change_pct": 0.85},
                "深证成指": {"close": 10420.11, "change_pct": 1.12},
            },
            "sentiment_score": 58.5,
            "sentiment_label": mod._sentiment_label(58.5),
            "notes": "测试数据",
        }

        path = mod.save_daily_review(today, sample)
        print(f"[TEST] saved to {path}")
        assert path.exists(), "save_daily_review 应该创建文件"

        loaded = mod.load_daily_review(today)
        assert loaded is not None, "load_daily_review 应返回数据"
        assert loaded["date"] == today, "日期字段不匹配"
        assert loaded["sentiment_label"] == "偏强震荡", "情绪标签错误"
        print(f"[TEST] load_daily_review OK: sentiment_label={loaded['sentiment_label']}")

        future_date = "2099-12-31"
        missing = mod.load_daily_review(future_date)
        assert missing is None, f"不存在的日期应返回 None, 实际: {missing}"
        print("[TEST] load_daily_review 对不存在日期返回 None OK")

        dates = mod.list_review_dates()
        assert today in dates, f"{today} 应该在列表中, 实际: {dates}"
        print(f"[TEST] list_review_dates OK: {dates}")

        sample_fund_pool = {
            "funds": [
                {"code": "000001", "name": "示例基金A", "weight": 0.5},
                {"code": "110022", "name": "示例基金B", "weight": 0.5},
            ],
            "updated_at": today,
        }
        mod.save_fund_pool(sample_fund_pool)
        loaded_pool = mod.load_fund_pool()
        assert loaded_pool["funds"][0]["code"] == "000001", "基金池 roundtrip 失败"
        print(f"[TEST] save/load_fund_pool OK: {len(loaded_pool['funds'])} funds")

        df = pd.DataFrame({
            "date": [today],
            "net_value": [1.2345],
            "daily_return": [0.012],
        })
        csv_path = mod.save_market_csv("test_nav", df)
        assert csv_path.exists(), "save_market_csv 应该创建 CSV 文件"

        loaded_df = mod.load_market_csv("test_nav")
        assert not loaded_df.empty, "load_market_csv 不应返回空 DataFrame"
        assert len(loaded_df) == 1, f"应有 1 行, 实际 {len(loaded_df)}"
        print(f"[TEST] save/load_market_csv OK: shape={loaded_df.shape}")

        mod.save_fund_pool({})
        assert mod.load_fund_pool() == {}, "空 dict 应可正常 roundtrip"

        print("\n✅ 全部测试通过")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    _run_tests()
