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
from typing import Optional, List
import yaml

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich import print as rprint

from models import QueryParams, TimeRange, AnalysisResult, ComplaintDetail
from data_source import fetch_posts
from analyzer import analyze, Analyzer
from report_generator import ReportGenerator, generate_report


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


def run_analysis(params: QueryParams, config: dict) -> AnalysisResult:
    with console.status("[bold green]正在抓取论坛数据...[/bold green]") as status:
        posts = fetch_posts(params, count=300, seed=42)
        status.update("[bold green]数据抓取完成，正在分析...[/bold green]")
        result = analyze(posts, params, config=config)
        return result


def interactive_session(result: AnalysisResult, config: dict):
    report_gen = ReportGenerator(config=config)
    analyzer_engine = Analyzer(config=config)

    console.print()
    console.print(Panel(
        "[bold]命令提示:[/bold]\n"
        "  [cyan]追问 <槽点关键词>[/cyan]  深挖某个槽点\n"
        "  [cyan]列表[/cyan]                   查看所有槽点/优点/疑问关键词\n"
        "  [cyan]导出[/cyan]                   保存为会议纪要格式\n"
        "  [cyan]新查询[/cyan]                 开始新一轮调研\n"
        "  [cyan]退出[/cyan]                   退出程序",
        border_style="yellow",
        expand=False,
    ))

    while True:
        try:
            cmd = Prompt.ask("\n[bold blue]>[/bold blue] 请输入命令").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]再见！[/yellow]")
            break

        if not cmd:
            continue

        cmd_lower = cmd.lower()

        if cmd_lower in ["退出", "exit", "quit", "q"]:
            console.print("[yellow]再见！[/yellow]")
            break

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
            for sep in ["追问", "dive", "detail", " "]:
                if sep in cmd:
                    parts = cmd.split(sep, 1)
                    if len(parts) > 1:
                        keyword = parts[1].strip()
                        break
            if not keyword:
                keyword = Prompt.ask("请输入要深挖的槽点关键词")
            keyword = keyword.strip()

            ta = result.theme_analysis
            matched = None
            for source in [ta.complaints, ta.advantages, ta.questions]:
                for kw in source:
                    if kw.keyword == keyword or keyword in kw.keyword or kw.keyword in keyword:
                        matched = kw.keyword
                        break
                if matched:
                    break

            if not matched:
                matched = keyword

            detail = analyzer_engine.get_complaint_detail(matched, result)
            report_gen.print_complaint_detail(detail, matched)

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

        elif cmd_lower in ["新查询", "new", "reset", "n"]:
            if Confirm.ask("确定要开始新一轮查询吗？", default=True):
                return True

        elif cmd_lower in ["帮助", "help", "h", "?"]:
            console.print(Panel(
                "[bold]可用命令:[/bold]\n"
                "  [cyan]追问 <关键词>[/cyan]   深挖某个槽点（如：追问 售后差）\n"
                "  [cyan]列表[/cyan]                列出所有关键词\n"
                "  [cyan]重绘[/cyan]                重新显示完整报告\n"
                "  [cyan]导出[/cyan]                保存为会议纪要TXT\n"
                "  [cyan]新查询[/cyan]              开始新一轮调研\n"
                "  [cyan]帮助[/cyan]                显示本帮助\n"
                "  [cyan]退出[/cyan]                退出程序",
                border_style="blue",
                title="帮助",
                expand=False,
            ))

        else:
            console.print(f"[yellow]未知命令: {cmd}，输入「帮助」查看可用命令[/yellow]")

    return False


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reputation_checker",
        description="品牌口碑速查工具 - 面向品牌咨询顾问的论坛贴吧声音速查工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py --brand 小米手机 --competitors 华为手机,苹果手机 --days 30 --themes 售后,新品,涨价
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
    parser.add_argument("--export", type=str, nargs="?", const="./reports", help="直接导出为会议纪要，可指定输出目录")
    parser.add_argument("--no-interactive", action="store_true", help="非交互模式，输出报告后直接退出")
    return parser


def show_banner():
    banner = """
[bold magenta]░█▀█░█▀▀░█▀█░█░█░▀█▀░█▀█░▀█▀░░░░░█▀▀░█░█░█▀▀░█▀▀░█░█░█▀▀░█▀▄[/bold magenta]
[bold magenta]░█▀▀░█▀▀░█░█░█░█░░█░░█░█░░█░░░░░░█░░█▀█░█▀▀░█░░░█▀▄░█▀▀░█▀▄[/bold magenta]
[bold magenta]░▀░░░▀▀▀░▀░▀░▀▀▀░░▀░░▀░▀░░▀░░▀▀▀░░▀▀▀░▀░▀░▀▀▀░▀▀▀░▀░▀░▀▀▀░▀░▀[/bold magenta]
[dim]Reputation Quick Check Tool v1.0  |  面向品牌咨询顾问[/dim]
    """
    console.print(banner)


def main():
    show_banner()

    arg_parser = build_arg_parser()
    args = arg_parser.parse_args()

    config = load_config(args.config)

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
    result = run_analysis(params, config)

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
            should_restart = interactive_session(result, config)
            if not should_restart:
                break
            console.clear()
            show_banner()
            params = build_query_params_interactive()
            result = run_analysis(params, config)
            report_gen.print_full_report(result)
    except KeyboardInterrupt:
        console.print("\n\n[yellow]程序被中断，再见！[/yellow]")


if __name__ == "__main__":
    main()
