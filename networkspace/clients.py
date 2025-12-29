"""
各平台 API 客户端骨架
----------------------

这里只定义统一的抽象接口和三个平台的基本类结构，
方便后续分别实现具体的 HTTP 请求和结果解析逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Protocol, runtime_checkable

import base64
import json
import re
import urllib.parse

import requests

from .config import AppConfig

QueryType = Literal["domain", "ip", "company"]


@runtime_checkable
class SearchClient(Protocol):
    """
    所有搜索客户端需要实现的统一接口。
    """

    name: str

    def search(
        self,
        query: str,
        query_type: QueryType,
        page: int = 1,
        size: int = 100,
    ) -> Dict[str, Any]:
        """
        执行搜索。

        当前仅定义返回结构为 Dict，后续可以引入 Pydantic 或自定义模型。
        """


@dataclass
class FofaClient:
    """
    FOFA API 客户端骨架。
    """

    config: AppConfig
    name: str = "fofa"

    def _build_query(self, query: str, query_type: QueryType) -> str:
        # FOFA 不需要支持企业查询
        if query_type == "ip":
            # FOFA IP 查询语法：尝试不带引号的版本，因为某些情况下可能更准确
            # 如果不行，可以改回 ip="xxx"
            return f'ip={query}'
        # 默认按域名/主机名搜索
        return f'host="{query}"'

    def search(
        self,
        query: str,
        query_type: QueryType,
        page: int = 1,
        size: int = 100,
    ) -> Dict[str, Any]:
        if query_type == "company":
            raise ValueError("FOFA 不支持企业查询")

        if not self.config.fofa.key:
            raise ValueError("FOFA 配置缺失：请在配置文件中设置 fofa.key")

        q = self._build_query(query, query_type)
        qbase64 = base64.b64encode(q.encode("utf-8")).decode("utf-8")

        # 按照官方文档，URL 应该是 https://fofoapi.com/api/v1/search/all
        # 如果配置里只给了域名，自动补全路径；如果给了完整路径，直接使用
        base_url = self.config.fofa.base_url.rstrip("/")
        if not base_url.endswith("/api/v1/search/all"):
            if base_url.endswith("/api/v1"):
                url_base = f"{base_url}/search/all"
            else:
                url_base = f"{base_url}/api/v1/search/all"
        else:
            url_base = base_url.rstrip("?")

        # 按照官方 API 文档，支持以下参数：
        # - qbase64: 必填，base64编码的查询语句
        # - key: 必填，API Key
        # - page: 可选，页码，默认1
        # - size: 可选，每页数量，默认100，最大10000
        # - fields: 可选，字段列表，默认host,ip,port
        # - r_type: 可选，指定返回json格式
        # 注意：FOFA API 要求 URL 格式为 ?&key=...&qbase64=...（第一个参数前有 &）
        from urllib.parse import urlencode
        params_dict = {
            "key": self.config.fofa.key,
            "qbase64": qbase64,
            "page": page,
            "size": size,
            "fields": "host,ip,port,title,domain",  # 按文档支持更多字段
            "r_type": "json",  # 确保返回 JSON 格式
        }
        # 手动构建 URL，确保格式为 ?&key=...&qbase64=...
        url = f"{url_base}?&{urlencode(params_dict)}"

        # 增加超时时间，因为 FOFA 查询可能返回大量数据，需要更长时间
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()

        # 某些镜像站可能返回 HTML / 纯文本，这里先保留原始文本，
        # 解析失败时把前一段内容放进异常里，方便你排查。
        raw_text = resp.text
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"FOFA 返回内容不是 JSON，前 200 字符为：{raw_text[:200]!r}"
            ) from exc
        
        # 不再输出调试信息，查询语句会在 CLI 中统一显示

        # 检查 FOFA API 是否返回了错误
        if data.get("error") is True:
            error_msg = data.get("errmsg") or data.get("message") or "未知错误"
            raise ValueError(f"FOFA API 返回错误：{error_msg}")

        # 调试信息：输出 API 返回的关键信息
        total_size = data.get("size", 0)
        if total_size == 0:
            # 如果总数为 0，可能是查询语法问题或者确实没有数据
            # 输出查询语句和响应信息，方便排查
            query_used = data.get("query", q)
            tip = data.get("tip", "")
            if tip:
                # FOFA 有时会在 tip 字段给出提示信息
                import warnings
                warnings.warn(f"FOFA 查询提示：{tip}（查询语句：{query_used}）")

        # 确保 results 是列表类型
        raw_results = data.get("results", [])
        if not isinstance(raw_results, list):
            raise ValueError(
                f"FOFA API 返回的 results 格式异常，期望列表但得到 {type(raw_results).__name__}。"
                f"响应内容：{str(data)[:200]}"
            )

        results: List[Dict[str, Any]] = []
        for row in raw_results:
            # FOFA API 返回的 results 应该是列表的列表，每个子列表是 [host, ip, port, ...]
            # 但需要处理可能的异常情况（比如 row 是字典或其他类型）
            if not isinstance(row, list):
                # 如果不是列表，尝试从字典中提取字段，或者跳过这条记录
                if isinstance(row, dict):
                    results.append(
                        {
                            "source": self.name,
                            "ip": row.get("ip"),
                            "domain": row.get("domain") or row.get("host"),
                            "host": row.get("host"),
                            "port": row.get("port"),
                            "title": row.get("title"),
                            "company": None,
                            "raw": row,
                        }
                    )
                else:
                    # 未知格式，跳过
                    continue
            else:
                # 按照 fields 参数顺序解析：host,ip,port,title,domain
                # 与上面 params 中的 fields 顺序保持一致
                host, ip, port, title, domain = (row + [None] * 5)[:5]
                results.append(
                    {
                        "source": self.name,
                        "ip": ip,
                        "domain": domain or host,
                        "host": host,
                        "port": port,
                        "title": title,
                        "company": None,
                        "raw": row,
                    }
                )

        # 在返回结果中包含更多调试信息
        return {
            "source": self.name,
            "query": query,
            "query_type": query_type,
            "page": page,
            "size": size,
            "results": results,
            "raw": data,
            # 添加一些便于调试的字段
            "total_size": data.get("size", 0),
            "query_used": data.get("query", q),
            "tip": data.get("tip", ""),
        }


@dataclass
class HunterClient:
    """
    Hunter API 客户端。
    
    根据官方文档实现：
    - 用户信息接口：/openApi/userInfo（用于验证）
    - 搜索接口：/openApi/search（用于查询）
    """

    config: AppConfig
    name: str = "hunter"

    def _build_query(self, query: str, query_type: QueryType) -> str:
        """
        构建 Hunter 查询语法。
        
        根据文档，Hunter 支持：
        - IP: ip="xxx"
        - Domain: domain="xxx" 或 host="xxx"
        - Company: company="xxx"
        """
        if query_type == "ip":
            return f'ip="{query}"'
        if query_type == "company":
            return f'company="{query}"'
        # domain 查询可以使用 domain 或 host
        return f'domain="{query}"'

    def _encode_search(self, query: str) -> str:
        """
        使用 base64url 编码（RFC 4648 标准）。
        
        Python 的 base64.urlsafe_b64encode 会生成 base64url 编码。
        """
        encoded = base64.urlsafe_b64encode(query.encode("utf-8"))
        return encoded.decode("utf-8").rstrip("=")  # 移除 padding

    def verify_credential(self) -> tuple[bool, str]:
        """
        验证 API 密钥有效性（通过用户信息接口）。
        
        返回 (是否有效, 原因)
        """
        if not self.config.hunter.api_key:
            return False, "未配置 API Key"
        
        try:
            url = f"{self.config.hunter.base_url}/userInfo"
            params = {"api-key": self.config.hunter.api_key}
            
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("code") == 200:
                return True, "可用"
            else:
                message = data.get("message", "未知错误")
                return False, f"API 返回错误：{message}"
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in {401, 403}:
                return False, f"凭据无效或无权限（HTTP {status}）"
            return False, f"HTTP 错误 {status}: {exc}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def search(
        self,
        query: str,
        query_type: QueryType,
        page: int = 1,
        size: int = 100,
    ) -> Dict[str, Any]:
        """
        执行 Hunter 搜索查询。
        
        根据文档：
        - search 参数需要 base64url 编码
        - 返回数据在 data.arr 中
        - total 字段表示总记录数
        - page_size 必须为 10（Hunter API 的特殊要求，仅对 Hunter 生效）
        """
        if not self.config.hunter.api_key:
            raise ValueError("Hunter 配置缺失：请在配置文件中设置 hunter.api_key")

        # Hunter API 特殊要求：page_size 必须为 10
        # 注意：此限制仅对 Hunter 生效，不影响 FOFA 和 Quake
        if size != 10:
            size = 10

        q = self._build_query(query, query_type)
        search_encoded = self._encode_search(q)

        url = f"{self.config.hunter.base_url}/search"
        params = {
            "api-key": self.config.hunter.api_key,
            "search": search_encoded,
            "page": page,
            "page_size": size,
        }

        # 构建用于显示的 URL（隐藏 API key）
        display_params = params.copy()
        display_params["api-key"] = "***"
        display_url = f"{url}?{urllib.parse.urlencode(display_params)}"

        resp = requests.get(url, params=params, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        # 检查 API 是否返回了错误
        if data.get("code") != 200:
            error_msg = data.get("message") or "未知错误"
            # 如果是 page_size 相关的错误，提供更友好的提示
            if "页大小" in error_msg or "page_size" in error_msg.lower():
                raise ValueError(
                    f"Hunter API 返回错误：{error_msg}。"
                    f"提示：Hunter API 要求 page_size 必须为 10。"
                )
            raise ValueError(f"Hunter API 返回错误：{error_msg}")

        # 提取结果数组
        data_obj = data.get("data", {})
        arr = data_obj.get("arr", []) or []

        # 解析结果
        results: List[Dict[str, Any]] = []
        for item in arr:
            ip = item.get("ip")
            domain = item.get("domain")
            port = item.get("port")
            title = item.get("web_title")
            company = item.get("company")
            url_str = item.get("url", "")
            
            # 从 url 字段提取 host（如果有）
            host = domain
            if url_str:
                # 从 URL 中提取 host（去除协议前缀）
                host_match = re.search(r"://([^/]+)", url_str)
                if host_match:
                    host = host_match.group(1)
            
            results.append(
                {
                    "source": self.name,
                    "ip": ip,
                    "domain": domain,
                    "host": host or domain or url_str,  # 优先使用 domain，其次 url
                    "port": port,
                    "title": title,
                    "company": company,
                    "raw": item,
                }
            )

        # 返回统一格式
        total_size = data_obj.get("total", 0)
        return {
            "source": self.name,
            "query": query,
            "query_type": query_type,
            "page": page,
            "size": size,
            "results": results,
            "raw": data,
            "total_size": total_size,
            "query_used": q,  # 原始查询语句
            "tip": data_obj.get("syntax_prompt", ""),
            "request_url": display_url,  # 请求 URL（用于显示）
        }


@dataclass
class QuakeClient:
    """
    Quake API 客户端。
    
    根据官方文档实现：
    - 用户信息接口：/api/v3/user/info (用于验证凭据)
    - 服务数据查询接口：/api/v3/search/quake_service
    """

    config: AppConfig
    name: str = "quake"

    def verify_credential(self) -> tuple[bool, str]:
        """
        验证 Quake API 凭据是否有效。
        
        使用用户信息接口 /api/v3/user/info 进行验证。
        """
        if not self.config.quake.api_key:
            return False, "未配置凭据"
        
        # 构建 URL：如果 base_url 已经包含 /api/v3，直接拼接路径；否则添加 /api/v3
        base_url = self.config.quake.base_url.rstrip("/")
        if "/api/v3" in base_url:
            # base_url 已经包含 /api/v3，直接拼接路径
            url = f"{base_url}/user/info"
        else:
            # base_url 不包含 /api/v3，需要添加
            url = f"{base_url}/api/v3/user/info"
        
        headers = {
            "X-QuakeToken": self.config.quake.api_key,
        }
        
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            
            # Quake API 返回格式：{"code": 0, "message": "Successful", "data": {...}}
            if data.get("code") == 0:
                return True, "可用"
            else:
                error_msg = data.get("message", "未知错误")
                return False, f"API 返回错误：{error_msg}"
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in {401, 403}:
                return False, f"凭据无效或无权限（HTTP {status}）"
            return False, f"HTTP 错误 {status}: {exc}"
        except Exception as exc:
            return False, f"验证失败：{exc}"

    def _build_query(self, query: str, query_type: QueryType) -> str:
        """
        根据查询类型构建 Quake 查询语句。
        
        根据文档：
        - IP: ip:"1.1.1.1"
        - 域名: domain:"360.cn" 或 hostname:"xxx"
        - 组织: org:"xxx" 或 owner:"xxx"
        """
        if query_type == "ip":
            return f'ip:"{query}"'
        if query_type == "company":
            # 使用 org 字段查询组织/企业
            return f'org:"{query}"'
        # 域名查询：优先使用 domain 字段，也可以使用 hostname
        return f'domain:"{query}"'

    def search(
        self,
        query: str,
        query_type: QueryType,
        page: int = 1,
        size: int = 100,
    ) -> Dict[str, Any]:
        """
        执行 Quake 搜索查询。
        
        根据文档：
        - 接口地址：/api/v3/search/quake_service
        - 请求方式：POST
        - 参数：query, start, size, latest, ignore_cache 等
        - 返回格式：{"code": 0, "message": "Successful.", "data": [...], "meta": {...}}
        """
        if not self.config.quake.api_key:
            raise ValueError("Quake 配置缺失：请在配置文件中设置 quake.api_key")

        q = self._build_query(query, query_type)

        # 构建完整的 API URL
        # 如果 base_url 已经包含 /api/v3，直接拼接路径；否则添加 /api/v3
        base_url = self.config.quake.base_url.rstrip("/")
        if "/api/v3" in base_url:
            # base_url 已经包含 /api/v3，直接拼接路径
            url = f"{base_url}/search/quake_service"
        else:
            # base_url 不包含 /api/v3，需要添加
            url = f"{base_url}/api/v3/search/quake_service"

        payload = {
            "query": q,
            "start": (page - 1) * size,
            "size": size,
            "latest": True,  # 使用最新数据
            "ignore_cache": False,
        }

        headers = {
            "X-QuakeToken": self.config.quake.api_key,
            "Content-Type": "application/json",
        }

        # 增加超时时间，因为查询可能返回大量数据，需要更长时间
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        # 检查 API 返回的错误
        if data.get("code") != 0:
            error_msg = data.get("message", "未知错误")
            raise ValueError(f"Quake API 返回错误：{error_msg}")

        arr = data.get("data", [])
        if not isinstance(arr, list):
            arr = []

        # 获取分页信息
        pagination = data.get("meta", {}).get("pagination", {})
        total_size = pagination.get("total", 0)

        results: List[Dict[str, Any]] = []
        for item in arr:
            if not isinstance(item, dict):
                continue
                
            ip = item.get("ip", "")
            port = item.get("port", "")
            hostname = item.get("hostname", "")
            
            # 从 service.http.host 获取域名（如果有）
            service = item.get("service", {})
            http_service = service.get("http", {}) if isinstance(service, dict) else {}
            domain = http_service.get("host", "") or hostname
            title = http_service.get("title", "") if isinstance(http_service, dict) else ""
            
            # 组织信息
            org = item.get("org", "")
            
            # 如果没有 hostname，尝试从 domain 字段获取
            if not hostname and not domain:
                domain_field = item.get("domain", "")
                if domain_field:
                    domain = domain_field
                    hostname = domain_field
            
            results.append(
                {
                    "source": self.name,
                    "ip": ip,
                    "domain": domain or hostname,
                    "host": hostname or domain,
                    "port": port,
                    "title": title,
                    "company": org,
                    "raw": item,
                }
            )

        return {
            "source": self.name,
            "query": query,
            "query_type": query_type,
            "page": page,
            "size": size,
            "results": results,
            "total_size": total_size,
            "query_used": q,
            "tip": "",
        }


def get_client(
    app_config: AppConfig,
    source: str,
) -> Optional[SearchClient]:
    """
    根据 `source` 名称创建对应的客户端实例。
    """
    source_lower = source.lower()
    if source_lower == "fofa":
        return FofaClient(config=app_config)
    if source_lower == "hunter":
        return HunterClient(config=app_config)
    if source_lower == "quake":
        return QuakeClient(config=app_config)
    return None


__all__ = [
    "QueryType",
    "SearchClient",
    "FofaClient",
    "HunterClient",
    "QuakeClient",
    "get_client",
]


