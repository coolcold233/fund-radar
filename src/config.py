# -*- coding: utf-8 -*-
"""
配置管理模块
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class AppConfig:
    project_root: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    data_dir: Path = field(init=False)
    db_path: Path = field(init=False)
    app_name: str = "基金雷达"
    app_version: str = "0.1.0"
    cache_ttl: int = 3600
    request_timeout: int = 30
    default_display_count: int = 50
    chart_theme: str = "streamlit"
    
    def __post_init__(self):
        self.data_dir = self.project_root / "data"
        self.db_path = self.data_dir / "fund_radar.db"
        self._ensure_directories()
    
    def _ensure_directories(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_root": str(self.project_root),
            "data_dir": str(self.data_dir),
            "db_path": str(self.db_path),
            "app_name": self.app_name,
            "app_version": self.app_version,
            "cache_ttl": self.cache_ttl,
            "request_timeout": self.request_timeout,
            "default_display_count": self.default_display_count,
            "chart_theme": self.chart_theme,
        }


_global_config = None

def get_config() -> AppConfig:
    global _global_config
    if _global_config is None:
        _global_config = AppConfig()
    return _global_config


if __name__ == "__main__":
    print("当前应用配置:")
    config = get_config()
    for key, value in config.to_dict().items():
        print(f"  {key}: {value}")
    print("✅ 配置模块测试通过!")
