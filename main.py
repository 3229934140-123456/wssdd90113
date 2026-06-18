#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
品牌口碑速查工具 - 命令行入口
面向品牌咨询顾问的论坛贴吧声音速查工具
"""

import sys
import os
import argparse
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
import yaml

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich import box
from rich import print as rprint

from models import (
    QueryParams, TimeRange, AnalysisResult, ComplaintDetail,
    BatchComparisonResult
)
from data_source import fetch_posts_with_library
from analyzer import analyze, Analyzer
from report_generator import ReportGenerator, generate_report
from sample_library import get_library, SampleLibrary


console = Console()


def load_config(config_path: str = "config.yaml") -> dict:
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        console.print(f"[yellow]未找到配置文件 {config_path}，使用默认配置[/yellow]")
        return {}
    except Exception as e:
        console.print(f"[red]配置文件加载失败: {e}，使用默认配置[/red]")
        return {}


def parse_date(date_str: str, default_offset_days: int = 0) -> datetime:
    date_str = date_str.strip()
    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%m-%d", "%m/%d"]:
        try:
            d = datetime.strptime(date_str, fmt)
            if fmt in ["%m-%d", "%m/%d"]:
                d = d.replace(year=datetime.now().year)
            return d.replace(hour=0, minute=0, second=0) + timedelta(days=default_offset_days)
        except ValueError:
            continue
    try:
        if "天前" in date_str:
            days = int(date_str.replace("天前", "").strip())
            return (datetime.now() - timedelta(days=days)).replace(hour=0, minute=0, second=0)
        if "周前" in date_str:
            weeks = int(date_str.replace("周前", "").strip())
            return (datetime.now() - timedelta(weeks=weeks)).replace(hour=0, minute=0, second=0)
    except ValueError:
        pass
    raise ValueError(f"无法解析日期: {date_str}，支持格式: YYYY-MM-DD, MM-DD, N天前")


def build_query_params_interactive() -> QueryParams:
    console.print(Panel(
        "[bold]请输入调研参数[/bold]\n（留空使用默认值，回车跳过）",
        border_style="cyan",
        expand=False,
    ))
    target_brand = Prompt.ask("[bold green]1. 目标品牌名[/bold green]", default="小米手机")

    competing_input = Prompt.ask(
        "[bold green]2. 竞品名（多个用英文逗号分隔，可留空）[/bold green]",
        default="华为手机,苹果手机"
    )
    competing_brands = [b.strip() for b in competing_input.replace("，", ",").split(",") if b.strip()]

    time_mode = Prompt.ask(
        "[bold green]3. 时间范围[/bold green] [1]近7天 [2]近30天 [3]近3个月 [4]自定义",
        choices=["1", "2", "3", "4"], default="2"
    )
    time_range: Optional[TimeRange] = None
    now = datetime.now().replace(hour=23, minute=59, second=59)
    if time_mode == "1":
        time_range = TimeRange(start_date=now - timedelta(days=7), end_date=now)
    elif time_mode == "2":
        time_range = TimeRange(start_date=now - timedelta(days=30), end_date=now)
    elif time_mode == "3":
        time_range = TimeRange(start_date=now - timedelta(days=90), end_date=now)
    else:
        start_str = Prompt.ask("   起始日期 (YYYY-MM-DD)", default=(now - timedelta(days=30)).strftime("%Y-%m-%d"))
        end_str = Prompt.ask("   结束日期 (YYYY-MM-DD)", default=now.strftime("%Y-%m-%d"))
        try:
            start = parse_date(start_str)
            end = parse_date(end_str, default_offset_days=1)
            if end <= start:
                end = start + timedelta(days=1)
            time_range = TimeRange(start_date=start, end_date=end.replace(hour=23, minute=59, second=59))
        except ValueError as e:
            console.print(f"[red]日期解析失败: {e}，默认使用近30天[/red]")
            time_range = TimeRange(start_date=now - timedelta(days=30), end_date=now)

    themes_input = Prompt.ask(
        "[bold green]4. 关注主题（多个用英文逗号分隔，如：售后,新品,涨价）[/bold green]",
        default="售后,新品,涨价"
    )
    focus_themes = [t.strip() for t in themes_input.replace("，", ",").split(",") if t.strip()]

    return QueryParams(
        target_brand=target_brand,
        competing_brands=competing_brands,
        time_range=time_range,
        focus_themes=focus_themes,
    )


def build_query_params_from_args(args) -> QueryParams:
    target_brand = args.brand
    competing_brands = []
    if args.competitors:
        competing_brands = [b.strip() for b in args.competitors.replace("，", ",").split(",") if b.strip()]

    time_range: Optional[TimeRange] = None
    now = datetime.now().replace(hour=23, minute=59, second=59)
    if args.days:
        time_range = TimeRange(start_date=now - timedelta(days=args.days), end_date=now)
    elif args.start_date or args.end_date:
        try:
            start = parse_date(args.start_date) if args.start_date else (now - timedelta(days=30))
            end = parse_date(args.end_date, default_offset_days=1) if args.end_date else now
            time_range = TimeRange(start_date=start, end_date=end)
        except ValueError as e:
            console.print(f"[red]日期解析失败: {e}[/red]")
            sys.exit(1)
    else:
        time_range = TimeRange(start_date=now - timedelta(days=30), end_date=now)

    focus_themes = []
    if args.themes:
        focus_themes = [t.strip() for t in args.themes.replace("，", ",").split(",") if t.strip()]

    return QueryParams(
        target_brand=target_brand,
        competing_brands=competing_brands,
        time_range=time_range,
        focus_themes=focus_themes,
    )


def run_analysis(
    params: QueryParams,
    config: dict,
    use_library: bool = True,
) -> Tuple[AnalysisResult, dict]:
    library = get_library() if use_library else None

    status_text = "[bold green]正在从样本库读取+补充生成数据...[/bold green]" if use_library else "[bold green]正在生成模拟数据...[/bold green]"
    with console.status(status_text) as status:
        posts, lib_stats = fetch_posts_with_library(
            params, count=400, use_library=use_library, library=library
        )
        status.update("[bold green]数据准备完成，正在分析...[/bold green]")
        result = analyze(posts, params, config=config)

    if use_library:
        hint_parts = []
        if lib_stats.get("library_hit", 0) > 0:
            hint_parts.append(f"样本库命中 {lib_stats['library_hit']} 条")
        if lib_stats.get("new_generated", 0) > 0:
            hint_parts.append(f"新生成 {lib_stats['new_generated']} 条")
        if lib_stats.get("saved", 0) > 0:
            hint_parts.append(f"已入库 {lib_stats['saved']} 条")
        if hint_parts:
            console.print(f"  [dim]📚 {' | '.join(hint_parts)}[/dim]")

    return result, lib_stats


def run_batch_comparison(
    params: QueryParams,
    config: dict,
    use_library: bool = True,
) -> BatchComparisonResult:
    library = get_library() if use_library else None

    with console.status("[bold green]正在准备多品牌对比数据...[/bold green]") as status:
        posts, lib_stats = fetch_posts_with_library(
            params, count=500, use_library=use_library, library=library
        )
        status.update("[bold green]正在执行批量对比分析...[/bold green]")
        analyzer = Analyzer(config=config)
        comp_result = analyzer.compare_brands(
            all_posts=posts,
            target_brand=params.target_brand,
            competing_brands=params.competing_brands,
            time_range=params.time_range,
        )

    comp_result.brand_results = {}
    brands = [params.target_brand] + params.competing_brands
    for brand in brands:
        sub_params = QueryParams(
            target_brand=brand,
            competing_brands=[b for b in brands if b != brand],
            time_range=params.time_range,
            focus_themes=params.focus_themes,
        )
        comp_result.brand_results[brand] = analyze(posts, sub_params, config=config)

    return comp_result


def print_library_status():
    library = get_library()
    brands = library.list_brands()
    if not brands:
        console.print("[dim]样本库当前为空，下次查询时会自动写入。[/dim]")
        return

    console.print(f"\n[bold cyan]📚 离线样本库（共 {len(brands)} 个品牌）:[/bold cyan]")
    table = Table(box=box.MINIMAL, show_lines=False)
    table.add_column("品牌", style="bold")
    table.add_column("累计帖数", justify="right")
    table.add_column("最新帖子时间", justify="right")
    for brand, count, latest in brands:
        latest_str = "-"
        if latest:
            try:
                latest_str = datetime.fromisoformat(latest).strftime("%Y-%m-%d %H:%M")
            except Exception:
                latest_str = str(latest)[:16]
        table.add_row(brand, f"{count:,}", latest_str)
    console.print(table)


def clear_library_brand(brand: str):
    library = get_library()
    info = library.count_by_brand(brand)
    if info["total"] == 0:
        console.print(f"[dim]样本库中没有「{brand}」的数据。[/dim]")
        return
    if Confirm.ask(f"确认要清空样本库中「{brand}」的 {info['total']} 条数据吗？", default=False):
        removed = library.clear_brand(brand)
        console.print(f"[green]✓ 已删除 {removed} 条「{brand}」相关数据。[/green]")


def interactive_session(
    result: AnalysisResult,
    config: dict,
    params: QueryParams,
):
    report_gen = ReportGenerator(config=config)
    analyzer_engine = Analyzer(config=config)

    console.print()
    console.print(Panel(
        "[bold]命令提示:[/bold]\n"
        "  [cyan]追问 <任意描述>[/cyan]   深挖槽点（支持模糊，如「追问售后为什么差」「追问涨价」）\n"
        "  [cyan]列表[/cyan]                    查看所有关键词\n"
        "  [cyan]对比[/cyan]                    输出多品牌批量对比摘要\n"
        "  [cyan]导出[/cyan]                    保存为会议纪要格式\n"
        "  [cyan]样本库|库[/cyan]              查看离线样本库状态\n"
        "  [cyan]清空 <品牌>[/cyan]           清空某品牌的样本库数据\n"
        "  [cyan]新查询[/cyan]                  开始新一轮调研\n"
        "  [cyan]退出[/cyan]                    退出程序",
        border_style="yellow",
        expand=False,
    ))

    while True:
        try:
            cmd = Prompt.ask("\n[bold blue]>[/bold blue] 请输入命令").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]再见！[/yellow]")
            return False

        if not cmd:
            continue

        cmd_lower = cmd.lower()

        if cmd_lower in ["退出", "exit", "quit", "q"]:
            console.print("[yellow]再见！[/yellow]")
            return False

        elif cmd_lower in ["重绘", "report", "r"]:
            report_gen.print_full_report(result)

        elif cmd_lower in ["列表", "list", "l", "ls"]:
            ta = result.theme_analysis
            console.print("\n[bold cyan]=== 所有关键词 ===[/bold cyan]")
            if ta.advantages:
                console.print("[green]优点:[/green] " + ", ".join(f"{k.keyword}({k.count})" for k in ta.advantages[:10]))
            if ta.complaints:
                console.print("[red]槽点:[/red] " + ", ".join(f"{k.keyword}({k.count})" for k in ta.complaints[:10]))
            if ta.questions:
                console.print("[cyan]疑问:[/cyan] " + ", ".join(f"{k.keyword}({k.count})" for k in ta.questions[:10]))

        elif cmd_lower.startswith("追问") or cmd_lower.startswith("dive") or cmd_lower.startswith("detail"):
            keyword = ""
            for sep in ["追问", "dive", "detail"]:
                idx = cmd_lower.find(sep)
                if idx >= 0:
                    keyword = cmd[idx + len(sep):].strip()
                    keyword = keyword.lstrip(" :：-—")
                    break
            if not keyword:
                keyword = Prompt.ask("请输入要深挖的描述（如「售后为什么差」「涨价」）")
            keyword = keyword.strip()
            if not keyword:
                continue

            detail = analyzer_engine.get_complaint_detail(keyword, result)
            report_gen.print_complaint_detail(detail, keyword)

        elif cmd_lower in ["导出", "export", "save", "s"]:
            default_dir = config.get("output", {}).get("default_dir", "./reports")
            output_dir = Prompt.ask("保存目录", default=default_dir)
            with console.status("[bold green]正在生成会议纪要...[/bold green]"):
                minutes = report_gen.build_meeting_minutes(result)
                filepath = report_gen.export_meeting_minutes(minutes, output_dir=output_dir)
            console.print(f"\n[bold green]✓ 会议纪要已保存:[/bold green] [underline]{os.path.abspath(filepath)}[/underline]")

            if Confirm.ask("是否打开文件所在目录？", default=False):
                abs_dir = os.path.abspath(os.path.dirname(filepath))
                try:
                    if os.name == "nt":
                        os.startfile(abs_dir)
                    elif sys.platform == "darwin":
                        os.system(f'open "{abs_dir}"')
                    else:
                        os.system(f'xdg-open "{abs_dir}"')
                except Exception as e:
                    console.print(f"[yellow]无法打开目录: {e}[/yellow]")

        elif cmd_lower in ["对比", "compare", "cmp", "c"]:
            if not params.competing_brands:
                console.print("[yellow]当前没有设置竞品，请先使用「新查询」增加竞品。[/yellow]")
                continue
            with console.status("[bold green]正在生成批量对比...[/bold green]"):
                comp_result = run_batch_comparison(params, config)
            report_gen.print_batch_comparison(comp_result)

        elif cmd_lower in ["样本库", "库", "library", "lib", "db"]:
            print_library_status()

        elif cmd_lower.startswith("清空") or cmd_lower.startswith("clear"):
            brand_to_clear = ""
            for sep in ["清空", "clear"]:
                idx = cmd_lower.find(sep)
                if idx >= 0:
                    brand_to_clear = cmd[idx + len(sep):].strip()
                    break
            if not brand_to_clear:
                brand_to_clear = Prompt.ask("请输入要清空的品牌名", default=params.target_brand)
            clear_library_brand(brand_to_clear)

        elif cmd_lower in ["新查询", "new", "reset", "n"]:
            if Confirm.ask("确定要开始新一轮查询吗？", default=True):
                return True

        elif cmd_lower in ["帮助", "help", "h", "?"]:
            console.print(Panel(
                "[bold]可用命令:[/bold]\n"
                "  [cyan]追问 <描述>[/cyan]   模糊匹配后深挖槽点（如「追问售后差」「涨价」「新品翻车」）\n"
                "  [cyan]列表[/cyan]            列出所有优点/槽点/疑问关键词\n"
                "  [cyan]重绘[/cyan]            重新显示完整三段式报告\n"
                "  [cyan]对比[/cyan]            目标品牌 vs 多竞品批量对照摘要\n"
                "  [cyan]导出[/cyan]            保存会议纪要 TXT\n"
                "  [cyan]样本库[/cyan]          查看离线样本库累计数据量\n"
                "  [cyan]清空 <品牌>[/cyan]    清除某品牌的样本库数据\n"
                "  [cyan]新查询[/cyan]          开始新一轮调研\n"
                "  [cyan]帮助[/cyan]            显示本帮助\n"
                "  [cyan]退出[/cyan]            退出程序",
                border_style="blue",
                title="帮助",
                expand=False,
            ))

        else:
            console.print(f"[yellow]未知命令: {cmd}，输入「帮助」查看可用命令[/yellow]")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reputation_checker",
        description="品牌口碑速查工具 v2 - 面向品牌咨询顾问的论坛声音速查",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
v2 更新内容:
  · 讨论量环比含上一周期可比数据（不再固定+100%）
  · 离线样本库：SQLite 持久化，重启仍可复用历史帖子
  · 追问支持模糊匹配：「追问售后为什么差」自动定位到对应槽点
  · 新增批量对比模式：--compare 输出多品牌对照摘要

示例:
  python main.py --brand 小米手机 --competitors 华为手机,苹果手机 --days 30 --themes 售后,新品,涨价
  python main.py --brand 小米手机 --competitors 华为手机,苹果手机 --days 30 --compare
  python main.py  (进入交互模式)
        """,
    )
    parser.add_argument("-b", "--brand", type=str, help="目标品牌名")
    parser.add_argument("-c", "--competitors", type=str, help="竞品名，多个用逗号分隔")
    parser.add_argument("-d", "--days", type=int, help="最近N天的数据")
    parser.add_argument("-s", "--start-date", type=str, help="起始日期 (YYYY-MM-DD)")
    parser.add_argument("-e", "--end-date", type=str, help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("-t", "--themes", type=str, help="关注主题，多个用逗号分隔")
    parser.add_argument("--config", type=str, default="config.yaml", help="配置文件路径")
    parser.add_argument("--compare", action="store_true", help="输出多品牌批量对比报告")
    parser.add_argument("--export", type=str, nargs="?", const="./reports", help="直接导出为会议纪要，可指定输出目录")
    parser.add_argument("--no-library", action="store_true", help="不使用离线样本库（仅临时生成）")
    parser.add_argument("--no-interactive", action="store_true", help="非交互模式，输出报告后直接退出")
    return parser


def show_banner():
    banner = """
[bold magenta]░█▀█░█▀▀░█▀█░█░█░▀█▀░█▀█░▀█▀░░░░░█▀▀░█░█░█▀▀░█▀▀░█░█░█▀▀░█▀▄[/bold magenta]
[bold magenta]░█▀▀░█▀▀░█░█░█░█░░█░░█░█░░█░░░░░░█░░█▀█░█▀▀░█░░░█▀▄░█▀▀░█▀▄[/bold magenta]
[bold magenta]░▀░░░▀▀▀░▀░▀░▀▀▀░░▀░░▀░▀░░▀░░▀▀▀░░▀▀▀░▀░▀░▀▀▀░▀▀▀░▀░▀░▀▀▀░▀░▀[/bold magenta]
[dim]Reputation Quick Check Tool v2.0  |  双周期可比 · 离线样本库 · 模糊追问 · 多品牌对比[/dim]
    """
    console.print(banner)


def main():
    show_banner()

    arg_parser = build_arg_parser()
    args = arg_parser.parse_args()

    config = load_config(args.config)

    use_library = not args.no_library

    if args.brand:
        params = build_query_params_from_args(args)
    else:
        if sys.stdin.isatty():
            params = build_query_params_interactive()
        else:
            arg_parser.print_help()
            console.print("\n[red]非交互模式下必须指定 --brand 参数[/red]")
            sys.exit(1)

    console.print()

    if args.compare:
        if not params.competing_brands:
            console.print("[yellow]--compare 需要配合 --competitors 指定至少一个竞品[/yellow]")
            sys.exit(1)
        comp_result = run_batch_comparison(params, config, use_library=use_library)
        report_gen = ReportGenerator(config=config)
        report_gen.print_batch_comparison(comp_result)
        if args.no_interactive:
            return
        dummy_result = list(comp_result.brand_results.values())[0] if comp_result.brand_results else None
        if dummy_result:
            if interactive_session(dummy_result, config, params):
                pass
            return

    result, _ = run_analysis(params, config, use_library=use_library)
    report_gen = generate_report(result, config=config)

    if args.export is not None:
        with console.status("[bold green]正在生成会议纪要...[/bold green]"):
            minutes = report_gen.build_meeting_minutes(result)
            filepath = report_gen.export_meeting_minutes(minutes, output_dir=args.export)
        console.print(f"\n[bold green]✓ 会议纪要已保存:[/bold green] [underline]{os.path.abspath(filepath)}[/underline]")

    if args.no_interactive:
        return

    try:
        while True:
            should_restart = interactive_session(result, config, params)
            if not should_restart:
                break
            console.clear()
            show_banner()
            params = build_query_params_interactive()
            result, _ = run_analysis(params, config, use_library=use_library)
            report_gen.print_full_report(result)
    except KeyboardInterrupt:
        console.print("\n\n[yellow]程序被中断，再见！[/yellow]")


if __name__ == "__main__":
    main()
