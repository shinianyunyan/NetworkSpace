"""
命令行入口骨架
--------------

提供统一的 CLI 界面，支持：

- 对 **域名**、**IP**、**企业（公司）** 进行查询
- 选择数据源：FOFA / Hunter / Quake / 全部

当前仅输出参数解析结果和伪造的返回结构，
后续再补充真实 API 调用逻辑与结果展示格式。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List, Optional, Tuple, Dict

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

import requests
import json

from .config import load_config_from_file
from .clients import QueryType, get_client
from .exporters import dedup_assets, export_csv, export_txt

console = Console()


def _parse_targets(input_str: str) -> List[str]:
    """
    解析用户输入的目标，支持：
    1. 逗号分隔的多个目标（中英文逗号都支持）
    2. 文件路径（*.txt），从文件中读取，每行一个目标
    """
    input_str = input_str.strip()
    
    # 检查是否是文件路径
    if input_str.endswith('.txt') and Path(input_str).exists():
        try:
            targets = []
            with open(input_str, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):  # 忽略空行和注释
                        targets.append(line)
            return targets
        except Exception as e:
            raise ValueError(f"读取文件失败：{e}")
    
    # 按逗号分隔（支持中英文逗号）
    targets = re.split(r'[,，]+', input_str)
    # 去除空白并过滤空字符串
    targets = [t.strip() for t in targets if t.strip()]
    return targets


def _detect_target_type(target: str) -> Optional[QueryType]:
    """
    检测单个目标的类型（IP / 域名 / 公司名）。
    
    返回 'ip', 'domain', 'company' 或 None（无法确定）。
    """
    target = target.strip()
    
    # IP 地址检测（IPv4）
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ip_pattern, target):
        parts = target.split('.')
        if all(0 <= int(p) <= 255 for p in parts):
            return "ip"
    
    # 域名检测（简单规则：包含点，且符合域名格式）
    # 简化域名匹配：至少包含一个点，且每个部分都是有效的域名标签
    if '.' in target and not target.startswith('.') and not target.endswith('.'):
        # 检查是否看起来像域名（包含字母或数字，用点分隔）
        domain_parts = target.split('.')
        if len(domain_parts) >= 2:
            # 每个部分应该只包含字母、数字、连字符
            if all(re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?$', part) for part in domain_parts):
                return "domain"
    
    # 如果既不是 IP 也不是域名，可能是公司名
    # 但这里无法准确判断，返回 None 让用户明确指定类型
    return None


def _validate_targets_type(targets: List[str], query_type: QueryType) -> Tuple[bool, Optional[str]]:
    """
    验证所有目标是否为同一类型。
    
    返回 (是否通过, 错误信息)
    """
    detected_types = []
    for target in targets:
        detected = _detect_target_type(target)
        detected_types.append((target, detected))
    
    # 检查是否有明显不匹配的
    mismatches = []
    for target, detected in detected_types:
        if detected is not None and detected != query_type:
            mismatches.append(f"{target} (检测为 {detected})")
    
    if mismatches:
        return False, f"目标类型不一致：{', '.join(mismatches)}，但查询类型为 {query_type}。请确保所有目标都是同一类型。"
    
    return True, None


def _has_credential(app_config, source: str) -> bool:
    """
    判断指定数据源是否配置了可用的 API 凭据。
    """
    s = source.lower()
    if s == "fofa":
        return bool(app_config.fofa.key)
    if s == "hunter":
        return bool(app_config.hunter.api_key)
    if s == "quake":
        return bool(app_config.quake.api_key)
    return False


def _probe_source(app_config, source: str) -> tuple[bool, str]:
    """
    真实请求一次各平台 API，粗略检测凭据是否"可用"。

    Hunter 使用用户信息接口验证，其他平台使用小查询验证。
    """
    if not _has_credential(app_config, source):
        return False, "未配置凭据"

    client = get_client(app_config, source)
    if client is None:
        return False, "未知数据源"

    try:
        # Hunter 和 Quake 有专门的验证接口，使用它们更合适
        if source.lower() in {"hunter", "quake"} and hasattr(client, "verify_credential"):
            return client.verify_credential()
        
        # 其他平台使用一个固定的、开销较小的查询作为"健康检查"
        client.search(query="example.com", query_type="domain", page=1, size=1)  # type: ignore[arg-type]
        return True, "可用"
    except requests.Timeout:
        # 验证时超时，可能是网络问题，但不代表凭据无效
        return False, "验证请求超时（可能是网络问题）"
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in {401, 403}:
            return False, f"凭据无效或无权限（HTTP {status})"
        return False, f"HTTP 错误 {status}: {exc}"
    except (ValueError, json.JSONDecodeError) as exc:
        # 某些镜像站可能返回非 JSON 内容，但只要 HTTP 层面是通的，
        # 且未返回 401/403，就认为凭据是"表面可用"的，后续查询再报具体错误。
        return True, f"HTTP 正常但解析响应失败：{exc}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

    return True, "可用"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="networkspace",
        description="通过 FOFA / Hunter / Quake 进行资产信息搜集的工具",
    )
    
    parser.add_argument(
        "-s",
        "--source",
        choices=["fofa", "hunter", "quake", "all"],
        default="all",
        help="选择数据源，默认为 all（全部）。",
    )

    parser.add_argument(
        "-t",
        "--type",
        dest="query_type",
        choices=["domain", "ip", "company"],
        help="查询类型：domain / ip / company。（交互模式下可省略）",
    )

    parser.add_argument(
        "-q",
        "--query",
        help="查询关键字，支持多个目标（用逗号分隔）或 .txt 文件路径。例如：'1.1.1.1,2.2.2.2' 或 'targets.txt'。（交互模式下可省略）",
    )

    parser.add_argument(
        "--page",
        type=int,
        default=1,
        help="页码，默认 1。",
    )

    parser.add_argument(
        "--size",
        type=int,
        default=100,
        help="每页数量，默认 100。",
    )

    parser.add_argument(
        "-o",
        "--output",
        help="导出文件路径（包含目录和文件名，支持 .csv 或 .txt 后缀）。例如：results/baidu.com.csv 或 output/ip_list.txt。如果目录不存在会自动创建。不指定则只在终端显示。",
    )

    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="进入交互式模式，逐步选择查询参数。",
    )

    parser.add_argument(
        "--config",
        help="配置文件路径（默认：当前目录下的 config.json）。",
    )

    return parser


def _print_results_summary(results: List[dict]) -> None:
    """
    显示搜索结果概览（简单统计表格）。
    """
    table = Table(title="搜索结果概览")
    table.add_column("Source", style="cyan", no_wrap=True)
    table.add_column("Query")
    table.add_column("Type")
    table.add_column("Count", justify="right")

    total = 0
    for item in results:
        count = len(item.get("results", []) or [])
        total += count
        table.add_row(
            str(item.get("source", "")),
            str(item.get("query", "")),
            str(item.get("query_type", "")),
            str(count),
        )

    table.caption = f"Total records (before global dedup): {total}"

    console.print(table)


def _print_detailed_results(assets: List[dict], query_type: str) -> None:
    """
    显示详细的搜索结果表格（包含所有字段）。
    """
    if not assets:
        console.print("[yellow]没有查询结果[/yellow]")
        return
    
    table = Table(title="详细查询结果")
    table.add_column("序号", justify="right", style="dim", no_wrap=True)
    table.add_column("Source", style="cyan", no_wrap=True)
    table.add_column("IP", style="green")
    table.add_column("Host", style="yellow")
    table.add_column("Port", justify="right")
    table.add_column("Domain")
    table.add_column("Title", style="dim")
    table.add_column("Company", style="dim")

    for idx, asset in enumerate(assets, start=1):
        table.add_row(
            str(idx),
            str(asset.get("source", "")),
            str(asset.get("ip", "")),
            str(asset.get("host", "")),
            str(asset.get("port", "")),
            str(asset.get("domain", "")),
            str(asset.get("title", ""))[:50] if asset.get("title") else "",  # 限制标题长度
            str(asset.get("company", "")),
        )

    console.print(table)
    console.print(f"[green]Total records (before global dedup): {len(assets)}[/green]")


def _interactive_args(available_sources: List[str], allow_company: bool) -> argparse.Namespace:
    """
    通过交互式问答构造一份“伪 argv 参数对象”，
    以复用原有 main 逻辑。
    """
    console.print("[bold cyan]交互式模式[/bold cyan]（也可以使用参数模式：python main.py -h 查看）")

    # 查询类型（使用数字序号选择）
    # 如果只有 FOFA 可用，则不提供 company 选项
    if allow_company:
        type_options: List[QueryType] = ["domain", "ip", "company"]
    else:
        type_options = ["domain", "ip"]

    console.print("\n请选择查询类型：")
    for idx, t in enumerate(type_options, start=1):
        console.print(f"  {idx}. {t}")
    console.print("  0. 退出程序")
    type_choice = Prompt.ask(
        "请输入序号",
        choices=[str(i) for i in range(0, len(type_options) + 1)],
        default="1",
    )
    if type_choice == "0":
        raise SystemExit(0)
    qtype = type_options[int(type_choice) - 1]

    # 查询关键字（根据查询类型显示不同的提示和默认值）
    # 支持多个目标：用逗号分隔，或从 .txt 文件读取
    targets: List[str] = []
    query_input: str = ""
    
    while True:
        if qtype == "domain":
            query_input = Prompt.ask(
                "请输入要查询的域名（支持多个目标，用逗号分隔，或输入 .txt 文件路径）",
                default="example.com" if not query_input else query_input
            )
        elif qtype == "ip":
            query_input = Prompt.ask(
                "请输入要查询的 IP 地址（支持多个目标，用逗号分隔，或输入 .txt 文件路径）",
                default="1.1.1.1" if not query_input else query_input
            )
        else:  # company
            query_input = Prompt.ask(
                "请输入要查询的企业名称（支持多个目标，用逗号分隔，或输入 .txt 文件路径）",
                default="" if not query_input else query_input
            )
        
        # 解析多个目标
        try:
            targets = _parse_targets(query_input)
            if not targets:
                console.print("[red]错误：未找到任何有效目标，请重新输入[/red]")
                continue
            
            # 检查是否是文件输入
            is_file_input = query_input.strip().endswith('.txt') and Path(query_input.strip()).exists()
            
            # 验证所有目标是否为同一类型
            is_valid, error_msg = _validate_targets_type(targets, qtype)
            if not is_valid:
                console.print(f"[red]错误：{error_msg}[/red]")
                if is_file_input:
                    console.print("[yellow]请检查文件内容，确保所有目标都是同一类型[/yellow]")
                continue
            
            # 如果是文件输入，显示文件内容表格
            if is_file_input:
                table = Table(title=f"文件内容预览 ({query_input})")
                table.add_column("序号", justify="right", style="dim", no_wrap=True)
                table.add_column("目标", style="cyan")
                table.add_column("类型", style="green")
                
                for idx, target in enumerate(targets, start=1):
                    detected_type = _detect_target_type(target)
                    type_display = detected_type if detected_type else "未知"
                    table.add_row(
                        str(idx),
                        target,
                        type_display
                    )
                
                console.print(table)
                console.print(f"[green]共 {len(targets)} 个目标，类型验证通过[/green]")
            
            # 验证通过，退出循环
            break
            
        except ValueError as e:
            console.print(f"[red]错误：{e}[/red]")
            console.print("[yellow]请重新输入[/yellow]")
            continue
    
    # 将多个目标用逗号连接，作为 query 参数（后续会拆分处理）
    query = ",".join(targets)

    # 数据源（只展示可用的数据源，使用数字序号选择）
    console.print("\n可用数据源：")
    source_options: List[str] = available_sources.copy()
    # 如果有多个数据源可用，添加 "all" 选项
    if len(available_sources) > 1:
        source_options.append("all")
    
    for idx, s in enumerate(source_options, start=1):
        console.print(f"  {idx}. {s}")
    console.print("  0. 退出程序")
    source_choice = Prompt.ask(
        "请选择数据源序号",
        choices=[str(i) for i in range(0, len(source_options) + 1)],
        default="1",
    )
    if source_choice == "0":
        raise SystemExit(0)
    source = source_options[int(source_choice) - 1]

    # 页码与数量
    page_str = Prompt.ask("页码(page)", default="1")
    size_str = Prompt.ask("每页数量(size)", default="100")

    try:
        page = int(page_str)
    except ValueError:
        page = 1
    try:
        size = int(size_str)
    except ValueError:
        size = 100

    # 是否导出（现在不需要输入文件名，会自动按目标名称生成）
    need_output = Prompt.ask(
        "是否导出结果到文件？",
        choices=["y", "n"],
        default="n",
    )
    output = None
    out_format = "csv"
    if need_output == "y":
        out_format = Prompt.ask(
            "选择导出格式",
            choices=["csv", "txt"],
            default="csv",
        )
        # 使用一个占位符，实际文件名会根据目标自动生成
        output = "results"  # 结果会保存到 results 文件夹

    # 用 argparse.Namespace 模拟解析结果
    return argparse.Namespace(
        source=source,
        query_type=qtype,
        query=query,
        page=page,
        size=size,
        output=output,
        out_format=out_format,
        interactive=True,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    
    # 如果是交互模式，进入循环
    if getattr(args, "interactive", False) or (args.query_type is None and args.query is None):
        return _interactive_loop(parser, args.config)
    
    # 非交互模式，执行一次查询
    return _execute_query(parser, args, args.config)


def _interactive_loop(parser: argparse.ArgumentParser, config_path: Optional[str]) -> int:
    """
    交互式循环模式：持续提供查询服务，直到用户选择退出。
    """
    app_config = load_config_from_file(config_path)
    
    # 启动阶段先对三家平台做一次"可用性检测"
    all_sources: List[str] = ["fofa", "hunter", "quake"]
    probe_ok: dict[str, bool] = {}

    console.print("[bold]开始检测各数据源 API 凭据可用性...[/bold]")
    for src in all_sources:
        if not _has_credential(app_config, src):
            console.print(f"[yellow]{src}: 未配置凭据，跳过检测[/yellow]")
            probe_ok[src] = False
            continue

        # 只有配置了凭据才进行有效性验证
        ok, reason = _probe_source(app_config, src)
        probe_ok[src] = ok
        if ok:
            console.print(f"[green]{src}: 凭据{reason}[/green]")
        else:
            console.print(f"[red]{src}: 凭据不可用（{reason}）[/red]")

    available_sources = [s for s in all_sources if probe_ok.get(s)]
    if not available_sources:
        console.print("[red]所有数据源凭据均不可用，程序退出。[/red]")
        return 1

    # 只有 Hunter / Quake 支持 company 查询
    allow_company = any(s in {"hunter", "quake"} for s in available_sources)
    
    # 循环查询
    while True:
        console.print("\n[bold cyan]========== 开始新的查询 ==========[/bold cyan]")
        console.print("[dim]提示：在任意选择步骤输入 0 可退出程序[/dim]\n")
        
        try:
            # 获取查询参数
            args = _interactive_args(available_sources, allow_company)
            
            # 执行查询（传入已检测的可用数据源，跳过重复检测）
            _execute_query(parser, args, config_path, available_sources)
            
            # 询问是否继续
            console.print("\n" + "="*50)
            continue_choice = Prompt.ask(
                "是否继续查询？",
                choices=["y", "n"],
                default="y"
            )
            
            if continue_choice == "n":
                console.print("[green]感谢使用，再见！[/green]")
                break
                
        except KeyboardInterrupt:
            console.print("\n[yellow]用户中断，退出程序[/yellow]")
            return 0
        except SystemExit as e:
            # 如果用户输入了 0 退出，或者有其他错误
            if e.code == 0:
                console.print("[green]感谢使用，再见！[/green]")
                return 0
            # 其他错误继续循环
            continue
        except Exception as e:
            console.print(f"[red]发生错误：{e}[/red]")
            continue_choice = Prompt.ask(
                "是否继续？",
                choices=["y", "n"],
                default="y"
            )
            if continue_choice == "n":
                break
    
    return 0


def _execute_query(parser: argparse.ArgumentParser, args: argparse.Namespace, config_path: Optional[str], available_sources: Optional[List[str]] = None) -> int:
    """
    执行一次查询（交互模式和非交互模式共用）。
    
    available_sources: 如果提供，则跳过凭据检测（交互模式循环中使用）
    """
    app_config = load_config_from_file(config_path)

    # 如果没有提供可用数据源列表，则进行检测（非交互模式）
    if available_sources is None:
        # 全局：先检查“是否至少存在一个可用的 API 凭据”，否则直接退出
        if not (
            app_config.fofa.key
            or app_config.hunter.api_key
            or app_config.quake.api_key
        ):
            console.print(
                "[red]未检测到任何可用的 API 凭据，请先在配置文件中设置：[/red]\n"
                "  - fofa.key\n"
                "  - hunter.api_key\n"
                "  - quake.api_key"
            )
            return 1

        # 根据用户指定的数据源决定验证哪些平台
        all_sources: List[str] = ["fofa", "hunter", "quake"]
        sources_to_check: List[str]
        
        if args.source == "all":
            # 选择 all 时，验证所有数据源
            sources_to_check = all_sources
        else:
            # 选择具体数据源时，只验证该数据源
            sources_to_check = [args.source]
        
        probe_ok: dict[str, bool] = {}

        console.print("[bold]开始检测各数据源 API 凭据可用性...[/bold]")
        for src in sources_to_check:
            if not _has_credential(app_config, src):
                console.print(f"[yellow]{src}: 未配置凭据，跳过检测[/yellow]")
                probe_ok[src] = False
                continue

            # 只有配置了凭据才进行有效性验证
            ok, reason = _probe_source(app_config, src)
            probe_ok[src] = ok
            if ok:
                console.print(f"[green]{src}: 凭据{reason}[/green]")
            else:
                console.print(f"[red]{src}: 凭据不可用（{reason}）[/red]")

        available_sources = [s for s in sources_to_check if probe_ok.get(s)]
        if not available_sources:
            console.print("[red]指定的数据源凭据不可用，程序退出。[/red]")
            return 1

    # 只有 Hunter / Quake 支持 company 查询
    allow_company = any(s in {"hunter", "quake"} for s in available_sources)

    if not getattr(args, "interactive", False):
        # 非交互模式下，确保必须提供 type 和 query
        if not args.query_type or not args.query:
            parser.error("arguments -t/--type and -q/--query are required unless using --interactive")

    # 根据用户输入与检测结果决定最终使用的数据源
    sources: List[str]
    if args.source == "all":
        sources = available_sources
    else:
        if args.source not in available_sources:
            console.print(f"[red]{args.source} 凭据不可用或未配置，无法用于查询。[/red]")
            return 1
        sources = [args.source]

    # 解析多个目标（支持逗号分隔）
    targets = [t.strip() for t in args.query.split(",") if t.strip()]
    if not targets:
        console.print("[red]错误：未找到任何有效查询目标[/red]")
        return 1
    
    # 验证所有目标是否为同一类型（如果不是交互模式，需要验证）
    if not getattr(args, "interactive", False):
        is_valid, error_msg = _validate_targets_type(targets, args.query_type)  # type: ignore[arg-type]
        if not is_valid:
            console.print(f"[red]错误：{error_msg}[/red]")
            return 1
    
    console.print(f"[cyan]共 {len(targets)} 个查询目标，开始查询...[/cyan]")
    
    # 按目标分组存储结果，每个目标单独处理
    target_results: Dict[str, List[dict]] = {target: [] for target in targets}
    
    # 如果不保存到文件，逐个查询并立即显示结果，避免连续请求导致限流
    if not args.output:
        # 逐个查询并立即显示
        for target_idx, target in enumerate(targets, 1):
            console.print(f"[dim]正在查询第 {target_idx}/{len(targets)} 个目标: {target}[/dim]")
            
            target_results_list: List[dict] = []
            
            for src in sources:
                client = get_client(app_config, src)
                if client is None:
                    console.print(f"[red]未知的数据源: {src}[/red]")
                    continue

                # FOFA 不支持企业查询：直接跳过并提示
                if src == "fofa" and args.query_type == "company":
                    if target_idx == 1:  # 只提示一次
                        console.print("[yellow]FOFA 不支持企业查询，已跳过 FOFA[/yellow]")
                    continue

                try:
                    result = client.search(
                        query=target,
                        query_type=args.query_type,  # type: ignore[arg-type]
                        page=args.page,
                        size=args.size,
                    )
                    # 显示查询语句
                    query_used = result.get("query_used", target)
                    console.print(f"[dim]查询语句: {query_used}[/dim]")
                    
                    # 显示请求 URL（如果有）
                    request_url = result.get("request_url")
                    if request_url:
                        console.print(f"[dim]请求 URL: {request_url}[/dim]")
                    
                    # 如果返回结果为空，输出提示
                    result_count = len(result.get("results", []))
                    total_size = result.get("total_size", 0)
                    tip = result.get("tip", "")
                    
                    if result_count == 0:
                        if total_size == 0:
                            console.print(
                                f"[yellow]提示：{src} 查询返回 0 条结果"
                                f"{'。' + tip if tip else ''}[/yellow]"
                            )
                        else:
                            console.print(
                                f"[yellow]提示：{src} 查询共找到 {total_size} 条结果，"
                                f"但当前页（第 {args.page} 页）无数据。[/yellow]"
                            )
                    
                    # 将结果添加到当前目标的结果列表
                    target_results_list.append(result)
                except requests.HTTPError as exc:
                    status = exc.response.status_code if exc.response is not None else None
                    if status in {401, 403}:
                        console.print(
                            f"[red]{src} 查询目标 '{target}' 失败：API 凭据无效或无权限（HTTP {status}）。"
                            " 请检查对应的 Key / 邮箱 是否正确。[/red]"
                        )
                    else:
                        console.print(f"[red]{src} 查询目标 '{target}' 失败（HTTP 错误 {status}）：{exc}[/red]")
                    continue
                except Exception as exc:  # noqa: BLE001
                    console.print(f"[red]{src} 查询目标 '{target}' 失败：{exc}[/red]")
                    continue
            
            # 立即显示当前目标的结果
            if target_results_list:
                raw_assets: List[dict] = []
                for block in target_results_list:
                    raw_assets.extend(block.get("results", []) or [])
                
                uniq_assets = dedup_assets(raw_assets, args.query_type)
                
                # 显示该目标的详细结果
                console.print(f"\n[bold cyan]目标: {target}[/bold cyan]")
                _print_detailed_results(uniq_assets, args.query_type)  # type: ignore[arg-type]
            
            # 存储结果（虽然不导出，但为了代码一致性保留）
            target_results[target] = target_results_list
    else:
        # 保存到文件时，先收集所有结果
        for target_idx, target in enumerate(targets, 1):
            console.print(f"[dim]正在查询第 {target_idx}/{len(targets)} 个目标: {target}[/dim]")
            
            for src in sources:
                client = get_client(app_config, src)
                if client is None:
                    console.print(f"[red]未知的数据源: {src}[/red]")
                    continue

                # FOFA 不支持企业查询：直接跳过并提示
                if src == "fofa" and args.query_type == "company":
                    if target_idx == 1:  # 只提示一次
                        console.print("[yellow]FOFA 不支持企业查询，已跳过 FOFA[/yellow]")
                    continue

                try:
                    result = client.search(
                        query=target,
                        query_type=args.query_type,  # type: ignore[arg-type]
                        page=args.page,
                        size=args.size,
                    )
                    # 显示查询语句
                    query_used = result.get("query_used", target)
                    console.print(f"[dim]查询语句: {query_used}[/dim]")
                    
                    # 显示请求 URL（如果有）
                    request_url = result.get("request_url")
                    if request_url:
                        console.print(f"[dim]请求 URL: {request_url}[/dim]")
                    
                    # 如果返回结果为空，输出提示
                    result_count = len(result.get("results", []))
                    total_size = result.get("total_size", 0)
                    tip = result.get("tip", "")
                    
                    if result_count == 0:
                        if total_size == 0:
                            console.print(
                                f"[yellow]提示：{src} 查询返回 0 条结果"
                                f"{'。' + tip if tip else ''}[/yellow]"
                            )
                        else:
                            console.print(
                                f"[yellow]提示：{src} 查询共找到 {total_size} 条结果，"
                                f"但当前页（第 {args.page} 页）无数据。[/yellow]"
                            )
                    
                    # 将结果按目标分组存储
                    target_results[target].append(result)
                except requests.HTTPError as exc:
                    status = exc.response.status_code if exc.response is not None else None
                    if status in {401, 403}:
                        console.print(
                            f"[red]{src} 查询目标 '{target}' 失败：API 凭据无效或无权限（HTTP {status}）。"
                            " 请检查对应的 Key / 邮箱 是否正确。[/red]"
                        )
                    else:
                        console.print(f"[red]{src} 查询目标 '{target}' 失败（HTTP 错误 {status}）：{exc}[/red]")
                    continue
                except Exception as exc:  # noqa: BLE001
                    console.print(f"[red]{src} 查询目标 '{target}' 失败：{exc}[/red]")
                    continue

        # 汇总所有结果用于显示概览
        all_collected: List[dict] = []
        for target_results_list in target_results.values():
            all_collected.extend(target_results_list)
        
        # 保存到文件时，只显示概览
        _print_results_summary(all_collected)

    # 每个目标单独去重和导出
    if args.output:
        is_interactive = getattr(args, "interactive", False)
        
        if is_interactive:
            # 交互模式：每个目标单独保存到 results 文件夹，格式由用户选择
            output_dir = Path("results")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # 从 args 获取格式（交互模式下用户已选择）
            out_format = getattr(args, "out_format", "csv")
            
            total_uniq_count = 0
            for target, target_results_list in target_results.items():
                if not target_results_list:
                    continue
                
                # 每个目标单独去重
                raw_assets: List[dict] = []
                for block in target_results_list:
                    raw_assets.extend(block.get("results", []) or [])
                
                uniq_assets = dedup_assets(raw_assets, args.query_type)
                total_uniq_count += len(uniq_assets)
                
                # 生成文件名：将目标名称中的特殊字符替换为下划线
                safe_filename = re.sub(r'[<>:"/\\|?*]', '_', target)
                # 确保文件名不会太长
                if len(safe_filename) > 200:
                    safe_filename = safe_filename[:200]
                
                output_file = output_dir / f"{safe_filename}.{out_format}"
                
                # 导出
                if out_format == "txt":
                    export_txt(uniq_assets, args.query_type, str(output_file))
                else:
                    export_csv(uniq_assets, str(output_file))
                
                console.print(
                    f"[green]目标 '{target}' 去重后 {len(uniq_assets)} 条，已导出到: {output_file.absolute()}[/green]"
                )
            
            console.print(
                f"[green]所有结果已保存到文件夹: {output_dir.absolute()}[/green]"
                f"[green]（共 {len([t for t in target_results.values() if t])} 个目标，"
                f"总计 {total_uniq_count} 条去重后资产）[/green]"
            )
        else:
            # 参数模式：从 -o 参数指定的路径判断格式
            output_path = Path(args.output)
            
            # 从文件扩展名判断格式
            ext = output_path.suffix.lower().lstrip('.')
            if ext not in ['csv', 'txt']:
                console.print(f"[yellow]警告：文件扩展名 '{ext}' 不是 csv 或 txt，默认使用 csv[/yellow]")
                ext = 'csv'
                output_path = output_path.with_suffix('.csv')
            
            # 自动创建目录
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 如果只有一个目标，直接导出到指定文件
            if len(targets) == 1:
                target = targets[0]
                target_results_list = target_results.get(target, [])
                if target_results_list:
                    raw_assets: List[dict] = []
                    for block in target_results_list:
                        raw_assets.extend(block.get("results", []) or [])
                    
                    uniq_assets = dedup_assets(raw_assets, args.query_type)
                    
                    # 导出
                    if ext == "txt":
                        export_txt(uniq_assets, args.query_type, str(output_path))
                    else:
                        export_csv(uniq_assets, str(output_path))
                    
                    console.print(
                        f"[green]去重后 {len(uniq_assets)} 条资产，已导出到: {output_path.absolute()}[/green]"
                    )
            else:
                # 多个目标：导出到指定目录，每个目标一个文件
                output_dir = output_path.parent
                if output_path.is_dir():
                    output_dir = output_path
                else:
                    output_dir = output_path.parent
                
                output_dir.mkdir(parents=True, exist_ok=True)
                
                total_uniq_count = 0
                for target, target_results_list in target_results.items():
                    if not target_results_list:
                        continue
                    
                    raw_assets: List[dict] = []
                    for block in target_results_list:
                        raw_assets.extend(block.get("results", []) or [])
                    
                    uniq_assets = dedup_assets(raw_assets, args.query_type)
                    total_uniq_count += len(uniq_assets)
                    
                    # 生成文件名
                    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', target)
                    if len(safe_filename) > 200:
                        safe_filename = safe_filename[:200]
                    
                    output_file = output_dir / f"{safe_filename}.{ext}"
                    
                    # 导出
                    if ext == "txt":
                        export_txt(uniq_assets, args.query_type, str(output_file))
                    else:
                        export_csv(uniq_assets, str(output_file))
                    
                    console.print(
                        f"[green]目标 '{target}' 去重后 {len(uniq_assets)} 条，已导出到: {output_file.absolute()}[/green]"
                    )
                
                console.print(
                    f"[green]所有结果已保存到文件夹: {output_dir.absolute()}[/green]"
                    f"[green]（共 {len([t for t in target_results.values() if t])} 个目标，"
                    f"总计 {total_uniq_count} 条去重后资产）[/green]"
                )
    # 注意：不导出时，结果已经在查询循环中立即显示了，这里不需要再处理

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


