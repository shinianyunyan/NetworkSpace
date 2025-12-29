"""
结果导出工具
------------

支持将资产结果导出为 CSV / TXT：

- TXT：只导出 IP 或域名（根据查询类型自动选择）
- CSV：导出完整字段
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, List, Dict


def dedup_assets(assets: Iterable[Dict], query_type: str) -> List[Dict]:
    """
    根据 host 去重，因为每个 host 代表一个独立的资产。
    
    去重逻辑：
    - 优先使用 host 字段（去除 https:// 前缀，统一格式）
    - 如果没有 host，则使用 ip:port 组合
    - 如果都没有，则使用 domain:port 组合
    """
    seen = set()
    uniq: List[Dict] = []

    for a in assets:
        host = (a.get("host") or "").strip()
        ip = (a.get("ip") or "").strip()
        port = a.get("port")
        domain = (a.get("domain") or "").strip()

        # 构建去重 key：优先使用 host
        if host:
            # 统一 host 格式：去除 https:// 前缀，统一为小写
            host_normalized = host.lower().replace("https://", "").replace("http://", "")
            key = f"{host_normalized}:{port}" if port else host_normalized
        elif ip and port:
            # 如果没有 host，使用 ip:port
            key = f"{ip}:{port}"
        elif ip:
            # 只有 ip
            key = ip
        elif domain and port:
            # 使用 domain:port
            key = f"{domain}:{port}"
        elif domain:
            # 只有 domain
            key = domain
        else:
            # 如果所有字段都没有，跳过这条记录
            continue

        if key in seen:
            continue

        seen.add(key)
        uniq.append(a)

    return uniq


def export_txt(assets: Iterable[Dict], query_type: str, path: str) -> None:
    """
    TXT 导出：只存储 IP 或域名数据（不包含端口等其他信息）

    - ip 查询：只写 ip
    - domain/company 查询：优先写 domain，没有则写 host（去除协议前缀和端口），再没有则写 ip
    """
    items: List[str] = []
    for a in assets:
        ip = (a.get("ip") or "").strip()
        domain = (a.get("domain") or "").strip()
        host = (a.get("host") or "").strip()

        if query_type == "ip":
            # IP 查询：只写 IP
            value = ip
        else:
            # 域名/企业查询：优先写 domain，没有则写 host（去除协议前缀和端口）
            if domain:
                value = domain
            elif host:
                # 去除 https:// 和 http:// 前缀
                host_clean = host.replace("https://", "").replace("http://", "")
                # 去除端口（如果有）
                if ":" in host_clean:
                    host_clean = host_clean.split(":")[0]
                value = host_clean
            else:
                value = ip

        if value:
            items.append(value)

    # 再做一次去重，保证输出干净（虽然已经在 dedup_assets 中去重过，但这里再确保一下）
    uniq_items = sorted(set(items))

    p = Path(path)
    p.write_text("\n".join(uniq_items), encoding="utf-8")


def export_csv(assets: Iterable[Dict], path: str) -> None:
    """
    CSV 导出所有关键字段。
    """
    p = Path(path)
    fieldnames = ["source", "ip", "domain", "host", "port", "title", "company"]

    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for a in assets:
            row = {k: a.get(k, "") for k in fieldnames}
            writer.writerow(row)


__all__ = ["dedup_assets", "export_txt", "export_csv"]




