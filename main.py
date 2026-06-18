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
    BatchComparisonResult, ResearchProject
)
from data_source import fetch_posts_with_library
from analyzer import analyze, Analyzer
from report_generator import ReportGenerator, generate_report, export_project_progress_minutes
from sample_library import get_library, SampleLibrary
from project_manager import get_project_manager, ProjectManager


console = Console()


def _extract_result_summary(result: AnalysisResult) -> dict:
    va = result.volume_analysis
    ta = result.theme_analysis
    summary = {
        "current_posts": va.time_range_posts,
        "previous_posts": va.previous_range_posts,
        "volume_change": va.volume_change_rate,
        "negative_ratio": va.negative_ratio,
    }
    if ta.complaints:
        summary["top_complaint"] = f"{ta.complaints[0].keyword}({ta.complaints[0].count}次)"
    if ta.advantages:
        summary["top_advantage"] = f"{ta.advantages[0].keyword}({ta.advantages[0].count}次)"
    return summary


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
    library_mode: str = "smart",
    project: Optional[ResearchProject] = None,
) -> Tuple[AnalysisResult, dict]:
    library = get_library() if use_library else None

    status_text = f"[bold green]数据获取模式: {library_mode}，正在处理...[/bold green]"
    with console.status(status_text) as status:
        posts, lib_stats = fetch_posts_with_library(
            params, count=400, use_library=use_library, library=library, mode=library_mode
        )
        status.update("[bold green]数据准备完成，正在分析...[/bold green]")
        result = analyze(posts, params, config=config)

    if use_library:
        hint_parts = [f"模式: {lib_stats.get('mode', library_mode)}"]
        if lib_stats.get("library_hit", 0) > 0:
            hint_parts.append(f"样本库命中 {lib_stats['library_hit']} 条")
        if lib_stats.get("new_generated", 0) > 0:
            hint_parts.append(f"新生成 {lib_stats['new_generated']} 条")
        if lib_stats.get("saved", 0) > 0:
            hint_parts.append(f"已入库 {lib_stats['saved']} 条")
        console.print(f"  [dim]📚 {' | '.join(hint_parts)}[/dim]")

    if project:
        pm = get_project_manager()
        result_summary = _extract_result_summary(result)
        pm.add_query_snapshot(project, params, result_summary)

    return result, lib_stats


def run_batch_comparison(
    params: QueryParams,
    config: dict,
    use_library: bool = True,
    library_mode: str = "smart",
) -> BatchComparisonResult:
    library = get_library() if use_library else None

    with console.status("[bold green]正在准备多品牌对比数据...[/bold green]") as status:
        posts, lib_stats = fetch_posts_with_library(
            params, count=500, use_library=use_library, library=library, mode=library_mode
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


def print_project_list(pm: ProjectManager):
    projects = pm.list_projects()
    if not projects:
        console.print("[dim]还没有任何调研项目，使用「新建项目 <项目名>」创建第一个项目。[/dim]")
        return

    console.print(f"\n[bold cyan]📁 调研项目列表（共 {len(projects)} 个）:[/bold cyan]")
    table = Table(box=box.MINIMAL, show_lines=False)
    table.add_column("ID", style="bold dim", width=14)
    table.add_column("项目名", style="bold")
    table.add_column("目标品牌", style="cyan")
    table.add_column("最后更新", justify="right")
    table.add_column("追问次数", justify="right")
    table.add_column("导出次数", justify="right")

    for p in projects:
        export_count = len(p.exported_minutes_paths) + len(p.exported_comparison_paths)
        table.add_row(
            p.project_id,
            p.name,
            p.query_params.target_brand,
            p.updated_at.strftime("%m-%d %H:%M"),
            str(len(p.follow_up_history)),
            str(export_count),
        )
    console.print(table)


def print_project_detail(project: ResearchProject):
    console.print(Panel(
        f"[bold]项目名:[/bold] {project.name}\n"
        f"[bold]ID:[/bold] {project.project_id}\n"
        f"[bold]目标品牌:[/bold] {project.query_params.target_brand}\n"
        f"[bold]竞品:[/bold] {', '.join(project.query_params.competing_brands) or '-'}\n"
        f"[bold]时间范围:[/bold] {project.query_params.time_range or '-'}\n"
        f"[bold]关注主题:[/bold] {', '.join(project.query_params.focus_themes) or '-'}\n"
        f"[bold]创建时间:[/bold] {project.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"[bold]最近更新:[/bold] {project.updated_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"[bold]查询快照:[/bold] {len(project.query_snapshots)} 次\n"
        f"[bold]追问历史:[/bold] {len(project.follow_up_history)} 条\n"
        f"[bold]导出纪要:[/bold] {len(project.exported_minutes_paths)} 份\n"
        f"[bold]导出对比:[/bold] {len(project.exported_comparison_paths)} 份",
        title="[bold cyan]项目总览[/bold cyan]",
        border_style="cyan",
        expand=False,
    ))

    if project.query_snapshots:
        console.print(f"\n[bold]查询快照（按时间排列）:[/bold]")
        snap_table = Table(box=box.MINIMAL, show_lines=False)
        snap_table.add_column("#", justify="right", style="dim")
        snap_table.add_column("时间", style="cyan")
        snap_table.add_column("品牌", style="bold")
        snap_table.add_column("当前帖数", justify="right")
        snap_table.add_column("负面占比", justify="right", style="red")
        snap_table.add_column("主要槽点", style="yellow")
        for i, snap in enumerate(project.query_snapshots, 1):
            s = snap.result_summary
            snap_table.add_row(
                str(i),
                snap.created_at.strftime("%m-%d %H:%M"),
                snap.query_params.target_brand,
                str(s.get("current_posts", "-")),
                f"{s.get('negative_ratio', 0):.1f}%" if "negative_ratio" in s else "-",
                s.get("top_complaint", "-"),
            )
        console.print(snap_table)

    if project.follow_up_history:
        console.print(f"\n[bold]最近追问:[/bold]")
        for f in project.follow_up_history[-5:]:
            console.print(f"  • 「{f.query}」→ {f.matched_keyword}（{f.total_mentions}次） {f.created_at.strftime('%m-%d %H:%M')}")

    if project.exported_minutes_paths or project.exported_comparison_paths:
        console.print(f"\n[bold]导出纪要:[/bold]")
        for p in project.exported_minutes_paths[-3:]:
            console.print(f"  📄 会议: {p}")
        for p in project.exported_comparison_paths[-3:]:
            console.print(f"  📊 对比: {p}")

    if project.query_params:
        console.print(f"\n[dim]提示: 输入「继续」可基于上次参数（{project.query_params.target_brand}、{project.query_params.time_range}）重新查询[/dim]")


def interactive_session(
    result: AnalysisResult,
    config: dict,
    params: QueryParams,
    project: Optional[ResearchProject] = None,
    library_mode: str = "smart",
):
    report_gen = ReportGenerator(config=config)
    analyzer_engine = Analyzer(config=config)
    pm = get_project_manager()
    use_library = library_mode != "off"

    console.print()
    project_note = f" [bold cyan](当前项目: {project.name})[/bold cyan]" if project else ""
    mode_note = f" [dim]样本模式: {library_mode}[/dim]"
    console.print(Panel(
        "[bold]命令提示:[/bold]\n"
        "  [cyan]追问 <任意描述>[/cyan]   深挖槽点（支持模糊，如「追问售后为什么差」「追问涨价」）\n"
        "  [cyan]列表[/cyan]                    查看所有关键词\n"
        "  [cyan]对比[/cyan]                    输出多品牌批量对比摘要\n"
        "  [cyan]导出对比|导出对比纪要[/cyan]  保存客户版对比纪要（适合会前分发）\n"
        "  [cyan]导出[/cyan]                    保存为会议纪要格式\n"
        "  [cyan]样本库|库[/cyan]              查看离线样本库状态\n"
        "  [cyan]模式 <smart|reuse|resample>[/cyan]  切换样本策略\n"
        "  [cyan]清空 <品牌>[/cyan]           清空某品牌的样本库数据\n"
        "  [cyan]项目|projects[/cyan]         列出所有调研项目\n"
        "  [cyan]新建项目 <名>[/cyan]         基于当前查询创建新项目\n"
        "  [cyan]打开项目 <ID>[/cyan]         打开已有项目续查\n"
        "  [cyan]项目详情|项目总览[/cyan]     查看当前项目总览（快照/追问/纪要）\n"
        "  [cyan]快照[/cyan]                    查看当前项目的查询快照列表\n"
        "  [cyan]继续[/cyan]                    基于当前项目参数重新查询\n"
        "  [cyan]导出进展[/cyan]              导出项目进展纪要\n"
        "  [cyan]新查询[/cyan]                  开始新一轮调研\n"
        "  [cyan]退出[/cyan]                    退出程序"
        + project_note + mode_note,
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
            console.print("\n[bold cyan]=== 所有关键词（仅当前周期） ===[/bold cyan]")
            if ta.advantages:
                console.print("[green]优点:[/green] " + ", ".join(f"{k.keyword}({k.count})" for k in ta.advantages[:10]))
            if ta.complaints:
                console.print("[red]槽点:[/red] " + ", ".join(f"{k.keyword}({k.count})" for k in ta.complaints[:10]))
            if ta.questions:
                console.print("[cyan]疑问:[/cyan] " + ", ".join(f"{k.keyword}({k.count})" for k in ta.questions[:10]))
            console.print(f"[dim]（仅当前周期 {len(result.current_range_posts)} 条参与分析，上一周期 {len(result.previous_range_posts)} 条仅用于环比）[/dim]")

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

            if project:
                pm.add_follow_up(
                    project,
                    query=keyword,
                    matched_keyword=detail.matched_keyword or keyword,
                    total_mentions=detail.total_mentions,
                )

        elif cmd_lower in ["导出", "export", "save", "s"]:
            default_dir = config.get("output", {}).get("default_dir", "./reports")
            output_dir = Prompt.ask("保存目录", default=default_dir)
            with console.status("[bold green]正在生成会议纪要...[/bold green]"):
                minutes = report_gen.build_meeting_minutes(result)
                filepath = report_gen.export_meeting_minutes(minutes, output_dir=output_dir)
            console.print(f"\n[bold green]✓ 会议纪要已保存:[/bold green] [underline]{os.path.abspath(filepath)}[/underline]")
            if project:
                pm.add_exported_minutes(project, os.path.abspath(filepath))

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

        elif cmd_lower.startswith("导出对比") or cmd_lower.startswith("对比导出") or cmd_lower in ["exportcmp", "exportcompare"]:
            if not params.competing_brands:
                console.print("[yellow]当前没有设置竞品，无法导出对比纪要。[/yellow]")
                continue
            default_dir = config.get("output", {}).get("default_dir", "./reports")
            output_dir = Prompt.ask("保存目录", default=default_dir)
            with console.status("[bold green]正在生成并导出对比纪要...[/bold green]"):
                comp_result = run_batch_comparison(params, config, use_library=use_library, library_mode=library_mode)
                filepath = report_gen.export_comparison_minutes(comp_result, output_dir=output_dir)
            console.print(f"\n[bold green]✓ 客户版对比纪要已保存:[/bold green] [underline]{os.path.abspath(filepath)}[/underline]")
            if project:
                pm.add_exported_comparison(project, os.path.abspath(filepath))

        elif cmd_lower in ["对比", "compare", "cmp", "c"]:
            if not params.competing_brands:
                console.print("[yellow]当前没有设置竞品，请先使用「新查询」增加竞品。[/yellow]")
                continue
            with console.status("[bold green]正在生成批量对比...[/bold green]"):
                comp_result = run_batch_comparison(params, config, use_library=use_library, library_mode=library_mode)
            report_gen.print_batch_comparison(comp_result)
            if Confirm.ask("是否导出为客户版对比纪要？", default=True):
                default_dir = config.get("output", {}).get("default_dir", "./reports")
                output_dir = Prompt.ask("保存目录", default=default_dir)
                filepath = report_gen.export_comparison_minutes(comp_result, output_dir=output_dir)
                console.print(f"  [bold green]✓ 已保存:[/bold green] [underline]{os.path.abspath(filepath)}[/underline]")
                if project:
                    pm.add_exported_comparison(project, os.path.abspath(filepath))

        elif cmd_lower in ["样本库", "库", "library", "lib", "db"]:
            print_library_status()

        elif cmd_lower.startswith("模式") or cmd_lower.startswith("mode"):
            mode_val = ""
            for sep in ["模式", "mode"]:
                idx = cmd_lower.find(sep)
                if idx >= 0:
                    mode_val = cmd[idx + len(sep):].strip().lower()
                    break
            if not mode_val:
                mode_val = Prompt.ask("选择样本策略", choices=["smart", "reuse", "resample"], default=library_mode)
            if mode_val not in ["smart", "reuse", "resample"]:
                console.print(f"[yellow]无效模式: {mode_val}，可选 smart/reuse/resample[/yellow]")
                continue
            library_mode = mode_val
            console.print(f"[green]✓ 已切换为「{library_mode}」模式:[/green]")
            mode_desc = {
                "smart": "复用库中数据，不足时自动生成新样本并入库（默认）",
                "reuse": "仅复用库中已有数据，不生成新样本（保证结果完全可重现）",
                "resample": "忽略已有数据，重新生成新样本并追加入库（补采样）",
            }
            console.print(f"  {mode_desc[library_mode]}")

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

        elif cmd_lower in ["项目", "projects", "proj"]:
            print_project_list(pm)

        elif cmd_lower.startswith("新建项目") or cmd_lower.startswith("newproject"):
            project_name = ""
            for sep in ["新建项目", "newproject"]:
                idx = cmd_lower.find(sep)
                if idx >= 0:
                    project_name = cmd[idx + len(sep):].strip()
                    break
            if not project_name:
                default_name = f"{params.target_brand}_调研_{datetime.now().strftime('%m%d')}"
                project_name = Prompt.ask("项目名", default=default_name)
            project = pm.create_project(name=project_name, params=params)
            console.print(f"[bold green]✓ 项目已创建:[/bold green] {project.name} (ID: {project.project_id})")
            print_project_detail(project)

        elif cmd_lower.startswith("打开项目") or cmd_lower.startswith("openproject"):
            project_id = ""
            for sep in ["打开项目", "openproject"]:
                idx = cmd_lower.find(sep)
                if idx >= 0:
                    project_id = cmd[idx + len(sep):].strip()
                    break
            if not project_id:
                print_project_list(pm)
                project_id = Prompt.ask("请输入项目ID")
            project = pm.load_project(project_id)
            if not project:
                console.print(f"[red]项目不存在: {project_id}[/red]")
                continue
            print_project_detail(project)
            if Confirm.ask(f"是否加载项目「{project.name}」并基于其参数重新分析？", default=True):
                params = project.query_params
                with console.status("[bold green]正在基于项目参数重新分析...[/bold green]"):
                    result, _ = run_analysis(params, config, use_library=use_library, library_mode="reuse", project=project)
                report_gen.print_full_report(result)

        elif cmd_lower in ["项目详情", "项目总览", "projectinfo"]:
            if not project:
                console.print("[yellow]当前没有关联项目，使用「新建项目」创建或「打开项目」加载。[/yellow]")
            else:
                project = pm.load_project(project.project_id)
                print_project_detail(project)

        elif cmd_lower in ["快照", "snapshots"]:
            if not project:
                console.print("[yellow]当前没有关联项目。[/yellow]")
            else:
                project = pm.load_project(project.project_id)
                if not project.query_snapshots:
                    console.print("[dim]当前项目暂无查询快照，执行查询后会自动记录。[/dim]")
                else:
                    console.print(f"\n[bold cyan]📋 查询快照（共 {len(project.query_snapshots)} 次）:[/bold cyan]")
                    snap_table = Table(box=box.MINIMAL, show_lines=False)
                    snap_table.add_column("#", justify="right", style="dim")
                    snap_table.add_column("时间", style="cyan")
                    snap_table.add_column("品牌", style="bold")
                    snap_table.add_column("竞品", style="dim")
                    snap_table.add_column("时间范围")
                    snap_table.add_column("当前帖数", justify="right")
                    snap_table.add_column("负面占比", justify="right", style="red")
                    snap_table.add_column("主要槽点", style="yellow")
                    snap_table.add_column("环比", justify="right")
                    for i, snap in enumerate(project.query_snapshots, 1):
                        s = snap.result_summary
                        snap_table.add_row(
                            str(i),
                            snap.created_at.strftime("%m-%d %H:%M"),
                            snap.query_params.target_brand,
                            ", ".join(snap.query_params.competing_brands[:2]) or "-",
                            str(snap.query_params.time_range) if snap.query_params.time_range else "-",
                            str(s.get("current_posts", "-")),
                            f"{s.get('negative_ratio', 0):.1f}%" if "negative_ratio" in s else "-",
                            s.get("top_complaint", "-"),
                            f"{s.get('volume_change', 0):+.1f}%" if "volume_change" in s else "-",
                        )
                    console.print(snap_table)

        elif cmd_lower in ["继续", "continue", "resume"]:
            if not project:
                console.print("[yellow]当前没有关联项目，请先「新建项目」或「打开项目」。[/yellow]")
                continue
            project = pm.load_project(project.project_id)
            params = project.query_params
            console.print(f"[cyan]基于项目参数重新查询: {params.target_brand}，{params.time_range}[/cyan]")
            with console.status("[bold green]正在重新分析...[/bold green]"):
                result, _ = run_analysis(params, config, use_library=use_library, library_mode=library_mode, project=project)
            report_gen.print_full_report(result)

        elif cmd_lower in ["导出进展", "exportprogress"]:
            if not project:
                console.print("[yellow]当前没有关联项目。[/yellow]")
                continue
            project = pm.load_project(project.project_id)
            default_dir = config.get("output", {}).get("default_dir", "./reports")
            output_dir = Prompt.ask("保存目录", default=default_dir)
            with console.status("[bold green]正在生成项目进展纪要...[/bold green]"):
                filepath = export_project_progress_minutes(project, output_dir=output_dir)
            console.print(f"\n[bold green]✓ 项目进展纪要已保存:[/bold green] [underline]{os.path.abspath(filepath)}[/underline]")
            pm.add_exported_minutes(project, os.path.abspath(filepath))

        elif cmd_lower in ["新查询", "new", "reset", "n"]:
            if Confirm.ask("确定要开始新一轮查询吗？", default=True):
                return True

        elif cmd_lower in ["帮助", "help", "h", "?"]:
            console.print(Panel(
                "[bold]可用命令:[/bold]\n"
                "  [cyan]追问 <描述>[/cyan]      模糊匹配后深挖槽点（如「追问售后为什么差」「涨价」）\n"
                "  [cyan]列表[/cyan]               列出所有优点/槽点/疑问关键词（仅当前周期）\n"
                "  [cyan]重绘[/cyan]               重新显示完整三段式报告\n"
                "  [cyan]对比[/cyan]               目标品牌 vs 多竞品批量对照摘要\n"
                "  [cyan]导出[/cyan]               保存会议纪要 TXT\n"
                "  [cyan]导出对比[/cyan]           保存客户版对比纪要（会前分发用，含证据附录）\n"
                "  [cyan]导出进展[/cyan]           保存项目进展纪要（含快照对比趋势）\n"
                "  [cyan]模式 <策略>[/cyan]       smart/reuse/resample 样本策略切换\n"
                "  [cyan]样本库[/cyan]             查看离线样本库累计数据量\n"
                "  [cyan]清空 <品牌>[/cyan]       清除某品牌的样本库数据\n"
                "  [cyan]项目[/cyan]               列出所有调研项目\n"
                "  [cyan]新建项目 <名>[/cyan]    创建新项目，绑定当前查询\n"
                "  [cyan]打开项目 <ID>[/cyan]    加载已有项目并复用其参数\n"
                "  [cyan]项目详情|项目总览[/cyan] 查看当前项目总览（快照/追问/纪要）\n"
                "  [cyan]快照[/cyan]               查看当前项目的查询快照列表\n"
                "  [cyan]继续[/cyan]               基于当前项目参数重新查询\n"
                "  [cyan]新查询[/cyan]             开始新一轮调研\n"
                "  [cyan]帮助[/cyan]               显示本帮助\n"
                "  [cyan]退出[/cyan]               退出程序",
                border_style="blue",
                title="帮助",
                expand=False,
            ))

        else:
            console.print(f"[yellow]未知命令: {cmd}，输入「帮助」查看可用命令[/yellow]")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reputation_checker",
        description="品牌口碑速查工具 v4 - 面向品牌咨询顾问的论坛声音速查",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
v4 更新内容:
  · 项目沉淀：查询快照自动记录，项目总览展示，继续查询，项目进展纪要导出
  · 样本复核：reuse模式按当前/上一周期比例分配截断，补采样后切换reuse双周期样本稳定
  · 口径纯净：当前范围无帖子时追问显示暂无提及，不拿上周期凑数
  · 证据附录：对比纪要每品牌附可引用原帖摘要+来源时间

示例:
  python main.py --brand 小米手机 --competitors 华为手机,苹果手机 --days 30 --themes 售后,新品,涨价
  python main.py --brand 小米手机 --competitors 华为手机,苹果手机 --days 30 --compare --export-compare
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
    parser.add_argument("--export-compare", type=str, nargs="?", const="./reports", help="直接导出客户版对比纪要")
    parser.add_argument("--project", type=str, help="绑定项目名，自动创建或打开同名项目")
    parser.add_argument("--library-mode", type=str, default="smart", choices=["smart", "reuse", "resample"], help="样本库策略 smart/reuse/resample")
    parser.add_argument("--no-library", action="store_true", help="不使用离线样本库（仅临时生成）")
    parser.add_argument("--no-interactive", action="store_true", help="非交互模式，输出报告后直接退出")
    return parser


def show_banner():
    banner = """
[bold magenta]░█▀█░█▀▀░█▀█░█░█░▀█▀░█▀█░▀█▀░░░░░█▀▀░█░█░█▀▀░█▀▀░█░█░█▀▀░█▀▄[/bold magenta]
[bold magenta]░█▀▀░█▀▀░█░█░█░█░░█░░█░█░░█░░░░░░█░░█▀█░█▀▀░█░░░█▀▄░█▀▀░█▀▄[/bold magenta]
[bold magenta]░▀░░░▀▀▀░▀░▀░▀▀▀░░▀░░▀░▀░░▀░░▀▀▀░░▀▀▀░▀░▀░▀▀▀░▀▀▀░▀░▀░▀▀▀░▀░▀[/bold magenta]
[dim]Reputation Quick Check Tool v4.0  |  项目沉淀 · 样本复核 · 口径纯净 · 证据附录[/dim]
    """
    console.print(banner)


def main():
    show_banner()

    arg_parser = build_arg_parser()
    args = arg_parser.parse_args()

    config = load_config(args.config)
    pm = get_project_manager()

    use_library = not args.no_library
    library_mode = args.library_mode if use_library else "off"

    if args.brand:
        params = build_query_params_from_args(args)
    else:
        if sys.stdin.isatty():
            params = build_query_params_interactive()
        else:
            arg_parser.print_help()
            console.print("\n[red]非交互模式下必须指定 --brand 参数[/red]")
            sys.exit(1)

    project: Optional[ResearchProject] = None
    if args.project:
        existing = next((p for p in pm.list_projects() if p.name == args.project), None)
        if existing:
            project = existing
            console.print(f"[cyan]📂 已加载项目: {project.name} (ID: {project.project_id})[/cyan]")
        else:
            project = pm.create_project(name=args.project, params=params)
            console.print(f"[bold green]✓ 新项目已创建: {project.name} (ID: {project.project_id})[/bold green]")

    console.print()

    if args.compare:
        if not params.competing_brands:
            console.print("[yellow]--compare 需要配合 --competitors 指定至少一个竞品[/yellow]")
            sys.exit(1)
        comp_result = run_batch_comparison(params, config, use_library=use_library, library_mode=library_mode)
        report_gen = ReportGenerator(config=config)
        report_gen.print_batch_comparison(comp_result)

        if args.export_compare is not None:
            filepath = report_gen.export_comparison_minutes(comp_result, output_dir=args.export_compare)
            console.print(f"\n[bold green]✓ 客户版对比纪要已保存:[/bold green] [underline]{os.path.abspath(filepath)}[/underline]")
            if project:
                pm.add_exported_comparison(project, os.path.abspath(filepath))

        if args.no_interactive:
            return
        dummy_result = list(comp_result.brand_results.values())[0] if comp_result.brand_results else None
        if dummy_result:
            if interactive_session(dummy_result, config, params, project=project, library_mode=library_mode):
                pass
            return

    result, _ = run_analysis(params, config, use_library=use_library, library_mode=library_mode, project=project)
    report_gen = generate_report(result, config=config)

    if args.export is not None:
        with console.status("[bold green]正在生成会议纪要...[/bold green]"):
            minutes = report_gen.build_meeting_minutes(result)
            filepath = report_gen.export_meeting_minutes(minutes, output_dir=args.export)
        console.print(f"\n[bold green]✓ 会议纪要已保存:[/bold green] [underline]{os.path.abspath(filepath)}[/underline]")
        if project:
            pm.add_exported_minutes(project, os.path.abspath(filepath))

    if args.export_compare is not None and params.competing_brands:
        comp_result = run_batch_comparison(params, config, use_library=use_library, library_mode=library_mode)
        filepath = report_gen.export_comparison_minutes(comp_result, output_dir=args.export_compare)
        console.print(f"[bold green]✓ 客户版对比纪要已保存:[/bold green] [underline]{os.path.abspath(filepath)}[/underline]")
        if project:
            pm.add_exported_comparison(project, os.path.abspath(filepath))

    if args.no_interactive:
        return

    try:
        while True:
            should_restart = interactive_session(result, config, params, project=project, library_mode=library_mode)
            if not should_restart:
                break
            console.clear()
            show_banner()
            params = build_query_params_interactive()
            result, _ = run_analysis(params, config, use_library=use_library, library_mode=library_mode, project=project)
            report_gen.print_full_report(result)
    except KeyboardInterrupt:
        console.print("\n\n[yellow]程序被中断，再见！[/yellow]")


if __name__ == "__main__":
    main()
