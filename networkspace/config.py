"""
配置模块
--------

用于存放 FOFA、Hunter、Quake 等平台的 API 配置信息。
实际使用时建议通过环境变量或本地配置文件加载敏感信息。
"""

from dataclasses import dataclass
from typing import Optional, Any, Dict
from pathlib import Path
import json


@dataclass
class FofaConfig:
    """
    FOFA 配置

    目前只需要 API Key，不再需要 email。
    """

    key: Optional[str] = None
    # 可根据你实际使用的 FOFA / 镜像地址调整
    base_url: str = "https://fofoapi.com/api/v1"


@dataclass
class HunterConfig:
    api_key: Optional[str] = None
    base_url: str = "https://hunter.qianxin.com/openApi"


@dataclass
class QuakeConfig:
    api_key: Optional[str] = None
    base_url: str = "https://quake.360.net/api/v3"


@dataclass
class AppConfig:
    """
    顶层配置对象，统一管理各平台配置。
    """

    fofa: FofaConfig
    hunter: HunterConfig
    quake: QuakeConfig


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw) if raw.strip() else {}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件 {path} 解析失败：{exc}") from exc


def load_config_from_file(path: Optional[str] = None) -> AppConfig:
    """
    从配置文件加载配置。

    默认读取项目根目录下的 `config.json`：

    {
      "fofa": {
        "key": "your_fofa_key",
        "base_url": "https://fofoapi.com/api/v1"
      },
      "hunter": {
        "api_key": "your_hunter_key"
      },
      "quake": {
        "api_key": "your_quake_key"
      }
    }
    """
    cfg_path = Path(path or "config.json")
    data = _load_json(cfg_path)

    fofa_data = data.get("fofa") or {}
    hunter_data = data.get("hunter") or {}
    quake_data = data.get("quake") or {}

    fofa = FofaConfig(**fofa_data)
    hunter = HunterConfig(**hunter_data)
    quake = QuakeConfig(**quake_data)
    return AppConfig(fofa=fofa, hunter=hunter, quake=quake)


__all__ = [
    "FofaConfig",
    "HunterConfig",
    "QuakeConfig",
    "AppConfig",
    "load_config_from_file",
]



